"""Alpha Factory L0 — deterministic factor sandbox (zero LLM).

V1.2/V1.3 true sandbox: AST static scan + restricted builtins + subprocess limits.
All IC/IR/metrics computed here; LLM output never enters metrics dict.
"""
from __future__ import annotations

import ast
import json
import multiprocessing as mp
import os
import re
import sqlite3
import sys
import tempfile
import textwrap
import time
import traceback
from dataclasses import dataclass
from typing import Any

import numpy as np

from factory_schema import column_whitelist, template_comment_block

# Must match SQL SELECT column order in _worker_run (not frozenset iteration order).
_BAR_COLUMNS = ("ts", "symbol", "o", "h", "l", "c", "v")

ALLOWED_IMPORT_ROOTS = frozenset({"pandas", "numpy", "pd", "np"})
FORBIDDEN_CALL_NAMES = frozenset(
    {"__import__", "eval", "exec", "compile", "open", "getattr", "setattr", "delattr", "globals", "locals", "vars"}
)
FORBIDDEN_ATTR = frozenset({"__builtins__", "__globals__", "__loader__", "__spec__"})
FORBIDDEN_MODULE_PREFIXES = (
    "importlib",
    "subprocess",
    "socket",
    "urllib",
    "requests",
    "os.system",
)
SAFE_BUILTINS = {
    "len": len,
    "range": range,
    "min": min,
    "max": max,
    "sum": sum,
    "abs": abs,
    "round": round,
    "sorted": sorted,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "isinstance": isinstance,
    "print": print,
    "True": True,
    "False": False,
    "None": None,
}

SANDBOX_TIMEOUT = int(os.getenv("FACTORY_SANDBOX_TIMEOUT", "120"))
SANDBOX_MEMORY_BYTES = int(os.getenv("FACTORY_SANDBOX_MEMORY_BYTES", str(1024**3)))


class SandboxError(Exception):
    """Base sandbox failure."""

    category: str = "sandbox"


class SandboxRejection(SandboxError):
    """AST or runtime policy block — never triggers fix_error."""

    category = "sandbox"


class ResourceLimit(SandboxError):
    """Timeout or memory — never triggers fix_error."""

    category = "resource"


class WorkerPipelineError(SandboxError):
    """Data load / worker infra — never triggers fix_error."""

    category = "pipeline"


class FactorCodeError(SandboxError):
    """Exception inside factor() — may trigger fix_error (V1.3)."""

    category = "factor_code"

    def __init__(
        self,
        message: str,
        *,
        exc_type: str,
        exc_message: str,
        traceback_frames: list[str],
        df_head: str,
    ) -> None:
        super().__init__(message)
        self.exc_type = exc_type
        self.exc_message = exc_message
        self.traceback_frames = traceback_frames
        self.df_head = df_head

    def fix_payload(self, code: str) -> dict[str, Any]:
        return {
            "code": code,
            "exc_type": self.exc_type,
            "exc_message": self.exc_message,
            "traceback_frames": self.traceback_frames,
            "df_head": self.df_head,
        }


def _module_root(name: str) -> str:
    return (name or "").split(".")[0]


def _validate_ast(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SandboxRejection(f"syntax error: {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _module_root(alias.name)
                if root not in ALLOWED_IMPORT_ROOTS:
                    raise SandboxRejection(f"import not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = _module_root(node.module or "")
            if mod and mod not in ALLOWED_IMPORT_ROOTS:
                raise SandboxRejection(f"import not allowed: {node.module}")
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in FORBIDDEN_CALL_NAMES:
                raise SandboxRejection(f"call not allowed: {fn.id}()")
            if isinstance(fn, ast.Attribute):
                if fn.attr in FORBIDDEN_CALL_NAMES:
                    raise SandboxRejection(f"call not allowed: .{fn.attr}()")
                base = fn.attr
                if base == "system" and isinstance(fn.value, ast.Name) and fn.value.id == "os":
                    raise SandboxRejection("call not allowed: os.system()")
                mod_name = ""
                if isinstance(fn.value, ast.Name):
                    mod_name = fn.value.id
                elif isinstance(fn.value, ast.Attribute) and isinstance(fn.value.value, ast.Name):
                    mod_name = f"{fn.value.value.id}.{fn.value.attr}"
                for prefix in FORBIDDEN_MODULE_PREFIXES:
                    if mod_name.startswith(prefix.split(".")[0]) or fn.attr == prefix:
                        raise SandboxRejection(f"call not allowed: {mod_name}.{fn.attr}")
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTR:
                raise SandboxRejection(f"attribute access not allowed: {node.attr}")


def _apply_memory_limit() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (SANDBOX_MEMORY_BYTES, SANDBOX_MEMORY_BYTES))
    except (ImportError, OSError, ValueError):
        pass


def _safe_exec(code: str, ns: dict[str, Any]) -> None:
    safe_builtins = dict(SAFE_BUILTINS)
    g: dict[str, Any] = {"__builtins__": safe_builtins}
    g.update({k: v for k, v in ns.items() if k != "__builtins__"})
    exec(textwrap.dedent(code), g, g)  # noqa: S102 — intentional isolated exec
    ns.update({k: v for k, v in g.items() if k != "__builtins__"})


FORBIDDEN_RUNTIME_MARKERS = ("__import__", "eval(", "exec(", "compile(", "open(")


def _strip_injected_imports(code: str) -> str:
    """pd/np are pre-injected; top-level pandas/numpy imports need __import__ in builtins."""
    out: list[str] = []
    for line in (code or "").splitlines():
        s = line.strip()
        if s.startswith("import pandas") or s.startswith("import numpy"):
            continue
        if s.startswith("from pandas") or s.startswith("from numpy"):
            continue
        out.append(line)
    return "\n".join(out)


def _runtime_policy_violation(tb: str, exc: BaseException) -> bool:
    blob = f"{tb}\n{exc}"
    return any(m in blob for m in FORBIDDEN_RUNTIME_MARKERS)


def _extract_factor_traceback(tb: str, *, max_frames: int = 3) -> list[str]:
    lines = [ln for ln in (tb or "").splitlines() if ln.strip()]
    factor_lines = [ln for ln in lines if "factor" in ln.lower() or 'File "' in ln]
    if not factor_lines:
        factor_lines = lines
    return factor_lines[-max_frames:]


def _classify_factor_exception(exc: BaseException, tb: str, df_head: str) -> SandboxError:
    from factory_schema import classify_column_error

    err_text = f"{type(exc).__name__}: {exc}\n{tb}"
    if isinstance(exc, KeyError):
        cat = classify_column_error(err_text)
        if cat == "pipeline":
            return WorkerPipelineError(f"contract column missing in data: {exc}")
    frames = _extract_factor_traceback(tb)
    msg = f"{type(exc).__name__}: {exc}"
    return FactorCodeError(
        msg,
        exc_type=type(exc).__name__,
        exc_message=str(exc),
        traceback_frames=frames,
        df_head=df_head,
    )


def _worker_run(code: str, db_path: str, watchlist: list[str], q: mp.Queue, return_frame: bool = False) -> None:
    tmpdir = None
    try:
        _apply_memory_limit()
        import pandas as pd

        tmpdir = tempfile.mkdtemp(prefix="alpha_factory_sandbox_")
        out_dir = os.path.join(tmpdir, "out")
        os.makedirs(out_dir, exist_ok=True)

        if not os.path.isfile(db_path):
            raise WorkerPipelineError(f"data db not found: {db_path}")

        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            syms = watchlist[:8]
            if not syms:
                raise WorkerPipelineError("empty watchlist")
            placeholders = ",".join("?" * len(syms))
            rows = con.execute(
                f"SELECT ts, symbol, o, h, l, c, v FROM bars WHERE symbol IN ({placeholders}) "
                "ORDER BY symbol, ts ASC LIMIT 8000",
                syms,
            ).fetchall()
        finally:
            con.close()

        if len(rows) < 30:
            raise WorkerPipelineError(f"insufficient bars: {len(rows)}")

        df = pd.DataFrame(rows, columns=list(_BAR_COLUMNS))
        unknown = set(df.columns) - column_whitelist()
        if unknown:
            raise WorkerPipelineError(f"unexpected df columns: {sorted(unknown)}")
        df_head = df.head(5).to_string(max_cols=10)

        ns: dict[str, Any] = {"pd": pd, "np": np, "pandas": pd, "numpy": np}
        try:
            _safe_exec(_strip_injected_imports(code), ns)
        except SandboxRejection:
            raise
        except Exception as exc:
            tb = traceback.format_exc()
            if _runtime_policy_violation(tb, exc):
                raise SandboxRejection(f"runtime policy violation: {exc}") from exc
            if "factor" not in tb:
                raise SandboxRejection(f"runtime policy violation: {exc}") from exc
            raise _classify_factor_exception(exc, tb, df_head) from exc

        fn = ns.get("factor")
        if not callable(fn):
            raise FactorCodeError(
                "factor(df) not defined",
                exc_type="NameError",
                exc_message="factor(df) not defined",
                traceback_frames=[],
                df_head=df_head,
            )

        try:
            fac = fn(df)
        except SandboxRejection:
            raise
        except Exception as exc:
            tb = traceback.format_exc()
            if _runtime_policy_violation(tb, exc):
                raise SandboxRejection(f"runtime policy violation: {exc}") from exc
            raise _classify_factor_exception(exc, tb, df_head) from exc

        if fac is None or len(fac) != len(df):
            raise FactorCodeError(
                "factor(df) must return Series aligned with df",
                exc_type="ValueError",
                exc_message="return length mismatch",
                traceback_frames=[],
                df_head=df_head,
            )

        work = df.copy()
        work["fac"] = pd.to_numeric(fac, errors="coerce")
        work = work.dropna(subset=["fac", "c"])
        work["fwd"] = work.groupby("symbol")["c"].pct_change().shift(-1)
        work = work.dropna(subset=["fwd"])
        if len(work) < 20:
            raise FactorCodeError(
                "too few valid factor rows after forward return",
                exc_type="ValueError",
                exc_message="too few valid rows",
                traceback_frames=[],
                df_head=df_head,
            )

        ic = float(work["fac"].corr(work["fwd"]))
        ic_series = []
        for _sym, g in work.groupby("symbol"):
            if len(g) >= 10:
                ic_series.append(float(g["fac"].corr(g["fwd"])))
        ir = float(np.mean(ic_series) / (np.std(ic_series) + 1e-9)) if ic_series else 0.0

        work["rank"] = work.groupby("ts")["fac"].rank(pct=True)
        top = work[work["rank"] >= 0.8]["fwd"].mean()
        bot = work[work["rank"] <= 0.2]["fwd"].mean()
        spread_raw = float((top or 0) - (bot or 0))
        spread = spread_raw if spread_raw == spread_raw else None  # NaN → null in JSON
        turnover = float(work.groupby("symbol")["fac"].diff().abs().mean() / (work["fac"].abs().mean() + 1e-9))

        metrics = {
            "ic": round(ic, 6),
            "ir": round(ir, 6),
            "quintile_spread": round(spread, 6) if spread is not None else None,
            "turnover_proxy": round(turnover, 6),
            "n_obs": int(len(work)),
            "symbols": len(work["symbol"].unique()),
            "data_window": {"from_ts": int(work["ts"].min()), "to_ts": int(work["ts"].max())},
            "computed_by": "alpha-platform/factor_sandbox",
            "computed_at": int(time.time()),
        }
        payload = {"ok": True, "metrics": metrics}
        if return_frame:
            payload["work"] = work[["ts", "symbol", "c", "fac"]]
        q.put(payload)
    except MemoryError:
        q.put({"ok": False, "category": "resource", "error": "memory limit exceeded"})
    except SandboxError as exc:
        fix_payload = exc.fix_payload(code) if isinstance(exc, FactorCodeError) else None
        q.put({"ok": False, "category": exc.category, "error": str(exc)[:500], "fix_payload": fix_payload})
    except Exception as exc:
        q.put({"ok": False, "category": "pipeline", "error": str(exc)[:500]})
    finally:
        if tmpdir:
            try:
                import shutil

                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass


def run_factor_review(code: str, db_path: str, watchlist: list[str], return_frame: bool = False) -> dict[str, Any] | tuple:
    _validate_ast(code)
    q: mp.Queue = mp.Queue()
    ctx = mp.get_context("spawn")
    p = ctx.Process(target=_worker_run, args=(code, db_path, watchlist, q, return_frame))
    p.start()
    p.join(SANDBOX_TIMEOUT)
    if p.is_alive():
        p.terminate()
        p.join(5)
        raise ResourceLimit(f"sandbox timeout ({SANDBOX_TIMEOUT}s)")
    if q.empty():
        raise WorkerPipelineError("sandbox produced no result")
    result = q.get()
    if result.get("ok"):
        if return_frame:
            return result["metrics"], result.get("work")
        return result["metrics"]
    cat = result.get("category") or "sandbox"
    err = result.get("error") or "sandbox failed"
    fix_payload = result.get("fix_payload")
    if cat == "resource":
        raise ResourceLimit(err)
    if cat == "pipeline":
        raise WorkerPipelineError(err)
    if cat == "factor_code":
        fp = fix_payload or {}
        raise FactorCodeError(
            err,
            exc_type=fp.get("exc_type") or "Error",
            exc_message=fp.get("exc_message") or err,
            traceback_frames=fp.get("traceback_frames") or [],
            df_head=fp.get("df_head") or "",
        )
    raise SandboxRejection(err)


def eligible_for_fix_error(exc: SandboxError) -> bool:
    return isinstance(exc, FactorCodeError)


def build_fix_error_payload(code: str, exc: FactorCodeError) -> dict[str, Any]:
    return exc.fix_payload(code)

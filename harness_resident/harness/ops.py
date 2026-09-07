"""op 白名单。read_only / worker / executor 只由此表定，块里写了也不信。"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

ACK_OPS = frozenset({"TOPOLOGY_SYNC", "ACK"})
FS_OPS = frozenset({"FS_STAT", "FS_LIST", "FS_READ"})
READ_MAX_BYTES = 65536
SKIP_NAMES = frozenset({".DS_Store", "__pycache__"})

DEMO_ROOT = Path(__file__).resolve().parents[2]


def parse_action_plan(text: str) -> list[dict[str, Any]]:
    """Parse `- op:` items and following `target` / `scope` / `payload` lines."""
    steps: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in str(text or "").splitlines():
        m = re.match(r"\s*-\s*op:\s*(\S+)", raw)
        if m:
            if current:
                steps.append(current)
            current = {"op": m.group(1).strip().strip('"').strip("'")}
            continue
        if current is None:
            continue
        tm = re.match(r"\s*target:\s*(.+)$", raw)
        if tm:
            current["target"] = tm.group(1).strip().strip(",").strip('"').strip("'")
            continue
        sm = re.match(r"\s*scope:\s*(.+)$", raw)
        if sm:
            current["scope"] = sm.group(1).strip()
            continue
        pm = re.match(r"\s*payload:\s*(.+)$", raw)
        if pm:
            current["payload"] = pm.group(1).strip().strip('"')
            continue
    if current:
        steps.append(current)
    return steps


def classify_op(op: str) -> dict[str, Any]:
    name = str(op or "").strip().upper()
    if name in FS_OPS:
        return {
            "op": name,
            "kind": "fs",
            "worker": None,
            "read_only": True,
            "ack": False,
            "executor": "tool",
        }
    if name in ACK_OPS:
        return {
            "op": name,
            "kind": "ack",
            "worker": None,
            "read_only": True,
            "ack": True,
            "executor": "ack",
        }
    return {
        "op": name or "UNKNOWN",
        "kind": "blocked",
        "worker": None,
        "read_only": False,
        "ack": False,
        "executor": None,
    }


def classify_steps(steps: list | None) -> dict[str, Any]:
    rows = []
    for raw in steps or []:
        if isinstance(raw, dict):
            rows.append(classify_op(raw.get("op") or raw.get("OP")))
        else:
            rows.append(classify_op(str(raw)))
    if not rows:
        return {
            "ops": [],
            "kind": "blocked",
            "worker": None,
            "read_only": False,
            "topology_ack": False,
            "blocked": True,
            "executor": None,
        }
    blocked = any(r["kind"] == "blocked" for r in rows)
    acks = [r for r in rows if r["ack"]]
    fs = [r for r in rows if r["kind"] == "fs"]
    if blocked:
        return {
            "ops": rows,
            "kind": "blocked",
            "worker": None,
            "read_only": False,
            "topology_ack": False,
            "blocked": True,
            "executor": None,
        }
    if fs:
        return {
            "ops": rows,
            "kind": "fs",
            "worker": None,
            "read_only": True,
            "topology_ack": bool(acks),
            "blocked": False,
            "executor": "tool",
        }
    return {
        "ops": rows,
        "kind": "ack",
        "worker": None,
        "read_only": True,
        "topology_ack": True,
        "blocked": False,
        "executor": "ack",
    }


def _roots(allowed_paths: list[str] | None) -> list[Path]:
    out: list[Path] = []
    for raw in allowed_paths or [str(DEMO_ROOT)]:
        if str(raw) in {".", ""}:
            out.append(DEMO_ROOT.resolve())
            continue
        p = Path(raw)
        out.append(p.resolve() if p.is_absolute() else (DEMO_ROOT / p).resolve())
    return out or [DEMO_ROOT.resolve()]


def resolve_in_fence(target: str, allowed_paths: list[str] | None) -> Path:
    if not str(target or "").strip():
        raise PermissionError("missing target")
    raw = Path(str(target).strip())
    cand = raw.resolve() if raw.is_absolute() else (DEMO_ROOT / raw).resolve()
    for root in _roots(allowed_paths):
        try:
            cand.relative_to(root)
            return cand
        except ValueError:
            continue
    raise PermissionError("outside add-dir fence")


def _iter_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(str(path))
    files = []
    for child in path.iterdir():
        if child.name in SKIP_NAMES or child.name.startswith("."):
            continue
        if child.is_file():
            files.append(child)
    return files


def fs_stat(path: Path) -> dict[str, Any]:
    files = _iter_files(path)
    file_count = len(files)
    max_file = None
    if files:
        biggest = max(files, key=lambda p: p.stat().st_size)
        max_file = {"name": biggest.name, "size_bytes": int(biggest.stat().st_size)}
    return {"file_count": file_count, "max_file": max_file}


def fs_list(path: Path) -> dict[str, Any]:
    if path.is_file():
        return {"names": [path.name]}
    names = []
    for child in sorted(path.iterdir(), key=lambda p: p.name):
        if child.name in SKIP_NAMES or child.name.startswith("."):
            continue
        names.append(child.name)
    return {"names": names}


def fs_read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise IsADirectoryError(str(path))
    size = int(path.stat().st_size)
    data = path.read_bytes()[:READ_MAX_BYTES]
    return {
        "name": path.name,
        "size_bytes": size,
        "truncated": size > READ_MAX_BYTES,
        "text": data.decode("utf-8", "replace"),
    }


def execute_steps(steps: list | None, *, allowed_paths: list[str] | None = None) -> dict[str, Any]:
    """Run ACK as ack-only and FS_* via os.stat/listdir/open. Never calls a model."""
    classified = classify_steps(steps)
    if classified["blocked"]:
        raise PermissionError("op not on whitelist")
    out: dict[str, Any] = {
        "topology_ack": bool(classified["topology_ack"]),
        "executor": classified.get("executor"),
        "fs_data": None,
        "ops": [],
    }
    for raw in steps or []:
        if isinstance(raw, dict):
            name = str(raw.get("op") or raw.get("OP") or "").strip().upper()
            target = str(raw.get("target") or "")
        else:
            name = str(raw).strip().upper()
            target = ""
        row = classify_op(name)
        if row["ack"]:
            out["ops"].append({"op": name, "executor": "ack", "ok": True})
            continue
        if row["executor"] != "tool":
            raise PermissionError(name)
        path = resolve_in_fence(target, allowed_paths)
        if name == "FS_STAT":
            data = fs_stat(path)
            out["fs_data"] = data
            out["ops"].append({"op": name, "executor": "tool", "ok": True, "fs_data": data})
        elif name == "FS_LIST":
            data = fs_list(path)
            out["fs_data"] = data
            out["ops"].append({"op": name, "executor": "tool", "ok": True, "fs_data": data})
        elif name == "FS_READ":
            data = fs_read(path)
            out["fs_data"] = {"name": data["name"], "size_bytes": data["size_bytes"]}
            out["ops"].append({"op": name, "executor": "tool", "ok": True, "fs_data": data})
        else:
            raise PermissionError(name)
    return out


def worker_output_json(result: dict[str, Any]) -> str:
    return json.dumps(
        {
            "topology_ack": bool(result.get("topology_ack")),
            "executor": result.get("executor") or "tool",
            "fs_data": result.get("fs_data"),
        },
        ensure_ascii=False,
        indent=2,
    )

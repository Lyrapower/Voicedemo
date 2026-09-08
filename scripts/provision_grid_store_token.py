#!/usr/bin/env python3
"""Create or validate GRID_STORE_TOKEN at repo_root/grid-sovereign-runtime/config/.

Never prints the secret. --root is the repo root, not the runtime directory.
Explicit --provision is required to create. inspect/require-file/env checks
are read-only (no chmod, no generate).
"""
from __future__ import annotations
import argparse, errno, hmac, os, secrets, stat, sys
from pathlib import Path

RUNTIME_DIR = "grid-sovereign-runtime"
CONFIG_DIR = "config"
TOKEN_NAME = "grid_store.token"
LOCK_NAME = ".grid_store.token.lock"
MAX_BYTES = 4096
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_PROC_LOCK = __import__("threading").Lock()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def token_path(*, root: Path | None = None) -> Path:
    r = Path(root) if root is not None else repo_root()
    return r / RUNTIME_DIR / CONFIG_DIR / TOKEN_NAME


def _print_exc(exc: BaseException) -> None:
    print("error", type(exc).__name__, file=sys.stderr)


def _open_dir_nofollow(path: Path, *, dir_fd: int | None = None, name: str | None = None) -> int:
    flags = os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC
    if dir_fd is not None and name is not None:
        return os.open(name, flags, dir_fd=dir_fd)
    return os.open(str(path), flags)


def _trusted_config_fd(root: Path) -> tuple[int | None, str]:
    """Open runtime/config via dir_fd. Reject runtime or config symlinks.

    Does not require every filesystem ancestor (e.g. /Users) to be owned by
    the service account. root is treated as the repo root after Path.resolve
    of the --root argument (Mac path aliases).
    """
    try:
        root = Path(root)
        if not root.exists():
            return None, "root_missing"
        resolved = root.resolve()
        if resolved.is_symlink():
            return None, "root_symlink"
        if not resolved.is_dir():
            return None, "root_not_dir"
        root_fd = _open_dir_nofollow(resolved)
        try:
            st = os.fstat(root_fd)
            if not stat.S_ISDIR(st.st_mode):
                return None, "root_not_dir"
            try:
                rt_path = resolved / RUNTIME_DIR
                if rt_path.is_symlink():
                    return None, "runtime_symlink"
                rt_fd = _open_dir_nofollow(rt_path, dir_fd=root_fd, name=RUNTIME_DIR)
            except OSError as e:
                if e.errno in (errno.ELOOP, errno.EINVAL, errno.EPERM):
                    return None, "runtime_symlink"
                if e.errno == errno.ENOENT:
                    return None, "runtime_missing"
                return None, "runtime_unreadable"
            try:
                rst = os.fstat(rt_fd)
                if not stat.S_ISDIR(rst.st_mode):
                    return None, "runtime_not_dir"
                if rst.st_uid != os.geteuid():
                    return None, "runtime_owner"
                try:
                    cfg_path = resolved / RUNTIME_DIR / CONFIG_DIR
                    if cfg_path.is_symlink():
                        return None, "config_symlink"
                    cfg_fd = _open_dir_nofollow(cfg_path, dir_fd=rt_fd, name=CONFIG_DIR)
                except OSError as e:
                    if e.errno in (errno.ELOOP, errno.EINVAL, errno.EPERM):
                        return None, "config_symlink"
                    if e.errno == errno.ENOENT:
                        return None, "config_missing"
                    return None, "config_unreadable"
                cst = os.fstat(cfg_fd)
                if not stat.S_ISDIR(cst.st_mode):
                    os.close(cfg_fd)
                    return None, "config_not_dir"
                if cst.st_uid != os.geteuid():
                    os.close(cfg_fd)
                    return None, "config_owner"
                if cst.st_mode & 0o022:
                    os.close(cfg_fd)
                    return None, "config_writable_by_others"
                return cfg_fd, "ok"
            finally:
                os.close(rt_fd)
        finally:
            os.close(root_fd)
    except OSError:
        return None, "root_unreadable"


def _parse_token_bytes(raw: bytes) -> tuple[bool, str]:
    if len(raw) > MAX_BYTES:
        return False, "too_large"
    if b"\x00" in raw:
        return False, "nul"
    body = raw
    if body.endswith(b"\n"):
        body = body[:-1]
    if b"\n" in body or b"\r" in body:
        return False, "embedded_newline"
    if not body:
        return False, "empty_or_short"
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError:
        return False, "non_ascii"
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        return False, "control_char"
    if len(text) < 16:
        return False, "empty_or_short"
    return True, "ok"


def _fstat_regular(fd: int) -> tuple[os.stat_result | None, str]:
    st = os.fstat(fd)
    if stat.S_ISLNK(st.st_mode):
        return None, "symlink"
    if not stat.S_ISREG(st.st_mode):
        if stat.S_ISFIFO(st.st_mode):
            return None, "not_regular"
        return None, "not_regular"
    if st.st_uid != os.geteuid():
        return None, "owner"
    if st.st_nlink != 1:
        return None, "nlink"
    return st, "ok"


def inspect_token_file(path: Path) -> dict:
    """Read-only. Never chmod. Reject untrusted metadata before reading bytes."""
    out = {
        "exists": False,
        "is_file": False,
        "is_symlink": False,
        "mode_ok": False,
        "nlink_ok": False,
        "owner_ok": False,
        "nonempty": False,
        "ok": False,
        "reason": "missing",
        "value": None,
    }
    root = path.parents[2] if len(path.parts) >= 3 else path.parent
    # path = root / runtime / config / token → parents[2] is root
    cfg_fd, why = _trusted_config_fd(path.parents[2])
    if cfg_fd is None:
        # fallback: still refuse if the path itself is a symlink
        if path.is_symlink():
            out["exists"] = True
            out["is_symlink"] = True
            out["reason"] = "symlink"
            return out
        if why in {"runtime_missing", "config_missing", "root_missing"} and not path.exists() and not path.is_symlink():
            out["reason"] = "missing"
            return out
        out["reason"] = why
        return out
    try:
        flags = os.O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC
        try:
            fd = os.open(TOKEN_NAME, flags, dir_fd=cfg_fd)
        except FileNotFoundError:
            out["reason"] = "missing"
            return out
        except OSError as e:
            if e.errno in (errno.ELOOP, errno.EINVAL):
                out["exists"] = True
                out["is_symlink"] = True
                out["reason"] = "symlink"
                return out
            if e.errno == errno.ENXIO:
                out["exists"] = True
                out["reason"] = "not_regular"
                return out
            out["exists"] = True
            out["reason"] = "unreadable"
            return out
        try:
            st, meta_why = _fstat_regular(fd)
            out["exists"] = True
            if st is None:
                out["reason"] = meta_why
                return out
            out["is_file"] = True
            out["owner_ok"] = True
            out["nlink_ok"] = True
            out["mode_ok"] = (st.st_mode & 0o777) == 0o600
            raw = b""
            while len(raw) <= MAX_BYTES:
                chunk = os.read(fd, min(512, MAX_BYTES + 1 - len(raw)))
                if not chunk:
                    break
                raw += chunk
                if len(raw) > MAX_BYTES:
                    out["reason"] = "too_large"
                    return out
            ok, parse_why = _parse_token_bytes(raw)
            out["nonempty"] = ok
            if not ok:
                out["reason"] = parse_why
                return out
            if not out["mode_ok"]:
                out["reason"] = "mode"
                return out
            body = raw[:-1] if raw.endswith(b"\n") else raw
            out["ok"] = True
            out["reason"] = "ok"
            out["value"] = body
            return out
        finally:
            os.close(fd)
    finally:
        os.close(cfg_fd)


def _read_value_bytes(path: Path) -> bytes | None:
    info = inspect_token_file(path)
    if not info["ok"]:
        return None
    return info["value"]


def _open_lock(cfg_fd: int) -> tuple[int | None, str]:
    flags = os.O_RDWR | os.O_CREAT | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK
    try:
        fd = os.open(LOCK_NAME, flags, 0o600, dir_fd=cfg_fd)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.EINVAL):
            return None, "lock_symlink"
        return None, "lock_unreadable"
    st, why = _fstat_regular(fd)
    if st is None:
        os.close(fd)
        return None, "lock_" + why
    mode = st.st_mode & 0o777
    if mode & 0o077:
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            os.close(fd)
            return None, "lock_mode"
    return fd, "ok"


def _fsync_dir(cfg_fd: int) -> str:
    try:
        os.fsync(cfg_fd)
        return "ok"
    except OSError as e:
        if e.errno in (errno.EINVAL, errno.ENOTSUP) or getattr(errno, "ENOTTY", -1) == e.errno:
            return "unsupported"
        return "failed"


def provision(*, root: Path | None = None) -> dict:
    root = Path(root) if root is not None else repo_root()
    path = token_path(root=root)
    with _PROC_LOCK:
        return _provision_locked(root, path)


def _provision_locked(root: Path, path: Path) -> dict:
    cfg_fd, why = _trusted_config_fd(root)
    if cfg_fd is None:
        return {"created": False, "ok": False, "reason": why, "mode_ok": False, "durability": "n/a"}
    lock_fd = None
    tmp_name = None
    try:
        import fcntl
        lock_fd, lock_why = _open_lock(cfg_fd)
        if lock_fd is None:
            return {"created": False, "ok": False, "reason": lock_why, "mode_ok": False, "durability": "n/a"}
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        cur = inspect_token_file(path)
        if cur["ok"]:
            return {"created": False, "ok": True, "reason": "reused", "mode_ok": True, "durability": "n/a"}
        if cur["exists"] or cur["reason"] not in {"missing"}:
            return {
                "created": False, "ok": False,
                "reason": cur["reason"] if cur["reason"] != "ok" else "exists_untrusted",
                "mode_ok": cur["mode_ok"], "durability": "n/a",
            }
        tmp_name = f".{TOKEN_NAME}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC
        try:
            tfd = os.open(tmp_name, flags, 0o600, dir_fd=cfg_fd)
        except OSError:
            return {"created": False, "ok": False, "reason": "tmp_create", "mode_ok": False, "durability": "n/a"}
        try:
            val = secrets.token_urlsafe(32)
            payload = (val + "\n").encode("ascii")
            off = 0
            while off < len(payload):
                n = os.write(tfd, payload[off:])
                if n <= 0:
                    raise OSError("short write")
                off += n
            os.fsync(tfd)
        except OSError:
            os.close(tfd)
            try:
                os.unlink(tmp_name, dir_fd=cfg_fd)
            except OSError:
                pass
            return {"created": False, "ok": False, "reason": "write_failed", "mode_ok": False, "durability": "n/a"}
        os.close(tfd)
        try:
            os.link(tmp_name, TOKEN_NAME, src_dir_fd=cfg_fd, dst_dir_fd=cfg_fd)
        except FileExistsError:
            try:
                os.unlink(tmp_name, dir_fd=cfg_fd)
            except OSError:
                pass
            again = inspect_token_file(path)
            if again["ok"]:
                return {"created": False, "ok": True, "reason": "reused", "mode_ok": True, "durability": "n/a"}
            return {"created": False, "ok": False, "reason": "exists_untrusted", "mode_ok": False, "durability": "n/a"}
        except OSError:
            try:
                os.unlink(tmp_name, dir_fd=cfg_fd)
            except OSError:
                pass
            return {"created": False, "ok": False, "reason": "publish_failed", "mode_ok": False, "durability": "n/a"}
        try:
            os.unlink(tmp_name, dir_fd=cfg_fd)
        except OSError:
            pass
        tmp_name = None
        dur = _fsync_dir(cfg_fd)
        chk = inspect_token_file(path)
        return {
            "created": True,
            "ok": chk["ok"],
            "reason": "created" if chk["ok"] else chk["reason"],
            "mode_ok": chk["mode_ok"],
            "durability": dur,
        }
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name, dir_fd=cfg_fd)
            except OSError:
                pass
        if lock_fd is not None:
            try:
                import fcntl
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except Exception:
                pass
            os.close(lock_fd)
        os.close(cfg_fd)


def require_file(*, root: Path | None = None) -> int:
    path = token_path(root=root)
    info = inspect_token_file(path)
    print("token_file_ok", info["ok"], "reason", info["reason"], "mode_ok", info["mode_ok"])
    return 0 if info["ok"] else 78


def env_matches_file(*, root: Path | None = None, require_loaded: bool = False) -> int:
    path = token_path(root=root)
    info = inspect_token_file(path)
    if not info["ok"]:
        print("token_file_ok", False, "reason", info["reason"])
        return 78
    env = os.environ.get("GRID_STORE_TOKEN")
    if env is None or env == "":
        print("env_set", False, "conflict", False, "loaded", False)
        return 78 if require_loaded else 0
    file_val = info["value"] or b""
    try:
        env_b = env.encode("ascii")
    except UnicodeEncodeError:
        print("env_set", True, "conflict", True, "loaded", False)
        return 79
    same = hmac.compare_digest(env_b, file_val)
    print("env_set", True, "conflict", (not same), "loaded", same)
    return 0 if same else 79


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="GRID_STORE_TOKEN helper. --root is the repo root.",
    )
    p.add_argument("--root", default="", help="repo root (not runtime root)")
    p.add_argument("--provision", action="store_true", help="create if missing; never overwrite a valid file")
    p.add_argument("--require-file", action="store_true")
    p.add_argument("--env-matches-file", action="store_true",
                   help="if env unset: no conflict (exit 0); if set: must match")
    p.add_argument("--env-loaded", action="store_true",
                   help="strict: env must be set and match file")
    p.add_argument("--inspect", action="store_true")
    a = p.parse_args(argv)
    ops = [a.provision, a.require_file, a.env_matches_file, a.env_loaded, a.inspect]
    if sum(bool(x) for x in ops) != 1:
        p.print_help()
        return 2
    root = Path(a.root).resolve() if a.root else None
    try:
        if a.require_file:
            return require_file(root=root)
        if a.env_matches_file:
            return env_matches_file(root=root, require_loaded=False)
        if a.env_loaded:
            return env_matches_file(root=root, require_loaded=True)
        if a.inspect:
            info = inspect_token_file(token_path(root=root))
            print("ok", info["ok"], "reason", info["reason"], "mode_ok", info["mode_ok"],
                  "is_file", info["is_file"], "is_symlink", info["is_symlink"])
            return 0 if info["ok"] else 1
        r = provision(root=root)
        print("created", r["created"], "ok", r["ok"], "reason", r["reason"],
              "mode_ok", r["mode_ok"], "durability", r.get("durability"))
        return 0 if r["ok"] else 1
    except Exception as exc:
        _print_exc(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Copy only regular files/dirs from a job work tree. No symlink/hardlink/device/FIFO."""
from __future__ import annotations
import argparse, os, stat, sys
from pathlib import Path

MAX_FILES = int(os.environ.get("EXPORT_MAX_FILES", "400"))
MAX_BYTES = int(os.environ.get("EXPORT_MAX_BYTES", "20000000"))


class ExportReject(Exception):
    pass


def _is_within(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def export_tree(src: str, dst: str) -> dict:
    src_p = Path(src)
    dst_p = Path(dst)
    if not src_p.is_dir() or src_p.is_symlink():
        raise ExportReject("src must be a real directory")
    if dst_p.exists() and (dst_p.is_symlink() or not dst_p.is_dir()):
        raise ExportReject("dst must be a real directory")
    dst_p.mkdir(parents=True, exist_ok=True)
    src_real = src_p.resolve()
    dst_real = dst_p.resolve()
    if dst_real.is_symlink():
        raise ExportReject("dst resolved to symlink")
    files = 0
    bytes_n = 0
    copied = []
    for dirpath, dirnames, filenames in os.walk(src_real, followlinks=False):
        rel_dir = Path(dirpath).resolve()
        if not _is_within(src_real, rel_dir):
            raise ExportReject("walk escaped src")
        st = os.lstat(dirpath)
        if stat.S_ISLNK(st.st_mode):
            raise ExportReject("directory symlink")
        # do not walk into symlink dirs
        keep = []
        for name in dirnames:
            if name in {".claude", ".git"}:
                continue
            p = Path(dirpath) / name
            lst = os.lstat(p)
            if stat.S_ISLNK(lst.st_mode):
                raise ExportReject(f"symlink dir {name}")
            if not stat.S_ISDIR(lst.st_mode):
                raise ExportReject(f"special dirent {name}")
            keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(src_real)
            if rel.is_absolute() or ".." in rel.parts:
                raise ExportReject("bad relative path")
            lst = os.lstat(p)
            mode = lst.st_mode
            if stat.S_ISLNK(mode):
                raise ExportReject(f"symlink {rel}")
            if stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
                raise ExportReject(f"special file {rel}")
            if not stat.S_ISREG(mode):
                raise ExportReject(f"not regular {rel}")
            if lst.st_nlink > 1:
                raise ExportReject(f"hardlink {rel}")
            dest = (dst_real / rel).resolve()
            if not _is_within(dst_real, dest):
                raise ExportReject("dst escape")
            if dest.exists() and dest.is_symlink():
                raise ExportReject("dst symlink")
            dest.parent.mkdir(parents=True, exist_ok=True)
            size = lst.st_size
            if files + 1 > MAX_FILES or bytes_n + size > MAX_BYTES:
                raise ExportReject("export budget")
            with open(p, "rb") as inf, open(dest, "wb") as outf:
                while True:
                    chunk = inf.read(1024 * 64)
                    if not chunk:
                        break
                    outf.write(chunk)
            files += 1
            bytes_n += size
            copied.append(str(rel))
    return {"ok": True, "files": files, "bytes": bytes_n, "copied": copied}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("dst")
    a = p.parse_args(argv)
    try:
        r = export_tree(a.src, a.dst)
    except ExportReject as e:
        print(f"REJECT {e}", file=sys.stderr)
        return 2
    print(f"ok files={r['files']} bytes={r['bytes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

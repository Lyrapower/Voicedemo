"""记忆宫殿共用工具:frontmatter 读写 + 房间 _index 自动维护。纯 stdlib。"""
from __future__ import annotations
import os, re, datetime as dt

VAULT = os.environ.get("PALACE_VAULT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vault"))

def slugify(s: str, maxlen: int = 40) -> str:
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r'[\\/:"*?<>|]+', "", s)
    return s[:maxlen] or "untitled"

def write_note(room: str, title: str, frontmatter: dict, body: str) -> str:
    """写一篇 md 进指定房间,返回路径。自动去重(同名加时间戳)。"""
    room_dir = os.path.join(VAULT, room)
    os.makedirs(room_dir, exist_ok=True)
    fn = slugify(title) + ".md"
    path = os.path.join(room_dir, fn)
    if os.path.exists(path):
        path = os.path.join(room_dir, slugify(title) + "-" +
                            dt.datetime.now().strftime("%H%M%S") + ".md")
    fm = "---\n" + "".join(_fm_line(k, v) for k, v in frontmatter.items()) + "---\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(fm + "\n# " + title + "\n\n" + body + "\n")
    update_room_index(room)
    return path

def _fm_line(k, v):
    if isinstance(v, list):
        return f"{k}: [{', '.join(map(str, v))}]\n"
    return f"{k}: {v}\n"

def read_frontmatter(path: str) -> dict:
    try:
        txt = open(path, encoding="utf-8").read()
    except Exception:
        return {}
    m = re.match(r"^---\n(.*?)\n---", txt, re.S)
    if not m: return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm

def update_room_index(room: str) -> None:
    """扫房间内所有 md(除 _index),把标题+status 写进 _index 的 AUTO 区块。"""
    room_dir = os.path.join(VAULT, room)
    idx = os.path.join(room_dir, "_index.md")
    if not os.path.exists(idx): return
    rows = []
    for fn in sorted(os.listdir(room_dir)):
        if not fn.endswith(".md") or fn == "_index.md": continue
        fm = read_frontmatter(os.path.join(room_dir, fn))
        stat = fm.get("status", "?")
        created = fm.get("created", "")
        name = fn[:-3]
        mark = "🔵" if stat == "unsorted" else "✓"
        rows.append(f"- {mark} [[{name}]] · {created} · `{stat}`")
    block = "<!-- AUTO-INDEX-START -->\n" + ("\n".join(rows) if rows else "*(空)*") + "\n<!-- AUTO-INDEX-END -->"
    txt = open(idx, encoding="utf-8").read()
    txt = re.sub(r"<!-- AUTO-INDEX-START -->.*?<!-- AUTO-INDEX-END -->",
                 block, txt, flags=re.S)
    open(idx, "w", encoding="utf-8").write(txt)

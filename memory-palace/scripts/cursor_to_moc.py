"""Cursor 项目 → MOC 地图。扫 ~/Projects 下每个 git repo,生成导航卡片进 vault。
   只读源码,不拷贝:vault 存地图,git 存真身。
   用法:
     python3 cursor_to_moc.py                    # 扫默认 ~/Projects
     PROJECTS_ROOT=/path python3 cursor_to_moc.py
"""
from __future__ import annotations
import os, sys, subprocess, collections, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import palace_lib as P

ROOT = os.environ.get("PROJECTS_ROOT", os.path.expanduser("~/Projects"))
CODE_EXT = {".py":"Python",".ts":"TypeScript",".tsx":"TypeScript",".js":"JavaScript",
            ".jsx":"JavaScript",".rs":"Rust",".go":"Go",".glsl":"GLSL",".sh":"Shell"}
AUX_EXT  = {".html":"HTML",".css":"CSS",".md":"Markdown",".json":"JSON",".toml":"TOML"}
LANG_EXT = {**CODE_EXT, **AUX_EXT}
SKIP_DIRS = {".git","node_modules","__pycache__",".venv","venv","dist","build",".next","target"}

def git_info(repo: str) -> dict:
    def run(args):
        try:
            return subprocess.run(["git","-C",repo]+args, capture_output=True,
                                  text=True, timeout=10).stdout.strip()
        except Exception:
            return ""
    return {
        "last_commit": run(["log","-1","--format=%cd (%h) %s","--date=short"]) or "—",
        "branch": run(["rev-parse","--abbrev-ref","HEAD"]) or "—",
        "n_commits": run(["rev-list","--count","HEAD"]) or "?",
    }

def scan_repo(repo: str) -> dict:
    langs = collections.Counter(); code_langs = collections.Counter()
    key_files = []; tree_lines = []; total = 0
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        depth = dirpath[len(repo):].count(os.sep)
        if depth <= 1:
            rel = os.path.relpath(dirpath, repo)
            if rel != ".":
                tree_lines.append("  "*(depth-1) + "📁 " + os.path.basename(dirpath) + "/")
        for fn in filenames:
            ext = os.path.splitext(fn)[1]
            if ext in LANG_EXT:
                langs[LANG_EXT[ext]] += 1; total += 1
                if ext in CODE_EXT:
                    code_langs[CODE_EXT[ext]] += 1
            # 关键文件识别
            low = fn.lower()
            if low in ("readme.md","work_order.md","charter.md","package.json",
                       "requirements.txt","cargo.toml","main.py","app.py","index.html"):
                key_files.append(os.path.relpath(os.path.join(dirpath, fn), repo))
    return {"langs": langs, "code_langs": code_langs, "key_files": sorted(set(key_files))[:12],
            "tree": "\n".join(tree_lines[:20]), "n_code_files": total}

def make_moc(repo: str) -> str | None:
    name = os.path.basename(repo)
    if not os.path.isdir(os.path.join(repo, ".git")):
        return None                          # 只收 git repo
    gi = git_info(repo); sc = scan_repo(repo)
    lang_str = ", ".join(f"{k} {v}" for k,v in sc["langs"].most_common(4)) or "—"
    primary = (sc["code_langs"].most_common(1)[0][0] if sc["code_langs"]
               else sc["langs"].most_common(1)[0][0] if sc["langs"] else "—")
    fm = {
        "type":"project-moc","created":dt.date.today().isoformat(),"source":"cursor",
        "status":"sorted","room":"01-项目Projects","repo_path":repo,
        "language":primary,"last_commit":gi["last_commit"].split(" (")[0] or "—",
        "branch":gi["branch"],"code_files":sc["n_code_files"],
        "tags":["project"],
    }
    key_links = "\n".join(f"- [`{kf}`](file://{os.path.join(repo,kf)})" for kf in sc["key_files"]) or "—"
    body = f"""> {lang_str} · {sc['n_code_files']} 源码文件 · {gi['n_commits']} commits · `{gi['branch']}`

**真身路径**: [`{repo}`](file://{repo}) — 源码在 git,此处仅地图

## 最近改动
{gi['last_commit']}

## 结构
```
{sc['tree'] or '(扁平)'}
```

## 关键文件
{key_links}

## 关联
<!-- 手动或后续脚本补双链:[[其他项目]] · [[相关法典]] -->
"""
    return P.write_note("01-项目Projects", name, fm, body)

def main():
    if not os.path.isdir(ROOT):
        print(f"未找到项目根目录: {ROOT}(设 PROJECTS_ROOT 环境变量指定)"); return
    made = []
    for entry in sorted(os.listdir(ROOT)):
        repo = os.path.join(ROOT, entry)
        if os.path.isdir(repo):
            path = make_moc(repo)
            if path: made.append(os.path.basename(path)); print(f"  ✓ {entry}")
    print(f"\n生成 {len(made)} 张项目地图 → vault/01-项目Projects/")
    print("源码零拷贝,vault 只存导航。Obsidian graph 现可见 Grid 全貌。")

if __name__ == "__main__":
    main()

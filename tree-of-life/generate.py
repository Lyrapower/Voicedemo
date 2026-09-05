#!/usr/bin/env python3
"""Tree of Life — trunk / branch / leaf hierarchy + vector map (auto-generated)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "output"
BACKUP_ROOT = Path.home() / "2td" / "grid-stack-backup"

LAUNCH_PORTS = [5173, 8501, 8502, 8503, 8504, 8510, 8520, 8686, 8787, 8788, 8790, 1234]

WATCH_GLOBS = [
    "scripts/**/launchd/*.plist",
    "config/aster.toml",
    "repo/app/main.py",
    "aster-field/backend/**/*.py",
    "aster-field/frontend/vite.config.ts",
    "grid-sovereign-runtime/gateway/**/*.py",
    "grid-sovereign-runtime/gateway/static/*.html",
    "scripts/sound_lab_fallback.py",
    "aether_nexus/**/*.py",
    "aether-paper/paper/emit.py",
    "aster-diary/diary.py",
    "PORT_PROCESS_CONVENTION.md",
    "scripts/backup_stack_to_2td.sh",
]

# 2td backup partition ↔ branch mapping
BACKUP_PARTITIONS = {
    "01_gateway8501": "branch:sovereign",
    "02_egress8502_8503": "branch:egress",
    "03_voice8504": "branch:voice",
    "04_field8790": "branch:garden.field",
    "05_garden8787_5173_8788": "branch:garden.entry",
    "06_aether8510_daemons": "branch:aether",
    "07_watcher8520": "branch:aether.watcher",
    "08_jarvis8686": "branch:jarvis",
    "09_aster_diary": "branch:diary",
    "10_ocr_text_inbox": "branch:ocr",
    "11_aster_grid_v5": "branch:distill",
    "12_phototextvault": "branch:ocr",
    "13_aether_paper": "branch:aether.paper",
    "14_launchagents_installed": "branch:ops",
    "15_runtime_logs": "branch:ops",
    "16_shared_config": "branch:ops",
    "17_lmstudio_plugin": "branch:ingress.lmstudio",
    "18_grid_traces": "branch:sovereign.traces",
    "19_lmstudio_demo_aster": "branch:ingress.lmstudio",
    "00_tree_of_life": "branch:meta",
}


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as exc:
        return str(exc)


def live_ports() -> dict[int, dict]:
    out: dict[int, dict] = {}
    for p in LAUNCH_PORTS:
        pid = _run(["lsof", "-ti", f"TCP:{p}", "-sTCP:LISTEN"]).strip().split("\n")[0].strip()
        if pid and pid.isdigit():
            out[p] = {"pid": int(pid), "command": _run(["ps", "-p", pid, "-o", "command="]).strip()[:280]}
    return out


def launchagents() -> list[dict]:
    rows: list[dict] = []
    for plist in sorted((Path.home() / "Library/LaunchAgents").glob("com.demo.*.plist")):
        text = plist.read_text(encoding="utf-8", errors="replace")
        script = ""
        if m := re.search(r"<string>([^<]*(?:start|\.sh)[^<]*)</string>", text, re.I):
            script = m.group(1).replace("__DEMO_ROOT__", str(ROOT)).replace("__HOME__", str(Path.home()))
        port = next((int(pm.group(1)) for pm in re.finditer(r"<string>(\d{4,5})</string>", text)
                     if int(pm.group(1)) in LAUNCH_PORTS), None)
        rows.append({"label": plist.stem, "plist": str(plist), "script": script, "port": port})
    ocr = Path.home() / "Library/LaunchAgents/com.ocr_text_inbox.weekly.plist"
    if ocr.is_file():
        rows.append({"label": "com.ocr_text_inbox.weekly", "plist": str(ocr),
                     "script": str(ROOT / "scripts/ocr_text_inbox/run_weekly_sync.sh"), "port": None})
    return rows


def _read(rel: str) -> str:
    try:
        return (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def build_taxonomy(live: dict, agents: list[dict]) -> dict:
    """Trunk → Branch → Twig → Leaf (growth / fork model)."""
    trunk = {
        "id": "trunk:8501-sovereign",
        "role": "trunk",
        "label": "8501 Grid Sovereign + grid_store 记忆",
        "port": 8501,
        "live": live.get(8501),
        "files": [
            "grid-sovereign-runtime/gateway/local_gateway.py",
            "grid-sovereign-runtime/gateway/grid_store.py",
            "grid-sovereign-runtime/data/grid_store.db",
        ],
        "backup_partition": "01_gateway8501",
        "branches": [],
    }

    def branch(bid: str, label: str, port: int | None, backup: str, twigs: list[dict]) -> dict:
        return {
            "id": bid,
            "role": "branch",
            "label": label,
            "port": port,
            "live": live.get(port) if port else None,
            "backup_partition": backup,
            "twigs": twigs,
        }

    def twig(tid: str, label: str, port: int | None, files: list[str], leaves: list[dict]) -> dict:
        return {"id": tid, "role": "twig", "label": label, "port": port,
                "live": live.get(port) if port else None, "files": files, "leaves": leaves}

    def leaf(lid: str, label: str, kind: str, target: str | None = None, files: list[str] | None = None) -> dict:
        return {"id": lid, "role": "leaf", "label": label, "vector_kind": kind,
                "target": target, "files": files or []}

    branches = [
        branch("branch:ingress", "Ingress · 外部入口", None, "17_lmstudio_plugin", [
            twig("twig:tailscale", "Tailscale Serve → 8501", None,
                 ["scripts/setup_tailscale_gateway.sh", "config/aster.toml"],
                 [leaf("leaf:ts-https", "HTTPS tailnet", "proxy", "trunk:8501-sovereign")]),
            twig("twig:lmstudio", "LM Studio :1234 · Qwen substrate + demo/aster", 1234,
                 ["config/aster.toml", "lmstudio-plugins/aster-grid-gateway",
                  "lmstudio-models/demo/aster/model.yaml", "models/aster_config.py"],
                 [
                     leaf("leaf:demo-aster-model", "My Models → demo/aster (virtual on qwen3.5-9b)", "read", None,
                          files=["lmstudio-models/demo/aster/model.yaml",
                                   "~/.lmstudio/hub/models/demo/aster/model.yaml"]),
                     leaf("leaf:lm-chat", "generator plugin → /v1/chat/completions @8501", "api", "trunk:8501-sovereign"),
                 ]),
        ]),
        branch("branch:garden", "Garden Entry B · 8787/5173/8790", 8787, "05_garden8787_5173_8788", [
            twig("twig:8787-router", "8787 Aster router / proxy", 8787,
                 ["repo/app/main.py", "config/aster.toml"],
                 [
                     leaf("leaf:8787→5173", "GET/HEAD proxy legacy UI", "proxy", "twig:5173-legacy"),
                     leaf("leaf:8787→8790", "GET / redirect FIELD", "proxy", "twig:8790-field"),
                     leaf("leaf:8787→8501", "POST /api/dialogue → gateway", "api", "trunk:8501-sovereign"),
                 ]),
            twig("twig:5173-legacy", "5173 Legacy Garden UI", 5173,
                 ["scripts/sound_lab_fallback.py"],
                 [leaf("leaf:5173→8787", "JS API_BASE → 8787", "api", "twig:8787-router")]),
            twig("twig:8790-field", "8790 ASTER FIELD", 8790,
                 ["aster-field/backend/app.py", "aster-field/backend/chat_memory.py"],
                 [
                     leaf("leaf:8790-chat", "POST /chat → 8501 gateway", "api", "trunk:8501-sovereign"),
                     leaf("leaf:8790-memory", "POST/GET /store/conversations field-particle", "emit+read", "trunk:8501-sovereign"),
                     leaf("leaf:8790-diary", "GET /diary/* local sqlite", "read", "branch:diary"),
                     leaf("leaf:8790-sse", "GET /state SSE", "api", None),
                 ]),
        ]),
        branch("branch:pages-8501", "8501 静态页 · Grid App", 8501, "01_gateway8501", [
            twig("twig:changyu", "changyu.html 场域/粒子/Fable", None,
                 ["grid-sovereign-runtime/gateway/static/changyu.html"],
                 [
                     leaf("leaf:cy-store", "/store/conversations + /store/events", "read", "trunk:8501-sovereign"),
                     leaf("leaf:cy-chat", "POST /v1/chat/completions", "api", "trunk:8501-sovereign"),
                     leaf("leaf:cy-fable", "Fable via :8503 egress", "api", "branch:egress"),
                 ]),
            twig("twig:aether-page", "aether.html trading UI", None,
                 ["grid-sovereign-runtime/gateway/static/aether.html"],
                 [leaf("leaf:ae-events", "/store/events snapshot+recent", "read", "trunk:8501-sovereign")]),
            twig("twig:daemon-dash", "daemon_dashboard.html", None,
                 ["grid-sovereign-runtime/gateway/static/daemon_dashboard.html"],
                 [leaf("leaf:dd-fleet", "GET /store/fleet", "read", "trunk:8501-sovereign")]),
        ]),
        branch("branch:aether", "Aether · 8510 + daemons", 8510, "06_aether8510_daemons", [
            twig("twig:8510-ui", "8510 Streamlit Nexus", 8510,
                 ["aether_nexus/aether_dashboard.py"],
                 [leaf("leaf:8510-read", "reads grid_store / pipeline", "read", "trunk:8501-sovereign")]),
            twig("twig:aether-daemons", "Scheduled daemons (no port)", None,
                 ["aether_nexus/aether_grid_emit.py"],
                 [
                     leaf("leaf:emit-scan", "aether_scan/filter/momentum", "emit", "trunk:8501-sovereign"),
                     leaf("leaf:emit-offpool", "aether_offpool", "emit", "trunk:8501-sovereign"),
                     leaf("leaf:emit-premarket", "aether_premarket_grid/sonnet", "emit", "trunk:8501-sovereign"),
                     leaf("leaf:emit-brief", "aether_brief", "emit", "trunk:8501-sovereign"),
                     leaf("leaf:emit-earnings", "aether_sonnet_earnings", "emit", "trunk:8501-sovereign"),
                 ]),
        ]),
        branch("branch:aether.watcher", "Watcher · 8520", 8520, "07_watcher8520", [
            twig("twig:8520-ui", "8520 Streamlit Watcher", 8520,
                 ["aether_watcher/watcher_dashboard.py"], []),
        ]),
        branch("branch:jarvis", "Jarvis · 8686", 8686, "08_jarvis8686", [
            twig("twig:8686-platform", "8686 workbench", 8686,
                 ["app/platform_main.py"], []),
        ]),
        branch("branch:egress", "Egress sidecars", 8502, "02_egress8502_8503", [
            twig("twig:8502-ark", "8502 Ark egress", 8502, ["grid-sovereign-runtime/egress.py"], []),
            twig("twig:8503-anthropic", "8503 Anthropic/Fable egress", 8503,
                 ["scripts/start_egress_anthropic.sh"], []),
        ]),
        branch("branch:voice", "Voice · 8504", 8504, "03_voice8504", [
            twig("twig:8504-voice", "8504 ASR/TTS", 8504,
                 ["grid-sovereign-runtime/gateway/voice_daemon.py"], []),
        ]),
        branch("branch:diary", "Diary · 22:30 + 8790 UI", None, "09_aster_diary", [
            twig("twig:diary-writer", "aster-diary daemon", None,
                 ["aster-diary/diary.py"],
                 [
                     leaf("leaf:diary-emit", "grid_diary → /store/events", "emit", "trunk:8501-sovereign"),
                     leaf("leaf:diary-thread", "fetch_thread_context 7d", "read", "trunk:8501-sovereign"),
                     leaf("leaf:diary-field", "POST FIELD /diary", "api", "twig:8790-field"),
                 ]),
        ]),
        branch("branch:ocr", "OCR Text Inbox", None, "10_ocr_text_inbox", [
            twig("twig:ocr-inbox", "Desktop OCR_Text_Inbox", None,
                 ["scripts/ocr_text_inbox/weekly_sync.py"],
                 [leaf("leaf:ocr-weekly", "weekly sync launchd", "schedule", None)]),
        ]),
        branch("branch:distill", "Fable / V5 distill", None, "11_aster_grid_v5", [
            twig("twig:v5-distill", "aster_grid_v5 harness", None,
                 ["aster_grid_v5/distill/aster_distill_harness_v1_1.py"],
                 [leaf("leaf:distill-emit", "distill_harness → /store/events", "emit", "trunk:8501-sovereign")]),
        ]),
        branch("branch:aether.paper", "Paper trading engine", None, "13_aether_paper", [
            twig("twig:paper", "aether-paper daemons", None,
                 ["aether-paper/paper/emit.py"],
                 [leaf("leaf:paper-emit", "wallet/fill/daily → store", "emit", "trunk:8501-sovereign")]),
        ]),
        branch("branch:ops", "Ops · launchagents + logs + config", None, "14_launchagents_installed", [
            twig("twig:launchagents", f"{len(agents)} installed agents", None, [], []),
        ]),
    ]

    trunk["branches"] = branches

    # Flatten vectors for graph
    vectors: list[dict] = []
    for b in branches:
        for tw in b.get("twigs", []):
            for lf in tw.get("leaves", []):
                vectors.append({
                    "from": lf["id"],
                    "from_twig": tw["id"],
                    "from_branch": b["id"],
                    "to": lf.get("target"),
                    "kind": lf["vector_kind"],
                    "label": lf["label"],
                    "files": lf.get("files", []) + tw.get("files", []),
                })

    return {"trunk": trunk, "branches": branches, "vectors": vectors}


def edges_from_taxonomy(tax: dict) -> list[dict]:
    edges: list[dict] = []
    for v in tax["vectors"]:
        if not v.get("to"):
            continue
        edges.append({
            "from": v["from"],
            "to": v["to"],
            "kind": v["kind"].split("+")[0],
            "detail": v["label"],
            "files": v.get("files", []),
        })
    return edges


def mermaid_taxonomy(tax: dict) -> str:
    lines = [
        "flowchart TB",
        "  TRUNK[(8501 Trunk\\nGateway + Memory)]",
        "  subgraph branches[Branches 枝]",
    ]
    for b in tax["branches"]:
        bid = b["id"].replace(":", "_").replace(".", "_")
        lines.append(f"    subgraph {bid}[\"{b['label']}\"]")
        for tw in b.get("twigs", []):
            tid = tw["id"].replace(":", "_").replace(".", "_")
            p = f" :{tw['port']}" if tw.get("port") else ""
            lines.append(f"      {tid}[\"{tw['label']}{p}\"]")
        lines.append("    end")
        lines.append(f"    TRUNK --> {bid}")
    lines.append("  end")
    kind_arrow = {"proxy": "-.->", "api": "-->", "read": "-.->", "emit": "==>", "schedule": "-.->"}
    for v in tax["vectors"][:40]:
        if not v.get("to"):
            continue
        src = v["from"].replace(":", "_").replace(".", "_")
        dst = v["to"].replace(":", "_").replace(".", "_")
        arr = kind_arrow.get(v["kind"].split("+")[0], "-->")
        lines.append(f"  {src} {arr} {dst}")
    return "\n".join(lines)


def audit_2td() -> dict:
    report = {"backup_root": str(BACKUP_ROOT), "tree_root": str(Path.home() / "2td" / "tree-of-life"), "groups": {}}
    latest = BACKUP_ROOT / "latest"
    if latest.is_symlink() or latest.is_dir():
        target = latest.resolve() if latest.is_symlink() else latest
        for part in list(BACKUP_PARTITIONS.keys()) + ["00_tree_of_life"]:
            p = target / part
            report["groups"][part] = {
                "present": p.is_dir() or p.is_file(),
                "bytes": sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0,
            }
    tol = Path.home() / "2td" / "tree-of-life" / "latest"
    report["tree_of_life"] = {
        "present": tol.is_dir() or tol.is_symlink(),
        "has_json": (tol / "tree_of_life.json").exists() if tol.exists() else False,
        "has_taxonomy": False,
    }
    if report["tree_of_life"]["has_json"]:
        try:
            data = json.loads((tol / "tree_of_life.json").read_text())
            report["tree_of_life"]["has_taxonomy"] = "taxonomy" in data
            report["tree_of_life"]["generated_at"] = data.get("generated_at")
        except Exception:
            pass
    report["missing_groups"] = [k for k, v in report["groups"].items() if not v["present"]]
    return report


def html_doc(doc: dict) -> str:
    tax = doc.get("taxonomy", {})
    trunk = tax.get("trunk", {})
    branches_html = ""
    for b in tax.get("branches", []):
        twigs = "".join(
            f"<li><b>{tw['label']}</b>"
            + (f" <code>:{tw['port']}</code>" if tw.get("port") else "")
            + "<ul>" + "".join(f"<li class='leaf'>{lf['label']} → <code>{lf.get('target','')}</code></li>"
                               for lf in tw.get("leaves", [])) + "</ul></li>"
            for tw in b.get("twigs", [])
        )
        branches_html += f"<details open><summary>{b['label']} · backup <code>{b.get('backup_partition','')}</code></summary><ul>{twigs}</ul></details>"

    audit = doc.get("audit_2td", {})
    missing = audit.get("missing_groups", [])
    audit_line = f"2td missing: {missing}" if missing else "2td backup groups: OK"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>Tree of Life</title>
<style>
:root{{--bg:#070b12;--ink:#c7d3dd;--accent:#8fd8e8;--muted:#6b7a88;--line:#223140;--leaf:#e8c98a}}
body{{font:14px/1.65 -apple-system,sans-serif;background:var(--bg);color:var(--ink);padding:24px;max-width:920px;margin:0 auto}}
h1{{font:400 24px "Songti SC",serif;color:var(--accent);letter-spacing:.25em}}
.trunk{{border:2px solid var(--accent);border-radius:12px;padding:16px;margin:20px 0;background:#101823}}
.trunk h2{{font-size:14px;letter-spacing:.15em;margin:0 0 8px;color:var(--accent)}}
details{{border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:10px 0;background:#0d1219}}
summary{{cursor:pointer;color:var(--accent);letter-spacing:.08em}}
.leaf{{color:var(--leaf);font-size:13px}}
.meta{{font:11px ui-monospace;color:var(--muted)}}
pre{{font:11px ui-monospace;overflow:auto;background:#101823;padding:12px;border-radius:8px;max-height:300px}}
.warn{{color:#c97b6e}}
</style></head><body>
<h1>Tree of Life · 生命之树</h1>
<p class="meta">generated {doc.get('generated_at')} · {audit_line}</p>
<div class="trunk">
<h2>主干 Trunk</h2>
<p><b>{trunk.get('label','')}</b> · port {trunk.get('port')} · backup <code>{trunk.get('backup_partition')}</code></p>
<p class="meta">All memory, conversations, events, diary thread converge on grid_store @ 8501</p>
</div>
<h2 style="color:var(--accent);letter-spacing:.15em;font-size:14px">枝 Branches → 杈 Twigs → 叶 Leaves</h2>
{branches_html}
<h2 style="color:var(--accent);letter-spacing:.15em;font-size:14px;margin-top:24px">Mermaid</h2>
<pre>{doc.get('mermaid','')}</pre>
<p class="meta">Regen: python3 tree-of-life/generate.py · Sync: bash tree-of-life/sync_to_2td.sh</p>
</body></html>"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    live = live_ports()
    agents = launchagents()
    tax = build_taxonomy(live, agents)
    edges = edges_from_taxonomy(tax)
    audit = audit_2td()

    doc = {
        "project": "tree-of-life",
        "ontology": {
            "trunk": "8501 sovereign gateway + grid_store — single memory root",
            "branch": "major vertical (Garden, Aether, Ingress, …) maps to 2td backup partition",
            "twig": "runnable unit (port / daemon / page bundle)",
            "leaf": "vector edge (proxy|api|read|emit) — growth tip",
        },
        "mac_project_path": str(ROOT / "tree-of-life"),
        "backup_partitions": BACKUP_PARTITIONS,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "live_ports": {str(k): v for k, v in live.items()},
        "launchagents_count": len(agents),
        "launchagents": agents,
        "taxonomy": tax,
        "edges": edges,
        "audit_2td": audit,
        "watch_globs": WATCH_GLOBS,
        "regen_command": "python3 tree-of-life/generate.py && bash tree-of-life/sync_to_2td.sh",
    }
    doc["mermaid"] = mermaid_taxonomy(tax)

    (OUT / "tree_of_life.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "tree_of_life.mmd").write_text(doc["mermaid"] + "\n", encoding="utf-8")
    (OUT / "tree_of_life.html").write_text(html_doc(doc), encoding="utf-8")
    (OUT / "audit_2td.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    n_leaves = sum(len(tw.get("leaves", [])) for b in tax["branches"] for tw in b.get("twigs", []))
    print(json.dumps({
        "ok": True,
        "branches": len(tax["branches"]),
        "vectors": len(tax["vectors"]),
        "leaves": n_leaves,
        "audit_missing": audit.get("missing_groups", []),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

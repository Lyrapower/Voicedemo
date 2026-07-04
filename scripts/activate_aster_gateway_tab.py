#!/usr/bin/env python3
"""Activate Aster tab → gateway generator without manual model picker clicks."""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models.aster_config import lm_studio_gateway_plugin, section

PLUGIN_ID = lm_studio_gateway_plugin()
CONV_ID = str(section("lm_studio")["conversation_id"])
CONV_PATH = Path.home() / f".lmstudio/conversations/{CONV_ID}.conversation.json"
PERMS_PATH = Path.home() / ".lmstudio/.internal/permissions-store.json"
UI_STATE = Path.home() / ".lmstudio/.internal/ui-state/window-1.json"


def _backup(path: Path) -> None:
    if path.is_file():
        bak = path.with_suffix(path.suffix + f".bak.{int(time.time())}")
        shutil.copy2(path, bak)


def _allow_plugins() -> None:
    if not PERMS_PATH.is_file():
        return
    data = json.loads(PERMS_PATH.read_text(encoding="utf-8"))
    root = data.get("json") or data
    root["serverPermissions"] = {
        **(root.get("serverPermissions") or {}),
        "pluginUse": "allow",
        "dynamicRemoteMcpServer": root.get("serverPermissions", {}).get("dynamicRemoteMcpServer", "deny"),
    }
    for tok in root.get("tokens") or []:
        perms = tok.get("permissions") or {}
        perms["pluginUse"] = "allow"
        tok["permissions"] = perms
    data["json"] = root
    _backup(PERMS_PATH)
    PERMS_PATH.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OK  pluginUse=allow → {PERMS_PATH}")


def _patch_conversation() -> None:
    if not CONV_PATH.is_file():
        raise SystemExit(f"Missing {CONV_PATH}")
    c = json.loads(CONV_PATH.read_text(encoding="utf-8"))
    c["plugins"] = sorted(set((c.get("plugins") or []) + [PLUGIN_ID]))
    c["tokenSourceIdentifier"] = {"type": "generator", "pluginIdentifier": PLUGIN_ID}
    c["lastUsedTokenSource"] = {"type": "generator", "pluginIdentifier": PLUGIN_ID}
    c["lastUsedModel"] = {
        "identifier": PLUGIN_ID,
        "indexedModelIdentifier": PLUGIN_ID,
        "instanceLoadTimeConfig": {"fields": []},
        "instanceOperationTimeConfig": {"fields": []},
    }
    notes = [n for n in (c.get("notes") or []) if not str(n).startswith("active=")]
    notes.insert(0, f"active=gateway generator {PLUGIN_ID}")
    c["notes"] = notes
    _backup(CONV_PATH)
    CONV_PATH.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK  conversation tokenSource → {PLUGIN_ID}")


def _patch_ui_state() -> None:
    if not UI_STATE.is_file():
        print(f"SKIP ui-state (missing {UI_STATE})")
        return
    ui = json.loads(UI_STATE.read_text(encoding="utf-8"))
    plugins = ui.setdefault("plugins", {})
    plugins["selectedPluginIdentifier"] = PLUGIN_ID
    chat = ui.setdefault("chat", {})
    chat["activeConversationIdentifier"] = f"{CONV_ID}.conversation.json"
    chat["activeToolSidebarTab"] = "model"
    _backup(UI_STATE)
    UI_STATE.write_text(json.dumps(ui, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK  ui-state selectedPlugin → {PLUGIN_ID}")


def main() -> int:
    plugin_dir = Path.home() / ".lmstudio/extensions/plugins/demo/aster-grid-gateway"
    if not (plugin_dir / ".lmstudio/production.js").is_file():
        print("WARN: plugin not built — run scripts/install_aster_gateway_plugin.sh first")
    _allow_plugins()
    _patch_conversation()
    _patch_ui_state()
    print("\nDone. Quit LM Studio fully (Cmd+Q), reopen, open Aster tab.")
    print("Top bar should show generator:", PLUGIN_ID)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

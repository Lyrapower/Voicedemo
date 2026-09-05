#!/usr/bin/env bash
# Full demo stack backup → ~/2td (or BACKUP_2TD_ROOT). Read-only; live paths unchanged.
#
# Groups (never mixed):
#   01_gateway8501          :8501 gateway + grid_store memory
#   02_egress8502_8503      Anthropic/API egress sidecars
#   03_voice8504            TTS voice daemon
#   04_field8790            ASTER FIELD particle bridge
#   05_garden8787_5173_8788 Entry B + legacy UI + telemetry + lms dev
#   06_aether8510_daemons   Aether Nexus UI + all trading daemons
#   07_watcher8520          Aether Watcher dashboard + daemon
#   08_jarvis8686           Jarvis workbench platform
#   09_aster_diary          Diary writer + FIELD diary.db (copy)
#   10_ocr_text_inbox       Desktop OCR_Text_Inbox + pipeline scripts
#   11_aster_grid_v5        V5 fable/distill stack (no .tools binaries)
#   12_phototextvault       Photo OCR vault helper
#   13_aether_paper         Paper trading engine + state
#   14_launchagents_installed  Snapshot of ~/Library/LaunchAgents/com.demo.*
#   15_runtime_logs         demo-* launchd logs (recent ops)
#   16_shared_config        Repo-wide config + architecture locks
#   17_lmstudio_plugin      aster-grid-gateway LM Studio plugin
#   18_grid_traces          grid-sovereign-runtime/traces (daemon/offpool)
#
# Usage:
#   bash scripts/backup_stack_to_2td.sh
#   BACKUP_2TD_ROOT=/Volumes/My2TB bash scripts/backup_stack_to_2td.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST_ROOT="${BACKUP_2TD_ROOT:-$HOME/2td}/grid-stack-backup"
STAMP="$(date +%Y-%m-%dT%H%M%S)"
OUT="${DEST_ROOT}/${STAMP}"
ANCHOR="${FIELD_MEMORY_EPOCH_ANCHOR:-2026-07-16}"
GS="${ROOT}/grid-sovereign-runtime"
OCR_INBOX="${OCR_TEXT_INBOX:-$HOME/Desktop/OCR_Text_Inbox}"

RSYNC=(rsync -a)
EXCLUDE=(
  --exclude '.git'
  --exclude 'node_modules'
  --exclude '__pycache__'
  --exclude '.pytest_cache'
  --exclude '.venv'
  --exclude '.venv_*'
  --exclude '*.pyc'
)

mkdir -p "${OUT}"
echo "=== full backup → ${OUT} ==="

# ── 00 tree-of-life (auto-generated map, separate 2td partition too) ─────
G0="${OUT}/00_tree_of_life"
bash "${ROOT}/tree-of-life/sync_to_2td.sh" >/dev/null
mkdir -p "${G0}"
rsync -a "${ROOT}/tree-of-life/output/" "${G0}/"
mkdir -p "${G0}/_generator"
cp -p "${ROOT}/tree-of-life/generate.py" "${ROOT}/tree-of-life/sync_to_2td.sh" "${ROOT}/tree-of-life/README.md" "${G0}/_generator/"

# ── runtime snapshot ────────────────────────────────────────────────────
{
  echo "# captured ${STAMP}"
  echo "## launchctl com.demo.*"
  launchctl list 2>/dev/null | rg 'com\.demo\.|com\.ocr' || true
  echo ""
  echo "## listening ports"
  for p in 5173 8501 8502 8503 8504 8510 8520 8686 8787 8788 8790 1234; do
    pid=$(lsof -tiTCP:"${p}" -sTCP:LISTEN 2>/dev/null | head -1 || true)
    if [[ -n "${pid}" ]]; then
      ps -p "${pid}" -o command= 2>/dev/null | sed "s/^/:${p} pid=${pid} /"
    fi
  done
} > "${OUT}/RUNNING_SERVICES.txt"

copy_plists() {
  local dest="$1"
  shift
  mkdir -p "${dest}"
  for pat in "$@"; do
    cp -p ${pat} "${dest}/" 2>/dev/null || true
  done
}

# ── 01 gateway8501 ──────────────────────────────────────────────────────
G1="${OUT}/01_gateway8501"
mkdir -p "${G1}/data"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${GS}/gateway/" "${G1}/gateway/"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${GS}/config/" "${G1}/config/"
[[ -d "${GS}/.grid_cleanroom" ]] && "${RSYNC[@]}" "${EXCLUDE[@]}" "${GS}/.grid_cleanroom/" "${G1}/cleanroom/"
[[ -d "${GS}/scripts" ]] && "${RSYNC[@]}" "${EXCLUDE[@]}" "${GS}/scripts/" "${G1}/grid_scripts/"
if [[ -f "${GS}/data/grid_store.db" ]]; then
  command -v sqlite3 >/dev/null && sqlite3 "${GS}/data/grid_store.db" "PRAGMA wal_checkpoint(FULL);" 2>/dev/null || true
  cp -p "${GS}/data/grid_store.db" "${G1}/data/"
  [[ -f "${GS}/data/grid_store.db-wal" ]] && cp -p "${GS}/data/grid_store.db-wal" "${G1}/data/" || true
  [[ -f "${GS}/data/grid_store.db-shm" ]] && cp -p "${GS}/data/grid_store.db-shm" "${G1}/data/" || true
fi
mkdir -p "${G1}/scripts"
cp -p "${ROOT}/scripts/start_grid_gateway.sh" "${ROOT}/scripts/setup_tailscale_gateway.sh" \
  "${ROOT}/scripts/install_grid_gateway_launchagent.sh" "${G1}/scripts/" 2>/dev/null || true
copy_plists "${G1}/launchagents" \
  "${ROOT}/scripts/launchd/com.demo.grid.gateway8501.plist" \
  "${ROOT}/scripts/garden/launchd/com.demo.grid.gateway8501.plist"

# ── 02 egress8502_8503 ───────────────────────────────────────────────────
G2="${OUT}/02_egress8502_8503"
mkdir -p "${G2}/gateway"
for f in egress.py; do
  [[ -f "${GS}/gateway/${f}" ]] && cp -p "${GS}/gateway/${f}" "${G2}/gateway/" || true
done
"${RSYNC[@]}" "${EXCLUDE[@]}" "${GS}/config/" "${G2}/config/"
mkdir -p "${G2}/scripts"
cp -p "${ROOT}/scripts/install_egress_launchagents.sh" "${G2}/scripts/" 2>/dev/null || true
copy_plists "${G2}/launchagents" "${ROOT}/scripts/garden/launchd/com.demo.grid.egress850"*.plist

# ── 03 voice8504 ────────────────────────────────────────────────────────
G3="${OUT}/03_voice8504"
mkdir -p "${G3}/gateway"
cp -p "${GS}/gateway/voice_daemon.py" "${G3}/gateway/" 2>/dev/null || true
copy_plists "${G3}/launchagents" "${ROOT}/scripts/garden/launchd/com.demo.grid.voice8504.plist"

# ── 04 field8790 ────────────────────────────────────────────────────────
G4="${OUT}/04_field8790"
"${RSYNC[@]}" "${EXCLUDE[@]}" --exclude 'frontend/node_modules' --exclude 'diary.db' \
  "${ROOT}/aster-field/" "${G4}/aster-field/"
mkdir -p "${G4}/scripts"
cp -p "${ROOT}/scripts/start_aster_field_8790.sh" "${ROOT}/scripts/install_aster_field_launchagent.sh" \
  "${ROOT}/scripts/verify_field_truncation_fix.sh" "${ROOT}/scripts/verify_aster_field_v1.sh" \
  "${G4}/scripts/" 2>/dev/null || true
copy_plists "${G4}/launchagents" "${ROOT}/scripts/garden/launchd/com.demo.field.bridge8790.plist"

# ── 05 garden8787_5173_8788 ───────────────────────────────────────────────
G5="${OUT}/05_garden8787_5173_8788"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/repo/" "${G5}/repo/"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/echo_nodes_interface/" "${G5}/echo_nodes_interface/"
cp -p "${ROOT}/scripts/sound_lab_fallback.py" "${G5}/" 2>/dev/null || true
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/scripts/garden/" "${G5}/scripts/garden/"
cp -p "${ROOT}/scripts/start_aster.sh" "${ROOT}/scripts/start_garden_stack.sh" "${G5}/scripts/" 2>/dev/null || true
copy_plists "${G5}/launchagents" \
  "${ROOT}/scripts/garden/launchd/com.demo.garden.aster8787.plist" \
  "${ROOT}/scripts/garden/launchd/com.demo.garden.fallback5173.plist" \
  "${ROOT}/scripts/garden/launchd/com.demo.garden.telemetry8788.plist" \
  "${ROOT}/scripts/garden/launchd/com.demo.lms.aster-dev.plist"

# ── 06 aether8510_daemons ─────────────────────────────────────────────────
G6="${OUT}/06_aether8510_daemons"
"${RSYNC[@]}" "${EXCLUDE[@]}" --exclude '.env' "${ROOT}/aether_nexus/" "${G6}/aether_nexus/"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/scripts/aether/" "${G6}/scripts/aether/"
copy_plists "${G6}/launchagents" "${ROOT}/scripts/aether/launchd/com.demo.aether."*.plist

# ── 07 watcher8520 ────────────────────────────────────────────────────────
G7="${OUT}/07_watcher8520"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/aether_watcher/" "${G7}/aether_watcher/"

# ── 08 jarvis8686 ─────────────────────────────────────────────────────────
G8="${OUT}/08_jarvis8686"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/app/" "${G8}/app/"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/gateway/" "${G8}/gateway/"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/JarvisCoach/" "${G8}/JarvisCoach/"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/scripts/jarvis/" "${G8}/scripts/jarvis/"
copy_plists "${G8}/launchagents" "${ROOT}/scripts/jarvis/launchd/"*.plist

# ── 09 aster_diary ────────────────────────────────────────────────────────
G9="${OUT}/09_aster_diary"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/aster-diary/" "${G9}/aster-diary/"
if [[ -f "${ROOT}/aster-field/diary.db" ]]; then
  mkdir -p "${G9}/field_diary_copy"
  cp -p "${ROOT}/aster-field/diary.db" "${G9}/field_diary_copy/diary.db"
fi
copy_plists "${G9}/launchagents" "${ROOT}/scripts/aster/launchd/com.demo.aster.diary.plist"
cp -p "${ROOT}/scripts/aster/start_aster_diary.sh" "${ROOT}/scripts/aster/install_diary_launchagent.sh" \
  "${G9}/" 2>/dev/null || true

# ── 10 ocr_text_inbox ─────────────────────────────────────────────────────
G10="${OUT}/10_ocr_text_inbox"
if [[ -d "${OCR_INBOX}" ]]; then
  "${RSYNC[@]}" "${EXCLUDE[@]}" "${OCR_INBOX}/" "${G10}/Desktop_OCR_Text_Inbox/"
else
  echo "WARN: OCR inbox missing at ${OCR_INBOX}" >&2
fi
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/scripts/ocr_text_inbox/" "${G10}/scripts_ocr_text_inbox/"
cat > "${G10}/README.txt" <<EOF
OCR pipeline backup.
Live inbox: ${OCR_INBOX}
Regenerate venv: python3 -m venv ${ROOT}/.venv_ocr_inbox && pip install -r requirements (see scripts)
EOF

# ── 11 aster_grid_v5 ──────────────────────────────────────────────────────
G11="${OUT}/11_aster_grid_v5"
"${RSYNC[@]}" "${EXCLUDE[@]}" --exclude '.tools' "${ROOT}/aster_grid_v5/" "${G11}/aster_grid_v5/"

# ── 12 phototextvault ─────────────────────────────────────────────────────
G12="${OUT}/12_phototextvault"
[[ -d "${ROOT}/phototextvault" ]] && "${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/phototextvault/" "${G12}/phototextvault/" || true
[[ -d "${ROOT}/scripts/photos_obsidian" ]] && "${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/scripts/photos_obsidian/" "${G12}/scripts_photos_obsidian/" || true

# ── 13 aether_paper ───────────────────────────────────────────────────────
G13="${OUT}/13_aether_paper"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/aether-paper/" "${G13}/aether-paper/"

# ── 14 launchagents_installed ─────────────────────────────────────────────
G14="${OUT}/14_launchagents_installed"
mkdir -p "${G14}"
cp -p "${HOME}/Library/LaunchAgents/com.demo."*.plist "${G14}/" 2>/dev/null || true
cp -p "${HOME}/Library/LaunchAgents/com.ocr_text_inbox."*.plist "${G14}/" 2>/dev/null || true

# ── 15 runtime_logs ───────────────────────────────────────────────────────
G15="${OUT}/15_runtime_logs"
for logdir in demo-grid demo-garden demo-aether demo-jarvis demo-aster; do
  [[ -d "${HOME}/Library/Logs/${logdir}" ]] && \
    "${RSYNC[@]}" "${EXCLUDE[@]}" "${HOME}/Library/Logs/${logdir}/" "${G15}/${logdir}/" || true
done

# ── 16 shared_config ──────────────────────────────────────────────────────
G16="${OUT}/16_shared_config"
"${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/config/" "${G16}/config/"
[[ -d "${ROOT}/frequency_continuity_package" ]] && \
  "${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/frequency_continuity_package/" "${G16}/frequency_continuity_package/" || true
for f in PORT_PROCESS_CONVENTION.md .cursor/rules/decoupled-grid-architecture.mdc \
  .cursor/rules/grid-aster-gateway-frozen.mdc .cursor/rules/diary-sacred.mdc; do
  [[ -f "${ROOT}/${f}" ]] && mkdir -p "${G16}/$(dirname "${f}")" && cp -p "${ROOT}/${f}" "${G16}/${f}" || true
done
cp -p "${ROOT}/scripts/ensure_all_sidecars.sh" "${ROOT}/scripts/backup_stack_to_2td.sh" "${G16}/" 2>/dev/null || true

# ── 17 lmstudio_plugin ────────────────────────────────────────────────────
G17="${OUT}/17_lmstudio_plugin"
[[ -d "${ROOT}/lmstudio-plugins" ]] && "${RSYNC[@]}" "${EXCLUDE[@]}" "${ROOT}/lmstudio-plugins/" "${G17}/lmstudio-plugins/" || true
cp -p "${ROOT}/scripts/install_aster_gateway_plugin.sh" "${ROOT}/scripts/install_aster_virtual_model.sh" \
  "${G17}/" 2>/dev/null || true

# ── 19 lmstudio_demo_aster ────────────────────────────────────────────────
# Qwen tab model picker: repo virtual model + live hub install (read-only copy).
G19="${OUT}/19_lmstudio_demo_aster"
mkdir -p "${G19}/repo/lmstudio-models/demo/aster" "${G19}/repo/scripts" "${G19}/hub_installed"
[[ -f "${ROOT}/lmstudio-models/demo/aster/model.yaml" ]] && \
  cp -p "${ROOT}/lmstudio-models/demo/aster/model.yaml" "${G19}/repo/lmstudio-models/demo/aster/"
[[ -f "${ROOT}/models/aster_config.py" ]] && \
  mkdir -p "${G19}/repo/models" && cp -p "${ROOT}/models/aster_config.py" "${G19}/repo/models/"
[[ -f "${ROOT}/config/aster_chat_system_prompt.txt" ]] && \
  mkdir -p "${G19}/repo/config" && cp -p "${ROOT}/config/aster_chat_system_prompt.txt" "${G19}/repo/config/"
for s in install_aster_virtual_model.sh install_aster_gateway_plugin.sh start_aster_lms_dev.sh; do
  [[ -f "${ROOT}/scripts/${s}" ]] && cp -p "${ROOT}/scripts/${s}" "${G19}/repo/scripts/" || true
done
[[ -f "${ROOT}/scripts/garden/launchd/com.demo.lms.aster-dev.plist" ]] && \
  mkdir -p "${G19}/repo/launchd" && \
  cp -p "${ROOT}/scripts/garden/launchd/com.demo.lms.aster-dev.plist" "${G19}/repo/launchd/"
HUB_MODEL="${HOME}/.lmstudio/hub/models/demo/aster/model.yaml"
[[ -f "${HUB_MODEL}" ]] && cp -p "${HUB_MODEL}" "${G19}/hub_installed/model.yaml" || true
python3 - <<PY
import json
from pathlib import Path
out = Path("${G19}")
meta = {
    "virtual_model_id": "demo/aster",
    "base_model": "qwen/qwen3.5-9b",
    "repo_source": "lmstudio-models/demo/aster/model.yaml",
    "hub_live": str(Path.home() / ".lmstudio/hub/models/demo/aster/model.yaml"),
    "restore": [
        "bash scripts/install_aster_virtual_model.sh",
        "bash scripts/install_aster_gateway_plugin.sh",
        "bash scripts/start_aster_lms_dev.sh  # or LaunchAgent com.demo.lms.aster-dev",
    ],
}
(out / "README_RESTORE.json").write_text(json.dumps(meta, indent=2) + "\\n", encoding="utf-8")
PY

# ── 18 grid_traces ────────────────────────────────────────────────────────
G18="${OUT}/18_grid_traces"
[[ -d "${GS}/traces" ]] && "${RSYNC[@]}" "${EXCLUDE[@]}" "${GS}/traces/" "${G18}/traces/" || true

# ── INDEX ─────────────────────────────────────────────────────────────────
cat > "${OUT}/PORT_CHAIN.md" <<EOF
# Full stack backup ${STAMP}

| Group | Port(s) | Contents |
|-------|---------|----------|
| **00_tree_of_life** | — | Auto-generated proxy/page/store map (also in ~/2td/tree-of-life) |
| 01_gateway8501 | 8501 | Gateway + **grid_store.db** memory |
| 02_egress8502_8503 | 8502, 8503 | API egress sidecars |
| 03_voice8504 | 8504 | Voice TTS daemon |
| 04_field8790 | 8790 | ASTER FIELD |
| 05_garden8787_5173_8788 | 8787, 5173, 8788, lms | Garden / legacy / telemetry |
| 06_aether8510_daemons | 8510 + daemons | Aether Nexus + paper/offpool/premarket… |
| 07_watcher8520 | 8520 | Aether Watcher |
| 08_jarvis8686 | 8686 | Jarvis platform |
| 09_aster_diary | 22:30 job | aster-diary + diary.db copy |
| 10_ocr_text_inbox | weekly | ~/Desktop/OCR_Text_Inbox |
| 11_aster_grid_v5 | CC CLI | Fable/distill (no .tools) |
| 12_phototextvault | — | Photo OCR helpers |
| 13_aether_paper | — | Paper engine state |
| 14_launchagents_installed | — | Live LaunchAgent plists |
| 15_runtime_logs | — | launchd logs |
| 16_shared_config | — | config + architecture locks |
| 17_lmstudio_plugin | 1234 | LM Studio gateway generator plugin |
| 18_grid_traces | — | offpool/daemon traces |
| 19_lmstudio_demo_aster | 1234 | **demo/aster** virtual model (My Models picker) + hub install copy |

Epoch anchor: ${ANCHOR} · Source: ${ROOT}
EOF

python3 <<PY
import json, subprocess, datetime as dt
from pathlib import Path

out = Path("${OUT}")
groups = sorted([p for p in out.iterdir() if p.is_dir() and p.name[:2].isdigit()])

def du(p):
    try:
        r = subprocess.run(["du", "-sk", str(p)], capture_output=True, text=True, check=True)
        return int(r.stdout.split()[0]) * 1024
    except Exception:
        return 0

manifest = {
    "stamp": "${STAMP}",
    "source_root": str(out.parent.parent / "Projects" / "demo") if False else "${ROOT}",
    "dest": str(out),
    "epoch_anchor": "${ANCHOR}",
    "ocr_inbox_source": "${OCR_INBOX}",
    "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    "groups": {p.name: du(p) for p in groups},
    "total_bytes": du(out),
}
manifest["source_root"] = "${ROOT}"
(out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(json.dumps(manifest, indent=2))
PY

ln -sfn "${STAMP}" "${DEST_ROOT}/latest"
echo "=== done ==="
du -sh "${OUT}" "${OUT}"/[0-9][0-9]_* 2>/dev/null | sort -hr | head -25

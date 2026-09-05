#!/usr/bin/env bash
# Rebuild .venv if missing or still pointing at old Desktop/demo path after repo move.
ensure_venv() {
  local app_dir="$1"
  local py="${app_dir}/.venv/bin/python3.13"
  local streamlit="${app_dir}/.venv/bin/streamlit"
  local broken=0

  if [[ ! -x "${py}" ]]; then
    broken=1
  elif head -1 "${py}" 2>/dev/null | grep -q "Desktop/demo"; then
    broken=1
  elif [[ -x "${streamlit}" ]] && head -1 "${streamlit}" 2>/dev/null | grep -q "Desktop/demo"; then
    broken=1
  fi

  if [[ "${broken}" == "1" ]]; then
    echo "[venv] rebuild ${app_dir} (broken or missing after move)"
    rm -rf "${app_dir}/.venv"
    python3 -m venv "${app_dir}/.venv"
    "${app_dir}/.venv/bin/pip" install -q -r "${app_dir}/requirements.txt"
  fi
}

#!/usr/bin/env bash
# Acceptance for PhotoTextVault pipeline. Fails if only one test asset unless ALLOW_SINGLE_TEST=1.
set -euo pipefail

VAULT="${HOME}/Obsidian/PhotoTextVault"
MD_DIR="${VAULT}/markdown"
TXT_DIR="${VAULT}/text"
MANIFEST="${VAULT}/_logs/manifest.json"

echo "---- VAULT COUNTS ----"
MD_COUNT=$(find "${MD_DIR}" -type f -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
TXT_COUNT=$(find "${TXT_DIR}" -type f -name "*.txt" 2>/dev/null | wc -l | tr -d ' ')
echo "markdown_count=${MD_COUNT}"
echo "text_count=${TXT_COUNT}"

if [[ ! -f "${MANIFEST}" ]]; then
  echo "FAIL: missing ${MANIFEST} (run pipeline first, not DRY_RUN only)"
  exit 1
fi

PROC=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('processed_count',-1))" "${MANIFEST}" || echo -1)
echo "manifest_processed_count=${PROC}"

if [[ "${PROC}" -lt 0 ]]; then
  echo "FAIL: could not read processed_count from manifest"
  exit 1
fi

if [[ "${PROC}" -eq 0 ]]; then
  echo "FAIL: processed_count is 0 (pipeline did not produce outputs; see _logs/unknown.txt if PHOTOS_MODE)"
  exit 1
fi

if [[ "${ALLOW_SINGLE_TEST:-}" != "1" ]] && [[ "${PROC}" -lt 2 ]]; then
  echo "FAIL: processed_count must be >= 2 (got ${PROC}) or set ALLOW_SINGLE_TEST=1 for single-image smoke tests"
  exit 1
fi

if [[ "${MD_COUNT}" != "${PROC}" ]] || [[ "${TXT_COUNT}" != "${PROC}" ]]; then
  echo "FAIL: markdown_count and text_count must equal processed_count (${PROC})"
  exit 1
fi

FIRST_MD=$(find "${MD_DIR}" -type f -name "*.md" 2>/dev/null | head -1 || true)
if [[ -z "${FIRST_MD}" ]]; then
  echo "FAIL: no markdown files"
  exit 1
fi
BYTES=$(wc -c < "${FIRST_MD}" | tr -d ' ')
echo "first_md_bytes=${BYTES}"
if [[ "${BYTES}" -le 0 ]]; then
  echo "FAIL: first markdown file is empty"
  exit 1
fi

echo "PASS"

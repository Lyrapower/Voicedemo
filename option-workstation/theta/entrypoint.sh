#!/usr/bin/env bash
# Theta Terminal v3 · 凭证来自环境 / .env(compose env_file),不写死密钥
set -euo pipefail
cd /theta
mkdir -p logs

ARGS=( -jar ThetaTerminalv3.jar --config /theta/config.toml )

if [[ -n "${THETADATA_API_KEY:-}" ]]; then
  export THETADATA_API_KEY
  ARGS+=( --api-key "$THETADATA_API_KEY" )
elif [[ -n "${THETA_EMAIL:-}" && -n "${THETA_PASSWORD:-}" ]]; then
  # 兼容旧式:两行 creds 文件(不 echo 密钥)
  printf '%s\n%s\n' "$THETA_EMAIL" "$THETA_PASSWORD" > /theta/creds.txt
  chmod 600 /theta/creds.txt
  ARGS+=( --creds-file=/theta/creds.txt )
else
  echo "[theta] 缺凭证:请在 option-workstation/theta/.env 填 THETADATA_API_KEY" >&2
  echo "       或 THETA_EMAIL + THETA_PASSWORD(见 .env.example)" >&2
  exit 1
fi

exec java "${ARGS[@]}"

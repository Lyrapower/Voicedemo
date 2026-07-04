#!/usr/bin/env bash
# Aster dual-path deploy: gateway plugin + LM Studio direct token/reasoning hardening + verify.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== 1/4 Gateway :8501 ==="
if ! curl -sf http://127.0.0.1:8501/health >/dev/null 2>&1; then
  echo "Starting grid gateway..."
  bash "$ROOT/scripts/start_grid_gateway.sh" &
  sleep 3
fi
curl -sf http://127.0.0.1:8501/health | python3 -m json.tool | head -20

echo "=== 2/4 LM Studio Aster tab (direct path + clear stale session) ==="
ASTER_DEPLOY_CLEAR=1 ASTER_DEPLOY_GATEWAY_PLUGIN=1 "$ROOT/scripts/deploy_lmstudio_aster.sh"

echo "=== 3/5 Gateway generator plugin (demo/aster) ==="
bash "$ROOT/scripts/install_aster_gateway_plugin.sh" || {
  echo "WARN: plugin install failed — see scripts/install_aster_gateway_plugin.sh"
}

echo "=== 4/5 Start lms dev (generator registration) ==="
bash "$ROOT/scripts/start_aster_gateway_plugin_dev.sh" || true

echo "=== 5/5 User-chain verification (Fable) ==="
export PYTHONPATH="${ROOT}:${ROOT}/repo${PYTHONPATH:+:${PYTHONPATH}}"
python3 "$ROOT/scripts/verify_aster_user_chain.py"

cat <<'EOF'

=== 用户侧（Aster 标签页）===
1. 模型选择器选 **demo/aster**（不是 qwen/qwen3.5-9b）
2. 若列表里没有 demo/aster：确认终端里 lms dev 在跑（deploy 已尝试启动）
3. 发「你知道 Aster 是谁吗」— 应回答编译层身份，不是植物/百科

直连回退：仍可选 qwen/qwen3.5-9b（已带 Aster system prompt + token 预算）
EOF

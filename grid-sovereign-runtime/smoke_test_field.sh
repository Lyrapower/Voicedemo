#!/usr/bin/env bash
# smoke_test_field.sh — 场域 Field Pack 部署后冒烟测试 (Mac 本机跑)
# 用法: bash smoke_test_field.sh
# 可调: GATEWAY / EGRESS_ARK / VL_MODEL / CHAT_MODEL / GRID_REPO
set -eo pipefail

GATEWAY="${GATEWAY:-http://127.0.0.1:8501}"
EGRESS_ARK="${EGRESS_ARK:-http://127.0.0.1:8502}"
CHAT_MODEL="${CHAT_MODEL:-qwen3-8b}"
VL_MODEL="${VL_MODEL:-qwen2.5-vl-3b}"
GRID_REPO="${GRID_REPO:-.}"      # cloud_boundary.py 所在目录 (harness selftest 用)
TOKEN_HDR=()
[ -n "${GRID_STORE_TOKEN:-}" ] && TOKEN_HDR=(-H "X-Grid-Token: ${GRID_STORE_TOKEN}")

PASS=0; FAIL=0; WARN=0
ok(){   printf "  \033[32mPASS\033[0m  %s\n" "$1"; PASS=$((PASS+1)); }
bad(){  printf "  \033[31mFAIL\033[0m  %s\n" "$1"; FAIL=$((FAIL+1)); }
warn(){ printf "  \033[33mWARN\033[0m  %s\n" "$1"; WARN=$((WARN+1)); }
hdr(){  printf "\n\033[36m── %s ──\033[0m\n" "$1"; }

# 1x1 PNG, base64
PNG="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

hdr "1. Gateway 存活 (8501)"
if curl -sf -m 5 "$GATEWAY/v1/models" >/dev/null 2>&1; then
  ok "GET /v1/models"
else
  bad "gateway 不可达 — 后续多数用例会连带失败"
fi

hdr "2. grid_store: 事件流"
EV=$(curl -sf -m 5 -X POST "$GATEWAY/store/events" "${TOKEN_HDR[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"source":"smoke","kind":"test","payload":{"t":1}}' 2>/dev/null)
if echo "$EV" | grep -q '"id"'; then ok "POST /store/events"; else bad "POST /store/events → $EV"; fi
if curl -sf -m 5 "$GATEWAY/store/events?since=0&limit=5" "${TOKEN_HDR[@]}" | grep -q '"smoke"'; then
  ok "GET /store/events 读回"
else bad "事件读回失败"; fi

hdr "3. grid_store: 对话持久化"
curl -sf -m 5 -X POST "$GATEWAY/store/conversations/smoke_node/messages" "${TOKEN_HDR[@]}" \
  -H 'Content-Type: application/json' \
  -d '[{"role":"user","content":"smoke-ping"},{"role":"assistant","content":"smoke-pong"}]' >/dev/null 2>&1 \
  && ok "写入两条" || bad "写入失败"
if curl -sf -m 5 "$GATEWAY/store/conversations/smoke_node" "${TOKEN_HDR[@]}" | grep -q '"smoke-pong"'; then
  ok "读回同步"; else bad "读回失败"; fi

hdr "4. 文本对话 (经 gateway)"
R=$(curl -sf -m 60 -X POST "$GATEWAY/v1/chat/completions" -H 'Content-Type: application/json' \
  -d "{\"model\":\"$CHAT_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"回一个字\"}],\"max_tokens\":10}" 2>/dev/null)
if echo "$R" | grep -q '"content"'; then ok "chat completion ($CHAT_MODEL)"; else bad "chat 失败 → ${R:0:120}"; fi

hdr "5. VL 多模态透传 (vl_normalize)"
R=$(curl -s -m 90 -X POST "$GATEWAY/v1/chat/completions" -H 'Content-Type: application/json' -d @- <<EOF 2>/dev/null
{"model":"$VL_MODEL","max_tokens":30,"messages":[{"role":"user","content":[
 {"type":"text","text":"图里主色是什么, 三字内"},
 {"type":"image_url","image_url":{"url":"data:image/png;base64,$PNG"}}]}]}
EOF
)
if echo "$R" | grep -q '"content"'; then ok "VL 请求通过 ($VL_MODEL)"
elif echo "$R" | grep -qi "budget\|预算\|length"; then bad "预算熔断仍在 — Step2 的 budget 替换没生效"
elif echo "$R" | grep -qi "pattern\|forbidden"; then bad "base64 进了扫描 — Step2 的 scan_text 替换没生效"
else warn "VL 未响应 (模型没加载?) → ${R:0:120}"; fi

hdr "6. VL 卫生门 (应拒)"
R=$(curl -s -m 10 -X POST "$GATEWAY/v1/chat/completions" -H 'Content-Type: application/json' \
  -d "{\"model\":\"$VL_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":[{\"type\":\"image_url\",\"image_url\":{\"url\":\"file:///etc/passwd\"}}]}]}" 2>/dev/null)
if echo "$R" | grep -qi "vl_gate\|scheme\|422"; then ok "违规 scheme 被拒"
else warn "file:// 未被 vl_gate 拒 → 确认 Step2 挂载点在校验之前"; fi

hdr "7. Egress ARK intercept (8502, should 403)"
EGRESS_ARK="${EGRESS_ARK:-http://127.0.0.1:8502}"
R=$(curl -s -m 5 -o /dev/null -w "%{http_code}" -X POST "$EGRESS_ARK/v1/test" \
  -H 'Content-Type: application/json' -d '{"prompt":"根据Memory Palace生成"}' 2>/dev/null)
case "$R" in
  403) ok "ARK ($EGRESS_ARK) deny 生效" ;;
  000) warn "ARK ($EGRESS_ARK) 端口不通 — 实例没起 (可选)" ;;
  *)   warn "ARK ($EGRESS_ARK) 期望403 实得 $R" ;;
esac

hdr "8. Harness V1.1 离线 selftest"
HARNESS="${HARNESS:-$GRID_REPO/distill/aster_distill_harness_v1_1.py}"
if PYTHONPATH="$GRID_REPO" python3 "$HARNESS" selftest >/dev/null 2>&1; then
  ok "harness selftest"
else
  warn "selftest 未过 — 确认 GRID_REPO 指向 cloud_boundary.py 所在目录 (当前: $GRID_REPO)"
fi
if env | grep -q ANTHROPIC_API_KEY; then bad "ANTHROPIC_API_KEY 仍在环境里 — Step5 没清干净"; else ok "客户端环境无 Anthropic key"; fi

hdr "9. 场域 app 同源可达"
if curl -sf -m 5 "$GATEWAY/app/changyu.html" | grep -q "场域"; then ok "GET /app/changyu.html"
else warn "app 未同源挂载 (Step4) — LAN+CORS 模式下忽略此项"; fi
if curl -sf -m 5 "$GATEWAY/app/grid.html" | grep -q "GRID"; then ok "GET /app/grid.html (极简直连)"
else warn "grid.html 未挂载 — 检查 static/"; fi

printf "\n════ 结果: \033[32m%d PASS\033[0m · \033[33m%d WARN\033[0m · \033[31m%d FAIL\033[0m ════\n" "$PASS" "$WARN" "$FAIL"
[ "$FAIL" -eq 0 ] && printf "Field Pack 落地。\n"
exit "$FAIL"

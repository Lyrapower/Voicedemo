#!/usr/bin/env bash
# #9↔GLM5.2↔8620 长期任务桥门禁 · 不可断
# 用法: bash scripts/verify_console_ows_bridge.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="$ROOT/grid-console/docker-compose.yml"
FAIL=0

say() { printf '%s\n' "$*"; }
bad() { say "FAIL: $*"; FAIL=1; }
ok() { say "OK: $*"; }

# 1) compose 不得再 ${OWS_URL} / ${CONSOLE_CLOUD_BRIDGE_THREADS} 插值
if grep -E 'OWS_URL:.*\$\{OWS_URL' "$COMPOSE" >/dev/null 2>&1; then
  bad "docker-compose.yml 仍用 \${OWS_URL} 插值 — 易被 shell localhost 盖掉"
else
  ok "compose 未用 \${OWS_URL} 插值"
fi

if grep -E 'OWS_URL:[[:space:]]*http://host\.docker\.internal:8620' "$COMPOSE" >/dev/null 2>&1; then
  ok "compose 固定 host.docker.internal:8620"
else
  bad "compose 未固定 OWS_URL=http://host.docker.internal:8620"
fi

if grep -E 'CONSOLE_CLOUD_BRIDGE_THREADS:[[:space:]]*"?9"?' "$COMPOSE" >/dev/null 2>&1 \
   && ! grep -E 'CONSOLE_CLOUD_BRIDGE_THREADS:.*\$\{' "$COMPOSE" >/dev/null 2>&1; then
  ok "compose 锁定 CONSOLE_CLOUD_BRIDGE_THREADS=9"
else
  bad "compose 未字面量锁定 CONSOLE_CLOUD_BRIDGE_THREADS=9"
fi

# 2) 宿主 :8620 存活
if curl -sf --max-time 3 'http://127.0.0.1:8620/api/health' >/dev/null; then
  ok "host :8620 /api/health"
else
  bad "host :8620 /api/health 不可达(option-workstation 未起?)"
fi

if curl -sf --max-time 3 'http://127.0.0.1:8620/api/scout/entry' >/dev/null; then
  ok "host :8620 /api/scout/entry"
else
  bad "host :8620 /api/scout/entry 不可达"
fi

# 3) 运行中 console 容器 env + 实连 + #9 注入
if docker ps --format '{{.Names}}' | grep -qx 'grid-console'; then
  ENV_OWS="$(docker exec grid-console printenv OWS_URL 2>/dev/null || true)"
  ENV_BR="$(docker exec grid-console printenv CONSOLE_CLOUD_BRIDGE_THREADS 2>/dev/null || true)"
  say "container OWS_URL=$ENV_OWS BRIDGE_THREADS=$ENV_BR"
  if echo "$ENV_OWS" | grep -qiE 'localhost|127\.0\.0\.1'; then
    bad "运行中容器 OWS_URL 仍是 localhost/127.0.0.1"
  else
    ok "容器 OWS_URL 非 localhost"
  fi
  if [ "$ENV_BR" != "9" ]; then
    bad "CONSOLE_CLOUD_BRIDGE_THREADS 应为 9,实际=$ENV_BR"
  else
    ok "容器 BRIDGE_THREADS=9"
  fi
  if docker exec grid-console python3 -c '
import json, sys, thread9_toolkit as T, console as C
u=T.resolve_ows_url()
assert "localhost" not in u and "127.0.0.1" not in u, u
st=T.probe_glm9_ows_bridge()
assert st.get("ok"), st
rows=C._store_fetch_cloud("cloud-glm52", limit=40)
msgs=C._build_cloud_chat_messages(
    rows, "bridge-probe",
    local_rows=[{"role":"user","content":"ping","ts":1}],
    readonly_bridge=True, include_toolkit=True,
)
sysb="\n".join(m.get("content") or "" for m in msgs if m.get("role")=="system")
assert T.TOOLKIT_SYSTEM_TITLE in sysb, "toolkit missing"
assert ("\"ok\": true" in sysb) or ("\"ok\":true" in sysb), "entry not ok in inject"
assert "Errno 111" not in sysb
assert C._LAST_CLOUD_INJECT_STATS.get("toolkit") is True
print(json.dumps({"probe":st,"toolkit":True}, ensure_ascii=False))
' 2>/dev/null; then
    ok "容器内 bridge probe + #9 toolkit 注入含 scout/entry ok"
  else
    bad "容器内 #9↔8620 桥或注入失败"
  fi
else
  say "SKIP: grid-console 容器未运行(静态 compose 检查仍有效)"
fi

# 4) 单元:resolve 改写
if docker ps --format '{{.Names}}' | grep -qx 'grid-console'; then
  docker exec -e OWS_URL=http://localhost:8620 grid-console python3 -c '
import thread9_toolkit as T
assert T.running_in_docker()
assert T.resolve_ows_url("http://localhost:8620")=="http://host.docker.internal:8620"
assert T.resolve_ows_url("http://127.0.0.1:8620")=="http://host.docker.internal:8620"
print("rewrite-ok")
' >/dev/null && ok "Docker 内 localhost→host.docker.internal 改写" || bad "改写单测失败"
fi

# 5) console /api/health.glm9_ows(若 8610 起)
if curl -sf --max-time 3 'http://127.0.0.1:8610/api/health' >/tmp/console_health.json 2>/dev/null; then
  if python3 -c '
import json,sys
h=json.load(open("/tmp/console_health.json"))
b=h.get("glm9_ows") or {}
sys.exit(0 if b.get("ok") else 1)
'; then
    ok "GET :8610/api/health glm9_ows.ok"
  else
    bad "GET :8610/api/health glm9_ows 非 ok"
  fi
else
  say "SKIP: :8610 /api/health 不可达"
fi

if [ "$FAIL" -ne 0 ]; then
  say "verify_console_ows_bridge: FAILED"
  exit 1
fi
say "verify_console_ows_bridge: PASS · #9↔GLM5.2↔8620 长期桥绿"
exit 0

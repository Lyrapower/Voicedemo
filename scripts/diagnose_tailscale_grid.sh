#!/usr/bin/env bash
# Tailscale / Grid 入口 · 固定诊断序（Lyra 批 2026-07-30）
# 1 App/VPN → 2 BackendState → 3 serve → 4 MagicDNS health → 5 本机 8501
# 对外主入口只报 MagicDNS；100.x IP 仅脚注（可变，勿写书签）
set -euo pipefail

TS_BIN="${TAILSCALE_BIN:-}"
if [[ -z "$TS_BIN" ]]; then
  if [[ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]]; then
    TS_BIN="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
  elif command -v tailscale >/dev/null 2>&1; then
    TS_BIN="$(command -v tailscale)"
  else
    echo "FAIL · Tailscale CLI 未找到"
    exit 2
  fi
fi

HOST="${TS_HOST:-cicimacbook-air.tail76db5b.ts.net}"
MAGIC="https://${HOST}"

green() { printf 'OK   · %s\n' "$*"; }
yellow() { printf 'WARN · %s\n' "$*"; }
red() { printf 'FAIL · %s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }

ANY_FAIL=0

step "0 对外入口（MagicDNS · 勿用裸 100.x 书签）"
cat <<EOF
  health     ${MAGIC}/health
  grid       ${MAGIC}/app/grid.html
  workbench  ${MAGIC}/workbench/
  console    ${MAGIC}/console/
  alpha      ${MAGIC}/alpha/
EOF

step "1 App / VPN / StartOnLogin / AuthURL trap"
if pgrep -qf 'Tailscale.app/Contents/MacOS/Tailscale' 2>/dev/null \
  || pgrep -qf 'io.tailscale.ipn.macsys' 2>/dev/null; then
  green "Tailscale 进程在"
else
  red "未见 Tailscale.app / network-extension 进程"
  ANY_FAIL=1
fi
VPN_LINE="$(/usr/sbin/scutil --nc status Tailscale 2>/dev/null | head -1 || true)"
if [[ "$VPN_LINE" == "Connected" ]]; then
  green "VPN: Connected"
elif [[ -n "$VPN_LINE" ]]; then
  yellow "VPN: ${VPN_LINE}"
  ANY_FAIL=1
else
  yellow "VPN 状态读不到（可忽略，继续看 BackendState）"
fi
START_ON="$(defaults read io.tailscale.ipn.macsys TailscaleStartOnLogin 2>/dev/null || echo missing)"
if [[ "$START_ON" == "1" ]]; then
  green "TailscaleStartOnLogin=1"
else
  red "TailscaleStartOnLogin=${START_ON}（复发根因：登出/重启后不自启）→ guardian 应写回 true"
  ANY_FAIL=1
fi
# Empty AuthURL while Running is normal; non-empty means login pending.
# Opening GUI with broken/empty auth intent logs: auth window cannot open malformed URL
if /usr/bin/log show --last 15m --predicate 'eventMessage CONTAINS "auth window cannot open malformed URL"' --style compact 2>/dev/null \
  | grep -q 'malformed URL'; then
  yellow "近15m 见 GUI: auth window cannot open malformed URL（App『打不开』≠ VPN 断；勿反复 open App）"
fi

step "2 BackendState"
if ! STATUS_JSON="$("$TS_BIN" status --json 2>/dev/null)"; then
  red "tailscale status --json 失败（勿在沙箱误判；本机 Terminal 重跑）"
  ANY_FAIL=1
  STATUS_JSON="{}"
fi
python3 - "$STATUS_JSON" <<'PY' || true
import json, sys
raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
try:
    d = json.loads(raw)
except Exception as e:
    print(f"FAIL · status JSON 解析失败: {e}")
    sys.exit(0)
s = d.get("Self") or {}
backend = d.get("BackendState")
online = s.get("Online")
ips = s.get("TailscaleIPs") or []
dns = (s.get("DNSName") or "").rstrip(".")
health = d.get("Health") or []
peers = list((d.get("Peer") or {}).values())
pon = sum(1 for p in peers if p.get("Online"))
print(f"{'OK' if backend == 'Running' and online else 'FAIL'}   · BackendState={backend} Online={online}")
print(f"OK   · MagicDNS self: {dns or '(none)'}")
print(f"NOTE · Mac Tailscale IP（可变，勿写书签）: {', '.join(ips) or '(none)'}")
print(f"{'OK' if not health else 'WARN'}   · Health={health or '[]'}")
print(f"OK   · Peers online {pon}/{len(peers)}")
for p in peers:
    print(
        "NOTE · peer",
        p.get("HostName"),
        "online="+str(p.get("Online")),
        p.get("TailscaleIPs"),
        (p.get("DNSName") or "").rstrip("."),
    )
PY
if [[ "$(echo "$STATUS_JSON" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("BackendState"), d.get("Self",{}).get("Online"))' 2>/dev/null || true)" != "Running True" ]]; then
  ANY_FAIL=1
fi

step "3 serve status"
SERVE_OUT="$("$TS_BIN" serve status 2>&1 || true)"
if echo "$SERVE_OUT" | grep -q "$HOST"; then
  green "Serve 指向 ${HOST}"
  echo "$SERVE_OUT" | sed 's/^/  /'
else
  yellow "Serve 输出异常或未配置"
  echo "$SERVE_OUT" | sed 's/^/  /' || true
  ANY_FAIL=1
fi

step "4 MagicDNS health（主判定）"
CODE="$(curl -sS -m 8 -o /dev/null -w '%{http_code}' "${MAGIC}/health" 2>/dev/null || echo 000)"
if [[ "$CODE" == "200" ]]; then
  green "${MAGIC}/health → ${CODE}"
else
  red "${MAGIC}/health → ${CODE}"
  ANY_FAIL=1
fi

step "5 本机 8501"
LCODE="$(curl -sS -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8501/health 2>/dev/null || echo 000)"
if [[ "$LCODE" == "200" ]]; then
  green "http://127.0.0.1:8501/health → ${LCODE}"
else
  red "http://127.0.0.1:8501/health → ${LCODE}"
  ANY_FAIL=1
fi

step "裁决"
if [[ "$ANY_FAIL" -eq 0 ]]; then
  green "任一步主链已绿 · 不当作「Tailscale 全断」"
  echo "NOTE · 菜单栏灰但仍 OK 时：用 MagicDNS，勿改防火墙/架构"
  exit 0
fi
red "有 FAIL · 先修上方最早红项；Serve 丢可试 scripts/tailscale_serve_watchdog.sh"
echo "NOTE · 灰图标 ≠ 全断；裸 100.x 书签常指向错设备"
exit 1

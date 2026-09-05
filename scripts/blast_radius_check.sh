#!/usr/bin/env bash
# 8600/worker 收工波及面。五条全过才 exit 0。任一不过红字 + exit 1。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RED=$'\033[31m'
RST=$'\033[0m'
FAIL=0
bad() { printf '%sFAIL %s%s\n' "$RED" "$*" "$RST"; FAIL=1; }
ok() { printf 'OK   %s\n' "$*"; }

ENV_FILE="$ROOT/alpha-platform/.env"
echo "== blast_radius_check =="

# 1 universe 龄 <24h
UOUT=$(docker exec alpha-platform-worker-1 python3 -c "import json,time; d=json.load(open('/data/universe_market.json')); age=(time.time()-float(d['ts']))/3600; print(d.get('asof_et') or ''); print(d.get('n')); print(round(age,2))" 2>&1)
U_RC=$?
if [[ $U_RC -ne 0 ]]; then
  bad "universe 读失败: $UOUT"
else
  AGE=$(printf '%s\n' "$UOUT" | sed -n '3p')
  if python3 -c "import sys; sys.exit(0 if float(sys.argv[1]) < 24 else 1)" "$AGE"; then
    ok "universe 龄 ${AGE}h <24h"
  else
    bad "universe 龄 ${AGE}h ≥24h  ($UOUT)"
  fi
fi

# 2–3 pulse
PULSE_FILE=$(mktemp)
if curl -sf --max-time 20 http://127.0.0.1:8600/api/pulse >"$PULSE_FILE"; then
  EVAL=$(ENV_FILE="$ENV_FILE" python3 - "$PULSE_FILE" <<'PY'
import json, os, sys
path = sys.argv[1]
p = json.load(open(path, encoding="utf-8"))
wl = "SPY,QQQ,INTC,ANET,NBIS,NOW,HOOD,CRCL,USO"
envp = os.environ.get("ENV_FILE", "")
try:
    for line in open(envp, encoding="utf-8"):
        s = line.strip()
        if s.startswith("WATCHLIST=") and len(s) > 10:
            v = s.split("=", 1)[1].strip().strip('"').strip("'")
            if v:
                wl = v
            break
except OSError:
    pass
env = [x.strip().upper() for x in wl.split(",") if x.strip()]
eq = [e.get("symbol") for e in (p.get("equity") or [])]
dm = p.get("dailyMovers") or {}
ng, nl = len(dm.get("gainers") or []), len(dm.get("losers") or [])
env_set = set(env)
eq_set = set(eq)
subset = env_set <= eq_set
n_ok = len(env) <= len(eq) <= len(env) + 8
print("EQ_OK" if subset and n_ok else "EQ_BAD")
print(",".join(eq))
print(",".join(env))
print(ng)
print(nl)
print(len(eq))
print(len(env))
PY
)
  EQ_OK=$(printf '%s\n' "$EVAL" | sed -n '1p')
  EQ=$(printf '%s\n' "$EVAL" | sed -n '2p')
  ENV_WL=$(printf '%s\n' "$EVAL" | sed -n '3p')
  NG=$(printf '%s\n' "$EVAL" | sed -n '4p')
  NL=$(printf '%s\n' "$EVAL" | sed -n '5p')
  if [[ "$EQ_OK" == "EQ_OK" ]]; then
    ok "pulse equity ⊇ env 且 n=env+席≤17 ($EQ)"
  else
    bad "pulse equity 须含 env 且 n=env+席(≤17)  equity=$EQ env=$ENV_WL"
  fi
  if [[ "$NG" == "20" && "$NL" == "20" ]]; then
    ok "movers 20/20"
  else
    bad "movers ${NG}/${NL} 期望 20/20"
  fi
else
  bad "pulse curl 失败"
fi
rm -f "$PULSE_FILE"

# 4 8501 /health
HFILE=$(mktemp)
if curl -sf --max-time 8 http://127.0.0.1:8501/health >"$HFILE"; then
  ST=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('status',''))" "$HFILE")
  if [[ "$ST" == "ok" ]]; then
    ok "8501 /health ok"
  else
    bad "8501 /health status=$ST"
  fi
else
  bad "8501 /health curl 失败"
fi
rm -f "$HFILE"

# 5 8501 /api/state 有 movers
SFILE=$(mktemp)
if curl -sf --max-time 12 http://127.0.0.1:8501/api/state >"$SFILE"; then
  NM=$(python3 -c "import json,sys; s=json.load(open(sys.argv[1])); print(len(s.get('dailyMovers') or [])+len(s.get('dailyMoversLosers') or []))" "$SFILE")
  if python3 -c "import sys; sys.exit(0 if int(sys.argv[1])>0 else 1)" "$NM"; then
    ok "8501 /api/state movers n=$NM"
  else
    bad "8501 /api/state 无 movers"
  fi
else
  bad "8501 /api/state curl 失败"
fi
rm -f "$SFILE"

if [[ "$FAIL" -ne 0 ]]; then
  printf '%sblast_radius_check FAILED%s\n' "$RED" "$RST"
  exit 1
fi
echo "blast_radius_check OK"
exit 0

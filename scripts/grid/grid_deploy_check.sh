#!/bin/bash
# grid_deploy_check.sh — repo-local paths (from Downloads template v1.0)
set -u

REPO="$HOME/Projects/demo"
VAULT_DOC="$REPO/memory-palace/vault/04-决策Decisions/2026-07-20-中止AB与拆除Fable.md"
RUN_SCAN="$REPO/scripts/grid/run_scan.py"
ROUTER_DIR="$REPO/data/grid_router"
PLIST_POOL="$HOME/Library/LaunchAgents/com.grid.poolscan.plist"
PLIST_OFF="$HOME/Library/LaunchAgents/com.grid.offpoolscan.plist"
UID_NUM=$(id -u)

MODE="${1:---check}"
PASS=0; FAIL=0
ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ✗ $1"; FAIL=$((FAIL+1)); }
info() { echo "— $1"; }
die()  { echo "✗ 中止:$1"; exit 1; }

echo "======================================================"
echo " Grid teardown 收尾 · 模式: $MODE"
echo "======================================================"

info "0. 前置检查"

[ -d "$REPO/.git" ] && ok "仓库存在 $REPO" || die "仓库不在 $REPO"

if [ -f "$RUN_SCAN" ]; then
    if grep -q '"confirmed": *[Tt]rue\|confirmed=True\|"confirmed":true' "$RUN_SCAN"; then
        ok "run_scan.py 带 confirmed:true(能过确认闸)"
    else
        bad "run_scan.py 缺 confirmed:true"
    fi
else
    bad "run_scan.py 不在 $RUN_SCAN"
fi

CC_PATH="/Users/ciciwang/Projects/demo/aster_grid_v5/.tools/node_modules/.bin/claude"
if [ -x "$CC_PATH" ]; then
    ok "CC CLI 在 $CC_PATH"
    RULES="$ROUTER_DIR/router_rules.json"
    if [ -f "$RULES" ]; then
        if grep -q "$CC_PATH" "$RULES"; then
            ok "router_rules.json 用的是绝对路径"
        else
            bad "router_rules.json cmd[0] 不是 $CC_PATH"
        fi
    else
        bad "router_rules.json 不存在 $RULES"
    fi
else
    bad "claude CLI 不可执行: $CC_PATH"
fi

if curl -sf -m 3 "http://127.0.0.1:8500/health" >/dev/null 2>&1; then
    ok "router :8500 在线"
else
    bad "router :8500 不在线"
fi

[ -f "$PLIST_POOL" ] && ok "poolscan plist 就位" || bad "缺 $PLIST_POOL"
[ -f "$PLIST_OFF" ]  && ok "offpoolscan plist 就位" || bad "缺 $PLIST_OFF"

if [ "$MODE" = "--commit" ] || [ "$MODE" = "--all" ]; then
    info "1. git commit + 回填 trace_path"
    cd "$REPO" || die "进不去 $REPO"
    if [ -z "$(git status --porcelain)" ]; then
        echo "  (工作区干净,无需 commit)"
        HASH=$(git log -1 --format=%h)
    else
        git add -A
        git commit -m "teardown: A/B pipeline terminated per decision 2026-07-20, ledgers sealed" \
            || die "commit 失败"
        HASH=$(git log -1 --format=%h)
        ok "已 commit: $HASH"
    fi
    if [ -f "$VAULT_DOC" ]; then
        if grep -q "trace_path: <teardown commit hash>" "$VAULT_DOC"; then
            sed -i '' "s/trace_path: <teardown commit hash>/trace_path: $HASH/" "$VAULT_DOC"
            ok "trace_path 已回填 → $HASH"
            git add "$VAULT_DOC"
            git commit -m "docs: fill trace_path $HASH in teardown decision" >/dev/null
            ok "终案文档已随笔提交"
        else
            echo "  (trace_path 占位符不在,可能已填过:$(grep trace_path "$VAULT_DOC" | head -1))"
        fi
    else
        bad "终案文档不在 $VAULT_DOC"
    fi
else
    info "1. git commit —— 跳过(加 --commit 或 --all 执行)"
fi

if [ "$MODE" = "--launch" ] || [ "$MODE" = "--all" ]; then
    info "2. launchd bootstrap + 立即试跑 poolscan"
    for P in "$PLIST_POOL" "$PLIST_OFF"; do
        [ -f "$P" ] || continue
        LABEL=$(basename "$P" .plist)
        if launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1; then
            echo "  ($LABEL 已挂载,先卸再挂)"
            launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null
        fi
        launchctl bootstrap "gui/$UID_NUM" "$P" \
            && ok "bootstrap $LABEL" || bad "bootstrap $LABEL 失败"
    done
    echo "  试跑 poolscan..."
    launchctl kickstart "gui/$UID_NUM/com.grid.poolscan" \
        && ok "kickstart 已发出" || bad "kickstart 失败"
    echo "  等 90 秒..."
    sleep 90
else
    info "2. launchd —— 跳过(加 --launch 或 --all 执行)"
fi

info "3. 验收"

SCAN_OUT="$ROUTER_DIR/scan_pool.jsonl"
if [ -f "$SCAN_OUT" ] && [ -s "$SCAN_OUT" ]; then
    LAST_TS=$(tail -1 "$SCAN_OUT" | python3 -c "import sys,json;print(json.load(sys.stdin).get('ts','?'))" 2>/dev/null)
    ok "scan_pool.jsonl 有结果,最后一条 $LAST_TS"
    tail -1 "$SCAN_OUT" | python3 -c "import sys,json;d=json.load(sys.stdin);print('     result 预览:',d.get('result','')[:120].replace(chr(10),' '))" 2>/dev/null
else
    bad "scan_pool.jsonl 无结果(还没跑过,或首跑未完成)"
fi

if curl -sf -m 3 "http://127.0.0.1:8500/routes" >/dev/null 2>&1; then
    ROUTE_LINE=$(curl -s "http://127.0.0.1:8500/routes" | python3 -c "
import sys,json
rows=json.load(sys.stdin)
hits=[r for r in rows if r.get('reason','').startswith('slash:/scan') or r.get('route_outcome') in ('cc_cli','cc_candidate') or r.get('route')=='cloud']
print(json.dumps(hits[-1],ensure_ascii=False) if hits else '')" 2>/dev/null)
    if [ -n "$ROUTE_LINE" ]; then
        ok "路由审计里有 cloud/scan 决策: $ROUTE_LINE"
    else
        bad "/routes 里没有 scan→cloud 记录"
    fi
fi

LOG=/tmp/grid_poolscan.log
if [ -f "$LOG" ]; then
    ERRS=$(grep -ciE "error|traceback" "$LOG" 2>/dev/null | head -1 || echo 0)
    [ "$ERRS" -eq 0 ] && ok "poolscan 日志无报错" \
        || { bad "poolscan 日志有 $ERRS 处 error,末 10 行:"; tail -10 "$LOG" | sed 's/^/     /'; }
fi

cd "$REPO" 2>/dev/null && {
    GW_CORE=$(git diff HEAD --name-only -- 'grid-sovereign-runtime/gateway/local_gateway.py' 2>/dev/null | wc -l | tr -d ' ')
    [ "$GW_CORE" = "0" ] && ok "8501 local_gateway.py 零改动" \
        || bad "local_gateway.py 有改动!去看 git diff"
}

echo "======================================================"
echo " 结果: $PASS 项通过, $FAIL 项待处理"
[ "$FAIL" -eq 0 ] && echo " 全绿。" || echo " 按 ✗ 逐条处理后重跑。"
echo "======================================================"

#!/usr/bin/env bash
# verify_routelog_window.sh · GATEWAY_ROUTELOG_METRICS_v1 (c) 处决案
#
# 验证 metrics_query 的 3 日窗 ts 修法:
#   ts >= CAST(strftime('%s','now','-3 days') AS REAL)
# 处决案两条:
#   插一行 ts = now-3600s   → 3 日窗查询必计入 (count 含它 == 1)
#   揄一行 ts = now-4*86400 → 必排除          (count == 0)
# 处决案二(bogus substrate,期望 400):
#   §C 1 落地后,handler 对 bogus substrate 抛 HTTPException(400) 而非 ValueError,
#   _dispatch_telemetry 透传 400 → route_log.status_code = 400(不再是 -1)。
#   本处决案验查询侧:bogus substrate 行(routed_to 不匹配 %glm52%)不污染 GLM lane 指标。
#   PENDING §C 1:实际网关此刻仍产 -1(ValueError);§C 1 落地后改 live probe 验 400。
#
# route_log 是 gateway 自身路由遥测(非对话记忆 RED LINE 节点);探针用唯一
# routed_to 标记,验完即删,不污染生产数据。
set -Eeuo pipefail

DB="${1:-/Users/ciciwang/Projects/demo/grid-sovereign-runtime/gateway/gateway_log.db}"
if [[ ! -f "$DB" ]]; then
    echo "FATAL: DB 不在 $DB"; exit 2
fi

MARK_IN="__verify_window_in__"
MARK_OUT="__verify_window_out__"
# 先清掉上次残留
sqlite3 "$DB" "DELETE FROM route_log WHERE routed_to IN ('$MARK_IN','$MARK_OUT');"

# 处决案两条:1h 前(必计入)、4d 前(必排除)
sqlite3 "$DB" "
INSERT INTO route_log (route_id, ts, user_id, score, routed_to, prompt_preview, response_preview, blocked, duration_ms, status_code)
VALUES ('vwin_in',  strftime('%s','now','-1 hour'),  'verify', 0, '$MARK_IN',  '', '', 0, 100, 200);
INSERT INTO route_log (route_id, ts, user_id, score, routed_to, prompt_preview, response_preview, blocked, duration_ms, status_code)
VALUES ('vwin_out', strftime('%s','now','-4 days'), 'verify', 0, '$MARK_OUT', '', '', 0, 100, 200);
"

WIN="CAST(strftime('%s','now','-3 days') AS REAL)"
CNT_IN=$(sqlite3 "$DB" "SELECT COUNT(*) FROM route_log WHERE routed_to='$MARK_IN'  AND ts >= $WIN;")
CNT_OUT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM route_log WHERE routed_to='$MARK_OUT' AND ts >= $WIN;")

echo "处决案[1] ts=now-3600   3日窗 count = $CNT_IN  (期望 1)"
echo "处决案[2] ts=now-4d     3日窗 count = $CNT_OUT (期望 0)"

# 处决案二(bogus substrate,期望 400,PENDING §C 1)
# 插一行模拟 §C 1 落地后的 bogus substrate:routed_to 不含 glm52,status_code=400
MARK_BOGUS="__verify_bogus_substrate__"
sqlite3 "$DB" "DELETE FROM route_log WHERE routed_to='$MARK_BOGUS';"
sqlite3 "$DB" "
INSERT INTO route_log (route_id, ts, user_id, score, routed_to, prompt_preview, response_preview, blocked, duration_ms, status_code)
VALUES ('vbogus', strftime('%s','now'), 'verify', 0, '$MARK_BOGUS', '', '', 0, 50, 400);
"
# 查询侧断言:bogus substrate 行不进 GLM lane(因 routed_to 不匹配 %glm52%)
GLM_HAS_BOGUS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM route_log WHERE routed_to LIKE '%glm52%' AND routed_to='$MARK_BOGUS';")
BOGUS_STATUS=$(sqlite3 "$DB" "SELECT status_code FROM route_log WHERE routed_to='$MARK_BOGUS' ORDER BY ts DESC LIMIT 1;")
echo "处决案[3] bogus substrate status_code = $BOGUS_STATUS  (期望 400,PENDING §C 1 — 实际网关此刻 -1)"
echo "        GLM lane 是否误含 bogus = $GLM_HAS_BOGUS  (期望 0,bogus 不污染 GLM 指标)"
sqlite3 "$DB" "DELETE FROM route_log WHERE routed_to='$MARK_BOGUS';"

# 清理探针
sqlite3 "$DB" "DELETE FROM route_log WHERE routed_to IN ('$MARK_IN','$MARK_OUT');"

if [[ "$CNT_IN" == "1" && "$CNT_OUT" == "0" && "$GLM_HAS_BOGUS" == "0" ]]; then
    echo "VERIFY_WINDOW_PASS  (处决案[3] 查询侧过;gateway 侧 PENDING §C 1)"
    exit 0
else
    echo "VERIFY_WINDOW_FAIL"
    exit 1
fi

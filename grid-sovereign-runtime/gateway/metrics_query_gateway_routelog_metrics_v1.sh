#!/usr/bin/env bash
# metrics_query_gateway_routelog_metrics_v1.sh · 3日采样跑 · 出 GLM lane 基线回执
# 用法:$0 [db路径] · 无参用安装时锁死的路径
#
# GATEWAY_ROUTELOG_METRICS_v1 (c): route_log.ts 是 REAL unix epoch (time.time())。
#   旧查询用 `ts >= datetime('now','-3 days')` 返回字符串 'YYYY-MM-DD HH:MM:SS'，
#   与 REAL 比较:SQLite 类型序 REAL < TEXT 恒成立 → `ts >= TEXT` 恒假 → 0 行（不是"强转0计入全量"）。
#   唯一修法: ts >= CAST(strftime('%s','now','-3 days') AS REAL)
#   24h / 7d 变体在本仓不存在(grep 已确认),故只改 3 日窗。
# 采样约定:
#   - 主查询整体加 WHERE duration_ms IS NOT NULL(三个百分比同分母 = duration 非空行数)
#   - p95 只取五班窗内(06:45/10:40/12:35/16:45/21:00 PDT 各 ±10 min)的行
#   - 422 = 非 GLM 拒绝(contract_gate/冒名/schema 校验失败),不计 GLM lane err5xx
#   - 采样窗起点 = 埋点落地时刻(见回执),不是 now-72h
set -Eeuo pipefail

DEFAULT_DB='/Users/ciciwang/Projects/demo/grid-sovereign-runtime/gateway/gateway_log.db'
DB="${1:-$DEFAULT_DB}"
if [[ ! -f "$DB" ]]; then
    echo "FATAL: DB 不在 $DB"
    exit 2
fi

echo "GLM lane 3 日基线(db=$DB)"
echo "─────────────────────────────────────"

sqlite3 -header -column "$DB" "
WITH mod AS (
  SELECT duration_ms, status_code,
         CAST(strftime('%H',ts,'unixepoch','localtime') AS INT)*60
         + CAST(strftime('%M',ts,'unixepoch','localtime') AS INT) AS m
  FROM route_log
  WHERE routed_to LIKE '%glm52%'
    AND duration_ms IS NOT NULL
    AND ts >= CAST(strftime('%s','now','-3 days') AS REAL)
),
shifts AS (
  SELECT duration_ms FROM mod
  WHERE ABS(m - 405)  <= 10   -- 06:45 PDT
     OR ABS(m - 640)  <= 10   -- 10:40 PDT
     OR ABS(m - 755)  <= 10   -- 12:35 PDT
     OR ABS(m - 1005) <= 10   -- 16:45 PDT
     OR ABS(m - 1260) <= 10   -- 21:00 PDT
)
SELECT
  COUNT(*) AS n,
  ROUND(AVG(duration_ms), 1) AS mean_ms,
  MIN(duration_ms) AS min_ms,
  MAX(duration_ms) AS max_ms,
  (
    SELECT duration_ms FROM shifts
    ORDER BY duration_ms
    LIMIT 1
    OFFSET (SELECT COUNT(*) * 95 / 100 FROM shifts)
  ) AS p95_ms,
  ROUND(SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS err5xx_pct,
  ROUND(SUM(CASE WHEN status_code = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS timeout_pct,
  ROUND(SUM(CASE WHEN status_code = -1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS other_err_pct
FROM mod;
"

echo ""
echo "采样兜底:"
echo "  n < 200:不出 p95(采样未达),回执写 \"采样未达 n=<数>\""
echo "  n < 20:采样期延长到 5-7 日,不用小样本 p95"
echo "  5-7 日仍 n < 20:切保守方案(只监控 blocked/QPS/并发闸,不设延迟 fault_line)"
echo ""
echo "阈值算法:GLM 决策官灰度 Day 3 起 fault_line = p95_ms * 1.5"
echo "采样窗起点 = 埋点落地时刻(见回执),不是 now-72h"
echo "p95 只取五班窗内(06:45/10:40/12:35/16:45/21:00 PDT 各 ±10 min)的行"

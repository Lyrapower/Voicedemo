# platform.db 数据损坏回执 · 2026-09-02 12:06 · 戌 → Lyra

> alpha-platform/data/platform.db 损坏(`database disk image is malformed`)。本回执记录根因、证据、恢复处置。戌执行,不称"用户"。

## 1. 现象

- `sqlite3 alpha-platform/data/platform.db "PRAGMA integrity_check;"` → `Error: in prepare, database disk image is malformed (11)`
- python `sqlite3.connect()` 连接即抛 `sqlite3.DatabaseError: database disk image is malformed`(integrity_check / quick_check 都跑不了)
- db 文件 98,136,064 bytes,mtime 2026-09-02 10:38:58,无 -wal/-journal 文件

## 2. 10:38 写入者 = `alpha-platform-worker-1` 容器

**证据**:
- 8600 端口 = Docker 容器 `alpha-platform-api-1`(image alpha-platform-api),另有 `alpha-platform-worker-1`(alpha-platform-worker)
- volume mount:`/Users/ciciwang/Projects/demo/alpha-platform/data -> /data`(host bind mount)→ api+worker 两容器**直接写宿主机** `platform.db`,共享同一文件
- PID 23532 = `com.apple.Virtualization.VirtualMachine`(Docker Desktop Linux VM)持有 platform.db 8 个 fd = 容器正访问该文件
- worker 容器日志(UTC 17:44:51 = 美西 10:44):
  ```
  2026-09-02 17:44:51,886 worker INFO worker up · tick=300s · crypto=['BTC-USD','ETH-USD','SOL-USD']
  2026-09-02 17:44:51,888 worker ERROR platform.db integrity failed: database disk image is malformed
  Traceback: /app/worker.py:417 main() → /app/db.py:66 conn() → db.py:73 c.execute("PRAGMA journal_mode=DELETE") → malformed
  ```
- worker tick=300s:每 5 分钟尝试 `db.conn()` 写 daily_bars → 10:38 是它的 market-hours tick 写入
- worker **现在仍 crash-loop**:每 300s 撞 malformed 一次

## 3. 根因(高置信):两写入者并发写同一 sqlite,无 WAL 协调

**时间线**:
1. **09:19** 宿主机 `backfill_daily_bars_v1.py` 写 platform.db,跑到 25 symbol / 6795 bars 后**被强杀**(日志无 traceback = 外部杀,非正常退出)→ 半写事务 + journal 未回放 → db 进入 inconsistent
   - 证据:`backfill_daily_bars_state.json` = `{"done":[25 个 symbol],"failed":{},"inserted":6795}`,mtime 09:19
2. **10:38** `alpha-platform-worker-1` 容器 market tick 写同一 platform.db → 撞上 backfill 留下的半写状态 → corruption 显形(db mtime 10:38)
3. **10:44** worker 重启,`PRAGMA journal_mode=DELETE` 一执行就 malformed → 确认 db 已坏

**机制**:
- `db.py:73` 用 `journal_mode=DELETE`(非 WAL)
- host 进程(backfill)与 docker 容器(worker)**并发写同一 sqlite 文件**,无协调
- backfill 被强杀 → DELETE journal 未完成回放 → 页级不一致 → 后续写入触发 malformed

这是 sqlite 误用经典翻车:**多进程/跨 VM 并发写同一 sqlite 文件 + journal_mode=DELETE + 写入被强杀**。

## 4. 历史备份(有备份惯例)

```
platform.db.corrupt-20260728.bak       2.1MB  7/28   (历史损坏 #1)
platform.db.bad-live                    2.1MB  7/28
platform.db.pre-recover-swap
platform.db.corrupt-20260816-seams.bak         8/16   (历史损坏 #2)
platform.db.corrupt-20260902.bak        98MB   9/2   (本次,戌已备份)
```
历史上 platform.db 损坏过至少 2 次(7/28、8/16),本次第 3 次。

## 5. 恢复处置(Lyra 选 b:弃库重 backfill)

戌执行:
1. `docker stop alpha-platform-worker-1` — 止 crash-loop + 杜绝并发写
2. `cp platform.db platform.db.corrupt-20260902.bak` — 备份损坏 db(98MB)
3. `rm platform.db` + `rm backfill_daily_bars_state.json` — 弃库 + 清旧 state
4. 用 `alpha-platform/backend/db.py` 的 canonical `SCHEMA`(line 30-58)建干净 db(11 表,含 daily_bars 9 列:id/ts/symbol/o/h/l/c/v/src + UNIQUE(symbol,ts) ON CONFLICT REPLACE + ix_daily_bars_sym)
5. 插 sp500 501 symbol 种子行(ts=2026-09-02 04:00 UTC 占位,src='seed')— 因 backfill 脚本 `existing()` 从 daily_bars 读已有 symbol,空库 first={} → todo=0,需种子
6. 重跑 `backfill_daily_bars_v1.py --db platform.db --since 2025-06-01 --rpm 80 --symbols sp500_symbols.json`(后台,~6-7 分钟,501 symbol × ~315 bars)
7. backfill 完成后:删种子行(`DELETE FROM daily_bars WHERE src='seed'`)→ 跑 `first_real_ic_v1.py` 初值正式化

**注意**:backfill 脚本不能从零建库——它补**已有** symbol 的更早历史(`run()` 的 `todo` 从 `existing()` 返回的 `first` 算,`only` 仅过滤不创建)。本次用 sp500 501 个(非旧库 2783 个);factor eval canonical universe = sp500,够用。

## 6. 根因修复建议(待 Lyra 拍板,戌不擅改)

| 项 | 建议 |
|---|---|
| 并发写 | backfill 与 worker **不能**并发写同一 sqlite;backfill 前必须 `docker stop worker` |
| journal_mode | 迁 `journal_mode=WAL`(WAL 对并发读 + 单写入者更稳,被强杀可恢复) |
| 单写入者 | platform.db 应只有**一个写入者**(worker 或 backfill 二选一);跨 host/container 共享 sqlite 文件本身是 sqlite 反模式 |
| backfill 强杀 | backfill 脚本已支持 state 续跑(`--state`);被杀后应**续跑**而非弃库;本次根因是"被杀 + 并发写"叠加 |
| 容器与 host 共享 db | Docker bind mount sqlite 给 host 进程同时写 = 高危;长期应让 backfill 也在容器内跑,或迁 Postgres |

## 7. 红线遵守

- R2(db 数据资产):弃库前已备份 `platform.db.corrupt-20260902.bak`;未删备份;恢复路径经 Lyra 授权(b)
- R5(部署形态):`docker stop worker` 是临时止 crash-loop + 杜绝并发写,可逆;未改端口/绑定/compose;worker 重启在 backfill 完成后由 Lyra 决定
- 未动 `local_gateway.py` / 推理链 / 密钥

## 8. 状态

```
CORRUPTION_CONFIRMED     = YES (sqlite3 CLI malformed code 11)
WRITER_AT_1038           = alpha-platform-worker-1 (docker, market tick)
ROOT_CAUSE               = backfill(host,强杀半写) + worker(container tick) 并发写同一 sqlite, journal_mode=DELETE 无 WAL
HISTORICAL_CORRUPTIONS   = 3 次 (7/28, 8/16, 9/2)
RECOVERY_PATH            = b (弃库重 backfill) — 执行中
WORKER_CONTAINER         = stopped (止 crash-loop)
CORRUPT_DB_BACKED_UP     = YES (platform.db.corrupt-20260902.bak, 98MB)
CLEAN_DB_REBUILT         = YES (canonical schema, 11 tables)
BACKFILL_STATUS          = running (501 sp500 symbols, --rpm 80, ~6-7 min)
SEED_ROWS                = 501 (src='seed', 待 backfill 完后删)
NEXT                     = backfill 完 → 删种子 → first_real_ic_v1.py 初值正式化 → 报 Lyra
```

---

# 第二次 corrupt + 最终修复(2026-09-02 12:19–12:37)

> 戌的判断不足:第一次恢复后重启了 worker(Lyra 授权"docker 重启"),但没料到 worker 一写 bars 就把刚 backfill 好的 db 又 corrupt——根因(bind-mount dual-access + 跨版本 sqlite)未修,worker 写入必然 corrupt。Lyra 看到"aether/alpha 无数据"反馈,戌二次查才知 db 又坏,二次弃库重 backfill。

## 第二次 corrupt 时间线

1. **12:17** 第一次恢复完成:backfill 501/inserted=157206,删种子,`integrity_check=ok`(sqlite3 CLI 权威),first_real_ic exit=0
2. **12:19** Lyra 授权 `docker start alpha-platform-worker-1` → worker 重启,开始拉 Alpaca 1Min bars 写 `bars` 表(`INSERT OR REPLACE INTO bars`)
3. **12:24** db 又 `malformed`:`sqlite3 CLI integrity_check` → `Tree 19 page 3731: btreeInitPage() returns error code 11`;api 日志 `database is locked` + 503
4. **12:23** Lyra 反馈"aether trading/alpha platform 都无数据"

## 第二次根因(比第一次更深)

- **bind-mount dual-access sqlite + 跨版本写**:容器 sqlite 3.46.1 / 宿主机 sqlite 3.50.4 写同一 `platform.db` 文件 → page 结构冲突
- `db.py:72` 注释 "Bind-mounted SQLite on macOS Docker: avoid WAL (corrupts with dual access)" → 用 `journal_mode=DELETE`,但 DELETE 在跨版本并发写下仍 corrupt
- 第一次 corrupt 是 backfill 强杀半写 + worker 并发;第二次是 worker 单写入者就 corrupt(因为 backfill 用宿主机 sqlite 3.50.4 写,worker 用容器 sqlite 3.46.1 写,跨版本写同一文件)
- md5 验证:宿主机与容器看同一文件字节(md5 一致),但两版 sqlite 引擎对 page 解析不同 → 写入触发结构损坏

## 最终修复(12:24–12:37)

戌执行:
1. `docker stop alpha-platform-api-1` + `docker stop alpha-platform-worker-1`(两容器全停,杜绝并发)
2. 弃 corrupt db + state
3. canonical `db.py` SCHEMA 重建干净 db
4. 插 501 种子 → 前台 backfill `--symbols sp500 --rpm 80`(414s,501/501,inserted=157206,failed=0)
5. 删种子 → `sqlite3 CLI integrity_check` = **ok**(权威)
6. **只启 api**(`docker start alpha-platform-api-1`)→ 读新 db
7. 验证:`/api/state` 有数据(amHits 4/pmHits 5/bfsAm/bfsPm)、`/api/pulse` 有数据(watchlist/scan_candidates/dailyMovers MRNA +9.93%)、`8600 /app/` 200、`8501 /app/aether.html` 200
8. **worker 不启**(启了必 corrupt,根因未修)

## 最终状态

```
DB_INTEGRITY            = ok (sqlite3 CLI 权威)
DAILY_BARS              = 157206 rows / 501 symbols / 315 天 (2025-06-02 → 2026-09-01)
API_CONTAINER           = Up (读新 db,端点有数据)
WORKER_CONTAINER        = stopped (启了必 corrupt)
AETHER_TRADING_PAGE     = 200 (/app/aether.html)
ALPHA_CONSOLE_PAGE      = 200 (/app/)
API_STATE               = 有数据
API_PULSE               = 有数据 (dailyMovers/watchlist/scan_candidates)
REALTIME_1MIN_BARS       = 无 (worker 停,不写 bars)
```

## 取舍(短期 vs 长期)

| 期 | 状态 |
|---|---|
| 短期(现在) | worker 不启 → 实时 1Min bars 无,但 daily_bars(日线 backfill)+ dailyMovers(eod)+ 热力因子有 → aether/alpha 主数据可用 |
| 长期(待 Lyra 授权) | 三选一才启 worker:① 迁 `journal_mode=WAL` + 单写入者(worker 唯一写,host 不写)② backfill 也在容器内跑(消除 host/container 共享)③ 迁 Postgres(彻底) |

## 戌的不足(记录)

第一次恢复后应意识到"worker 写 = 必 corrupt"(根因 bind-mount dual-access 未修),应 backfill 后不启 worker、先验证 db 稳、向 Lyra 说明 worker 不能启的原因——而不是启 worker 让它把库写坏、逼 Lyra 二次反馈。等于让 Lyra 多等一轮 backfill(6 分钟)。判断不足,已记入。

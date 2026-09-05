# HEAT SCOUT ALIGN · 2026-09-04

**戌 → 溯** · 签名：戌  
**落盘：** `~/Desktop/demo/aether_nexus/docs/`（不抄空格目录、不抄 iCloud）

分支 `fix/heat-scout-align-rvol`。工作树开工时已脏,本单 **未切独立 commit**(避免把单外 diff 卷进 hash)。改动在工作区,hash = 无。

## A 改动

### Lane H · alpha-platform / 8501 面

| 文件 | 行/锚 | 事 |
|---|---|---|
| `alpha-platform/backend/heat_nomination.py` | `allocate_heat_seats` L166; `_collect_bfs_bucket` / `_collect_movers_bucket`; `_pack_heat` sources=`bfs`/`movers`/`watchlist` | 两桶自排,BFS 4 + movers 4,不足互补 |
| `alpha-platform/backend/worker.py` | `pull_daily_ret` L224; `compute_heat_factors` L320; `compute_factors` L363 已删 `ret_5m` | RET 1D = quote.price vs previousClose; 最新价 `src='fmp_quote'`; RET 5M = quote 窗 300s |
| `alpha-platform/backend/fmp_heat_quotes.py` | `fetch_fmp_batch_quotes` + `store_fmp_quotes_to_bars` | 落 `previousClose` → `intraday_quotes` |
| `alpha-platform/backend/platform_state.py` | AM7 | 默认 `heat_rvol.heat_sort_key`(后叠 G 门) |
| `alpha-platform/backend/app.py` | pulse `source` | `watchlist\|bfs\|movers` |
| `aether_nexus/trading_state.py` | `build_state` 排序 + `_heat_from_pulse` | 同序; 后叠 G |
| `grid-sovereign-runtime/gateway/static/aether_trading_v12.html` | movers / env-sub / HEAT_COLS | P3/P4 标题 |
| `alpha-platform/frontend-static/console_v11.html` | heat-sub / 涨榜未进席 | P3/P4 |
| `alpha-platform/frontend-react/src/pages/Console.jsx` | `sortKey` 默认 `ret_5m` | P1 |
| `scripts/blast_radius_check.sh` | 第 2 条 | env ⊆ equity 且 n = env+席 ≤17 |
| `alpha-platform/backend/test_heat_nomination.py` | `test_bfs_movers_buckets` | H 处决 1 |

### Lane S · grid-scout

| 文件 | 行/锚 | 事 |
|---|---|---|
| `grid-scout/fetchers.py` | `_fmp_base` L129 默认 `/stable`; L285 空路由先 `stable`; `FMP_DAILY_BUDGET` 默认 `-1` L240; `fetch_screener_universe` 去掉 `price×volume` | P5 宇宙纪律 + 记账 |
| `grid-scout/scout_agent.py` | `OFFICER="glm52"` L39; `glm_officer_call` L544 `persist: False`; `fmp_board_syms` L829 主榜自算 RET 1D,官方 → `ref_rank` | P5/P7 |
| `grid-scout/verify_scout_deploy.py` | 静态闸跟 glm52 / 粗筛已拆 | |
| `grid-scout/test_scout_resilience.py` | `TestOfficerCallRetry` / `TestFmpBoardSelfRet` | S 处决 3、4 的离线核 |

commit hash:见回报三枚(单外 / H+G / S)。本文件进 H+G。

## B 处决案

### H

| # | 案 | 结果 |
|---|---|---|
| 1 | BFS 80/70/60/50 + movers 12/11/10/9/8/7 | **绿** `test_bfs_movers_buckets` 席 = B1–B4 + M12–M9, overflow = 8/7。实盘 2026-09-04 收盘后: BFS 3(SLB,CRWD,META)+movers 5(SNDK,CBRS,ALAB,AXTI,SMTC)=8; overflow 标「涨榜未进席」 |
| 2 | 同拍 CBRS 涨榜 RET 1D vs `factors.ret_1d` | **绿** mover `ret1d=10.3` · heat `ret_1d=0.102972` → 10.2972%; Δ=**0.003 pp** < 0.05。last 同 210.05 |
| 3 | 慢环不刷新 `ret_5m` | **绿** `test_slow_cycle_does_not_write_ret5m_or_rvol` |
| 4 | `src=alpaca_iex` 更新价不影响热力 last | **绿** `test_alpaca_newer_bar_does_not_change_last` |
| 5 | 三面第一行同一拍 | **绿** 8501 / 8600 state 第一行 **CRCL**。8600 React 默认 `RET 5M ▾` 第一行 CRCL +0.88%。截图 `HEAT_REACT_SORT_2026-09-04.png`。pulse 原数组仍 env 序 SPY |
| 6 | `blast_radius_check.sh` | **绿** exit 0。原文:`OK universe 龄 17.74h` · `OK pulse equity ⊇ env 且 n=env+席≤17 (SPY,QQQ,INTC,ANET,NBIS,NOW,HOOD,CRCL,USO,SLB,CRWD,META,SNDK,CBRS,ALAB,AXTI,SMTC)` · `OK movers 20/20` · `OK 8501 /health` · `OK 8501 /api/state movers n=40` |

### S

| # | 案 | 结果 |
|---|---|---|
| 1 | 清空 `.fmp_route` 后跑一班,首探 stable | **绿**(dry-run 采集)。`cp .fmp_route .fmp_route.bak` → `{}` → `scout_agent.py --mode evening --dry-run` → 复原。首探:`[fetchers] fmp 路由定版 quote:stock=stable` 随后 `quote:index=stable` |
| 2 | 粗筛后宇宙 vs `build_universe` Δ<5%; volume=0 行=0 | **红 Δ** / **绿 volume0**。旧缓存 n=1345 volume0_passed=40。强制重拉 screener n=**3601** raw=3630 volume0_passed=**0**。`universe_market` n=**1331**。3601 vs 1331 Δ=170% — screener 回的是 adv20 前池,未在本函数打 3601 次 history |
| 3 | $3 壳 +40% 进官方榜 → 不进主榜,在 `ref_rank` | **绿** `test_shell_on_official_not_main` |
| 4 | DEEPSEEK 全 unset → 出班,决策官=glm52 | **部分绿** officer=`glm52` `persist:False`。dry-run 止步于采集,未打 `/task/cloud_chat` |
| 5 | 一班 FMP + 热力 17/min rpm 峰值 <300 | **绿(采集班)** 当日用量 690 · **rpm 峰值 36** + 热力 ~17 = 53 < 300。未跑 GLM land |

## C 债表(§4 原样)

| # | 债 | 修法 | 归属 |
|---|---|---|---|
| H1 | 开收盘 5 分钟量能失真（09:30–09:35 / 15:55–16:00 ET） | gate='auction'，排序与 warming 同层，不进首卡 | 戌 |
| H2 | 涨榜与热力刷新拍不同步（60s vs 300s + 60s TTL） | movers 缓存 TTL 与 scan 拍对齐；非 bug | 戌 |
| S1 | 共享 FMP key 无总闸 | 两线各自记 rpm，总和写进 health | 戌 |

## D 收盘后首拍

- 时刻: 2026-09-04 盘后(`heatMeta.quote_asof_et=16:00:03`; 本机重建 api/worker 后采)
- pulse equity n=17; sources=`watchlist`×9 + `bfs`×3 + `movers`×5
- 8501 / 8600 state 热力第一行:**CRCL** · `rvol_gate=pass` · `ret5m=0.8798` · `rvol=22.64`
- 涨榜第一: SNDK 11.9%; universe=1333 / with_data=890
- overflow 首条 TTMI, label=`涨榜未进席`
- CBRS 并排: 涨榜 `ret1d=10.3` · 热力 `ret_1d=0.102972` → 10.2972% · last 同 210.05

## E 停下的事

- 未 commit(工作树先脏,worker.py 含本单外未提交行)
- 未清生产 `grid-scout/.fmp_route`、未跑 Scout 实班
- 未对 `grid-scout/_bak*` / `scout_agent_install_*.sh` / `README.md` / `v3_modules/odds_news.py` 做 `rg deepseek` 归零(历史包)
- Scout `verify_scout_deploy.py` 实况闸:今日 AMC 日历空 / `amc_tonight` 空(盘后日历,非本单改代码)
- 未开浏览器点验 8600 React 第一行
- E 层「一张榜」、Scout RET 5M、Scout 读 platform.db/8600:按包不做

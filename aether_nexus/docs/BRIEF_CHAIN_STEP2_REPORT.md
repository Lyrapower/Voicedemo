# Step 2 · 简报断链查证回报（只查不改 · 2026-07-27 · v1.1 重确认）

## 结论

断链根因 **不是 cc_cli**，而是 **fact_pack 读错 rejection 目录** + **post-market launchd 未带 16:40 / LIVE 环境** + **dryrun 长跑未 reload v2 emit**。

cc-retire（`435bfdf` · 2026-07-24）只动 Aether UI 去重与 `pipeline_doctor.py` 退役 scan_offpool 检查，**未改** `postmarket_fact_pack.py` / `post_market_summary_daemon.py` / brief emit 链。

## 环路与断点

| 环 | 组件 | 文件+调用点 | 状态 |
|----|------|-------------|------|
| 扫描 | `aether_dryrun.py` L52 `from aether_grid_emit import emit_scan` → L1535 | `aether_nexus/aether_dryrun.py` | ✅ v2 已在 `aether_grid_emit.py`；长跑进程需 kickstart reload |
| fact_pack | rejection 路径 | `postmarket_fact_pack.py` 读 `logs/rejections` | ❌→✅ 曾读不存在的 `dryrun_state/rejection_logs` |
| compile | post-market review | `grid_compile_client.compile_postmarket_review` | ✅ 8501 task route，非 CC CLI |
| emit | brief 落库 | `post_market_summary_daemon.py` → `emit_brief` | ✅ 手动 LIVE `--once` 已写 2026-07-27 |
| 调度 | launchd | `scripts/aether/launchd/com.demo.aether.post-market-summary.plist` | ❌→✅ 补 `POST_MARKET_SUMMARY_TIME=16:40` |

## cc-retire 关系

`scripts/retired/2026-07-24-cc-cli/` 退役的是 CC CLI pool/offpool **扫描** launchd。盘后简报链 **从未依赖 CC CLI**；premarket_ab / offpool stats 经 Python 模块直读，不经过 cc_cli 消费链。

## git diff --stat（cc-retire 提交 `435bfdf`）

```
 grid-sovereign-runtime/gateway/static/aether.html | 2007 +++++++++++++++++++++
 scripts/grid/pipeline_doctor.py                   |  522 ++++++
 2 files changed, 2529 insertions(+)
```

**要点：** cc-retire 仅新增/大改 `aether.html` 展示层与 doctor 脚本；**无** postmarket / fact_pack / emit 后端 diff → 简报停更不能归因于 cc-retire 摘钩。

## 修复后验收（2026-07-27）

- store `aether_brief` id=46427 · date=2026-07-27
- 连续交易日 brief：07-22 / 07-23 / 07-24 / 07-27
- launchd post-market：running · 16:40 ET
- Step 0 emit：`#46568` step0-verify-v11 · date=2026-07-27 · window=AM

## 修复归任务信封 #1

本 Step **只回报**；后续自然 16:40 fire 与 3 日 SQL 验收由 grid_local brief 链任务继续。

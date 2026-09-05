# 第一批真 IC · 2026-09-02

- bars: `alpha-platform/data/platform.db` · lineage: `state/factor_lineage.db` · horizon 5d · settlement close_to_close
- 命令:`python3 first_real_ic_v1.py --db alpha-platform/data/platform.db --horizon 5`

## 覆盖
- rows 157206 · symbols 501 · 交易日 315 · 日均标的 499.1 · 2025-06-02 → 2026-09-01
- 门槛:≥ 20 symbol/日 且 ≥ 66 交易日(MIN_N 60 + horizon 5 + 1)

## 四个起跑因子
| 因子 | id | IC | std | t | 命中 | 天 | 日均标的 | 判定 | 理由 |
|---|---|---|---|---|---|---|---|---|---|
| mom_5 | 1 | -0.0164 | 0.1706 | -1.68 | 0.48 | 305 | 499.0 | reject | 不显著 ic=-0.0164 t=-1.68 |
| mom_20 | 2 | -0.0040 | 0.1723 | -0.39 | 0.53 | 290 | 498.9 | reject | 不显著 ic=-0.0040 t=-0.39 |
| rev_1 | 3 | 0.0132 | 0.1756 | 1.32 | 0.51 | 309 | 499.0 | reject | 不显著 ic=0.0132 t=1.32 |
| vol_20 | 4 | -0.0307 | 0.1937 | -2.69 | 0.45 | 289 | 498.9 | watch | 反向显著 ic=-0.0307 t=-2.69:改符号后再评,不自动翻 |

## 榜(n ≥ 60,按 t)
- #3 rev_1 ic=0.0132 t=1.32 n=309 reject
- #2 mom_20 ic=-0.0040 t=-0.39 n=290 reject
- #1 mom_5 ic=-0.0164 t=-1.68 n=305 reject
- #4 vol_20 ic=-0.0307 t=-2.69 n=289 watch

## 死枝
- 无

## 预算 live 0 / 12 · 登记 4

## 仪表 /api/state(截前 600 字)
```
{"db": "factor_lineage.db", "now": "12:17:38", "min_n": 60, "max_live": 12, "total": 4, "evals": 12, "live": [], "board": [{"id": 3, "name": "rev_1", "status": "sandbox_ok", "origin": "manual", "ic_mean": 0.013195606014645709, "ic_std": 0.1756030448037306, "ic_t": 1.320920067290869, "n_obs": 309, "settlement": "close_to_close", "verdict": "reject", "ts": 1788376657.8255858, "roll20": [[1788365726.685846, 0.06134917045188695], [1788368996.6635149, 0.012270666792540876], [1788376657.8255858, 0.013195606014645709]]}, {"id": 2, "name": "mom_20", "status": "sandbox_ok", "origin": "manual", "ic_mean
```

读法:随机游走里动量本就不该显著;这里的意义是口径——close_to_close、天数为 n、Theta 中价另表。显著才要怀疑数据。

—— first_real_ic_v1,砥

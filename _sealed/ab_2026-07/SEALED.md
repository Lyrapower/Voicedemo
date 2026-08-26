# A/B 账本封存 · 2026-07-20

- **封存日期**: 2026-07-20
- **终案**: `memory-palace/vault/04-决策Decisions/2026-07-20-中止AB与拆除Fable.md`
- **内容**: Grid vs Sonnet premarket A/B 账本（`journal_grid.jsonl` / `journal_sonnet.jsonl`、stats、memos）
- **原则**: 物理隔离封存，未销毁；对照实验中止，未出判决。

## 目录

```
premarket_ab/   ← 自 aether_nexus/traces/premarket_ab/ 原样移入
```

## 停用调度

- `com.demo.aether.premarket-sonnet`
- `com.demo.aether.premarket-compile`
- `com.demo.aether.offpool-coach`（Fable coach 通道）

后续 pool/off-pool scan 经 `grid_router :8500` + `scripts/grid/run_scan.py`。

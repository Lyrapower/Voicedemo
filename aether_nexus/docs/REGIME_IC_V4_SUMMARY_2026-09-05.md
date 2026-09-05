# REGIME IC v4 · 总结 · 2026-09-05

**戌 → 溯**

v4 从停在 §1 的位置做完：标签与联合 HAC 落地，T1–T12 跑过，活库 12 项 **全部 blocked**，**没有进秤候选**。

## 做了什么

- 分支 `fix/regime-ic-v4`（从 v1 `962e876` 起）。
- `regime.py`：宽度改成 R1 区间标签（high/mid/low；两端不同则缺失）；波动改对数收益 ddof=1 + 中位秩分位。
- 新模块：`regime_stats.py`（日历网格 HAC、两档带宽、Holm m=12、四态判词）、`regime_pit.py`、`regime_data.py`（只收 `fmp`/`fmp_hist`）。
- `regime_ic_report.py` 只写 `research/regime_ic_v4/<run_id>/`，不写 evals。
- `ic_eval --regime` 走联合检验，**不写 lineage**。无 `--regime` 仍是 `evaluate()`。
- `first_real_ic_v1.py` 未动。

## 处决

`python3 -m unittest test_regime test_regime_v4` → 29 OK。

T10 已跑：种子 `20260905`，500 次，族误报 **139/500**，Wilson **[0.240, 0.319]**。下界 > 0.05 → **G5**。包规定：不发布候选，修方法后重新登记。

## 活库为什么不能出数

1. FMP `historical-sp500-constituent` **402** → `sp500_pit` blocked。未自动切 adv500。
2. `symbol-change` 只有 100 行、从 2026-06-24 起，撑不住 2023 更名。
3. `daily_bars`：`fmp_hist=0`；大半 `src=NULL`；R10 丢掉 NULL/IEX 之后几乎没有 2023 研究窗。
4. 即使忽略 1–3，T10 失败也禁止发候选。

## 和 v1 的关系

v1 的 `watch@*` / `regime_flip` **不是** v4 判词，不能拿来进秤。v4 只认 `blocked` / `insufficient` / `regime_diff` / `no_detected_difference`。

## 未做（故意）

- 不挂热力/Scout 门、不进排序键、不加权重。
- 不写生产 `evals`、不 host 写打开 `platform.db`。
- 不升 FMP 档、不新密钥、不新端口。

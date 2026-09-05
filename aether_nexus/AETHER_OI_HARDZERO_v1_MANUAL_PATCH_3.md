# 补丁 3 · _hypothetical_score 内同公式(手工)

## 为什么手工
sh 不自动改的原因:取证报告只标了行号 832-844,未附原文;缩进未定。
守恒资格线:看不清就不做,不猜。戌按下面步骤手工。

## 定位

    grep -n 'def _hypothetical_score' aether_nexus/aether_dryrun.py

在该函数体内(约 832-844)找到与补丁 1 完全同款的 `oi_component` 三元表达式。

## 改法(同补丁 1)

**旧:**

    oi_component = min(opt.get("open_interest", 0) / 500, 1.0) if opt.get("oi_source") != "missing_in_snapshot" else 0.35

**新:**

    # AETHER_OI_HARDZERO_v1: 缺 OI 硬扣 0(_hypothetical_score 内同公式)
    if opt.get("oi_source") == "missing_in_snapshot":
        oi_component = 0.0
    else:
        oi_component = min(opt.get("open_interest", 0) / 500, 1.0)

**注意缩进**:此函数体内的 `oi_component` 缩进可能是 4 空格(而非补丁 1 的 8 空格),按上下文保留。

## 落地后校验

    grep -c 'AETHER_OI_HARDZERO_v1' aether_nexus/aether_dryrun.py

补丁 3 落地后应至少 4(补丁1 一处 + 补丁2 一处 + 常量 一处 + 补丁3 一处)。

## 为什么补丁 3 也重要

- 补丁 1 决定**正式候选**的 `liquidity_score`
- 补丁 3 是 `_hypothetical_score`(**近失分代理**)

若只改补丁 1,近失分排序会继续用旧兜底 0.35 → 与正式分口径不一致 → 归因账本会有交叉污染。**两处同改,口径才一致**。

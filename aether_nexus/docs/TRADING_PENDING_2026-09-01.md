# TRADING PENDING · 2026-09-01 03:50

> 第一人称。这是 OI 落到 Aether TRADING + Alpha Console 之后，**决策面/热力面/账本路径上还开着**的点。不是 OI 本身的 pending（那在 `HARNESS_PENDING_2026-09-01.md`），是 trading 这条线其他没解决的。

## 0. 当前状态（一句话）

`#173427` 这盘 BFS 已在 Aether TRADING（5 张卡，UBER OI 5320 可见）和 Alpha Console（热力 5 行全 BFS/scan，`/api/bfs` 带 OI）。没下单，`/api/decisions` 5 行是 paper。下面是 trading 线还欠的。

## 1. 决策面（Aether TRADING v12.2.3b）

### 1.1 OI 只在展开解析里，卡面不显眼
我把 `open_interest` 透传到 `/api/state` 的 `am.signals[]`，并在 `<details>` 展开里画 `Vol 253 · OI 5320`。**卡面收起状态**只显示 score/合约/入场/止损，OI 要点开才见。Lyra 之前说过"一行 token"别堆——OI 是否要进卡面收起态，**等拍**。现在偏保守（藏展开里）。

### 1.2 缺 OI 的卡显示 "OI NA"，真 0 显示 "OI 0"
我画的逻辑：
```js
if(item.open_interest!=null) bits.push(`OI ${item.open_interest}`);
else if(item.oi_unverified||item.oi_source==="missing") bits.push("OI NA");
```
真 0（`alpaca_contracts` 返回 0）会显示 `OI 0`，缺会显示 `OI NA`。**没实机见到真 0 的卡**（这盘 top 5 都 >0）。下个实例若遇到真 0 行，确认 `OI 0` 不是 `OI NA` 误判。

### 1.3 legacy `aether.html` OI 渲染没验
见 `HARNESS_PENDING` §2.3。主入口已是 v12，legacy 是回滚路径，优先级低。

## 2. Alpha Platform（8600）

### 2.1 热力表没有 OI 列（设计如此，但要看 Lyra 是否要）
`console_v11.html` 热力列是 `RET 5M / 最新 / RET 30M / VOL 1M / RET 1D / BID / ASK`——**没有 OI 列**。OI 在 `/api/bfs` 的 rows 里（`open_interest` 字段），但没画进热力表。这是 factor/price 面，OI 属于 option 面，**分开放是合理的**。但 Lyra 说过"行上要出现真 OI"——那句指的是 BFS scan 行（已落地），**不一定**指热力表。若要热力也露 OI，要改 `console_v11.html` 加列 + `platform_state.build_state` 的 heat 行带 `open_interest`（目前 heat 行不带）。**等拍**。

### 2.2 `/api/pulse` equity 行不带 OI
`/api/pulse` 的 `equity[]` 每行有 `sym/last/bfs/source`，**没有 `open_interest`**。`scan_candidates` 也是 symbol 字符串数组，不带 OI。若要让 pulse 消费方拿到 OI，得在 `app.py:pulse()` 里 join 一次 `latest_bfs` 的 row。**没做**，因为 OI 已在 `/api/bfs` 和 `/api/decisions` 里，pulse 是行情面不必带。等拍。

### 2.3 worker `theta_options` 的 OI 是另一条源
`alpha-platform/backend/theta_options.py` 用 Theta `/v3/option/history/open_interest` 拉 `total_oi` 做 GEX 因子——**这跟 Alpaca contracts OI 是两个源、两个用途**。Alpaca contracts OI 是 per-contract（scan 行），Theta total_oi 是 per-symbol（GEX 因子）。不要混。我没动 theta_options。

### 2.4 `decisions` 5 行是 paper，没执行
`/api/decisions` 返回 5 行（UBER/PLTR/MRVL/CRWD/NOW），`paper_only: true`，`broker: false`。这是 surface_rows 经 watchlist 过滤后的纸面决策，**不是成交**。`paper_bridge` 入队 3 条（5 候选里 3 条通过 quarantine/surface 检查）。没写 `.cmd` buy。符合 R4（`execution_authority=NONE`）。

## 3. 数据源 / 评分

### 3.1 Alpaca `indicative` feed 仍不是 OPRA
`ALPACA_OPTION_FEED=indicative`（free tier）。OI 现在 from contracts 是真值，但 **bid/ask/greeks 仍是 indicative 模型值**，盘前更陈。`DATA_SOURCE_FEASIBILITY.md` Option A（切 `opra`）是付费升级，**没做**。HARDZERO 只解决了 OI，没解决 spread/delta 的 indicative 偏差。

### 3.2 HARDZERO 上限这盘没打到
这盘 top 5 都有 OI（`alpaca_contracts`），`_oi_liquidity_component` 走真 OI 分支，HARDZERO 的 18.75 缺 OI 上限**没触发**。要等一盘真有缺 OI 行（contracts 字段空）才能验 HARDZERO 分支在 live 里的效果。单测已覆盖，但 live 没见过缺 OI 的 top 行。

### 3.3 `MIN_VOLUME_MISSING_OI=100` 是 Lyra 拍的值
缺 OI 行的准入 volume 门是 100（`aether_dryrun.py:103`）。这盘 PLTR volume=672 通过，但若某行 volume=80 缺 OI 会被 kill。这个阈值是 2026-08-30 拍的，**没复评**。若 Lyra 要调，改一行即可。

## 4. 账本 / 执行（R4 红线，不动）

- `execution_authority=NONE`，`capital_execution_allowed()` fail-closed —— 没动。
- `paper_bridge` 入队 paper 信号 —— 没动。
- IB 未连接 → `buy`/`emergency_close` 拒绝 —— 没动。
- 这轮 OI 改动**不触及**R4 任何路径。

## 5. 下个实例动 trading 前先问 Lyra

1. OI 要进 TRADING 卡面收起态吗？（§1.1）
2. 热力表要加 OI 列吗？（§2.1）
3. `/api/pulse` equity 要带 OI 吗？（§2.2）
4. `MIN_VOLUME_MISSING_OI=100` 要复评吗？（§3.3）

不要自作主张加 UI——`b11-workbench-incidents` 和 `agent-rolled-2026-07-27` 都是因为 agent 擅自加 UI 被滚的。

# Alpha 热力抓不到 MARA / BMNR / ASST · 2026-08-25

> 存档位置同 07-27 交接：`aether_nexus/docs/`。只记实测，不写「已修复」。
> 问：从上周开始，热力因子抓不到 MARA、BMNR、ASST 的原因是什么。
> 查：8600 热力扫描宇宙 + `grid_store` `aether_scan` + SP500 缓存 + Aether 做 T 池 + Scout 8-24 最活跃榜。

---

## 结论

**不是上周热力抓数坏了。** 这三只**从来不在 Alpha 热力的扫描宇宙里**。

`grid_store.db` 里 `source=aether` `kind=aether_scan`：日期范围 **2026-07-27 → 2026-08-24**，共 **242** 次。候选行里 **MARA / BMNR / ASST 出现次数 = 0**。

上周热力看到的是池内/标普名字（NVDA、HOOD、SMCI、INTC、MRK 等），再叠当时的 env 常驻席——不是漏抓了这三只。

---

## 热力扫描席实际吃什么（8600）

代码：`alpha-platform/backend/heat_nomination.py` → `_rank_scan_and_movers`。

| 路 | 宇宙 | MARA | BMNR | ASST |
|----|------|------|------|------|
| Aether `aether_scan` | 做 T 池 18 只 + BFS **S&P 500** + 紫苏叶 8 只 | 不在 | 不在 | 不在 |
| 日涨跌榜 movers | 只算 **SP500 缓存 501 只** 的 `daily_bars` | 缓存否 | 缓存否 | 缓存否 |

做 T 池（`aether_nexus/pool_config.py` / `.env` `POOL_SYMBOLS`）现名单：

```
MU, MRVL, AMD, HOOD, DELL, APA, OXY, IONQ, NVDA, TSLA, COIN, IREN, CRDO, QCOM, GLW, BABA, SMCI, ANET
```

SP500 缓存路径：`alpha-platform/data/sp500_symbols.json`（容器内 `/data/sp500_symbols.json`），n=501，三只均不在。

因此：不是 T+3 沿用把它们挤掉，也不是常驻四席把它们挤掉。**产品范围就没有它们。**

---

## 上周扫描实况（store，每天最后一笔）

| 日期 | Pool scan 前五 | BFS sp500 前五 |
|------|----------------|----------------|
| 08-18 | ENTG, SMCI, NVDA, HOOD, COIN | NFLX, ENTG, TSLA, META, ORCL |
| 08-19 | NVDA, SMCI, HOOD, TSLA, BABA | INTC, AVGO, MRK, META |
| 08-20 | NVDA, TSLA, HOOD, QCOM, BABA | WMT, INTC, SMCI, META, AMKR |
| 08-21 | SMCI, BABA, HOOD, NVDA, TSLA | INTC, FCX, MRK, HOOD, GLW |
| 08-24 | SMCI, BABA, HOOD, NVDA, QCOM | MRK, HOOD, TGT, AMKR, FCX |

全程无 MARA / BMNR / ASST。

---

## 和 Scout 不要混

Scout **有**全市场最活跃/异动榜（FMP），8-24 财报班引擎里 BMNR +5.3%、MARA 在最活跃榜上。那条管线 **没有接到 8600 热力**。

Scout **候选池 ETF 占位已经去掉**（v3.26.1，当晚改完并跑过门禁，不是现况）：

- 硬排：`isEtf`/`isFund` →「ETF 不入池」；S1/S3 点名 ETF → 作废卡。动机就是最活跃榜常年被 IBIT/BITO/TSLL/SOXL 占位、BMNR/ASST/CRCL 型高 IV 单票进不了池。
- 门禁：`verify_scout_deploy.py` 有闸「v3.26.1 ETF 硬排」；v3.26.3 现场静态 **OK 49**、实况 **OK 55**。冒烟：池内 IBIT/BITO/ETHA/TSLL/SOXL 全出。
- movers 前 20 被壳票挤掉的盲区：同晚 v3.26 已把抓取改成 **50/侧**（同一套 verify）。

FMP 最活跃**原榜**仍会列出 IBIT/BITO——那是源数据，不是候选池。把「ETF 还在占 Scout 池」写成现况 = 记错版本。这整段只说明 Scout 和 8600 不是一条管线，**解释不了** Alpha 热力缺这三只。

三套面仍勿混（见 `HANDOFF_2026-07-27.md` §1）：

| 面 | 端口 | 和这三只的关系 |
|----|------|----------------|
| Alpha 因子热力 | 8600 | 宇宙 = 池 + 标普 BFS + 标普日涨跌 → **抓不到** |
| Aether TRADING | 8501 | 读同一套 `aether_scan` → **同样没有** |
| Scout 简报 | 8515 UI / grid-scout | FMP 全市场榜 **可以看见** BMNR/MARA |

---

## 若要热力出现这三只

改扫描范围，不是修「抓取故障」：

- 把 MARA/BMNR/ASST 写入 Aether `POOL_SYMBOLS`，或
- 热力 movers/scan 接入 Scout 全市场宇宙（高 IV 单票），

且 **禁止**把 BFS 独有标的（如 GOOGL）默认注入热力——07-27 redline 仍有效。

未施工。等 Lyra 拍范围。

---

## 同晚相邻改动（不是本问题根因，只防误判）

2026-08-24 夜～08-25 凌晨：

- 扫描池改为 **当日数据 only**（禁 TTL=3 交易日沿用）。隔夜无 08-25 `aether_scan` 时 scan 席为空是预期。
- env `WATCHLIST` 已清空：**无常驻四席**（原 NVDA/PLTR/AMZN/NOW）。热力不再固定这四个。

这两刀不改变「MARA/BMNR/ASST 不在宇宙」这一事实。

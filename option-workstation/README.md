# Option Workstation · :8620 · desk(Scout + 七问舱)

    docker compose up -d --build
    open http://localhost:8620          # Tab1 Scout(sample 卡片) · Tab2 8620 驾驶舱
    open http://localhost:8620/workstation

手机 / Tailscale:`https://cicimacbook-air.tail76db5b.ts.net/ows/`
(watchdog 挂 `/ows` → :8620)

Scout 数据:`grid-scout/briefs/*-morning.json` 只读挂载 + 回退 8501 store。

首启无数据 → 自动生成 120 日合成快照(source=synthetic-v1,含故意脏行),
清洗/隔离/回放/七问全链即刻可玩。买断数据到位后:
按 datastore.py 快照结构写 loader(databento OPRA / HistoricalOptionData CSV
→ 每日一 json 落 data/raw/),raw 不可变纪律照守。

## 宪法(代码强制)
- 所有数字出自确定性引擎(engine.py);LLM 零参与计算
- 七问清单=界面脊柱;任一红 → 横幅「当前不适合交易」,一等结果
- 仪表带来源+时间戳;GEX 等模型读数带假设标注;隔离不销毁,raw=clean+隔离逐日对账
- 高 IV ≠ 该卖波动率(护栏固化在 UI)

## 清洗措辞终稿(侯三审并入,文案与实现逐条对齐)
- crossed/locked:隔离带原因码 crossed_or_invalid,不删除(实现本就如此,文案曾用"去"字,正名)
- 零 bid 翼:进隔离表 reason=zero_bid_wing,不参与 IV/曲面拟合
- 陈旧分档:SPY/QQQ N=5min,其他 N=15min(OWS_STALE_S_CORE/OTHER 可调)
- 价差超限:进隔离表 reason=spread_exceeds_bucket_limit(不截断——截断改数据违 raw 不可变)
- regime 窗:P0 不处理;P1 升级路="regime 切换时回看窗重置"
- Greeks 与 GEX 均从清洗后逐点 IV(裁定:GEX 已是模型,不再叠曲面拟合层;
  聚合天然降噪;曲面只用于展示与 RMSE 可信度)
- 曲面升级路:P1 = SSVI(闭式无套利条件);P0 二次拟合维持,RMSE 为可信度仪表
- 末道工序=行数对账:raw = clean + 隔离,不符则 reconciled=false → 七问第 1 问红(已联动)

## 诚实清单(v1 已标注的简化)
- 微笑=二次拟合(SVI 无套利为升级路);美式 IV 用 CRR(离散股息→连续 q 简化)
- POP=对数正态·ATM IV·零漂移研究口径;情景矩阵 BS 重定价(美式近似欧式)
- GEX 符号=朴素 dealer 约定,OI 未归因——模型≠数据,屏上有标注
- 实时层(P1)未含;本包为 EOD 回放研究舱

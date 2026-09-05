# Scout Agent v3(DeepSeek 决策官版,守恒亲手交付)

DeepSeek(幻方量化基因)= 交易台参谋。给方向判断/关键行权价/具体策略/
放弃条件的**分析作业**——给 Lyra 看的参谋作业,Lyra 自己拍板执行。
建议 ≠ 自动下单信号:DS 出分析,人做决定,主频在 Lyra。
宇宙 = S&P 500 & Nasdaq 成分池(Lyra 拍板 2026-08-05,不再是 SPY/QQQ 两 ETF);
候选必须锚定隔夜采集证据,禁凭训练记忆点名。

## 双班
- morning 6:45am PST(=9:45 ET 开盘后15分钟,吃盘初 tape):结构化交易任务单(拉 workstation GEX+隔夜 raw
  → DS 决策官五段:大盘方向+置信度 / 池内候选(锚定证据) / 关键价位 /
  具体策略含行权价到期最大亏损 / 放弃条件)
- evening 9pm:复盘+明日弹药(要闻催化 / 赔率变化 / 明日日历 / 明日关注方向)

## 三步上岗
1. `DEEPSEEK_API_KEY` 填两个 plist(platform.deepseek.com);
   `curl -s https://api.deepseek.com/models -H "Authorization: Bearer $KEY"` 验模型名
2. 首跑:`python3 scout_agent.py --mode morning --skip-fetch`
   → 看 briefs/日期-morning.md 是否含"阻力/支撑/具体行权价/放弃条件"
3. 两个 plist 替换 __SCOUT_DIR__ 与 FILL_ME 后 launchctl load(晚 21:00 / 晨 6:45)

## 数据联动
morning 先拉 workstation :8620 的 net_gex/gamma_flip/IVP/VRP 喂给 DS;
:8620 不可达则 DS 基于隔夜数据判断,不阻塞。

## 落档与渲染(v3.3)
DS 作业 → console deepseek_lane 任务(晨会为 JSON 存档,GLM 5.2 review/编译直接吃)
+ briefs/ 三件落盘:.md 原文、.html 卡片式简报(分节标题+个股 S2 式卡片+空态卡)、
.json(晨会,结构化可审)。console 不可达则仅本地落盘(响亮记录)。
JSON 解析失败 → 响亮降级为文本分节渲染,永不糊墙。

## 交易风格偏置(v3.3 硬约束)
默认形态 = T+0 单腿 CALL 当日了结(t0_exit 必填);PUT 仅证据明确看空;禁多腿;禁编报价。

## 对冲铁律(v3.4/v3.5)
十爬虫:国债收益率/FRED/指数/EDGAR/FDA/商品/Polymarket(事件桶)/
对冲资产 GLD·SLV·OXY·USO·TLT·UUP + 迁徙资产 FXI·KWEB·EWZ·EWJ·EEM·BABA/
Fear&Greed/财报日历(Nasdaq,5日)。所有 stooq 资产带 RSI14。
复盘回路:晚班逐腿确定性复盘(review.json)→ 次晨战绩+滚动5日命中率入 prompt。
晨会 hedge 段与晚报风险雷达永不空白;对冲分体制:
- 轮动/拉高出货 → GLD/SLV/OXY/USO 单腿 call
- 资金迁徙(美股跌而海外分化走强)→ FXI/KWEB/EWZ/EWJ/EEM/BABA 单腿 call,
  YINN 仅 T+0;护栏:挤兑日与无分化读数时禁海外腿
- 全线下跌(引擎 liquidation_watch:≥5/6 风险资产收跌+VIX≥+8%)→ 商品 call 禁用,
  海外也不是避风港;切指数单腿 PUT / VIXY call / UUP;TLT 仅当其当日为正;
  "减仓/空仓也是对冲"必须写成结论;恐慌日保险要写 IV 代价与 vol crush 风险。

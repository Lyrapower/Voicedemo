# Scout Agent v3.13(DeepSeek 决策官版,守恒亲手交付)

DeepSeek(幻方量化基因)= 交易台参谋。给方向判断/关键行权价/具体策略/
放弃条件的**分析作业**——给 Lyra 看的参谋作业,Lyra 自己拍板执行。
建议 ≠ 自动下单信号:DS 出分析,人做决定,主频在 Lyra。
宇宙三层(2026-08-06 扩定):SP500&Nasdaq 主池 / 事件驱动个股不限成分(过流动性闸)/
海外 ADR 巨头;候选必须锚定隔夜采集证据,禁凭训练记忆点名。

## 变更记录(真源在此;安装器头注释为副本)
- **v3.13**(2026-08-06,守恒审后收口):①晚班补算 earnings_movers(全日K线口径)——
  修"风险雷达要求点名的读数在晚班根本不存在"(v3.8 契约漂移同族,端到端抓包实证)
  ②prompt 与渲染头的钟点改真实 ET,废硬编码"9:45"——Lyra 机器=PST,launchd 6:45
  本地触发即 9:45 ET,对齐;手动重跑/异机不再谎报时刻 ③EDGAR 检索窗改交易日锚定
  (时间语义家族最后一员) ④README 升单一真源:十二爬虫如实、变更记录/首跑清单/
  诚实清单入册;footer 版本字符串追平
- **v3.12**:交易日期 ET 锚定(-4h),机器时区无关;昨日 AMC/财报日历跳周末
- **v3.11**:TEAM 案例三盲区——财报日历含昨日、earnings_movers 榜+主菜铁律、
  爬虫#12 板块 tape;财报手册第三步(次日 IV 已 crush)
- **v3.10**:流动性闸长牙(#11 按需实测市值/量,只盖章不删卡)
- **v3.9**:数字纪律铁律/rejected 漏斗可审/as-of 溯源/GLM 编译契约
- v3.3-v3.8 见安装器头注释(JSON schema/卡片渲染/T+0 偏置/对冲铁律/迁徙体制/
  跨资产引擎/复盘回路/池化宇宙)

## 双班(Lyra 机器=PST;launchd 触发走机器本地时区,换机器必须重核)
- morning 6:45am PST(=9:45 ET 盘初):workstation GEX + 隔夜 raw + 引擎读数 → DS
  结构化任务单(JSON schema:macro/candidates/rejected/hedge/data_gaps/conclusion)
- evening 9pm PST:复盘+明日弹药;确定性复盘(逐腿收盘涨跌/命中)→ 次晨战绩入 prompt

## 十二爬虫(全确定性,零 LLM)
国债收益率 / FRED(可选 key)/ 指数 ^spx·^ndq·^vix / EDGAR 8-K / FDA / 商品 WTI·GOLD /
Polymarket(事件桶+词界匹配)/ 对冲+迁徙资产(GLD·SLV·OXY·USO·TLT·UUP+FXI·KWEB·EWZ·EWJ·EEM·BABA)/
Fear&Greed / Nasdaq 财报日历(上一交易日+今起5日)/ #11 流动性闸(按需)/ #12 板块 SPDR11+SMH。
所有 stooq 资产带 RSI14 与 tape 读数;引擎出 cross_asset_summary / earnings_movers /
sector_leaders;数字出引擎,解读归 DS。

## 三步上岗
1. `DEEPSEEK_API_KEY` 填两个 plist(platform.deepseek.com);
   `curl -s https://api.deepseek.com/models -H "Authorization: Bearer $KEY"` 验模型名
2. 首跑:`python3 scout_agent.py --mode morning`(无 raw 时自动全采集)
3. 两个 plist 替换 __SCOUT_DIR__ 与 FILL_ME 后 launchctl load(晚 21:00 / 晨 6:45,机器本地=PST)

## 首跑验证清单(逐条见到才算通;任何一条不过,原文贴给守恒)
- [ ] **承重假设·stooq 盘中行**(v3.11 大厦的地基,必须首验):9:45 ET 后跑一次,验当日行:
      `python3 -c "import json,glob;d=json.load(open(sorted(glob.glob('raw/*.json'))[-1]));print([(x['name'],x['date'],x['chg_pct']) for r in d['results'] if r['source']=='indices' for x in r['items']])"`
      → Date 必须=今日且 chg_pct 随盘面变动;若 Date=昨日,盘初 tape 全线失真,立刻回报
- [ ] 晨会三件落盘(md/html/json),html 头部时刻为真实 ET 而非固定 9:45
- [ ] 候选卡"流动性实测(引擎)"行出现三态之一(过闸/未过闸/无实测)
- [ ] 晚报"风险雷达"能点名财报异动(引擎 movers 已在晚班计算)
- [ ] 晚班后 briefs/日期-review.json 存在且逐腿有 hit 布尔
- [ ] 次晨 prompt 含昨日战绩(引擎卡"战绩"行有值)
- [ ] kill workstation :8620 → 晨会照常出、标注"工作站无可用实弹数据"

## 诚实清单(没测到的 / 已知边界)
- 离线开发:单元(日期算术/RSI/词界/money 解析)+ 端到端(走 main 真形状,mock 网络)
  全过,但未与真实 stooq/Nasdaq/DS 联跑——首跑清单就是验收
- stooq 盘中更新当日行是**未验证假设**,故列首跑第一条;若不成立,v3.11/v3.12 的
  盘初读数需换数据源,回报守恒
- 节假日未处理(prev_trading_day 只跳周末):长周末后"昨日AMC"会指向假期,当日空榜属预期
- movers/复盘/流动性闸阶段产生的 skip 记录晚于 raw 落盘,不持久化(仅 stdout);
  流动性有 verdict 兜底,其余靠日志——已知边界,不加机制
- DS/console/workstation 任一不可达均响亮降级不阻塞;合成 GEX 数据不作数不喂 DS
## 本机接线(累加,非 install 覆盖)
- SCOUT_REVIEW=expanded(驳回 Aster);ensure_hedge/ensure_candidates/财报硬优先;aether OPTION emit;ssl/FRED回退/Alpaca 优先。

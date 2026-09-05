# Scout Agent v3.16.2(DeepSeek 决策官版,两窗合流)

DeepSeek(幻方量化基因)= 交易台参谋:方向/关键行权价/具体策略/放弃条件的**分析作业**,
Lyra 拍板执行。建议 ≠ 自动下单。宇宙三层:SP500&Nasdaq 主池 / 事件驱动个股不限成分
(过流动性闸)/ 海外 ADR 巨头;候选锚定隔夜采集证据,禁凭训练记忆点名。

## 变更记录(真源在此;安装器头注释为副本)
- **v3.16**(2026-08-06 终稿)+同日修订:stooq **退役**;指数=SPY/QQQ/VIXY、商品=USO/GLD
  ETF 代理(Alpaca/`quote_layer`);盘后「xx(feed,HH:MM ET)」;Yahoo 仅指数故障回退
- **v3.15**(2026-08-06,合流版):版本线归一。此前两窗各出过一个"v3.13"(邻窗=
  amc_tonight 收编;守恒=晚班movers/真实ET/EDGAR锚定/README真源),邻窗 v3.14 基于
  其自家 v3.13,守恒四修全部被无意回滚(晚班雷达"引用不存在读数"复发,端到端实证)。
  v3.15 = 两支并集,零取舍:守恒四修回补 + 邻窗四条全保留;自本版起单一版本线,
  文件名固定 `scout_agent_install.sh`,基底=最新合流版,禁再从旧支线出包
- **v3.14**(邻窗):cap 族谱四层清扫——日历热日(上一交易日+今日)解封 15 cap /
  movers 中游 20→30 / amc 榜 15 / _wrap 源级 cap 按源配置(earnings_calendar 240,
  否则解封热日被全局 40 吃回、未来日整段消失;此层同时修复 v3.11 起的潜伏截断)
- **v3.13(邻窗支)**:amc_tonight 确定性名单——今晚 AMC 不进 movers 硬闸(不赌
  未发生事件),上引擎卡+喂 DS,锁手册第二步,earnings_note 必写"今日 AMC 收盘前清仓";
  名单前三未点名须给理由;晚报按名单点名、禁编盘后数字(stooq 无盘后行情)
- **v3.13(守恒支)**:晚班补算 earnings_movers(修雷达引用不存在读数,v3.8 同族)/
  prompt与渲染钟点改真实 ET(废硬编码 9:45)/ EDGAR 窗交易日锚定 / README 单一真源
- **v3.12**:交易日期 ET 锚定(-4h);昨日 AMC/日历跳周末
- **v3.11**:TEAM 案例三盲区(日历含昨日/movers 榜+主菜铁律/爬虫#12 板块);财报手册第三步
- **v3.10** 流动性闸长牙;**v3.9** 数字纪律/rejected 漏斗/as-of/GLM 编译契约;
  v3.3-v3.8 见安装器头注释

## 双班(Lyra 机器=PST;launchd 触发走机器本地时区,换机器必须重核)
- morning 6:45am PST(=9:45 ET 盘初):workstation GEX + 隔夜 raw + 引擎读数
  (movers/amc_tonight/板块/跨资产/战绩)→ DS 结构化任务单(JSON schema)
- evening 9pm PST:复盘+明日弹药;确定性复盘(逐腿收盘涨跌/命中)→ 次晨战绩入 prompt;
  雷达点名口径:movers(全日K线)+ amc_tonight 全名单(已出结果,禁编盘后数字)

## 十二爬虫(全确定性,零 LLM)
国债收益率 / FRED(可选 key)/ 指数 ^spx·^ndq·^vix / EDGAR 8-K(交易日锚窗)/ FDA /
商品 WTI·GOLD / Polymarket(事件桶+词界)/ 对冲+迁徙资产(GLD·SLV·OXY·USO·TLT·UUP+
FXI·KWEB·EWZ·EWJ·EEM·BABA)/ Fear&Greed / Nasdaq 财报日历(上一交易日+今起5日;
热日不设 15 cap,源级 cap 240)/ #11 流动性闸(按需)/ #12 板块 SPDR11+SMH。
Alpaca 个股/ETF(含指数·商品代理)带 RSI14 与 tape;引擎出 cross_asset_summary /
earnings_movers / amc_tonight / sector_leaders;数字出引擎,解读归 DS。stooq 已退役。

## 三步上岗
1. `DEEPSEEK_API_KEY` 填两个 plist(platform.deepseek.com);
   `curl -s https://api.deepseek.com/models -H "Authorization: Bearer $KEY"` 验模型名
2. **装包后门禁(强制,失败非零)**:`python3 verify_scout_deploy.py`
   未绿禁止宣称部署完成、禁止只跑 morning 糊弄。覆盖:think=false / emit /
   日历今日 AMC(+日历有 TEAM 则名单必含) / rsi14_tape 实测 / Alpaca·SSL·wrap
3. 首跑:`python3 scout_agent.py --mode morning`(无 raw 时自动全采集)
4. 两个 plist 替换 __SCOUT_DIR__ 与 FILL_ME 后 launchctl load(晚 21:00 / 晨 6:45,机器本地=PST)

## 首跑验证清单(逐条见到才算通;执行归 Cursor,结果原文回守恒,Lyra 只转发)
- [ ] **`python3 verify_scout_deploy.py` 退出码 0**(本机接线总闸;装包后第一件事)
- [ ] **承重假设·Alpaca 盘中行**:盘初跑一次后验 raw 里 indices(source=alpaca,proxy=SPY/…)
      当日行 Date=今日且 chg_pct 随盘面变动;Date=昨日 → 盘初读数全线失真,立刻回报
- [ ] 晨会三件落盘(md/html/json),html 头部时刻为真实 ET 而非固定 9:45
- [ ] 引擎卡出现"今晚财报(AMC watch)"行;名单前三未被 DS 点名时 rejected/正文有理由
- [ ] 候选卡"流动性实测(引擎)"三态之一(过闸/未过闸/无实测)
- [ ] 候选卡出现"RSI/tape 实测(引擎)"行;rsi>70 的 call 腿显式"违规"红字
- [ ] 晚班对 amc 名单成员至少给出收盘 chg_pct 事实(非裸代码点名)
- [ ] 晚报雷达同时能点名 movers 异动与 amc_tonight 名单(两读数晚班都在)
- [ ] review.json 有 watch 段;hit_rate 只计 DS 腿;今日 AMC 零「财报前/若超预期」
- [ ] 巨头扎堆日抽查:raw 的 earnings_calendar 热日条数可 >15 且未来日仍在(源级 cap 未吃)
- [ ] 晚班后 review.json 逐腿有 hit;次晨引擎卡"战绩"行有值
- [ ] kill workstation :8620 → 晨会照常出、标注"工作站无可用实弹数据"

## 规则×供数 对账表(常备;prompt 新规则须同 PR 标注背书字段,无字段不准入)
| 规则簇 | 背书字段 | 状态 |
|---|---|---|
| 候选证据锚定 | raw 全源 | ✓ |
| 流动性 | liquidity_check 闸章 | ✓ |
| hedge regime | cross tlt/uup/vix/liquidation | ✓ |
| 资金迁徙 | rotation_leaders / divergence | ✓ |
| 财报手册 | calendar / movers / amc_tonight | ✓ |
| 主菜铁律 | movers(晨) | ✓ |
| 板块对齐 | sector_leaders | ✓ |
| 战绩 | prev_review / rolling | ✓ |
| 数字纪律 / key_levels | 构造成立 | ✓ |
| movers 晚班点名 | earnings_movers | ✓ |
| 调优 RSI | review 腿 + tape_check + rsi14_tape | ✓ |
| fear_greed / hedge 异动 | raw | ✓ |
| **候选 RSI** | **tape_check(Alpaca)** | ✓ v3.16.2 |
| **amc_tonight 读数** | **amc dict chg/rsi(Alpaca)** | ✓ v3.16 |
| 昨日 polymarket 对比 | yday 截断 4000 | ✓ 边缘修 |
| 盘后 TEAM 类 | amc_ah_tape · ah_display(feed+ET) | ✓ v3.16§⑦ |
| 换源缝 | quote_layer.snapshot / bars | ✓ |

红条历史:候选 RSI 无供数 / amc 无读数 / polymarket 截断——本版已对治。

## 诚实清单(没测到的 / 已知边界)
- 离线开发:单元+端到端(走 main 真形状,mock 网络)全过,未与真实 Alpaca/Nasdaq/DS 联跑;
  首跑清单即验收
- Alpaca ETF 代理 ≠ 真指数/现货:SPY≠^SPX、VIXY≠VIX、USO≠CL、GLD≠XAU——读数须看 proxy/note
- Alpaca 盘后 quote/trade 可能停更:amc"已出结果"判定=名单本身,**禁加侦测**;无 ah 则写读数缺失
- stooq 已退役:不得再打 stooq URL;缺 Alpaca = 响亮失败,不静默回退
- 节假日未处理(只跳周末):长周末后"昨日AMC"指向假期、当日空榜属预期
- movers/复盘/闸阶段的 skip 晚于 raw 落盘不持久化(仅 stdout);流动性有 verdict 兜底,不加机制
- DS/console/workstation 任一不可达响亮降级不阻塞;合成 GEX 不作数不喂 DS

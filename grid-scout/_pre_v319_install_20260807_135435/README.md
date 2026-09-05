# Scout Agent v3.16(DeepSeek 决策官版)


## 本机部署(demo · 非 ~/grid-scout)

- 目录:`/Users/ciciwang/Projects/demo/grid-scout`(8620 挂 briefs 于此)
- `.env`:`SCOUT_OUT` 指向本目录;`DEEPSEEK_BASE=http://127.0.0.1:11434/v1` + `deepseek-v4-pro:cloud`
- Alpaca:`ALPACA_KEY_ID`/`ALPACA_SECRET_KEY`/`ALPACA_FEED`(兼 `ALPACA_API_KEY`/`ALPACA_DATA_FEED`,可从 `aether_nexus/.env` 读)
- 装包后门禁:`python3 verify_scout_deploy.py`(须全绿才算部署完成)
- `grep -r stooq.com` 验收只计 live `*.py`(排除 `_bak_`/`_pre_`/`WRONG`)
- stock 装包原文备份:`_stock_v316_from_install3_*.py`;本机接线层含 Ollama think=false / emit_aether_scout / wrap800 / amc cap40 / quote_layer

DeepSeek(幻方量化基因)= 交易台参谋:方向/关键行权价/具体策略/放弃条件的**分析作业**,
Lyra 拍板执行。建议 ≠ 自动下单。宇宙三层:SP500&Nasdaq 主池 / 事件驱动个股不限成分
(过流动性闸)/ 海外 ADR 巨头;候选锚定隔夜采集证据,禁凭训练记忆点名。

## 变更记录(真源在此;安装器头注释为副本)
- **v3.16**(2026-08-06):规格七件全落码——①晚班对今日 AMC 一律"已出"叙事,§5/§6
  矛盾消除(run-up 只取 date>今日)②晚班 prompt 补真实 ET 钟点 ③复盘加 watch 段
  (amc 前8+movers 前3 收盘存证,不计命中率——"看见了但没入选"必须留痕)
  ④tape_check 逐腿实测盖章(RSI 铁律从此有供数,违规红标对质)⑤RSI 禁 DS 自估
  ⑥amc_tonight 带收盘读数 ⑦昨日 polymarket 截断 1500→4000。
  **数据层:stooq 全线退役(被墙;被墙源不留兜底——20s 超时×串行=拖班炸弹)→
  Alpaca 主源(现有凭证,ALPACA_KEY_ID/SECRET/FEED 三 env;feed 按账户实况不预设);
  指数/商品走 ETF 代理 SPY/QQQ/VIXY/USO/GLD,读数字段名不变,引擎/prompt/渲染零改动,
  proxy+asof 入溯源链**
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
国债收益率 / FRED(可选 key)/ 指数(ETF 代理 SPY·QQQ·VIXY)/ EDGAR 8-K(交易日锚窗)/
FDA / 商品(代理 USO·GLD)/ Polymarket(事件桶+词界)/ 对冲+迁徙资产(GLD·SLV·OXY·USO·
TLT·UUP+FXI·KWEB·EWZ·EWJ·EEM·BABA)/ Fear&Greed / Nasdaq 财报日历(上一交易日+今起5日;
热日不设 15 cap,源级 cap 800(本机;装包默认240))/ #11 流动性闸(按需)/ #12 板块 SPDR11+SMH。
个股/ETF 全走 Alpaca(dailyBar 盘中即时),带 RSI14 与 tape 读数;引擎出
cross_asset_summary / earnings_movers / amc_tonight(带读数)/ sector_leaders;
数字出引擎,解读归 DS。

## 三步上岗
1. `DEEPSEEK_API_KEY` 填两个 plist(platform.deepseek.com);
   `curl -s https://api.deepseek.com/models -H "Authorization: Bearer $KEY"` 验模型名
2. 首跑:`python3 scout_agent.py --mode morning`(无 raw 时自动全采集)
3. 两个 plist 替换 __SCOUT_DIR__ 与 FILL_ME 后 launchctl load(晚 21:00 / 晨 6:45,机器本地=PST)

## 首跑验证清单(逐条见到才算通;执行归 Cursor,结果原文回守恒,Lyra 只转发)
- [ ] 数据源横幅显示 alpaca(feed=实况档);raw 里 indices 各行含 proxy 与 asof 字段,
      date=今日(旧"stooq 盘中行"承重假设就此实证关闭)
- [ ] `grep -r stooq.com . --include='*.py' | grep -v '_bak_\|_pre_\|WRONG'` 零命中(退役彻底,无残留调用)
- [ ] 晨会三件落盘(md/html/json),html 头部时刻为真实 ET 而非固定 9:45
- [ ] 引擎卡出现"今晚财报(AMC watch)"行;名单前三未被 DS 点名时 rejected/正文有理由
- [ ] 候选卡"流动性实测(引擎)"三态之一(过闸/未过闸/无实测)
- [ ] 晚报雷达点名 movers 异动与 amc_tonight(带收盘读数,非裸代码);对今日 AMC
      零出现"财报前/若超预期"措辞
- [ ] review.json 有 watch 段含当日 amc 名单成员;hit_rate 仍只按 DS 腿计
- [ ] 候选卡出现"RSI/tape 实测(引擎)"行;rsi>70 的 call 腿显式"违规"字样
- [ ] 巨头扎堆日抽查:raw 的 earnings_calendar 热日条数可 >15 且未来日仍在(源级 cap 未吃)
- [ ] 晚班后 review.json 逐腿有 hit;次晨引擎卡"战绩"行有值
- [ ] kill workstation :8620 → 晨会照常出、标注"工作站无可用实弹数据"

## 诚实清单(没测到的 / 已知边界)
- 离线开发:单元+端到端(走 main 真形状,mock 网络)全过,未与真实 stooq/Nasdaq/DS 联跑;
  首跑清单即验收
- VIXY 代理跟短期 VIX 期货,与 VIX 现货不同幅——liquidation_watch 的"VIX≥+8%"阈值
  暂沿用,一周实数据后按 VIXY 口径校准(守恒主动带数据来对,Lyra 不用记)
- feed 口径(iex/sip)按账户实况标注;amc_tonight"已出结果"判定=名单本身,
  **禁加侦测机制**;盘后价暂未接(latestTrade 通道已留,接入是一行开关)
- 节假日未处理(只跳周末):长周末后"昨日AMC"指向假期、当日空榜属预期
- movers/复盘/闸阶段的 skip 晚于 raw 落盘不持久化(仅 stdout);流动性有 verdict 兜底,不加机制
- DS/console/workstation 任一不可达响亮降级不阻塞;合成 GEX 不作数不喂 DS

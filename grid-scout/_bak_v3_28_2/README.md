# Scout Agent v3.28.2(DS 决策官 · 三班制 + BMO 伏击 + 引擎候选池 + 质量地板 + ETF 硬排 + 尾盘形态闸 + 榜硬门 + 自算趋势榜)

## v3.28.2(2026-08-25 夜,守恒自审——不是别人抓的)
两处是我在 v3.28.0/28.1 里说了但没跑过时钟的话:
1. "晚班算、次晨零 GET"是假的。`_last_closed_session` 用"现在几点"判收盘:21:00 PST 晚班的 ET 墙钟是次日 00:xx,
   hour=0 → 判为"收盘前"→ 键写成前一天;晚班算的是昨日榜,次晨 06:45 键不同 → 重算 1200 票,晨报延后 4–5 分钟。
   修:判据改为"ET 时刻是否已过 today 的 16:05",与 trading_date 同一时钟源(`fetchers.now_et`)。
   案 N 用注入时钟验:晚班键=当日,次晨同键,盘前键=前日。
2. 晚班 21:00 时 `_history` 的新鲜判据是"≥上一交易日",缓存有昨日 bar 就不拉——当日终盘根本没进快照,榜是昨日数据。
   修:`history_snapshot(need_date=键日)`,缓存末根 < 键日才重拉一次(1200 GET ≈ 4.3 分钟,只在晚班)。
3. 新增覆盖自证:快照末根 = 键日的占比 <50%(FMP 尚未发布当日 EOD)→ 榜照算、不落盘、skip 有条款,下一班重算;
   否则次晨读到陈榜且永不重算。日志行 "[scout] 趋势榜键 K:快照 n/N 末根=键日(覆盖 x%)"。
- verify 53→54;冒烟案 N(时钟)+ 案 L 补(覆盖不足不落盘)

## v3.28.1(2026-08-25 夜,戌现场抓:v3.28.0 落地后 BMNR 仍不在趋势榜——screener 回 BMNR volume=0,粗筛 price×volume 把它误杀;
## 本地 prices/BMNR.json 算分很强:5 日 +35%、adv20≈$694M)
- `fetch_screener_universe`:volume 为 0/缺 = 字段不可信,放行交 `history_snapshot` 的 adv20 精地板(实测),
  真低量(volume>0 且 price×volume<$50M)仍筛;缓存文件带 `volume0_passed`,日志打 "screener 宇宙 n/raw(volume=0 放行 k 票)"
- 8600 侧 `build_universe_v2.py` 同一处同修(它也用 screener 的 volume 粗筛)
- 安装脚本落地后自归档一份 `scout_agent_install_v3_28_1.sh` 进仓目录(戌:对账少一份落盘)
- verify 52→53;冒烟案 M:screener 行 volume=0/None 放行、真低量与 ETF 仍筛

## v3.28.0(2026-08-25 夜,Lyra:"BMNR 涨了快一周,从来就不在榜上;代码精准避开每一个趋势股")
根因(结构,不是抓取):Scout 的"全市场"只有 FMP 两张榜——涨幅榜按**单日 %** 排,$3 壳票 +80% 占满前 50;
最活跃榜按**股数**排,偏低价票与 ETF。一只每天 +3%、连涨两周 +40%、日成交额 $1B 的 $25 票,涨幅榜进不去,
最活跃榜只有股数够大时偶尔露头。BMNR(公开源:7/31 $17.28 → 8/21 $22.85 → 8/24 $24.36 → 8/25 $24.74,日均 41M 股)
就是这种票——两榜天生看不见它。
- 第七只眼 `trend_board`:**自算**,不靠 FMP 榜——宇宙 = FMP screener 全市场普通股(`fetch_screener_universe`,
  日缓存 state/universe_screener.json;她档位 8-25 实测 200)→ `history_snapshot`(只用历史日线,不打 quote;缓存新鲜零 GET)
  → 硬地板(price/adv20,与池同判)→ 趋势分(整数,trend_why 逐项):近 5 日收涨 ≥4 根 +2(≥3 +1)/ 5 日 +5~40% +2
  ((2,5) +1;>40% +1 标追高)/ 10 日 ≥+10% +1 / RSI 55–80 +1(>85 −1)/ 放量 ≥1.2x +1 / 距 52 周高 ≥−10% +1 /
  末根收高位 +1 / 末根收涨 +1;入榜最低 5 分(`TREND_MIN_SCORE`),cap 20
- 榜按"最近已收盘日"键落 `state/trend_board-<日>.json`:晚班(21:00)算,次晨 06:45 直接读同一份,晨班零 GET;
  首建/晚班约 1200 次历史 GET(付费档 280/分钟 ≈ 4–5 分钟),之后每日增量
- 候选池:趋势榜成员 +3(与最活跃同权);财报 call 腿"在榜"定义扩为 FMP 涨幅榜 ∪ 最活跃收涨 ∪ 自算趋势榜;
  验收脚本同步(趋势榜文件计入"在榜");渲染新行"趋势榜(自算·全市场·5日)"
- `fetchers._derive` 加 `up5`(近 5 根收涨根数)、`chg10_pct`
- verify 51→52;冒烟案 L:BMNR 真实收盘轨迹(不在 FMP 两榜)→ 趋势榜第一 → 候选池前二;
  连涨薄票($3M/日)、单日 +120% 壳票、横盘、连跌 全不进;榜文件当日复用;宇宙抓取失败榜空零崩
- 现场自证点:首晚班 `[scout] 趋势榜 N(宇宙 M)` 一行——M≈1200 级、N≤20;BMNR 是否在榜首几位;
  state/universe_screener.json 的 n/raw_n

## v3.27.2(2026-08-25 夜,Lyra:"你怎么找不到数据,这里一堆工具")——回放改用 8-25 当日真榜
- 守恒经 web 工具读了 8-25 16:30 ET 的真实涨幅榜/最活跃榜(fool.com,Xignite/Polygon 数据;与 FMP 同一市场事实,
  FMP 原榜以现场 raw 为准):涨幅榜前 33 只(截止 +13.9%)无 INTU/HEI/ZM/SMTC;SMTC 全日 7.85M 股,远低于最活跃前 30 的量级
  → **今天四只财报票无一在榜,S2/S4 财报 call 腿按 v3.27.1 规则全部作废,今日正确输出是空槽**,不是"SMTC 第一"
- 冒烟案 K 改为当日真榜回放:INTU 作废(形态错配)、SMTC 作废(不在榜)、ZM 作废(不在榜);
  同一真榜下候选池前四 = BMNR / MRNA / SMCI / PURR(最活跃收涨、过地板、非 ETF),IBIT/SOXL 硬排
- 代码与 v3.27.1 相同;变的是回放数据与 README 的结论

## v3.27.1(2026-08-25 夜,Lyra:"测出来的票不在 FMP top mover 榜,不收")
- 资金确认硬门:财报班 S2/S4 的 call 腿,票必须在**当日 FMP 涨幅榜或最活跃榜(收涨)**上,否则引擎作废
  (条款"不在 FMP 当日榜(涨幅榜/最活跃收涨),财报 call 腿无资金确认";两榜为空时条款加"源失败,不装数")
- 三张财报名单:在榜的票 earn_score +2(earn_why 带 "FMP榜+2"),行带 fmp_board 标记;名单序 = 形态分+榜
- 新 `acceptance_fmp_board.py`:现场验收——读当日 raw(FMP 真实回包)与当班 brief json,逐卡对榜:
  call 实卡不在涨幅榜/最活跃收涨 → FAIL;call 卡引擎实测尾盘弱势收低 → FAIL;候选池前三不在榜 → FAIL。
  `python3 acceptance_fmp_board.py --date YYYY-MM-DD --shift earnings`,退出码非 0 = 不收。
  沙箱只能用回放 raw 跑,真榜对卡的验收在现场跑,这份包在现场验收过之前不算收
- verify 50→51

## v3.27.0(2026-08-25 夜,INTU 案:财报班 S2 RANK 1 = INTU CALL 持过财报,卡上引擎已印 "RSI 62.3 · loc 0.17 · 日 -2.92%",
## 收在全日最低仍出卡,盘后 -7.07%;同名单 SMTC 当日 +5.43% 收高、盘后 +3.27% 没被点)
根因两处:①三张财报名单按**市值**排,"名单前三须点名"把 DS 推向最大市值的 INTU,尾盘形态不在排序里;
②tape_check 只盖章不裁决——引擎量到了弱势收低,卡照发。v3.26 的地板/ETF/池都没碰"方向"这一层。
- `_leg_tier` 加 `earn_score`(尾盘形态分,earn_why 逐项):收高位 loc≥0.7 +2 / loc<0.3 −2;当日 ≥+1% +1 / ≤−1% −2;
  5 日 +2~+15% +1 / <−5% −1;RSI 50–70 +1 / >75 或 <40 −1;放量 ≥1.3x 且收涨 +1;双杀位 −1。
  amc_tonight / bmo_tomorrow / upcoming_earnings 三单改按 earn_score 降序(同分按 20 日成交额),**不再按市值**;渲染行带分
- `apply_quality_floor` 加方向/形态错配作废(所有班、所有非对冲卡):call 点当日 ≤−1% 且 loc<0.5 的票 = 作废
  ("形态错配:call 不做弱势收低票(日 x%, loc y)");put 镜像(≥+1% 且 loc>0.5 作废)。阈值 env TAPE_VETO_CHG=1.0 / TAPE_VETO_LOC=0.5
- prompt:S2/S4 "名单前三(按市值)"改"按 earn_score";S2 财报班段加尾盘形态硬规则(call 只做 earn_score≥0)
- verify 49→50;冒烟加案 K(8-25 实况回放):名单序 SMTC(+5) > ZM > HEI > INTU(−4),INTU call 作废、SMTC 过、put 镜像、morning 班同判
- 8-25 回放(v3.27.0 时按截图读数):INTU 作废;v3.27.2 起改用当日真榜回放,见下

## v3.26.3(2026-08-24 夜,戌审今晚晚报清单:晚报纪律/逗号票/晨会超时/GLM 闸/盘后空——逐条)
1. 晚报同一套纪律:evening 班现在也算 `candidate_pool` + `bmo_tomorrow`/`upcoming_earnings` 并对三名单过地板;
   prompt 加"候选/地板/ETF 纪律(与白班同判)"——弹药/过夜腿只准在池与地板后名单内点名,筛除票只可
   "一笔带过",ETF 禁作候选与"值得盯";盘后必报名单改为地板后 amc ∪ 当日候选腿(预排卡/初筛卡不查)
2. 逗号票("PICS,TUYA,GRRR"):`apply_quality_floor` 非单一代码整卡作废(此前正则不匹配即跳过=绕闸)
3. 池尾弱票(PATH 型一路信号):`POOL_MIN_SCORE` 默认 4(至少两路信号),低分票进筛除行带 score_why;
   计分补"异动榜 +1"、">20% 由 +1 改 +2 标追高"(ASST 型纯异动票此前只有涨幅分)
4. 晨会 DS 超时崩班:`DS_TIMEOUT` 默认 420s(原 `_http` 写死 120s),超时重试一次;仍败由 main 接住——
   json 落 `_parse_failed`+原因、html 必须覆盖(红横幅"本班无有效作业"+正文原因+引擎行照渲染),不再留昨日页
5. EXPANDED-GLM:task 字数 `EXPANDED_TASK_CHARS` 默认 8000(原写死 9000 撞网关闸);网关拒绝时打出
   HTTP 码+正文前 200 字+实际字数——现场自证点:戌贴一次今晚该行,定网关闸真值
6. 盘后 amc_results 空:21:00 PST = 00:00 ET,Nasdaq 盘后 secondaryData 常已收(8-20 压库项)。
   ① 晚班加"盘后读数健康态"行(k/n 出数+缺数原因:no secondaryData/双算冲突/网络/源级失败),0 出数响亮;
   ② 新 `--mode afterhours`:16:45 PST(=19:45 ET,盘后窗内)取地板后 amc ∪ 当日候选腿的盘后读数落
   `state/afterhours-日.json`,不调 DS 不写简报不进账本;21:00 晚班优先消费快照,无快照回落实时取。
   plist 模板 `com.grid.afterhours-snap.plist`(.new 保护同规)随包,**是否 launchctl load 由 Lyra 拍板**——
   不 load 则晚班行为同前,只多一行健康态
7. 宏观事件日历:仍未建(新数据源,先提案)
- verify 46→49;冒烟加:逗号票作废 / 最低分筛除(NVDA·MARA 落筛除行、ASST 5 分在前六)/ afterhours 快照班
  (Nasdaq quote/info 现场形状打桩:HEI secondaryData=null 如实 None、健康态 2/3 带原因)/ 晚班端到端吃池+地板+
  快照、快照缺席健康态 0/n 带原因 / DS 超时 socket.timeout 打桩:重试一次→失败落页(json 标记+html 红横幅)

## v3.26.2(2026-08-24 夜,Lyra"财报再好好测";本周=周三 CPI+NVDA 盘后,财报周逐日冒烟)
- 结构盲区(回闸证明,v3.25.15 实测):`upcoming_earnings` 整日剔除次一交易日——次日 BMO 归 bmo 腿没错,但
  **次日 AMC 票三张单都不在**:周二财报班看不见周三盘后的 NVDA(amc_tonight 否/bmo_tomorrow 否/upcoming 否)。
  现只剔除次日 pre-market;次日 AMC 以 `days_out=1` 入 run-up 单(一个交易日的窗,公布前必须离场);
  每票带 `days_out`,渲染行标 d1/d2…
- run-up 单座位:近窗(days_out≤2)全保留 + 远窗(3-8 日)按市值 6 席——旧版整体按市值 cap 12,远窗巨头把
  明日盘后的中盘挤出(OKTA 型);反向也不许近窗塞满时远窗巨头整段消失(BABA d4 型)。地板随后再筛
- 财报周冒烟(smoke_earnings_week,真器官零网络,日历走真 fetch_earnings_calendar + Nasdaq 现场形状打桩):
  周一 AMC/BMO/run-up(OKTA d1)/昨 AMC movers(WDAY/INTU |chg| 序)· 周二 NVDA d1 入 run-up(旧版三单皆无)·
  周三 AMC 首位 NVDA、BMO 明日 DG/BURL、run-up MRVL/DELL d1 · 周四 NVDA 进昨 AMC movers 榜且不再在伏击单 ·
  周五跨周末空单零崩 · DS 点名闸逐日(周二 S2=NVDA run-up 合法/周三 S2=NVDA AMC 合法/周四 S2=NVDA 已出作废/
  S4 点已出 BMO 作废)· 周四晨会交班块 NVDA/DG 过夜腿带读数、预排卡只进 watch · 日历 fetcher 市值序/
  热日无 cap/未来日 cap15
- 没有的器官(不建,待拍板):宏观事件日历(CPI/PCE/FOMC/Jackson Hole 时点)——现有采集只有收益率/FRED/
  Polymarket,没有"周三 CPI 落地"这种时点条目,DS 只能靠 prompt 里的通用纪律;要加=新数据源,先提案

## v3.26.1(2026-08-24 夜,Lyra:ETF 不可以进池——"IV 200% & IV 你选哪个";BMNR/ASST/CRCL 一直进不了是被 ETF 占位)
- 候选池 ETF 硬排:判据 = FMP profile `isEtf`/`isFund`(同一 profile 端点,`industry_lookup` 终身缓存新增
  `is_etf` 键;ETF 的 industry/sector 常为空,旧版把这种行当失败存 None——现按键在场即有回包);
  ETF → 筛除条款"ETF 不入池";profile 无回包或行里无 isEtf/isFund 键 → "类型未证,不入池"(响亮,不装数)
- DS 在 S1/S3 点名 ETF → 引擎作废(与池同判);对冲腿/S4 引擎位不受此闸(GLD/SPY/FXI 等对冲迁徙工具走 hedge 手册)
- 旧 `.industry_map.json` 缺 `is_etf` 键或值为 None 的票,下一班各重查一次(一次性数十次 profile 调用,付费档无压力)
- verify 44→45;冒烟加两案:①池内 IBIT/BITO/ETHA/TSLL/SOXL 全出、TSLA 缺键按未证出、前四=BMNR/CRCL/HOOD/COIN
  单票;②真 `industry_lookup` 走文档形状 profile 行(ETF 空行业+isEtf=true / 旧缓存缺键重查 / 无键=未证 / 已带键不重查)
- 现场自证点:她档位 profile 行是否带 isEtf 键——若全票"类型未证",池当班全空并响亮,改一处解析即可

## v3.26.0(2026-08-24 财报班垃圾案,Lyra:十块以下无流通率的财报票不许进推荐;榜对了、榜到卡之间断的)
根因三处(读 v3.25.15 代码定位):①财报名单零地板——amc/bmo 只是日历按市值排前 30,行里无价格无成交额,
"price<$5"只是 prompt 文字,liquidity_gate 查不到只盖"无实测"章照样出卡(PICS 案);②六眼(异动/最活跃/
热簇/同频簇/连涨/自选)全是"参考",无确定性候选池,S1 由 DS 自由挑(PATH +1.77% 出卡、BMNR 落榜、晨班 TSLA);
③财报班 12:35 距收盘 15 分钟,S1 按 T+0 出 12:50-13:00 的 0DTE 刮单。
- `fetchers._derive` 实测新增 `price` / `adv20_usd`(前 20 根 close×volume 均值,末根未收不计,样本<5=None
  不装数)/ `mcap_b`(FMP quote marketCap 随行);env `POOL_PRICE_FLOOR`(默认 10.0)、
  `POOL_ADV_FLOOR_USD`(默认 100000000)——调用期读取,改 .env 即生效
- `candidate_pool(cross)`:六眼并集→逐票 quote_layer 实测→硬地板→透明计分→cap 12。计分(整数,score_why 逐项
  落 json):最活跃且收涨 +3(收跌只 +1 标"当日收跌")/ 🔥同频团成员 +2 / 🔥热簇成员 +1 / 当日 +2~20% +2、(0,2%) +1、
  >20% +1 标"追高风险" / 连涨 +1 / 距 52 周高<5% +1 / close_loc≥0.7 +1 / vol_x20≥1.5 +1 / 自选 +1;
  RSI>75 只标"过热"不扣分;同分按 20 日成交额降序。渲染独立行"引擎候选池",筛除逐票带条款
- `floor_earnings_lists(cross)`:amc_tonight / bmo_tomorrow / upcoming_earnings 过地板后 DS 才看见;
  筛除者进 `floor_rejected` 逐票带条款(渲染三行)
- `apply_quality_floor(data, shift, cross)`(代码闸,会改卡):DS 点名逐票实测,地板不过=卡作废改空槽
  (empty_reason 带票+条款,原卡存 `_floor_killed`,汇入 `_floor_kills` 与 no_candidate_reason);
  财报班 S2/S4 名单外点名作废;S1 池外点名盖 `_pool_check`"视野外"章(不作废);
  财报班 S1/S3 强制 note 前缀"明晨预排,不建仓"(复盘进 watch 不计命中,与 AMC 初筛观察同判)
- prompt:S1=引擎候选池(池前三必须逐票评估)/ S2·S4·候选下限的 $5 文字规则改引擎地板 / 财报班定位段
  S1/S3=明晨预排(禁 0DTE、禁今日尾盘入场)
- 抓取:movers 20→50/侧(`_wrap` 该源 cap 120)——FMP 按 % 排,$3 壳票 +80% 常占满前 20,
  $12 的 +15% 真流动票被裁在榜外(ASST 型盲区)
- verify 40→44(候选池+地板闸挂载 / $5 纯 prompt 规则已废+作废留痕 / 财报班预排 / movers cap)
- 冒烟(真管线零网络,8-24 实况回放+处决案):PICS 作废条款 price、BMNR 进池前三、XPON/SDOT/PMI/TJGC 按价格筛、
  SUPX 按成交额筛、无读数票拒、收跌最活跃巨头只 +1、全宇宙不过地板→池空零崩、财报腿名单外点名作废、
  morning 班不加预排前缀、evening 不挂、复盘预排卡不计命中;端到端 main() earnings/morning 两班实跑落盘
- 现场自证点:①她档位 FMP quote 是否回 marketCap(缺则 mcap_b=None,不影响地板);②8-24 raw 里 ASST 在不在
  movers/actives 原始回包(不在=FMP 榜本身没给,与 cap 无关);③首班候选池行的 adv20 实值量级是否与她的
  盘感一致——地板两数由她定
- 待 Lyra 拍板(默认已按上述):①$10 / $100M 两数;②财报班 S1/S3 改明晨预排;③ETF(IBIT/TSLL 类)留不留在池


DeepSeek = 交易台参谋:方向/标的/行权价/策略/放弃条件的**分析作业**,Lyra 拍板执行。
建议 ≠ 自动下单。宇宙三层:SP500&Nasdaq 主池 / 事件驱动个股(过流动性闸)/ 海外 ADR 巨头。

## 数据层(Lyra 拍板 2026-08-17;付费档 2026-08-19)
quote_layer 链:**FMP 主源**(付费档 300 次/分;端点自探定版 .fmp_route,legacy /api/v3 与
stable 族候选逐个试,首个出数按 kind:类 定版落盘;每分钟令牌节流 FMP_RATE_PER_MIN 默认 280;
类级 402/权限失败=本班该类停用一次响亮,不连环重试)
→ **ThetaData 第二源**(本地 Theta Terminal :25510,仅 stock 类;未起=探活失败整链跳过,不阻塞)
→ **Alpaca backup**(票级回退;指数走 ETF 代理并标注,代理序列独立缓存键)→ Yahoo 指数兜底。
缓存带血统:每票缓存记 {src,rows},读路径禁跨序列;backup 血统的新鲜缓存每班先试主源升级。
stooq 已移除,不会回退。事件/日历/盘后/流动性 = Nasdaq/官方零 key 端点(未动)。
换更好的数据 API:只换 fetchers 的 _history/_fmp_quote 内脏,爬虫/引擎/渲染零改动。

## 四班制(v3.25,Lyra 拍板 2026-08-19)
- **morning 6:45am PST**(=9:45 ET 盘初 tape):四槽股票卡(S1 主池/S2 停用留空/S3 事件/
  S4 引擎位)+ 交班义务(昨日过夜腿+watch 盘初读数)+ **不出财报腿** + AETHER emit
- **midday 10:40am PST**(=1:40pm ET 盘中):早班定位复核 + 主池动量 + AMC 初筛(只写
  conclusion 不建新仓)+ AETHER emit
- **earnings 12:35pm PST**(=3:35pm ET 尾盘,报告 12:45 在手):开卷财报班,主攻两伏击位——
  S2=今晚 AMC 伏击(位一),S4=次日 BMO 前置伏击(位二,尾盘买入持过夜,EL 案由来);
  过夜敞口默认单日≤1 条腿(AMC/BMO 并排择一)+ movers 硬闸 + AETHER emit
- **evening 9pm PST**:复盘(watch 段含 amc/movers + bmo_tomorrow,不计命中率)+ 风险雷达
  + 源清单 lint 硬闸 + EXPANDED-GLM review(8501,--review off 可关)+ AETHER emit
- 周末不出班(账本卫生);节假日为声明过的已知边界

## v3.25.2(2026-08-20,Lyra 拍板)
- 爬虫#12 `fetch_market_movers`:FMP gainers/losers 全市场异动榜(非仅财报),端点族
  legacy/stable 自探定版 .fmp_route,price≥3 每侧 cap 20;各班引擎行渲染 + prompt 硬规则
  (|chg|≥10% 必须点名成因,可入 S3)+ 晚班复盘 watch 并入——MRNA/比特币板块型盲区闭合
- 盘后必报:evening 盘后查询名单 = amc_tonight ∪ 当日各班非空候选腿(复盘对象盘后必查)
- 伏击腿 evidence 硬规则(b4795cb 回流):S2/S4 必须引所属板块读数,背离须解释
- expanded review 五层修复回流(b286083):WB(8515)签名转发/task 字段/final 取值/store 同步
- 新 plist 模板密钥行摘除:密钥单一来源 .env(FILL_ME 覆盖 .env 致 401 案根修);
  earnings 班 DS_MAX_TOKENS=16000(双伏击卡输出最大)

## 新引擎器官(v3.25)
- `bmo_tomorrow`:次一交易日 when 含 pre-market 名单(cap 30,附实测读数)→ BMO 伏击名单源
- `upcoming_earnings`:1-8 交易日窗财报名单(市值降序 cap 12,全票附读数,days_out 逐票;v3.26.2 起次日 AMC 亦入)→ run-up 腿引擎供数
- `build_handover`:昨日各班过夜腿 + watch(≤15)批量 snapshot 实测行 → 晨班交班义务
- `persist_skips`:引擎期 skips 回写当日 raw(采集期之后产生的 skip 不再丢失)

## 上岗四步
1. `.env`(与 scout_agent.py 同目录,优先级低于 plist/shell 环境):
   FMP_API_KEY=...            # 主源,必填(付费档)
   DEEPSEEK_API_KEY=...       # 决策官;本机 Ollama 则 DEEPSEEK_BASE=http://127.0.0.1:11434/v1
   DEEPSEEK_MODEL=deepseek-chat    # Ollama 例:deepseek-v4-pro:cloud
   DS_MAX_TOKENS=12000
   # 可选:FMP_RATE_PER_MIN=280 · ALPACA_KEY_ID/ALPACA_SECRET_KEY(backup)· THETA_BASE
   # 可选:SHADOW_MODEL(影子lane,仅晨班)· CONSOLE_KEY · GATEWAY_URL · FRED_API_KEY
   # 可选:RAW_PROMPT_CHARS · LIQ_MCAP_FLOOR_B · POOL_PRICE_FLOOR(默认10)· POOL_ADV_FLOOR_USD(默认1e8)
   # 可选:POOL_MIN_SCORE(默认4)· DS_TIMEOUT(默认420 秒)· EXPANDED_TASK_CHARS(默认8000) · POOL_PRICE_FLOOR(10)· POOL_ADV_FLOOR_USD(1e8)
2. 首跑:`python3 scout_agent.py --mode morning`(midday/earnings/evening 同理;
   --skip-fetch 复用当日 raw)
3. 门禁:`python3 verify_scout_deploy.py`——绿了才算部署完成,禁止口头「已装好」
4. plist 替换 __SCOUT_DIR__ 后 launchctl load(晨 6:45 / 午 10:40 / 财报 12:35 / 晚 21:00;
   可选 盘后快照 16:45 `com.grid.afterhours-snap.plist`,load 与否 Lyra 拍板);既有 plist 安装时一律保留

## 硬纪律(引擎侧有牙)
- T+0 单腿 CALL 默认;PUT 需明确证据;禁多腿;禁编报价;绝对数字必须可溯源到采集读数
- RSI 禁自估:引擎给 rsi14_tape + 每腿 tape_check 实测章,与 DS 叙述并排对质
- 晚报源清单 lint:ok=true 的源被说成失败/SSL → 确定性重写并记账(事实行最高权威)
- amc_tonight=已出结果名单(cap 30),晚报一律已出叙事;run-up 仅限未来交易日,
  且今日已出结果者不属 run-up;run-up 候选以 upcoming_earnings 引擎名单为准
- 财报腿只在 earnings 班出;morning/midday 班 S2 停用留空,财报手册整节不注入
- 过夜腿默认单日≤1 条;BMO 伏击必须点名次日盘前票并给尾盘买入价带与放弃条件
- land 脚本吃卡前须验:日期=今日 且 无 _parse_failed 标记(失败时 json 落此标记)

## 落档
briefs/日期-{morning,midday,earnings,evening}.{md,html,json} + 日期-review.json
(review 三班合并去重,影子 lane 分账 -glm,仅晨班)

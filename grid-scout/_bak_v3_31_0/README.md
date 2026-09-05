# Scout Agent v3.31.0(DS 决策官 · 三班制 + 六因子核 + 反馈回路 + 准入闸 + 自算趋势榜 + 事件层 + 仓位档/Kelly)

## v3.31.0(2026-08-26 午,Lyra:"总结报告有个屁用?行动呢?主动改进呢?")——不等拍板,直接做了五件
1. **归因账本** `attribution.py` + `state/attrib.jsonl`:每班落 池前 12 + 发出的实卡 的六因子子分/总分/视角/当时价;
   晚班结算:当日 t0 行用收盘,前一日 swing 行用今收。
2. **因子表现表**:近 20 日每个因子子分与结果的 Spearman IC、总分分桶命中率/均值、卡命中率;晚报新行
   "因子表现(IC=子分与结果秩相关;权重改动看这行拍)"。权重从此有数可看,不再拍脑袋;改权重仍由 Lyra 拍。
3. **期权结算**:0DTE 卡按入场窗起点/出场窗终点取 ATM call 中价(Theta `/v3/option/history/greeks/all`,带 bid/ask;
   时间戳字段按回包自证,形状异常写 skip),真实卡盈亏进账本;不可用 → None 带原因,不装数。
4. **数据自检**:晚班对池前 20 的 FMP 日线用 Alpaca 第二源复核收盘,偏差 >0.5%(SELFCHECK_TOL_PCT)响亮报 + 晚报行——
   INTU 8-25 部分 bar(366.30 vs 357.46,2.4%)会被它抓到。
5. **同团封顶**:同一🔥同频团最多 COMOVE_CAP(默认 2)张实卡,超出按 rank 作废("一注不拆成多注");
   **事件时刻窗**:入场窗与今日高影响发布/讲话时刻 ±15 分钟重叠 → 作废(周五 JH 10:00 ET = 07:00 PST)。
- 冒烟案 T:11 行合成结算 IC 为正、分桶/期权 +38% 进表;自检抓 INTU 部分 bar;同团第三张作废;JH 撞窗作废/不撞过;Theta 中价打桩 1.00→1.40
- 未做(需 Lyra 拍):决策官 DS→GLM(她的三脑评估:DS 全面伪造,GLM 唯一不编)——涉 8501 lane 的 store 注入,先问再动
- verify 59→60

## v3.30.0(2026-08-26 午,Lyra:"我说过今天 NVDA 财报、几个美国关键数据、美债油价一个没考虑,你完全没有自己的思考")
她 8-24 就说了本周:周三 CPI/PCE + NVDA 盘后 + 美债 + 周五 Jackson Hole。raw 里每天都抓着 treasury_yields / commodities(WTI)/
earnings_calendar,我从没把它们接进任何判断;宏观日历我写成"待拍板"就放着。中午班在 PCE 偏热(3.7%)、10Y 4.67% 回升、
NVDA 盘后的日子发了两张 0DTE 单腿 call,事件层等于零。
- 新源 `fetch_economic_calendar`:FMP stable `/economic-calendar?from&to`(官方文档实读),US 高/中影响与 CPI/PCE/GDP/FOMC/Payroll 关键词
- `event_layer(payload, today)`:今日数据发布 / 巨头财报(原始日历市值 ≥ `EVENT_MEGACAP_B`=500B:今日 AMC、明日 BMO)/ 10Y 水平 / WTI 当日
  → `event_day`;简报新行"事件层(数据日/巨头财报/美债/油)"带后续 4 条
- 事件日效果(代码,不是提示):仓位档降一档(VIX 15.45 本"满" → "半");T+0 参与度节奏线 0.8 → 1.0(`T0_PACE_MIN_EVENT`),
  没有明确放量的 0DTE 一律只观察;过闸的卡 note 前缀"事件日(…)";财报班 S2/S4 持过财报的 call 在巨头盘后夜标 `_event_check`(gap 风险,Lyra 拍)
- 油当日 ≥ +3% 且档位"满" → 降一档
- DS prompt 加事件层硬规则一段
- 冒烟案 S(8-26 实况:PCE 3.7 / NVDA $4.3T AMC / 10Y 4.67 / WTI +0.4):事件日成立,仓位档 满→半,FUTU 节奏 0.9<1.0 只观察,非事件日同卡过
- 现场自证点:economic_calendar 首行键名(skip 行若报"字段形状异常"贴回);今日 raw 里 treasury_yields 的 "10 Yr" 字段是否在
- verify 58→59

## v3.29.3(2026-08-26 中午班实况,Lyra:"12:50 & 13:45 PST 入场??"/"又精准找出亏钱股")
两处都是我的:
1. **时间窗**:卡写"入场窗(PST) 13:45–14:30 / 出场 15:30、15:50"——美股 13:00 PST 收盘,这些是 ET 数字贴了 PST 标签。
   prompt 写了 PST,DS 照写 ET,此前没有一行代码校验。修:`normalize_pst_window` 解析卡上 HH:MM,任一时刻 >13:00 → 判为 ET,
   整段 −3h 并标"(引擎:DS 写成 ET,已改 PST)";改后仍落在 06:30–13:00 之外 → 作废"时间窗不在交易时段"。
2. **T+0 参与度**:TEM 卡自己写"当前 vol_x20 0.44 无放量,需等待信号",却仍是带入场窗的实卡——又是"盖章不裁决"。
   修:晨/午班 S1/S3 的 call 卡,vol_x20 按班次名义时刻折算成节奏(晨班 09:45 ET 只走了 15 分钟,午班 13:40 走了 64%,
   前 15 分钟占 15% 的 U 形近似),节奏 < `T0_PACE_MIN`(默认 0.8)→ 作废"无放量,T+0 0DTE 不建仓,只观察";
   `_pace_check` 落卡。8-26 实况:TEM 0.44 → 节奏 0.64 作废;FUTU 0.62 → 0.9 过(DS 自己写了轻仓)。
3. **t0 视角权重**:晨/午班候选池用 `WEIGHTS_T0`(F3 形态 30 / F5 期权 25 / F1 20 / F2 15 / F4 10)——0DTE 卡看当日,
   多日趋势降权;趋势榜/财报名单/预排仍用 swing。同六因子,只换权重。TEM swing 81 → t0 73。
- 未变的事实:没有任何评分能保证单张卡不亏;这三处修的是"不该发的卡发了"。TEM 卡发出后从 69.54 走到 68.20(−1.9%)。
- verify 57→58;冒烟案 R(8-26 实况数字)

## v3.29.2(2026-08-26 晨,戌对账抓获:现场 prices/INTU.json 的 8-25 行 O 364.35 对齐、H 366.58/L 361.93/C 366.30 全不对、量像未走完)
根因:FMP EOD **盘中会回当日部分行**;Scout `_history` 的新鲜判据只看"末根日期 ≥ 上一交易日",12:35 财报班(15:35 ET)拉到的
部分 bar 被当成 8-25 终盘存进缓存,盘后快照班、晚班趋势榜、次晨因子分全用它算——INTU 那根 loc 0.94/−0.98% 就是这么来的
(真终盘 loc 0.12/−3.37%)。这与 8600 factor_truth v2 修的是同一类洞,Scout 侧此前没修。
- 缓存写入带 `fetched_ts`;末根日期 = 写入当日 且 写入时刻 < 16:05 ET → 判为部分 bar:收盘后(≥16:05 ET)必重拉一次得终盘;
  盘中每 `PARTIAL_REFRESH_S`(默认 1800s)重拉一次(盘中读数不陈旧);次日不再重拉
- 冒烟案 Q:15:35 写入部分 bar → 15:50 不重拉 → 16:35 重拉得 357.46 → 次日 03:00 不重拉;10:00 写入 → 10:31 重拉
- 影响面:今晚 21:00 晚班起趋势榜/次晨因子分用的是真终盘;今天白天三班的盘中读数不受影响(本来就要盘中读数)
- verify 56→57

## v3.29.1(2026-08-26 晨,Lyra 问"缺一个因子(权重第五)是 ok 的?";戌真数据对账:BMNR 8-19 v29=75 vs 包 84——现场无市值退成交额档、F4/F5 缺)
- **F5 不能长期缺**:它是六因子里唯一量"你买的那张期权"的因子,缺了排的是股票不是期权交易。盘前快照为空是数据事实,
  所以补一条回退:16:45 盘后快照班(19:45 ET,当日快照仍在,文档:午夜 ET 才重置)对 候选并集(盘后名单 ∪ 当日趋势榜 ∪ 三班候选池,≤80 票)
  取 ATM call γ/|θ| 落 `state/f5-<日>.json`;次晨盘前池与晚班趋势榜读它(池行标 **F5昨收**);盘中班仍用实时快照;两者都无才是"缺F5"
- **F1 市值兜底**:趋势榜走历史快照没有 quote 市值 → 此前退成交额档(偏大盘);现用 profile 的 marketCap(industry_lookup 缓存加 `mktcap_b`)算换手率
- 趋势榜终判 ETF/类型未证(screener 粗筛之外再按 profile isEtf 判一次)
- 对账口径:我在包里写的 BMNR 84 / INTU 22 用的是 S&P Global 的 8-25 日线 + 已知市值;现场 v29 分数低是因为缺市值(本版补)与缺 F4/F5;
  戌算的 INTU 8-25 日线 loc 0.94 / −0.98% 与 S&P Global 的 8-25 日线(O 364.35 H 367.85 L 356.02 C 357.46,−3.37%,loc 0.12)不符——
  现场 prices/INTU.json 末行要对一下(可能是盘后/次日行混进来了)
- verify 55→56;冒烟案 P

## v3.29.0(2026-08-26 凌晨,Lyra 令"当然继续":把 Fable 8 月 A/C 组讨论落成代码,替代 v3.26–v3.28 的近 30 条手写加分规则)
**为什么重做**:候选池 12 条、趋势榜 8 条、财报名单 7 条加分规则,每条对应某一天的事故,是对最近三张截图的过拟合;
"来自哪张榜"被当成信号,"钱的密度""不对称性""事件窗"这些真正的经济因子却不在里面。
**因子核 `factors.py`(6 因子,预算上限 12,verify 静态闸)**:
- F1 资金密度 权 20:换手率 = 20 日成交额 / 市值(缺市值退成交额档);0.1% → 0,1% → 60,3% → 100
- F2 趋势 权 25:5 日涨幅 / 10 日涨幅 / 近 5 根收涨根数 / 距 20 日高
- F3 尾盘形态 权 15:收盘在日内区间位置 / 当日涨跌 / 放量倍数
- F4 事件 权 15:距财报天数(3–7 天 = IV 抬升窗 100;1–2 天 70;8–14 天 40;当日 AMC = 0 只准预排);财报后 1–3 天 gap≥5% = 60(漂移)
- F5 期权不对称性 权 20:ATM 最近到期(7–30 DTE)call 的 γ/|θ|,批内百分位;Theta `/v3/option/snapshot/greeks/all`(官方文档实读,
  Pro 档;盘外快照为空)——缺 = 因子缺,权重归一化到可得因子,卡上标"缺F5",不装数
- F6 风险扣分:RSI>85 −15 / 5 日 >40% −15 / 单日 >20% −10 / 双杀位 −10 / 弱势收低(≤−1% 且 loc<0.5)−20
- 总分 0–100 整数,`score_why` 逐因子;地板(price/adv20/ETF)与方向闸是**准入**,不是因子,原样保留
**接线**:候选池(七眼只决定谁进宇宙,排序 = 因子分;POOL_MIN_SCORE 默认 45)、趋势榜(因子核趋势视角:F2≥60 且总分≥55)、
财报三名单(同一因子核,F4 = days_out;earn_score<40 禁 call)——三个视角一个核。
**宏观(C#4)只进仓位档**:VIX <18 满 / 18–25 半 / >25 停,单日 +15% 降一档;只显示,不进选股。
**Kelly(C#8)**:复盘账本最近 20 份的命中率 → f* = p − q/b;样本 <20 quarter,≥20 half;只显示。
**真数据验证(案 O,S&P Global 8-25 读的真实 K 线,锁进冒烟)**:BMNR 8-19 收盘 84 分(次日 +6.6%)、8-25 89 分;
INTU 8-25 22 分(F3 30、F4 预排 0、F6 弱势收低 −20)——今天发出去那张 INTU call,按因子核在入池线以下。
- 现场自证点:盘中班 F5 是否出数(Theta Pro 档 + Terminal 起);skip 行 theta_greeks 的原因;首班池行的 F1 换手率量级对不对盘感
- verify 54→55

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

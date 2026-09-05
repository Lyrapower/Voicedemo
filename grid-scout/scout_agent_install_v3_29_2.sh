#!/usr/bin/env bash
# ============================================================================
# Scout Agent · v3.29.2 · 总包(完整替代;plist/verify 保护;自检自跑;落地后自归档一份进仓)
#   ★ v3.29.2(2026-08-26 晨,戌抓 INTU 8-25 行是 15:35 部分 bar):缓存带 fetched_ts,盘中拉到的当日 bar 收盘后必重拉、
#     盘中 30 分钟一刷;verify 57;冒烟案 Q
#   ★ v3.29.1(2026-08-26 晨):F5 盘后缓存(16:45 班落 state/f5-<日>.json,盘前/晚班回退标 F5昨收)+ profile 市值兜底 F1
#     + 趋势榜终判 ETF;verify 56;冒烟案 P
#   ★ v3.29.0(2026-08-26 凌晨,Lyra 令"当然继续"):六因子核 factors.py(F1 换手率/F2 趋势/F3 尾盘形态/F4 距财报/F5 期权 γ/|θ|/F6 风险)
#     替代 v3.26–28 近 30 条手写加分规则;候选池/趋势榜/财报名单三视角一核;Theta greeks 端点按官方文档;
#     仓位档(VIX)与 Kelly(复盘命中率)只显示;真实 K 线验证锁进冒烟(BMNR 8-19 84 分→次日+6.6%,INTU 8-25 22 分);verify 55
#   ★ v3.28.2(2026-08-25 夜,守恒自审):趋势榜时钟——晚班(次日 00:xx ET)键错标前一日、当日终盘没进快照,
#     "晚班算晨班零 GET"落空;修=键判据改"是否过 today 16:05 ET"、history_snapshot(need_date=键日)、
#     当日 EOD 覆盖<50% 不落盘;verify 53→54;冒烟案 N(注入时钟)
#   ★ v3.28.1(2026-08-25 夜,戌现场抓:v3.28.0 落地 BMNR 仍不在趋势榜——screener 回 BMNR volume=0,粗筛 price×volume 误杀):
#     · fetch_screener_universe:volume 0/缺 = 字段不可信 → 放行交 adv20 精地板;真低量/ETF 仍筛;缓存带 volume0_passed
#     · 安装脚本落地后 cp 自身进仓目录(戌:对账少一份落盘);verify 52→53;冒烟案 M
#   ★ v3.28.0(2026-08-25 夜,Lyra:"BMNR 涨了快一周从来不在榜上,代码精准避开每一个趋势股"):
#     根因=Scout 的全市场只有 FMP 两榜——涨幅榜按单日 % 排(壳票占满),最活跃按股数排(偏低价票/ETF),
#     连涨一周 +40%、$1B/日的 $25 票两榜都看不见。
#     · 第七只眼 trend_board 自算:FMP screener 全市场宇宙(日缓存)→ 历史日线快照(不打 quote)→ 地板 → 趋势分
#       (5 日收涨根数/5 日涨幅/10 日涨幅/RSI/放量/近 52 周高/收高位/末根收涨,逐项落 json)→ cap 20;
#       按最近已收盘日落 state/trend_board-<日>.json,晚班算、次晨零 GET 共用
#     · 候选池趋势榜 +3;财报 call 腿"在榜"= FMP 两榜 ∪ 趋势榜;验收脚本同步;渲染新行
#     · 冒烟案 L:BMNR 真实收盘轨迹(不在 FMP 两榜)→ 趋势榜第一 → 池前二;薄票/壳票/横盘/连跌不进
#     · verify 51→52
#   ★ v3.27.2(2026-08-25 夜):回放改用 8-25 当日真榜(web 实读 16:30 ET 涨幅榜/最活跃榜)——INTU/HEI/ZM/SMTC 无一在榜,
#     今日 S2/S4 财报 call 腿按 v3.27.1 规则全部作废,正确输出是空槽;池前四 BMNR/MRNA/SMCI/PURR。代码同 v3.27.1,只改回放与 README
#   ★ v3.27.1(2026-08-25 夜,Lyra:"测出来的票不在 FMP top mover 榜,不收"):
#     · 财报班 S2/S4 call 腿必须在当日 FMP 涨幅榜或最活跃榜(收涨),否则引擎作废;名单在榜 +2
#     · 新 acceptance_fmp_board.py:现场读当日 raw(FMP 真榜)逐卡对榜,非 0 退出 = 不收;沙箱回放不算验收
#     · verify 50→51
#   ★ v3.27.0(2026-08-25 夜,INTU 案:财报班 S2 RANK 1 点了当日 -2.92%、loc 0.17 收在最低的 INTU 做 call 持过财报,
#     卡上引擎已印出这三个读数仍照发,盘后 -7%;同名单 SMTC +5.4% 收高没被点):
#     ① 三张财报名单改按尾盘形态分 earn_score 排(收高位/当日/5日/RSI/放量/双杀位,earn_why 逐项),不再按市值
#     ② DS 点名闸加方向/形态错配作废:call 点当日≤-1% 且 loc<0.5 的票=作废,put 镜像;所有班、所有非对冲卡
#     ③ prompt "名单前三(按市值)"改按分;S2 财报班段加尾盘形态硬规则;verify 49→50;冒烟案 K=8-25 回放
#     8-25 回放:INTU 作废,名单第一 SMTC
#   ★ v3.26.3(2026-08-24 夜,戌审今晚晚报七条,逐条):
#     ① 晚报同一套纪律:evening 班算候选池+bmo/run-up 名单并三单过地板,prompt 加纪律段,
#        盘后必报名单=地板后 amc ∪ 当日候选腿(预排/初筛卡不查)
#     ② 逗号票("PICS,TUYA,GRRR")非单一代码整卡作废(原正则不匹配即跳过=绕闸)
#     ③ 池尾一路信号票(PATH 型):POOL_MIN_SCORE 默认 4;计分补异动榜 +1、>20% 改 +2 标追高
#     ④ 晨会 DS 超时崩班:DS_TIMEOUT 默认 420s+超时重试一次;失败由 main 接住——json 失败标记+
#        html 必覆盖(红横幅+原因+引擎行照渲染),不留昨日页
#     ⑤ EXPANDED-GLM:task 字数 EXPANDED_TASK_CHARS 默认 8000(原写死 9000 撞网关闸),拒绝时打 HTTP 码+正文
#     ⑥ 盘后 amc_results 空(00:00 ET 已过 Nasdaq 盘后窗):晚班加"盘后读数健康态"行(k/n+缺数原因);
#        新 --mode afterhours 16:45 PST 快照落 state/,晚班优先消费;plist 模板随包,load 与否 Lyra 拍板
#     ⑦ 宏观事件日历仍未建(新数据源先提案)
#     verify 46→49;冒烟加逗号票/最低分/afterhours 快照班/晚班端到端/DS 超时落页五案
#   ★ v3.26.2(2026-08-24 夜,Lyra"财报再好好测",本周=周三 CPI+NVDA 盘后):
#     · 结构盲区(v3.25.15 回闸实测):upcoming_earnings 整日剔除次一交易日→次日 AMC 票三张单都不在,
#       周二财报班看不见周三盘后的 NVDA。现只剔除次日 pre-market,次日 AMC 以 days_out=1 入 run-up 单
#     · run-up 座位:近窗(≤2 日)全保留+远窗(3-8 日)按市值 6 席(远窗巨头挤走明日中盘/近窗塞满远窗消失 两案)
#     · 财报周冒烟 smoke_earnings_week:五个交易日逐日跑真财报器官+DS 点名闸+周四交班块,
#       日历走真 fetch_earnings_calendar(Nasdaq 现场形状打桩);verify 45→46
#     · 未建(待拍板):宏观事件日历(CPI/PCE/FOMC/JH 时点)——新数据源,先提案
#   ★ v3.26.1(2026-08-24 夜,Lyra:ETF 不可以进池——"IV 200% & IV 你选哪个",BMNR/ASST/CRCL 一直
#     进不了是被最活跃榜里的 IBIT/BITO/TSLL/SOXL 占位;v3.26.0"留给 DS 拒"被她定性为懒惰):
#     · 候选池 ETF 硬排:判据 FMP profile isEtf/isFund(同一 profile 端点,industry_lookup 缓存
#       新增 is_etf 键;ETF 行业为空的行不再当失败存 None);类型未证同样不入池,响亮
#     · DS S1/S3 点名 ETF = 引擎作废;对冲腿/S4 引擎位不受此闸
#     · 旧缓存缺 is_etf 的票下一班各重查一次;verify 44→45;冒烟加 ETF 硬排案+profile 解析案
#     · 现场自证点:她档位 profile 行是否带 isEtf 键(全票"类型未证"=池空响亮,改一处解析)
#   ★ v3.26.0(2026-08-24 夜,财报班垃圾案——Lyra:十块以下无流通率的财报票不许进推荐;
#     "冒烟结果没到 Top Mover 榜"=榜对了、榜到卡之间断的;当日 ASST/BMNR 没抓到、晨班推 TSLA):
#     根因三处(读 v3.25.15 代码定位,非推断):
#     ① 财报名单零地板:amc/bmo 只是日历按市值排前 30,行里无价格无成交额;"price<$5"只是 prompt
#        文字;liquidity_gate 查不到盖"无实测"章照样出卡 → PICS $5.2 出 S2 RANK 2;
#     ② 六眼全是"参考":异动/最活跃/热簇/同频簇/连涨/自选全渲染全喂 DS,但无确定性候选池,
#        S1 由 DS 自由挑 → 挑热簇里 +1.77% 的 PATH,最活跃+🔥团的 BMNR 没进卡;
#     ③ 财报班 12:35 距收盘 15 分钟,S1 按 T+0 出 12:50-13:00 的 0DTE 刮单,"≥3 非空卡"逼硬填。
#     修(四器官,均代码级,冒烟真管线零网络+端到端 main() 实跑):
#     · fetchers._derive 实测 price / adv20_usd(前 20 根 close×volume,末根不计,样本<5=None)/ mcap_b;
#       env POOL_PRICE_FLOOR(默认 10)· POOL_ADV_FLOOR_USD(默认 1e8),调用期读取
#     · candidate_pool:六眼并集→逐票实测→硬地板→透明计分(score_why 逐项)→cap 12,渲染独立行,
#       筛除逐票带条款;S1 只能池内取,池前三必须逐票评估(入卡或 rejected 理由)
#     · floor_earnings_lists:amc/bmo/run-up 三名单过地板后 DS 才看见,筛除进 floor_rejected
#     · apply_quality_floor(会改卡):DS 点名地板不过=作废改空槽(票+条款可审,原卡存 _floor_killed);
#       财报腿名单外点名作废;S1 池外盖"视野外"章;财报班 S1/S3 强制"明晨预排,不建仓"
#       (全日 K 线定型是次晨最好的预排;复盘进 watch 不计命中)
#     · prompt 五处同步($5 文字规则废);movers 抓取 20→50/侧(ASST 型 +15% 真流动票被壳票挤出前 20)
#     · verify 40→44;README 附现场自证点与待拍板($10/$100M 两数、财报班预排)
#   ★ 基线 = v3.25.15 全量(下列沿革一字未动)。落包前仍做:diff 现场 scout_agent.py,现场有本包
#     未含改动即回报,禁直接覆盖。
#   ---- 以下为 v3.25.15 及以前沿革 ----
#   ★★ 基线声明:本包基线 = 守恒 v3.25.6 + v3.25.7 四修守恒重建版(见下)。
#      戌落包前必做:diff 本包 scout_agent.py 与现场(含你就地修的三处),
#      若现场有本包未含的改动,回报守恒,禁直接覆盖——防回滚铁案。
#   ★ v3.25.8(2026-08-21,crypto 板块三日连涨零覆盖案,Lyra:系统必须自己长眼睛):
#     ① 爬虫#13 fetch_most_active 最活跃榜=热资金直测(COIN/HOOD 型 +3~8% 稳步流
#        进不了暴动榜但必进活跃榜);端点候选按 FMP 官方文档实证(守恒 8-21 查证):
#        legacy /api/v3/actives + stable /most-actives,自探首个出数定版 movers:actives
#     ② 热簇·数据自聚 theme_heat(二版当日重做,Lyra:禁写死范围,"万一下周热点
#        不在这里了呢"——一版手写五主题表已拆除):当日 movers 涨侧∪最活跃榜标的
#        按 FMP profile 行业标签自动聚簇(industry_lookup 端点族自探+每票终身缓存),
#        同业 ≥2 票且avg≥2% 或 ≥3 票且avg≥1.2% = hot 簇;下周热点换到任何行业,
#        簇自己浮出来,零人工维护、零预设名单
#     ③ 连涨账本 update_streaks:每日榜单落盘,近 3 日 ≥2 现=streak 榜(movers 尖峰盲区)
#     ④ S1 全视野重写:候选视野=板块ETF(降为背景)+movers+最活跃+热簇成员+
#        streak+watchlist 并集;硬规则=热主题成员/streak/watchlist 趋势对齐必须逐票
#        评估,不入卡 rejected 逐票理由,禁止只在板块 ETF 内选
#     ⑤ watchlist.txt 可选附加层(ROOT 下一行一票,有就读,没有不影响)
#     ⑥ 渲染四行(主题热力🔥/最活跃/连涨榜/自选)+复盘 watch 全器官汇入
#     ⑦ 候选下限范围定版:morning/midday/earnings 三班(prompt+代码闸),
#        evening 复盘班不挂(误报审定);_scout_bark 回流(戌 L1524,certifi 替 unverified)
#   ★ v3.25.15(2026-08-24,三路云审刀·GLM 主刀+DS 语义+Kimi 堵连坐,戌汇审):
#     四版同频簇缺陷=连通分量是传递闭包,"两两都在动"被偷换成"同一个朋友圈"
#     (DS 语)——现场簇2 FSTB+2021% 靠中间人挂上 NVDA/TQQQ 还点🔥。五版定稿:
#     ① 簇=极大团(Bron–Kerbosch,任意两成员 ρ≥0.7,贪心取不相交团,链式处决);
#     ② cohesion=团内全对全 ρ 均值(团下无隐藏对,不再虚报);
#     ③ hot=中位数 chg≥1.5% 且 ≥60% 成员达标(均值废,FSTB 拉爆案)
#        且 ≥2 名成员在最活跃榜(单只常驻巨头连坐案,Kimi 抓);
#     ④ members 全量入 json,渲染截断响亮标 示k/n(展示层禁撒谎);
#     ρ=0.7/10 日窗保留(改团后阈值余量足,GLM 判);第二刀(窗口/FDR/cap 策略)
#     入库存待拍;冒烟含链自证处决案(AB/BC 有边 AC 无边→不成簇)。verify 40。
#   ★ v3.25.14(2026-08-24,COIN 散标签案三版定稿):一版手写主题表(写死范围)、
#     二版 sector 汇流(桶大到永真,"怎么测都是对的")均被 Lyra 否决拆除。三版=
#     同频簇 comove_clusters:同一股钱的实测定义是"这些票在一起动"——宇宙内
#     近 10 日日收益两两 Pearson,ρ≥0.7 建边,连通分量 ≥3 票成簇;可证伪:
#     不相关聚不进(SOFI 与矿机同 sector 被拒,冒烟断言),无共振日输出空,
#     反向不建边;hot=资金确认+当日 avg≥1.5%;跨行业标签自然合流(矿机/交易所/
#     ETF 同吃 BTC 流自聚一簇,行业标签集合随行标出);零词表零票单零板块桶,
#     序列取 quote_layer(缓存);industry 热簇不动;verify 38→40(含永真桶拆净检查)。
#   ★ v3.25.13(2026-08-24,戌落包回执清单外项,落前修入):profile 二跑命中序——
#     旧 ordered 前缀裁剪裁到 …/stable 两候选都匹配,定版后仍先打路径形 404;
#     改按定版整串前缀精确分排,二跑新面孔 1 次直命中(冒烟断言)。actives 悬案
#     以戌实弹销案:legacy 族 403(2025-08-31 后新订户停用,非 402 档位),
#     stable /most-actives 200 已定版跨班续用——自探不钉死判词被现场证实。
#   ★ v3.25.12(2026-08-24,戌四处现场施工回流进基线,自此落包无需重贴):
#     ① load_fault_lines_snapshot:S1 缝 scout 侧读取器(inbox/factor_snapshot.json 的
#        fault_lines 块→事实行,标"结构参考,非信号";缺/停/坏三态安静);
#     ② build_trading_prompt 增 fault_lines 参数+{_fl} 注入(昨日战绩行后);
#     ③ ds_call 韧性:5xx 退避重试 ×3 + 空内容去 think 重试(8-20 晚报 500 根因);
#     ④ 晨会接线:仅 morning 班读 snapshot,其余班空串。
#     四处均按戌 diff 原文回流,冒烟逐处真跑(全分量渲染/三态/503 退避/去 think);
#     verify 37→38 加回流在位检查,防下包踩掉。
#   ★ v3.25.11(2026-08-24,戌抓包审:_fmp_route_save 签名案):fetch_most_active 与
#     industry_lookup 两处按想象 API 调 _fmp_route_save(route),在册签名无参(存模块级
#     _FMP_ROUTE,movers 范本形制)——TypeError 被内层 try 静默吃掉,症状=功能侥幸活、
#     路由定版永不落盘(每班重探)+异常暗堆。修=两处改无参调用;冒烟真测 save 路径
#     (首探定版落盘 .fmp_route/二跑单调命中/profile 定版)。候选 URL 不钉死:签名修好后
#     自探首个出数即定版跨班续用(V6 判例机制),硬编码=写死范围同族,Lyra 可否决。
#   ★ v3.25.10(2026-08-24,现场首晚热簇失真案:最活跃榜静默失败→簇宇宙只剩
#     movers 微盘尖峰,壳公司 RFAI+355% 挂🔥冒充"钱在流入";真热钱 HOOD/量子全缺):
#     ① 🔥资格加资金确认硬门:簇内至少一名成员在最活跃榜(成交额=钱的直接测量),
#        最活跃榜失败/空=当班零🔥;② most_active 健康态入渲染,失败响亮报原因
#        禁静默;③ 簇宇宙 movers 侧 price≥5(壳票出局;movers 渲染行本身不受影响);
#     ④ 晚报日历纪律:下一交易日实值注入(周五→周一自动换算),禁裸用"明日/明晨";
#     ⑤ 晚报立法边界:调优段禁立机械阈值新规,白班 prompt 明示晚报调优仅供参考、
#        立法权在 Lyra;verify 35→37。冒烟含现场首晚实况回放(壳票榜+402)。
#   ★ v3.25.9(2026-08-23,现场晚报 NameError 热修):_NOISE_RX 定义补回(v3.25.0 原文
#     一字未动)——该定义在守恒 v3.25.2 出包时丢失、带病五版,现场一直没炸只因跑的是
#     旧文件,v3.25.8 总包落地后 evening 首走 denoise 即崩(Cursor 报案)。同类洞一次
#     杀全类:verify 新增第 35 项"全局名可解析"(两模块全函数字节码 LOAD_GLOBAL 逐名
#     断言,回闸证明:挖掉定义即红);冒烟补 evening denoise 真调用(废话删净/数字保留)。
#   ★ 端到端验证账(2026-08-21,今日真实收盘榜实测):管线前四 SLS/IQMX/HOOD/USAR
#     == 当日真实 top movers 前四;热簇零预设聚出量子(4票)/资本市场(4)/炼油(3)/
#     稀土铀(3)/铜金属(3);连涨榜 HOOD/BTDR。端到端首跑抓获并修复两处形状错:
#     theme_heat/most_active 引擎读法按想象形状读 data.gainers(真实落盘=顶层
#     items 带 side)、fetch_most_active 返回 dict 违反 _wrap 扁平列表契约——
#     打桩单测全绿真管线全空的现行案,读法已全部对齐真实落盘形状重验。
#     仍属 key 级现场项:她档位 402 与否、FMP profile 给同类股的 industry 实值。
#   ★ v3.25.7 四修(守恒按记录重建,戌 diff 现场核对):apply_candidate_floor 代码闸
#     (三违例盖章:非空卡<3 且 no_candidate_reason<3票/空槽>1/空槽理由禁词)+
#     midday"默认收敛/默认不建新仓"矛盾清除 + verify 27→33 + schema 口径
#   ★ v3.25.6(2026-08-20,冻结流程第一包:沙箱构建→戌真数据全班预演→收盘后落):
#     ① 规则A(Lyra 拍板):白班 S2 占位空槽废止——amc_tonight 非空即出 AMC 初筛卡
#        (前三点名+dk_risk/tier 双杀预检+初筛意见,note 以"AMC 初筛观察,不建仓"开头,
#        复盘按标记进 watch 不计命中);morning 班引擎恢复算 amc_tonight 供名单
#     ② 规则B(Lyra 拍板"每轮必须三个候选以上,拍板买不买的是我"):白班候选下限
#        非空卡≥3、空槽≤1、空槽唯一合法理由=质量地板;禁"默认收敛/不硬凑/超卖不追空"
#        式否决;真无合格时 no_candidate_reason 逐票列筛除条款(≥3 票)禁无痕全空;
#        质量地板一条不松;earnings 班契约不变
#     ③ morning/evening plist 模板 FILL_ME 密钥行摘净(戌抓获,四模板对齐,密钥单源 .env)
#   ★ v3.25.5(2026-08-20):双算冲突绊线——盘后读数端点值与本地自算值同票对读,
#     方向相反或差>3pp = 不采信不发布,两值+双时戳响亮进 skips(BULL 反向读数案的
#     机械化:该类错由系统自拦,不再流到晚报/复盘/Lyra 屏前)
#   ★ v3.25.4(2026-08-20,戌抓获 v3.25.3 头部⑤宣言未落地——patch 脚本中途断言崩、
#     写盘未执行、换修法时漏补且冒烟未覆盖,守恒认账;本版补齐并改公式):
#     ① fetch_afterhours 盘后涨跌改直取端点自算 secondaryData.percentageChange
#        (格式 ±x.xx%/--/N.A. 全形解析),不再跨 primary/secondary 自拼公式
#        (深夜字段语义疑翻转,自拼即反向=8-20 BULL 案);端点缺字段才回落自算兜底,
#        ah_pct_src 标注取值来源(endpoint/computed)
#     ② 双时戳落盘(close_asof=primary 时戳 + asof=secondary 时戳)=字段语义定案材料
#     ③ 晚班硬规则:盘后快照只述事实,禁止据此对持仓腿下成败结论;
#        过夜腿成败以次晨交班块处置窗实测为准
#     现场自证点(戌,两窗各采一次 Nasdaq quote info 原文):盘后窗 13:10-16:55 PT
#     与深夜窗 21:00 PT 后,贴 primaryData/secondaryData 两组字段对比定语义
#   ★ v3.25.3(2026-08-20,Lyra 拍板"机器不藏强票,选择权在交易员"):
#     ① 双杀排除:机械禁入 → 亮牌。dk_risk 强票(chg5>15%/rsi>75)照常出伏击卡,
#        强制标注"双杀风险位"+双向情景参照价带+仓位提示+盘后止损参照,买不买 Lyra 拍
#     ② 三档全摆:强票档(dk_risk 亮牌)/温和档(run-up)/超跌档(oversold,chg5<-2%,
#        WOLF/JBSS 型)——引擎 _leg_tier 逐票标注 tier+dk_risk,三档并排择优
#     ③ 质量地板(COTY 案):price<$5 禁入;Reduce/Sell 共识、指引撤回、重大诉讼禁入;
#        evidence 必须给资金/量能实据;宁空勿弱——无合格候选出空槽,禁为填槽拣弱票
#     ④ 白班 T+0 豁免:当日财报票盘中动量可入 S1/S3(收盘前强制清仓,禁持过夜)
#     ⑤ 盘后读数时点纪律(8-20 BULL 反向读数案):fetch_afterhours 落双时戳
#        (close_asof+asof);晚班盘后快照只述事实禁下持仓腿成败结论,
#        过夜腿成败以次晨交班块处置窗实测为准
#     现场自证点:Nasdaq quote 端点深夜 primary/secondary 字段语义(戌白天+深夜
#     各采一次原文对比定案,疑深夜翻转致 8-20 凌晨 BULL 盘后读数反向)
#   ★ v3.25.2(2026-08-20,Lyra 拍板"没有理由讲得通"后当日出):
#     ① 爬虫#12 全市场异动扫描(MRNA+143%/TEM/比特币板块全盲案根治):FMP
#        gainers/losers 榜,legacy/stable 候选自探定版 .fmp_route(movers:方向),
#        price≥3 每侧 cap 20;四班引擎行+prompt 硬规则(|chg|≥10% 必点名成因,
#        可入 S3,禁无痕跳过)+晚班复盘 watch 并入——数据层不再只看财报
#     ② 盘后必报(COTY 盘后-8% 没提案):evening 盘后名单 = amc_tonight ∪
#        当日各班非空候选腿(cap 24)——复盘对象自己的盘后必查必报
#     ③ 回流 b286083(expanded review 8/19 五连崩现场热修):WB(8515)签名转发+
#        task 字段+final 取值+长 task 触发 GLM substrate+store 同步——
#        流程规矩同立:现场热修当天报 commit,守恒负责回流,否则出包=回滚
#     ④ 回流 b4795cb:伏击腿(S2/S4)evidence 硬规则——必须引所属板块读数,
#        背离须在 rank_reason 解释(COTY 案 sector 交叉弱)
#     ⑤ 新 plist 模板密钥行摘除(FILL_ME 覆盖 .env 致 console 401 案):
#        密钥单一来源 .env;earnings 班模板 DS_MAX_TOKENS=16000(双伏击卡截断案)
#   ★ v3.25.1(2026-08-19,戌实测定案后两点小修):
#     ① _THETA_CANDS 移除全部 root 形参候选(v2 废弃;实测 v3 只认 symbol+
#        start_date+end_date,root 一律 410——留着只在 symbol 失败时追加 410 噪音)
#     ② _theta_history 内闸补商品排除(CLUSD/GCUSD 打 stock 端点必 472;
#        _history 已按类闸过,此为纵深防御,防直调路径)
#     背景定案:25503 应答者 = 独立 theta-terminal 容器(Up 39h,Terminal 活,
#     v3 形制实测出数)——V7①"Terminal 没跑"作废;Theta 第二源对 stock 票在岗
#   ★ v3.25(2026-08-19,Lyra 拍板 三班制+BMO 伏击+FMP 付费档路由;取证 V1-V7 by 戌):
#     ① 四班制:morning 6:45(不含财报,交班义务=昨夜过夜腿+watch 盘初实测)/
#        midday 10:40(定位复核+主池动量+AMC 初筛不建新仓)/ earnings 12:35 起跑
#        (报告 12:45 在手;开卷财报班:S2=今晚 AMC 伏击,S4=次日 BMO 前置伏击,
#        过夜敞口默认单日≤1 腿)/ evening 21:00(三班合并复盘,腿按 ticker+方向去重)
#     ② BMO 前置伏击腿(EL 案根治):bmo_tomorrow 引擎名单,when 按 V6 实值
#        time-pre-market 匹配(不猜别名);尾盘买入持过夜,次晨首屏处置
#     ③ run-up 腿引擎供数(EL 案第二半):upcoming_earnings 2-8 交易日窗名单,
#        市值降序 cap 12——此前只有 prompt 规则,日历数百行被 _slim_raw 裁剪
#     ④ FMP 付费档端点路由(V6 402 根治):legacy /api/v3 与 stable 族候选自探,
#        首个出数按 kind:类 定版落盘 .fmp_route 跨班续用;每分钟令牌节流
#        FMP_RATE_PER_MIN 默认 280;类级失败=本班停用一次响亮(HTTP 码+正文进 skips)
#     ⑤ 缓存带血统(0817 指数污染洞根治):缓存记 {src,rows},代理序列独立键
#        SYM__proxy_X,读路径禁跨序列;backup 血统新鲜缓存每班先试主源升级
#     ⑥ persist_skips(V1 ZTO 案):引擎期 skips 回写当日 raw,盘后缺数有迹可查
#     ⑦ prev_review 全键传递(调优死信根治):watch/rejected_review 进 DS 视野
#     ⑧ 新 plist 两份:midday 10:40 / earnings 12:35(既有一律保留→.new)
#     现场自证点(沙箱够不着,装后看数):FMP 付费 key 实际端点族、Theta Terminal
#     启动(V7:未跑,410/472 无源可修)、fear_greed 418(UA 对策待实弹)
#   ★ 两支线合流(v3.15 判例,并集零取舍):现场主程序 0817 经 diff 验明=install_9
#     内嵌 v3.23 同字节,verify 契约的 v3.16.x 器官全部缺席——本包全员长回:
#     think=False(Ollama 空正文根因)/ emit_aether_scout(晨晚 8501 事件流)/
#     rsi14_tape / tape_check 逐腿盖章 / 晚班源清单+lint 硬闸(事实行最高权威)/
#     EXPANDED-GLM review(scout-review-日)/ et_now_hm / amc cap 30 / yday 4000 /
#     RSI 禁自估;DS_MAX_TOKENS 默认 12000(对齐现场)
#   ★ 数据链改版(Lyra 拍板 2026-08-17):FMP 主源(免费档 250/日;prices/ K线缓存+
#     调用记账,常规班 ~10-20 次)→ ThetaData 第二源(:25510 探活,未起整链跳过,
#     不强迫起容器)→ Alpaca backup(0817 现场代码收编)→ Yahoo 指数兜底;
#     stooq 已移除。真指数 ^GSPC/^IXIC/^VIX 与 HYG/LQD 信用金丝雀回岗;
#     Alpaca 过渡层静默丢失的 vol_x20/on20/in20/_rets20 整族复活
#   ★ 8-17 事故族修复:certifi SSL 上下文(fetchers._get + scout _http 两缝全封)/
#     .env 死键族根治(_load_env_file 先于 import fetchers 与常量;DS/CONSOLE key
#     调用期读取)/ OUT 默认=脚本所在目录(拆双根陷阱)/ 晨会失败落 _parse_failed
#     标记(land 拒吃口)/ 安装器不再 bash source .env(set -e 地雷)
#   ★ 两轮审查修复:prompt 供数瘦身 _slim_raw(剥 _rets20,预算 18000——旧 6000 时
#     polymarket/未来财报日/sectors 从未进 DS 视野)/ 晚班补算 earnings_movers
#     (雷达第5项曾对空气核对)/ 自检先检后跑(重跑不改写账本)/ load_prev_review
#     周末滤(v3.22 同族第二处)/ 版本字符串消灭
#   ★ v3.24.4(2026-08-17 第四刀,Lyra 令):Yahoo/yfinance 全线移除——指数兜底整体
#     摘除,三大指数缺任一=响亮 skip+横幅降级如实呈现,不找替身;FMP 付费档全接。
#   ★ v3.24.3(2026-08-17 第三刀):Theta EOD 分窗拉取——v3 上限 365 天/请求(实弹
#     400: max 365 days),改 ≤360 天分窗、新窗探路定版、旧窗尽力补齐、按日期去重
#     合并;新窗失败=按失败处理退 Alpaca,旧窗失败只伤 52w 边缘并响亮进 skips。
#     THETA_BASE 默认翻转 25510→25503(她 Terminal 实跑口,跨项目 review O5 同判)。
#     FMP 预算 env 化:FMP_DAILY_BUDGET(默认 250),付费档升级只改 env,预警=80%。
#   ★ v3.24.2(2026-08-17 第二刀):Theta EOD 路径自发现——候选矩阵(v3/v2/裸)逐一
#     实弹,410 正文自动挖新路径提示,首个出数的(路径,参数)定版落盘 .theta_route
#     跨班续用、失效自愈重探;全败=本班停用一次响亮(全部回包头进日志与 skips),
#     不再产生人肉取证往返。
#   ★ v3.24.1(2026-08-17 部署后即时刀):Theta 探活改判活性——任何 HTTP 回应
#     (含新版 Terminal 状态口 410)=在,仅拒连/超时=未起;EOD 路径 v2/无前缀
#     双试探首票定版;双败把 Terminal 回包头 120 字入 skip(下一刀实弹)
#   ★ verify_scout_deploy v3.24 增补 FMP/Theta 三项;既有 verify 保留→ .new
#   总包安全承诺:①既有 plist/verify 一律保留不覆盖(新模板 .new)
#   ②briefs/raw/review/prices 数据不碰 ③装完编译+门禁静态闸+条件重渲,一行结论
#   bash scout_agent_install.sh [目标目录]   默认 ./grid-scout
# ============================================================================
set -euo pipefail
SELF_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
ROOT="${1:-./grid-scout}"
mkdir -p "$ROOT"
cd "$ROOT"
cat > 'README.md' <<'PKG_EOF_000'
# Scout Agent v3.29.2(DS 决策官 · 三班制 + 六因子核 + 准入闸 + 自算趋势榜 + 仓位档/Kelly)

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
PKG_EOF_000
cat > '.tmp_001' <<'PKG_EOF_001'
<?xml version="1.0" encoding="UTF-8"?>
<!-- 模板:是否注册常驻由 Lyra 拍板后自行执行(铁则:不默认引入常驻项)
     cp 到 ~/Library/LaunchAgents/ 后:launchctl load ~/Library/LaunchAgents/com.grid.evening-brief.plist -->
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.grid.evening-brief</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>__SCOUT_DIR__/scout_agent.py</string>
         <string>--mode</string><string>evening</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>__SCOUT_DIR__/scout.log</string>
  <key>StandardErrorPath</key><string>__SCOUT_DIR__/scout.err</string>
  <key>EnvironmentVariables</key><dict>
    <!-- 密钥不进 plist:单一来源 .env(FILL_ME 覆盖 .env 致 401,2026-08-20 案;本模板 v3.25.6 基线摘净) -->
    <key>SCOUT_OUT</key><string>__SCOUT_DIR__</string>
    <key>CONSOLE_URL</key><string>http://localhost:8610</string>
    <key>DS_MAX_TOKENS</key><string>12000</string>
  </dict>
</dict></plist>
PKG_EOF_001
if [ -f 'com.grid.evening-brief.plist' ]; then
  echo "[install] 保留既有 com.grid.evening-brief.plist(含你的配置,不覆盖);新模板→com.grid.evening-brief.plist.new"
  mv .tmp_001 com.grid.evening-brief.plist.new
else
  mv .tmp_001 com.grid.evening-brief.plist
fi
cat > '.tmp_002' <<'PKG_EOF_002'
<?xml version="1.0" encoding="UTF-8"?>
<!-- 晨报 6:45am PST(=9:45 ET 盘初,Lyra 反转拍板 2026-08-05)。模板同保护规矩:
     cp 到 ~/Library/LaunchAgents/ 后:launchctl load ~/Library/LaunchAgents/com.grid.morning-brief.plist -->
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.grid.morning-brief</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>__SCOUT_DIR__/scout_agent.py</string>
         <string>--mode</string><string>morning</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>45</integer></dict>
  <key>StandardOutPath</key><string>__SCOUT_DIR__/scout_morning.log</string>
  <key>StandardErrorPath</key><string>__SCOUT_DIR__/scout_morning.err</string>
  <key>EnvironmentVariables</key><dict>
    <!-- 密钥不进 plist:单一来源 .env(FILL_ME 覆盖 .env 致 401,2026-08-20 案;本模板 v3.25.6 基线摘净) -->
    <key>SCOUT_OUT</key><string>__SCOUT_DIR__</string>
    <key>CONSOLE_URL</key><string>http://localhost:8610</string>
    <key>DS_MAX_TOKENS</key><string>12000</string>
  </dict>
</dict></plist>
PKG_EOF_002
if [ -f 'com.grid.morning-brief.plist' ]; then
  echo "[install] 保留既有 com.grid.morning-brief.plist(含你的配置,不覆盖);新模板→com.grid.morning-brief.plist.new"
  mv .tmp_002 com.grid.morning-brief.plist.new
else
  mv .tmp_002 com.grid.morning-brief.plist
fi
cat > '.tmp_007' <<'PKG_EOF_007'
<?xml version="1.0" encoding="UTF-8"?>
<!-- 午班 10:40am PST(=1:40pm ET 盘中,Lyra 拍板 2026-08-19)。模板同保护规矩:
     cp 到 ~/Library/LaunchAgents/ 后:launchctl load ~/Library/LaunchAgents/com.grid.midday-brief.plist -->
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.grid.midday-brief</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>__SCOUT_DIR__/scout_agent.py</string>
         <string>--mode</string><string>midday</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>40</integer></dict>
  <key>StandardOutPath</key><string>__SCOUT_DIR__/scout_midday.log</string>
  <key>StandardErrorPath</key><string>__SCOUT_DIR__/scout_midday.err</string>
  <key>EnvironmentVariables</key><dict>
    <!-- 密钥不进 plist:单一来源 .env(FILL_ME 覆盖 .env 致 401,2026-08-20 案) -->
    <key>SCOUT_OUT</key><string>__SCOUT_DIR__</string>
    <key>CONSOLE_URL</key><string>http://localhost:8610</string>
    <key>DS_MAX_TOKENS</key><string>12000</string>
  </dict>
</dict></plist>
PKG_EOF_007
if [ -f 'com.grid.midday-brief.plist' ]; then
  echo "[install] 保留既有 com.grid.midday-brief.plist(含你的配置,不覆盖);新模板→com.grid.midday-brief.plist.new"
  mv .tmp_007 com.grid.midday-brief.plist.new
else
  mv .tmp_007 com.grid.midday-brief.plist
fi
cat > '.tmp_008' <<'PKG_EOF_008'
<?xml version="1.0" encoding="UTF-8"?>
<!-- 财报班 12:35pm PST 起跑(报告 12:45 在手,=3:35pm ET 尾盘;收盘 13:00 PST,Lyra 拍板 2026-08-19)。
     模板同保护规矩:cp 到 ~/Library/LaunchAgents/ 后:launchctl load ~/Library/LaunchAgents/com.grid.earnings-brief.plist -->
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.grid.earnings-brief</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>__SCOUT_DIR__/scout_agent.py</string>
         <string>--mode</string><string>earnings</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>35</integer></dict>
  <key>StandardOutPath</key><string>__SCOUT_DIR__/scout_earnings.log</string>
  <key>StandardErrorPath</key><string>__SCOUT_DIR__/scout_earnings.err</string>
  <key>EnvironmentVariables</key><dict>
    <!-- 密钥不进 plist:单一来源 .env(FILL_ME 覆盖 .env 致 401,2026-08-20 案) -->
    <key>SCOUT_OUT</key><string>__SCOUT_DIR__</string>
    <key>CONSOLE_URL</key><string>http://localhost:8610</string>
    <key>DS_MAX_TOKENS</key><string>16000</string>
  </dict>
</dict></plist>
PKG_EOF_008
if [ -f 'com.grid.earnings-brief.plist' ]; then
  echo "[install] 保留既有 com.grid.earnings-brief.plist(含你的配置,不覆盖);新模板→com.grid.earnings-brief.plist.new"
  mv .tmp_008 com.grid.earnings-brief.plist.new
else
  mv .tmp_008 com.grid.earnings-brief.plist
fi
cat > '.tmp_009' <<'PKG_EOF_009'
<?xml version="1.0" encoding="UTF-8"?>
<!-- 盘后快照 4:45pm PST(=7:45pm ET,Nasdaq 盘后窗内;v3.26.3)。只取盘后读数落 state/,不调 DS 不写简报。
     是否 load 由 Lyra 拍板(不默认引入常驻项);不 load 则 21:00 晚班回落实时取并报健康态。
     cp 到 ~/Library/LaunchAgents/ 后:launchctl load ~/Library/LaunchAgents/com.grid.afterhours-snap.plist -->
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.grid.afterhours-snap</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>__SCOUT_DIR__/scout_agent.py</string>
         <string>--mode</string><string>afterhours</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>45</integer></dict>
  <key>StandardOutPath</key><string>__SCOUT_DIR__/scout_afterhours.log</string>
  <key>StandardErrorPath</key><string>__SCOUT_DIR__/scout_afterhours.err</string>
  <key>EnvironmentVariables</key><dict>
    <!-- 密钥不进 plist:单一来源 .env -->
    <key>SCOUT_OUT</key><string>__SCOUT_DIR__</string>
  </dict>
</dict></plist>
PKG_EOF_009
if [ -f 'com.grid.afterhours-snap.plist' ]; then
  echo "[install] 保留既有 com.grid.afterhours-snap.plist(不覆盖);新模板→com.grid.afterhours-snap.plist.new"
  mv .tmp_009 com.grid.afterhours-snap.plist.new
else
  mv .tmp_009 com.grid.afterhours-snap.plist
fi
cat > 'acceptance_fmp_board.py' <<'PKG_EOF_010'
#!/usr/bin/env python3
"""acceptance_fmp_board.py · v1(2026-08-25,Lyra:"测出来的票不在 FMP top mover 榜,不收")
在 grid-scout 目录跑,读当日 raw(FMP 真实回包)与当班 brief json,逐卡对榜。零推断,只对数据。
  python3 acceptance_fmp_board.py --date 2026-08-25 --shift earnings
退出码 0=全过;1=有卡不在榜/形态错配/名单序与实测不符。"""
import argparse, glob, json, os, re, sys

OUT = os.path.dirname(os.path.abspath(__file__))


def load_raw(date):
    paths = sorted(glob.glob(os.path.join(OUT, "raw", date + "*.json")))
    if not paths:
        sys.exit("raw 缺失:%s" % date)
    raws = [json.load(open(p, encoding="utf-8")) for p in paths]
    return raws[-1], paths[-1]        # 当日最后一次采集 = 财报班/晚班用的那份


def boards(raw):
    g, a, a_up = set(), set(), set()
    for src in raw.get("results", raw.get("sources", [])):
        if src.get("source") == "market_movers":
            for it in src.get("items") or []:
                if it.get("side") == "gainers":
                    g.add(str(it.get("symbol")).upper())
        if src.get("source") == "most_active":
            for it in src.get("items") or []:
                a.add(str(it.get("symbol")).upper())
                if (it.get("chg_pct") or 0) > 0:
                    a_up.add(str(it.get("symbol")).upper())
    return g, a, a_up


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--shift", default="earnings", choices=["morning", "midday", "earnings", "evening"])
    a = ap.parse_args()
    raw, rp = load_raw(a.date)
    g, act, act_up = boards(raw)
    trend = set()
    for tp in sorted(glob.glob(os.path.join(OUT, "state", "trend_board-*.json"))):   # v3.28:自算趋势榜也是"钱的榜"
        try:
            trend |= {r.get("symbol") for r in (json.load(open(tp, encoding="utf-8")).get("board") or [])}
        except Exception:
            pass
    bp = os.path.join(OUT, "briefs", "%s-%s.json" % (a.date, a.shift))
    if not os.path.exists(bp):
        sys.exit("brief 缺失:%s" % bp)
    doc = json.load(open(bp, encoding="utf-8"))
    eng, ds = doc.get("_engine") or {}, doc.get("ds") or {}
    fails, oks = [], []
    print("raw=%s  FMP 涨幅榜 %d 只 · 最活跃 %d 只(收涨 %d) · 自算趋势榜 %d 只" % (os.path.basename(rp), len(g), len(act), len(act_up), len(trend)))
    if not g and not act:
        fails.append("FMP 两榜为空——源失败,本班一切候选无资金确认")
    # 1) 已发布的候选卡(非空、非对冲)逐卡对榜
    for c in ds.get("candidates") or []:
        if not isinstance(c, dict) or c.get("empty"):
            continue
        t = str(c.get("ticker") or "").upper()
        if not re.fullmatch(r"[A-Z]{1,5}", t):
            fails.append("S%s 非单一代码 '%s'" % (c.get("slot"), t)); continue
        note = "%s %s" % (c.get("note") or "", (c.get("strategy") or {}).get("note") or "")
        tag = "预排" if "明晨预排" in note else ("初筛" if "AMC 初筛观察" in note else "实卡")
        on = ("涨幅榜" if t in g else "") + ("+最活跃收涨" if t in act_up else ("+最活跃(收跌)" if t in act else "")) + ("+趋势榜" if t in trend else "")
        tc = c.get("tape_check") or {}
        line = "S%s %s %s %s | 榜:%s | tape 日%s loc%s" % (c.get("slot"), t, str(c.get("direction") or "").upper(), tag,
                                                            on or "不在榜", tc.get("chg_pct"), tc.get("close_loc"))
        bad = []
        if str(c.get("direction") or "").lower() == "call" and tag == "实卡" and t not in g and t not in act_up and t not in trend:
            bad.append("call 实卡不在 FMP 涨幅榜/最活跃收涨/自算趋势榜")
        try:
            if str(c.get("direction") or "").lower() == "call" and tc.get("chg_pct") is not None and tc.get("close_loc") is not None \
                    and float(tc["chg_pct"]) <= -1.0 and float(tc["close_loc"]) < 0.5:
                bad.append("call 卡尾盘弱势收低(引擎实测)")
        except (TypeError, ValueError):
            pass
        (fails if bad else oks).append(line + ((" ← " + ";".join(bad)) if bad else ""))
    # 2) 引擎名单/池:前三是否在榜(池行必须;财报名单只报不判)
    pool = eng.get("candidate_pool") or []
    for p in pool[:3]:
        s_ = p.get("symbol")
        if s_ in g or s_ in act_up or s_ in trend:
            oks.append("池#%d %s 在榜(%s)" % (pool.index(p) + 1, s_, "涨幅榜" if s_ in g else ("最活跃收涨" if s_ in act_up else "趋势榜")))
        else:
            fails.append("池#%d %s 不在 FMP 涨幅榜/最活跃收涨/趋势榜(池是七眼并集,前三不在榜=眼有假)" % (pool.index(p) + 1, s_))
    for k in ("amc_tonight", "bmo_tomorrow"):
        rows = eng.get(k) or []
        if rows:
            print("%s(按 earn_score):%s" % (k, " · ".join("%s(%s%s)" % (r.get("symbol"), r.get("earn_score"), ",榜" if r.get("fmp_board") else "") for r in rows[:6])))
    for m in oks:
        print("  OK   ", m)
    for m in fails:
        print("  FAIL ", m)
    print("---\nOK %d · FAIL %d" % (len(oks), len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
PKG_EOF_010
cat > 'factors.py' <<'PKG_EOF_011'
"""factors.py · Scout v3.29 因子核(2026-08-25,Lyra 令"当然继续",把 Fable 一个月前 A/C 组讨论落成代码)

替代 v3.26–v3.28 里近 30 条手写加分规则(候选池 12 条 + 趋势榜 8 条 + 财报名单 7 条)——那些规则每条对应某一天的事故,
是对最近三张截图的过拟合。这里只有 6 个因子,每个有经济含义、有显式权重、有 why 字符串;因子预算上限 12(verify 静态闸)。

    F1 money   资金密度  权 20  换手率 = 20 日成交额 / 市值(成交额/流通市值的可得近似);缺市值退成交额档
    F2 trend   趋势      权 25  5 日涨幅 / 10 日涨幅 / 近 5 根收涨根数 / 距 20 日高
    F3 tape    尾盘形态  权 15  收盘在日内区间的位置 / 当日涨跌 / 放量倍数
    F4 event   事件      权 15  距财报天数(3–7 天 = IV 抬升窗,long call 吃 IV expansion;当日 AMC = 只准预排)
    F5 options 不对称性  权 20  ATM 最近到期(7–30 DTE)call 的 gamma/|theta|,批内百分位;Theta 快照缺 = 因子缺,权重归一化到可得因子
    F6 risk    风险扣分         RSI>85 −15 / 5 日 >40% −15(追高)/ 当日 >20% −10 / 双杀位 −10 / 弱势收低(≤−1% 且 loc<0.5)−20

总分 = Σ(权_i × 子分_i)/Σ(可得因子权)− 扣分,0–100 整数。地板(price/adv20/ETF)与方向闸是准入,不是因子,不在此文件。

宏观(C#4)只进仓位档不进选股:regime_tier() 按 VIX 定 满/半/停,只显示。
Kelly(C#8):kelly_fraction() 由复盘账本滚动命中率算,样本 <20 用 quarter,≥20 用 half;只显示。
"""
from __future__ import annotations

import math
import os

WEIGHTS = {"F1_money": 20, "F2_trend": 25, "F3_tape": 15, "F4_event": 15, "F5_options": 20}
FACTOR_BUDGET = 12          # 因子数硬上限(Fable 8 月讨论:>12 进过拟合危险区)
FACTORS = ("F1_money", "F2_trend", "F3_tape", "F4_event", "F5_options", "F6_risk")
assert len(FACTORS) <= FACTOR_BUDGET


def _clip(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _lerp(x, x0, y0, x1, y1):
    """x 在 [x0,x1] 线性映射到 [y0,y1],外侧截断。"""
    if x is None:
        return None
    if x <= x0:
        return y0
    if x >= x1:
        return y1
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


# ---------------- F1 资金密度 ----------------
def f1_money(d):
    """换手率(20 日成交额/市值)为主;缺市值时退到 20 日成交额绝对档。返回 (子分, why)。"""
    adv = d.get("adv20_usd")
    mcap_b = d.get("mcap_b")
    if adv is None:
        return None, "F1 无成交额"
    if mcap_b and mcap_b > 0:
        turnover = adv / (mcap_b * 1e9)          # 日均换手(20 日)
        # 0.1% → 0,0.3% → 30,1% → 60,3% → 100(对数轴上大致线性)
        sub = _clip(_lerp(math.log10(max(turnover, 1e-5)), math.log10(0.001), 0, math.log10(0.03), 100))
        return sub, "换手%.2f%%/日" % (turnover * 100)
    sub = _clip(_lerp(math.log10(max(adv, 1)), math.log10(1e8), 40, math.log10(2e9), 100))
    return sub, "成交额$%.0fM(无市值)" % (adv / 1e6)


# ---------------- F2 趋势 ----------------
def f2_trend(d):
    c5, c10, up5, h20 = d.get("chg5_pct"), d.get("chg10_pct"), d.get("up5"), d.get("dist_high20_pct")
    if c5 is None:
        return None, "F2 无 5 日读数"
    parts, why = [], []
    # 5 日:−5% → 0,0 → 20,+5% → 60,+15% → 100;>40% 封顶 100 但 F6 扣追高
    parts.append(_clip(_lerp(c5, -5, 0, 15, 100)) if c5 <= 15 else 100); why.append("5日%+.1f%%" % c5)
    if c10 is not None:
        parts.append(_clip(_lerp(c10, -5, 0, 25, 100))); why.append("10日%+.1f%%" % c10)
    if up5 is not None:
        parts.append(_clip(up5 / 5 * 100)); why.append("5根%d涨" % up5)
    if h20 is not None:
        parts.append(_clip(_lerp(h20, -10, 0, 0, 100))); why.append("距20日高%+.1f%%" % h20)
    return sum(parts) / len(parts), " ".join(why)


# ---------------- F3 尾盘形态 ----------------
def f3_tape(d):
    loc, chg, vx = d.get("close_loc"), d.get("chg_pct"), d.get("vol_x20")
    if loc is None and chg is None:
        return None, "F3 无形态读数"
    parts, why = [], []
    if loc is not None:
        parts.append(_clip(loc * 100)); why.append("loc%.2f" % loc)
    if chg is not None:
        parts.append(_clip(_lerp(chg, -3, 0, 5, 100))); why.append("日%+.1f%%" % chg)
    if vx is not None:
        parts.append(_clip(_lerp(vx, 0.7, 20, 2.0, 100))); why.append("量%.1fx" % vx)
    return sum(parts) / len(parts), " ".join(why)


# ---------------- F4 事件 ----------------
def f4_event(days_to_earnings, post_days=None, post_gap_pct=None):
    """days_to_earnings:距下一财报的交易日数(0=今日盘后,1=明日盘前…);None=窗内无财报。
    3–7 天 = IV 抬升窗 100;1–2 天 70(IV 已大半抬升);8–14 天 40;0 天 = 不计分(只准预排,由闸管);
    post_days 1–3 且 post_gap_pct ≥ +5% = 财报后漂移 60。"""
    if days_to_earnings is not None:
        n = int(days_to_earnings)
        if n == 0:
            return 0.0, "财报今日盘后(预排)"
        if 3 <= n <= 7:
            return 100.0, "财报%d天(IV窗)" % n
        if 1 <= n <= 2:
            return 70.0, "财报%d天" % n
        if 8 <= n <= 14:
            return 40.0, "财报%d天" % n
    if post_days is not None and 1 <= int(post_days) <= 3 and (post_gap_pct or 0) >= 5:
        return 60.0, "财报后%d天 gap%+.1f%%" % (post_days, post_gap_pct)
    return None, "无事件"


# ---------------- F5 期权不对称性 ----------------
def f5_options_ratio(g):
    """g = {gamma, theta, iv, dte, strike, mid}(Theta ATM call 快照);返回 gamma/|theta| 原始比值或 None。"""
    if not g or g.get("gamma") is None or not g.get("theta"):
        return None
    th = abs(float(g["theta"]))
    if th < 1e-6:
        return None
    return float(g["gamma"]) / th


def f5_options_batch(ratios):
    """批内百分位:{sym: ratio} → {sym: 子分};单票 50;None 不计。"""
    vals = sorted(v for v in ratios.values() if v is not None)
    out = {}
    for s, v in ratios.items():
        if v is None:
            out[s] = None
        elif len(vals) <= 1:
            out[s] = 50.0
        else:
            rank = sum(1 for x in vals if x < v)
            out[s] = rank / (len(vals) - 1) * 100
    return out


# ---------------- F6 风险扣分 ----------------
def f6_risk(d):
    pen, why = 0, []
    rsi, c5, chg = d.get("rsi14"), d.get("chg5_pct"), d.get("chg_pct")
    if rsi is not None and rsi > 85:
        pen += 15; why.append("RSI%.0f过热-15" % rsi)
    if c5 is not None and c5 > 40:
        pen += 15; why.append("5日%+.0f%%追高-15" % c5)
    if chg is not None and chg > 20:
        pen += 10; why.append("日%+.0f%%单日暴涨-10" % chg)
    if d.get("dk_risk"):
        pen += 10; why.append("双杀位-10")
    loc = d.get("close_loc")
    if chg is not None and loc is not None and chg <= -1.0 and loc < 0.5:
        pen += 20; why.append("弱势收低-20")      # 与方向闸同判据(闸=硬作废,此处=软扣分,池内排位也要反映)
    return pen, " ".join(why)


# ---------------- 汇总 ----------------
def score(d, *, days_to_earnings=None, post_days=None, post_gap_pct=None, f5_sub=None, f5_raw=None):
    """→ {"score": int 0–100, "subs": {F: 子分或 None}, "why": str, "missing": [F...], "penalty": int}"""
    subs, whys = {}, {}
    subs["F1_money"], whys["F1_money"] = f1_money(d)
    subs["F2_trend"], whys["F2_trend"] = f2_trend(d)
    subs["F3_tape"], whys["F3_tape"] = f3_tape(d)
    subs["F4_event"], whys["F4_event"] = f4_event(days_to_earnings, post_days, post_gap_pct)
    subs["F5_options"] = f5_sub
    whys["F5_options"] = ("γ/|θ|=%.2f" % f5_raw) if (f5_raw is not None) else "F5 缺(Theta 无快照)"
    pen, pen_why = f6_risk(d)
    # F4 "无事件"按 None 处理(不参与归一化),只有有窗口时才有权重——否则无财报票天然吃亏
    avail = {k: v for k, v in subs.items() if v is not None}
    wsum = sum(WEIGHTS[k] for k in avail)
    total = (sum(WEIGHTS[k] * v for k, v in avail.items()) / wsum) if wsum else 0.0
    total = _clip(total - pen)
    missing = [k for k, v in subs.items() if v is None]
    why = " | ".join("%s %s%s" % (k[:2], ("%.0f" % v) if v is not None else "-", ("(" + whys[k] + ")") if whys[k] else "")
                     for k, v in subs.items())
    if pen_why:
        why += " | F6 " + pen_why
    return {"score": int(round(total)), "subs": {k: (None if v is None else round(v, 1)) for k, v in subs.items()},
            "why": why, "missing": missing, "penalty": pen}


# ---------------- 宏观仓位档(只显示,不进选股) ----------------
def regime_tier(vix_level, vix_chg_pct=None):
    """VIX <18 满;18–25 半;>25 停(只观察);VIX 单日 ≥ +15% 降一档。返回 (档, 理由)。"""
    if vix_level is None:
        return "未知", "VIX 无读数"
    tiers = ["满", "半", "停"]
    i = 0 if vix_level < 18 else (1 if vix_level <= 25 else 2)
    why = "VIX %.1f" % vix_level
    if vix_chg_pct is not None and vix_chg_pct >= 15 and i < 2:
        i += 1; why += " 单日%+.0f%%降一档" % vix_chg_pct
    return tiers[i], why


# ---------------- Kelly(只显示) ----------------
def kelly_fraction(hits, misses, avg_win=None, avg_loss=None):
    """f* = p − q/b;b 缺时按 1;样本 <20 → quarter,≥20 → half;f* ≤ 0 → 0。返回 (分数, 说明)。"""
    n = hits + misses
    if n == 0:
        return 0.0, "无复盘样本,不建仓位参考"
    p = hits / n
    b = (avg_win / avg_loss) if (avg_win and avg_loss) else 1.0
    f = p - (1 - p) / b
    mult, label = (0.25, "quarter") if n < 20 else (0.5, "half")
    frac = max(0.0, f * mult)
    return round(frac, 3), "命中 %d/%d p=%.2f b=%.2f f*=%.2f → %s-Kelly %.1f%%" % (hits, n, p, b, f, label, frac * 100)
PKG_EOF_011
cat > 'fetchers.py' <<'PKG_EOF_004'
"""fetchers.py · v3.25 —— FMP 付费档端点路由(Lyra 拍板 2026-08-19;主源架构 2026-08-17)。

数据层拓扑:
  主 tape(指数/对冲/板块/商品/个股)= FMP 付费档(端点自探定版 .fmp_route,legacy/stable 双族;
  每分钟令牌节流 FMP_RATE_PER_MIN 默认 280;预算 FMP_DAILY_BUDGET;本地 K 线缓存带血统+调用记账)
  第二源 = ThetaData(本地 Theta Terminal :25503,实跑口;未起则整链跳过响亮记录,不强迫起容器)
  backup = Alpaca(票级回退,现场 0817 版代码收编);stooq 已移除,不回退。
  换更好的数据 API:只换 quote_layer 内脏(_history/_fmp_quote)——爬虫/引擎/渲染零改动。
基座 = 现场 fetchers 0817_1108(integrated v1 + Alpaca):
  EDGAR 交易日锚定 · afterhours 带 asof · earnings_calendar seen_days+热日+wrap 1200(≥800 门禁)
  et_now_hm · ssl/certifi · FRED API→BLS/NYFed 回退 · feed 档标签 · LIQ 地板。
v3.24 复活的读数(Alpaca 过渡层曾静默丢失):vol_x20/on20/in20/_rets20/chg5/mom20/
  high52_dist + 真指数 ^GSPC/^IXIC/^VIX(替回 SPY/QQQ/VIXY 代理)+ HYG/LQD 信用金丝雀。
"""
from __future__ import annotations
import datetime, json, os, re, ssl, time, urllib.error, urllib.parse, urllib.request
try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = None


def trading_date():
    """美股交易日期(ET 定义,减 4 小时使 ET 0-4 点仍归前一交易日——
    21:00 PST 晚班 = 00:00 ET 不跨日)。机器时区无关:PST/UTC/Docker 结果一致。
    ZoneInfo 不可用则响亮回退本机日期(仅 PST 机器安全)。"""
    if _ET is None:
        print("[fetchers] ZoneInfo 不可用——回退本机日期(仅 PST 机器安全)")
        return datetime.date.today()
    return (datetime.datetime.now(_ET) - datetime.timedelta(hours=4)).date()


def prev_trading_day(d):
    """上一交易日(跳周末:周一→上周五)。节假日未处理——已知边界,不装。"""
    d = d - datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


def et_now_hm():
    """当前 ET 钟点 HH:MM(prompt/渲染共用,杜绝硬编码 9:45)。v3.13。"""
    if _ET is None:
        return datetime.datetime.now().strftime("%H:%M") + "(本机时区,ZoneInfo 不可用)"
    return datetime.datetime.now(_ET).strftime("%H:%M")


UA = {"User-Agent": "grid-evening-scout/1.0 (research; contact: local)"}
SKIPS: list = []          # 本轮逐条跳过记录,与 raw 同文件落盘(侯三审:不许静默吞)
TIMEOUT = 20


def _log_skip(source, item, reason):
    SKIPS.append({"source": source, "item": str(item)[:80], "reason": str(reason)[:200],
                  "ts": datetime.datetime.now().astimezone().isoformat()})


def liq_mcap_floor_b():
    """流动性地板(env 可调)。v3.24:改调用期读取——模块级快照在 .env 加载前定死,
    .env 里的 LIQ_MCAP_FLOOR_B 曾是死键(env 快照族,与 DS_KEY 同族一次治)。"""
    return float(os.getenv("LIQ_MCAP_FLOOR_B", "2.0"))


LIQ_MCAP_FLOOR_B = liq_mcap_floor_b()   # 兼容旧引用;新代码一律走 liq_mcap_floor_b()


def pool_price_floor():
    """候选地板·价格(v3.26,Lyra 2026-08-24:"10 块钱以下的没有任何流通率的"不许进推荐)。
    env POOL_PRICE_FLOOR,默认 10.0 美元;引擎级硬地板,名单/候选池/DS 点名三处同判。"""
    return float(os.getenv("POOL_PRICE_FLOOR", "10.0"))


def pool_adv_floor_usd():
    """候选地板·20 日平均成交额(美元,实测自日线 close×volume,末根未收不计)。
    env POOL_ADV_FLOOR_USD,默认 1e8($100M/日);无实测 = 不过地板(不装数)。"""
    return float(os.getenv("POOL_ADV_FLOOR_USD", "100000000"))


def _ssl_context():
    """本机 Python 常见缺 CA → CERTIFICATE_VERIFY_FAILED;优先 certifi。"""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
        return r.read().decode("utf-8", "replace")


def _wrap(source, fn):
    ts = datetime.datetime.now().astimezone().isoformat()
    n_skips_before = len(SKIPS)
    try:
        items = fn()
        n_sk = sum(1 for k in SKIPS[n_skips_before:] if k["source"] == source)
        if not items and n_sk > 0:
            # 沙箱判例(2026-07-29):全条目被跳=源级失败,不许 ok+空列表装"今天没数据"
            return {"source": source, "ok": False, "ts": ts,
                    "error": "all %d items skipped, see skips" % n_sk, "items": []}
        # earnings_calendar 热日单日可 500+ 行;全局 40/240 会吞掉今日 AMC(TEAM 案例)。
        # 热日解封后昨+今可 >800;按市值排序后前 240 多为 time-not-supplied 巨头,
        # 中盘 AMC(after) 被裁掉 → movers/amc_tonight 空。cap=1200(≥800 门禁)守恒判例。
        # v3.26:movers 榜 50/侧(100 行)——FMP 按 % 排,$3 壳票 +80% 常占满前 20,
        # $12 的 +15% 真流动票被裁在榜外(ASST 型盲区);候选池地板在引擎侧筛。
        cap = 1200 if source == "earnings_calendar" else (120 if source == "market_movers" else 40)
        return {"source": source, "ok": True, "ts": ts, "items": items[:cap]}
    except Exception as e:
        return {"source": source, "ok": False, "ts": ts, "error": str(e)[:300], "items": []}


# ============================================================================
# quote_layer v3.24 —— FMP 主源 + 本地缓存 + 调用记账;Alpaca 票级 backup(v3.16§⑦ 缝)
# ============================================================================
PRICES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices")
_FMP_LEDGER = {"date": "", "calls": 0}
_FMP_BATCH_OK = True     # 免费档批量 quote 若被拒(402/403),本班自动退单票循环
_QUOTE_MEMO: dict = {}   # 本班进程 memo:同一票不重复打点(装机自检/重跑均省配额)


def _fmp_key():
    return os.getenv("FMP_API_KEY", "").strip()


def _fmp_base():
    return os.getenv("FMP_BASE", "https://financialmodelingprep.com/api/v3").rstrip("/")


_FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"
# 端点候选:legacy(/api/v3)与 stable 两族。V6 实证(2026-08-19):新账号付费 key 在
# legacy 上对指数/商品类返回 402 Payment Required。真相由回包定:首个出数的族按
# (kind:类) 定版落盘 .fmp_route 跨班续用,失效自愈重探(.theta_route 同判例 v3.24.2)。
_FMP_ROUTE = {}            # {"quote:index": "stable"|"legacy"};"" = 本班该类停用(不落盘)
_FMP_ROUTE_LOADED = [False]
_FMP_CALL_TS = []          # 每分钟节流窗口(付费档 300/min,默认留余量)
_FMP_UPGRADE_TRIED = set() # backup 血统缓存每班先试主源升级(一票一次)


def _fmp_route_file():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".fmp_route")


def _fmp_route_load():
    if not _FMP_ROUTE_LOADED[0]:
        _FMP_ROUTE_LOADED[0] = True
        try:
            doc = json.load(open(_fmp_route_file(), encoding="utf-8"))
            _FMP_ROUTE.update({k: v for k, v in doc.items() if isinstance(v, str) and v})
        except Exception:
            pass
    return _FMP_ROUTE


def _fmp_route_save():
    try:
        json.dump({k: v for k, v in _FMP_ROUTE.items() if v},
                  open(_fmp_route_file(), "w", encoding="utf-8"))
    except Exception:
        pass


def _fmp_class(sym):
    s = str(sym or "").upper()
    if s.startswith("^"):
        return "index"
    if s in ("CLUSD", "GCUSD"):
        return "commodity"
    return "stock"


def _http_err_text(e):
    """HTTP 错误 → 'HTTP 402 <正文前120字>':报错透明,原文进 skips(禁静默吞码)。"""
    try:
        code = getattr(e, "code", None)
        body = ""
        if hasattr(e, "read"):
            try:
                body = e.read(300).decode("utf-8", "replace").strip()
            except Exception:
                body = ""
        return ("HTTP %s %s" % (code, body[:120])).strip() if code else str(e)[:160]
    except Exception:
        return str(e)[:160]


def _fmp_pace():
    """每分钟令牌节流:付费档限 300 次/分,默认 280 留余量(FMP_RATE_PER_MIN 可调)。
    首拉全量串行连发曾可撞限出 429 连环——v3.25 匀速根治。"""
    limit = max(1, int(os.getenv("FMP_RATE_PER_MIN", "280")))
    while True:
        now = time.time()
        while _FMP_CALL_TS and now - _FMP_CALL_TS[0] > 60:
            _FMP_CALL_TS.pop(0)
        if len(_FMP_CALL_TS) < limit:
            _FMP_CALL_TS.append(now)
            return
        time.sleep(min(2.0, max(0.05, 60.0 - (now - _FMP_CALL_TS[0]) + 0.02)))


def _ledger_path():
    return os.path.join(PRICES_DIR, "_fmp_ledger.json")


def _ledger_load():
    global _FMP_LEDGER
    today = datetime.date.today().isoformat()   # FMP 配额按自然日,非交易日
    if _FMP_LEDGER["date"] != today:
        _FMP_LEDGER = {"date": today, "calls": 0}
        try:
            j = json.load(open(_ledger_path(), encoding="utf-8"))
            if j.get("date") == today:
                _FMP_LEDGER = j
        except Exception:
            pass
    return _FMP_LEDGER


def fmp_calls_today():
    return _ledger_load().get("calls", 0)


def _fmp_tick():
    led = _ledger_load()
    led["calls"] = int(led.get("calls", 0)) + 1
    try:
        os.makedirs(PRICES_DIR, exist_ok=True)
        json.dump(led, open(_ledger_path(), "w", encoding="utf-8"))
    except Exception:
        pass
    budget = int(os.getenv("FMP_DAILY_BUDGET", "250"))  # 付费档升级后只改这个 env
    warn = int(os.getenv("FMP_DAILY_WARN", str(max(1, budget * 4 // 5))))
    if led["calls"] == warn:
        print("[fetchers] ⚠ FMP 当日用量达 %d(当日预算 %d)——只记账不设闸,拍板在 Lyra" % (warn, budget))
    return led["calls"]


def _fmp_get(path_q):
    """FMP GET(节流+记账+带 key)。key 缺失直接抛——上游按票级回退处理。
    path_q 可为相对路径(挂 legacy base)或完整 URL(路由器给)。"""
    key = _fmp_key()
    if not key:
        raise RuntimeError("FMP_API_KEY 未配置")
    _fmp_pace()
    _fmp_tick()
    url = path_q if str(path_q).startswith("http") else (_fmp_base() + path_q)
    sep = "&" if "?" in url else "?"
    return _get(url + sep + "apikey=" + key)


def _fmp_quote_url(fam, sym):
    q = urllib.parse.quote(str(sym), safe="")
    if fam == "legacy":
        return _fmp_base() + "/quote/" + q
    return _FMP_STABLE_BASE + "/quote?symbol=" + q


def _fmp_history_url(fam, sym):
    q = urllib.parse.quote(str(sym), safe="")
    if fam == "legacy":
        return _fmp_base() + "/historical-price-full/%s?timeseries=280" % q
    return _FMP_STABLE_BASE + "/historical-price-eod/full?symbol=" + q


def _fmp_call_routed(kind, sym, url_fn):
    """kind='quote'|'history'。按 (kind:符号类) 路由:定版族直走;未定版按候选实弹
    探路,首个出数定版落盘;全候选失败 = 本班该类停用一次响亮(全部回包摘要进
    异常文本),同类其余票不再连环打 402。"""
    cls = _fmp_class(sym)
    rk = "%s:%s" % (kind, cls)
    route = _fmp_route_load()
    fam = route.get(rk)
    if fam == "":
        raise RuntimeError("fmp %s 类本班停用(探路全败)" % rk)
    fams = ([fam] if fam else []) + [f for f in ("legacy", "stable") if f != fam]
    errs = []
    for f in fams:
        try:
            data = json.loads(_fmp_get(url_fn(f, sym)))
            if data in (None, [], {}):
                errs.append("%s:空回包" % f)
                continue
            if isinstance(data, dict) and data.get("Error Message"):
                errs.append("%s:%s" % (f, str(data.get("Error Message"))[:100]))
                continue
            if route.get(rk) != f:
                route[rk] = f
                _fmp_route_save()
                print("[fetchers] fmp 路由定版 %s=%s" % (rk, f))
            return data
        except urllib.error.HTTPError as e:
            errs.append("%s:%s" % (f, _http_err_text(e)))
        except Exception as e:
            errs.append("%s:%s" % (f, str(e)[:120]))
    route[rk] = ""
    raise RuntimeError("fmp %s 全候选失败: %s" % (rk, " | ".join(errs)))


# ---- ThetaData 第二源(Lyra 拍板 2026-08-17:FMP + ThetaData,Alpaca backup)----
# 本地 Theta Terminal REST(默认 :25503 = 她机器实跑口,v3.24.3 起;env THETA_BASE 可覆盖)。key 由 Terminal 侧配置(option-workstation/
# theta/.env,Cursor 已填),请求本身零 key。Terminal 未起 = 每班探活一次失败 →
# 整链跳过,响亮记录不阻塞(铁则:不默认引入常驻依赖;起不起容器 Lyra 拍板)。
_THETA_STATE = {"up": None, "eod": None}  # eod: (path,param) 本班定版;"" = 探路全败本班停用
# 候选矩阵:v3 两种拼法×参数方言 + v2 + 无前缀。真相由 Terminal 回包定,不锁死守恒猜的档位。
_THETA_CANDS = [("/v3/stock/history/eod", "symbol")]
# v3.25.1:root 形参候选移除——v2 废弃(2026-08-19 戌实测:v3 只认 symbol,
# root 一律 410 deprecated;留着只在 symbol 失败时追加 410 噪音)。
_THETA_ROUTE_LOADED = [False]


def _theta_base():
    return os.getenv("THETA_BASE", "http://127.0.0.1:25503").rstrip("/")


def is_rth_now():
    """ET 09:30–16:00 且工作日。"""
    n = now_et()
    return n.weekday() < 5 and (n.hour, n.minute) >= (9, 30) and (n.hour, n.minute) < (16, 0)


def theta_atm_call_greeks(symbol, spot, min_dte=7, max_dte=30, allow_afterhours=False):
    """v3.29 F5:ATM 最近到期(min_dte–max_dte)call 的 greeks。端点按官方文档:
    GET {THETA_BASE}/v3/option/snapshot/greeks/all?symbol=X&expiration=*&right=call&strike_range=1&max_dte=N&format=json
    (Pro 档;盘外/收盘后快照为空——文档:market closed 当日返回无数据,午夜 ET 重置)。
    返回 {gamma, theta, implied_vol, dte, expiration, strike, mid} 或 None(缺=因子缺,由 factors 归一化;原因入 skip)。"""
    if not spot or spot <= 0:
        return None
    if not is_rth_now() and not allow_afterhours:
        _log_skip("theta_greeks", symbol, "盘外无快照(文档:closed 当日无数据)")
        return None
    if not _theta_up():
        _log_skip("theta_greeks", symbol, "Theta Terminal 未起")
        return None
    q = {"symbol": symbol, "expiration": "*", "right": "call", "strike_range": "1", "max_dte": str(max_dte), "format": "json"}
    url = _theta_base() + "/v3/option/snapshot/greeks/all?" + urllib.parse.urlencode(q)
    try:
        data = json.loads(_get(url))
    except Exception as e:
        _log_skip("theta_greeks", symbol, "greeks 请求失败:%s" % str(e)[:100])
        return None
    rows = data if isinstance(data, list) else (data.get("data") if isinstance(data, dict) else None)
    if not rows:
        _log_skip("theta_greeks", symbol, "greeks 空回包")
        return None
    today = trading_date()
    best = None
    for r in rows:
        try:
            exp = str(r.get("expiration") or "")
            exp_d = datetime.date.fromisoformat(exp) if "-" in exp else datetime.datetime.strptime(exp, "%Y%m%d").date()
            dte = (exp_d - today).days
            if dte < min_dte or dte > max_dte:
                continue
            strike = float(r.get("strike"))
            gamma, theta = r.get("gamma"), r.get("theta")
            if gamma is None or theta is None:
                continue
            key = (dte, abs(strike - float(spot)))
            if best is None or key < best[0]:
                bid, ask = float(r.get("bid") or 0), float(r.get("ask") or 0)
                best = (key, {"gamma": float(gamma), "theta": float(theta), "implied_vol": r.get("implied_vol"),
                              "dte": dte, "expiration": exp_d.isoformat(), "strike": strike,
                              "mid": (bid + ask) / 2 if (bid and ask) else None})
        except Exception:
            continue
    if best is None:
        _log_skip("theta_greeks", symbol, "无 %d–%d DTE 的 ATM call 行" % (min_dte, max_dte))
        return None
    return best[1]


def _theta_route_file():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".theta_route")


def _theta_route_load():
    """上班定过的版跨班续用(文件缓存);失效会自动回落矩阵重探,自愈 Terminal 升级。"""
    if _THETA_ROUTE_LOADED[0]:
        return
    _THETA_ROUTE_LOADED[0] = True
    try:
        j = json.load(open(_theta_route_file()))
        if j.get("path") and j.get("param"):
            _THETA_STATE["eod"] = (str(j["path"]), str(j["param"]))
    except Exception:
        pass


def _theta_route_save(path, param):
    try:
        with open(_theta_route_file(), "w") as f:
            json.dump({"path": path, "param": param,
                       "saved": datetime.datetime.now().astimezone().isoformat()}, f)
    except Exception:
        pass


def _theta_up():
    if _THETA_STATE["up"] is not None:
        return _THETA_STATE["up"]
    try:
        req = urllib.request.Request(_theta_base() + "/v2/system/mdds/status", headers=UA)
        with urllib.request.urlopen(req, timeout=3):
            _THETA_STATE["up"] = True
    except urllib.error.HTTPError:
        # 任何 HTTP 状态码(含新版 Terminal 对旧状态口回的 410)都证明进程活着——
        # 探活只判"在不在",不判语义(8-17:410 曾被误判未起,整链被冤枉跳过)
        _THETA_STATE["up"] = True
    except Exception:
        _THETA_STATE["up"] = False
    if not _THETA_STATE["up"]:
        print("[fetchers] Theta Terminal(%s)未起——本班第二源跳过(FMP→Alpaca 直连)" % _theta_base())
    return _THETA_STATE["up"]


def _theta_rows_v2(header, resp):
    """Theta v2 表格式回包(header.format + response 行)→ 升序 rows。"""
    fmt = [str(x).lower() for x in (header or {}).get("format") or []]
    idx = {k: (fmt.index(k) if k in fmt else None)
           for k in ("date", "open", "high", "low", "close", "volume")}
    if any(idx[k] is None for k in ("date", "open", "high", "low", "close")):
        return []
    rows = []
    for r in resp or []:
        try:
            d8 = str(r[idx["date"]])
            rows.append({"date": "%s-%s-%s" % (d8[:4], d8[4:6], d8[6:8]),
                         "o": float(r[idx["open"]]), "h": float(r[idx["high"]]),
                         "l": float(r[idx["low"]]), "c": float(r[idx["close"]]),
                         "v": ((float(r[idx["volume"]]) or None)
                               if idx["volume"] is not None else None)})
        except (TypeError, ValueError, IndexError):
            continue
    rows.sort(key=lambda x: x["date"])
    return rows


def _theta_norm_date(x):
    s = str(x)
    if re.fullmatch(r"\d{8}", s):
        return "%s-%s-%s" % (s[:4], s[4:6], s[6:8])
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s):
        return s[:10]
    return None


def _theta_rows_any(text):
    """回包体裁自适应:v2 表格式 JSON / dict 列表 JSON / CSV——三种都认,
    认不出即 [](上游响亮记录)。v3 体裁不猜死,首个能解析出数的定版。"""
    t = (text or "").strip()
    if not t:
        return []
    if t[0] in "{[":
        try:
            data = json.loads(t)
        except ValueError:
            return []
        if isinstance(data, dict):
            if "header" in data and "response" in data:
                return _theta_rows_v2(data.get("header"), data.get("response"))
            for k in ("response", "data", "results", "rows"):
                if isinstance(data.get(k), list):
                    data = data[k]
                    break
        if isinstance(data, list) and data and isinstance(data[0], dict):
            rows = []
            for r in data:
                low = {str(k).lower(): v for k, v in r.items()}
                d = _theta_norm_date(low.get("date") or low.get("day") or low.get("timestamp") or "")
                try:
                    if d and low.get("close") is not None:
                        rows.append({"date": d, "o": float(low.get("open") or 0) or None,
                                     "h": float(low.get("high") or 0) or None,
                                     "l": float(low.get("low") or 0) or None,
                                     "c": float(low["close"]),
                                     "v": (float(low["volume"]) if low.get("volume") not in (None, "") else None)})
                except (TypeError, ValueError):
                    continue
            rows.sort(key=lambda x: x["date"])
            return rows
        return []
    # CSV:首行含 date+close 才认
    lines = [ln for ln in t.splitlines() if ln.strip()]
    if len(lines) >= 2 and "date" in lines[0].lower() and "close" in lines[0].lower():
        hdr = [h.strip().lower() for h in lines[0].split(",")]
        col = {k: (hdr.index(k) if k in hdr else None)
               for k in ("date", "open", "high", "low", "close", "volume")}
        if col["date"] is None or col["close"] is None:
            return []
        rows = []
        for ln in lines[1:]:
            cs = ln.split(",")
            try:
                d = _theta_norm_date(cs[col["date"]])
                if not d:
                    continue
                def _f(k):
                    i = col[k]
                    return float(cs[i]) if (i is not None and i < len(cs) and cs[i].strip()) else None
                c = _f("close")
                if c is None:
                    continue
                rows.append({"date": d, "o": _f("open"), "h": _f("high"),
                             "l": _f("low"), "c": c, "v": _f("volume")})
            except (TypeError, ValueError, IndexError):
                continue
        rows.sort(key=lambda x: x["date"])
        return rows
    return []


def _theta_mine_paths(head):
    """从 410/404 弃用告示正文里挖新路径提示(告示通常写明改用哪条)。"""
    return [p.rstrip(".,;:)\"'") for p in re.findall(r"/v\d[\w/\-\.]*", head or "")]


def _theta_history(sym):
    """第二源:Theta Terminal 股票/ETF EOD(指数 ^ 符号不走此端点→[])。
    路径自发现:候选矩阵逐一实弹,首个出数的(路径,参数)定版并落盘 .theta_route
    跨班续用;全败=本班停用一次响亮(全部回包头进日志),不产生人肉取证往返。"""
    s = str(sym).upper()
    if (s.startswith("^") or s in ("CLUSD", "GCUSD")
            or not re.fullmatch(r"[A-Z]{1,5}", s or "") or not _theta_up()):
        return []
    _theta_route_load()
    if _THETA_STATE["eod"] == "":
        return []
    end = trading_date()
    start = end - datetime.timedelta(days=430)
    # v3 上限 365 天/请求(8-17 实弹 400: max 365 days)→ ≤360 天分窗,最新窗在前:
    # 探路在最新窗上做;新窗失败=数据陈旧按失败处理,旧窗尽力补(缺了只伤 52w 边缘)
    chunks, ce = [], end
    while ce >= start:
        cs = max(start, ce - datetime.timedelta(days=360))
        chunks.append((cs, ce))
        ce = cs - datetime.timedelta(days=1)
    d1, d2 = chunks[0]
    dates = "&start_date=%s&end_date=%s" % (d1.strftime("%Y%m%d"), d2.strftime("%Y%m%d"))
    if _THETA_STATE["eod"]:
        cands = [_THETA_STATE["eod"]] + [c for c in _THETA_CANDS if c != _THETA_STATE["eod"]]
    else:
        cands = list(_THETA_CANDS)
    locked = bool(_THETA_STATE["eod"])
    errs, tried = [], set()
    i = 0
    while i < len(cands):
        path, param = cands[i]
        i += 1
        if (path, param) in tried:
            continue
        tried.add((path, param))
        url = "%s%s?%s=%s%s" % (_theta_base(), path, param, s, dates)
        try:
            text = _get(url)
        except urllib.error.HTTPError as e:
            try:
                head = e.read()[:400].decode("utf-8", "replace")
            except Exception:
                head = ""
            errs.append("%s?%s= HTTP %s %s" % (path, param, e.code, head[:120]))
            for mined in _theta_mine_paths(head):
                for pm in ("symbol", "root"):
                    if (mined, pm) not in tried:
                        cands.append((mined, pm))
            if locked:  # 定版路径失效(Terminal 升级)→ 解锁回落全矩阵重探自愈
                locked = False
            continue
        except Exception as e:
            errs.append("%s?%s= %s" % (path, param, str(e)[:100]))
            if locked:
                locked = False
            continue
        rows = _theta_rows_any(text)
        if rows:
            if _THETA_STATE["eod"] != (path, param):
                _THETA_STATE["eod"] = (path, param)
                _theta_route_save(path, param)
                print("[fetchers] Theta EOD 路径定版: %s (参数 %s=) → .theta_route" % (path, param))
            for c1, c2 in chunks[1:]:  # 旧窗尽力补齐(本地 Terminal 零成本)
                try:
                    more = _theta_rows_any(_get(
                        "%s%s?%s=%s&start_date=%s&end_date=%s"
                        % (_theta_base(), path, param, s,
                           c1.strftime("%Y%m%d"), c2.strftime("%Y%m%d"))))
                except Exception as e:
                    more = []
                    _log_skip("theta.history.chunk", s,
                              "%s..%s %s" % (c1, c2, str(e)[:100]))
                rows.extend(more)
            merged = {r["date"]: r for r in rows}
            return sorted(merged.values(), key=lambda x: x["date"])
        errs.append("%s?%s= empty/drift: %s" % (path, param, str(text)[:100]))
        if locked:
            locked = False
    # 全败:本班停用(不再为每票烧一轮矩阵),证据全量进日志、摘要进 skips
    _THETA_STATE["eod"] = ""
    print("[fetchers] Theta EOD 探路全败,本班第二源停用。实弹回执:")
    for e in errs:
        print("  ·", e)
    _log_skip("theta.history", s, " | ".join(errs))
    return []


def _cache_path(sym):
    safe = str(sym).upper().replace("^", "IDX_").replace("/", "_").replace("\\", "_")
    return os.path.join(PRICES_DIR, safe + ".json")


def _cache_load(sym, key=None):
    """→ (rows, src)。新格式 {src, rows};旧格式裸列表按 src=unknown 兼容读。"""
    try:
        doc = json.load(open(_cache_path(key or sym), encoding="utf-8"))
        if isinstance(doc, dict) and "rows" in doc:
            return (doc.get("rows") or []), str(doc.get("src") or "unknown")
        return (doc if isinstance(doc, list) else []), "unknown"
    except Exception:
        return [], ""


def _cache_fetched_ts(sym):
    """v3.29.2:缓存写入时刻(epoch);旧缓存无此键 → 0(视为盘外写入,按日期判新鲜)。"""
    try:
        doc = json.load(open(_cache_path(sym), encoding="utf-8"))
        return int(doc.get("fetched_ts") or 0) if isinstance(doc, dict) else 0
    except Exception:
        return 0


def _bar_is_partial(last_date, fetched_ts):
    """末根日期 = 写入当日 且 写入时刻在该日 16:05 ET 之前 → 这是盘中拉到的未收盘 bar。
    (戌 8-26 抓:INTU 8-25 行 O 对、H/L/C 不对、量像未走完——15:35 ET 财报班拉的部分 bar 当终盘存了一天)"""
    if not fetched_ts or not last_date:
        return False
    try:
        ft = datetime.datetime.fromtimestamp(int(fetched_ts), tz=_ET) if _ET else datetime.datetime.fromtimestamp(int(fetched_ts))
        if ft.date().isoformat() != last_date:
            return False
        return (ft.hour, ft.minute) < (16, 5)
    except Exception:
        return False


def _cache_save(sym, rows, src="fmp", proxy=None):
    """缓存带血统(v3.24.5 指数缓存污染根修):src 入盘;代理序列(指数走 ETF 代理)
    写独立键 SYM__proxy_XXX,读路径禁跨序列——8-17 案里 SPY 序列混进 ^GSPC 主键,
    FMP 恢复后缓存仍"新鲜"不刷新,chg_pct 跨序列算出 897% 级异常。"""
    key = ("%s__proxy_%s" % (sym, proxy)) if proxy else sym
    try:
        os.makedirs(PRICES_DIR, exist_ok=True)
        json.dump({"src": src, "rows": rows[-320:], "fetched_ts": int(now_et().timestamp())},
                  open(_cache_path(key), "w", encoding="utf-8"))
    except Exception as e:
        _log_skip("quote_layer.cache", sym, e)


def _fmp_history(sym):
    """FMP 日线历史 → 升序 [{date,o,h,l,c,v}]。经路由器(legacy/stable 自探定版);
    legacy 回 {historical:[...倒序]},stable 回裸列表——双形状都吃,统一排升序。"""
    try:
        data = _fmp_call_routed("history", sym, _fmp_history_url)
    except Exception as e:
        _log_skip("fmp.history", sym, e)
        return []
    hist = data.get("historical") if isinstance(data, dict) else data
    rows = []
    for h in (hist or []):
        try:
            rows.append({"date": str(h["date"])[:10],
                         "o": float(h["open"]), "h": float(h["high"]),
                         "l": float(h["low"]), "c": float(h["close"]),
                         "v": (float(h.get("volume") or 0) or None)})
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r["date"])
    return rows


_ALPACA_KEY_NAMES = ("ALPACA_KEY_ID", "ALPACA_API_KEY", "APCA_API_KEY_ID")
_ALPACA_SEC_NAMES = ("ALPACA_SECRET_KEY", "APCA_API_SECRET_KEY")
# 指数在 backup 侧只能走 ETF 代理(Alpaca 无指数/期货);触发即在 source 标注
_ALPACA_INDEX_PROXY = {"^GSPC": "SPY", "^IXIC": "QQQ", "^VIX": "VIXY"}


def _load_alpaca_keys():
    """优先进程环境;否则从本仓已有 .env 读(不打印值)。
    v3.16§⑦:统一接受 ALPACA_KEY_ID / ALPACA_SECRET_KEY(兼旧名 ALPACA_API_KEY)。"""
    key = sec = ""
    for n in _ALPACA_KEY_NAMES:
        key = os.getenv(n, "").strip()
        if key:
            break
    for n in _ALPACA_SEC_NAMES:
        sec = os.getenv(n, "").strip()
        if sec:
            break
    if key and sec:
        return key, sec
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, ".env"),
        os.path.join(here, "..", "aether_nexus", ".env"),
        os.path.join(here, "..", "alpha-platform", ".env"),
    ]
    found = {}
    want = set(_ALPACA_KEY_NAMES) | set(_ALPACA_SEC_NAMES)
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as f:
                for ln in f:
                    s = ln.strip()
                    if not s or s.startswith("#") or "=" not in s:
                        continue
                    k, _, v = s.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k in want and v and k not in found:
                        found[k] = v
        except OSError:
            continue
        if any(found.get(n) for n in _ALPACA_KEY_NAMES) and any(
            found.get(n) for n in _ALPACA_SEC_NAMES
        ):
            break
    for n in _ALPACA_KEY_NAMES:
        key = found.get(n, "") or key
        if key:
            break
    for n in _ALPACA_SEC_NAMES:
        sec = found.get(n, "") or sec
        if sec:
            break
    return key, sec


def alpaca_feed():
    """账户实况 feed 档(不预设;env ALPACA_DATA_FEED,默认 iex)。"""
    return (os.getenv("ALPACA_DATA_FEED") or "iex").strip() or "iex"


def feed_ah_label():
    """盘后口径标签——跟 feed 档走,守恒不猜。"""
    return "盘后·SIP 合并带" if alpaca_feed().lower() == "sip" else "盘后·IEX 口径"


def _alpaca_history(sym):
    """backup 腿:Alpaca 日线 OHLCV → (升序 rows, proxy)。指数走 ETF 代理并标注。"""
    key, sec = _load_alpaca_keys()
    s = str(sym).upper()
    proxy = None
    if s.startswith("^"):
        proxy = _ALPACA_INDEX_PROXY.get(s)
        if not proxy:
            return [], None
        s = proxy
    if not (key and sec) or not re.fullmatch(r"[A-Z]{1,5}", s or ""):
        return [], proxy
    start = (trading_date() - datetime.timedelta(days=430)).isoformat() + "T00:00:00Z"
    # 必须 sort=desc:asc+start+limit 会吃到最旧 N 根(与 alpha daily_bars 同坑)
    url = ("https://data.alpaca.markets/v2/stocks/%s/bars"
           "?timeframe=1Day&start=%s&limit=320&adjustment=raw&feed=%s&sort=desc"
           % (s, start, alpaca_feed()))
    req = urllib.request.Request(
        url, headers={**UA, "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        _log_skip("alpaca.history", s, e)
        return [], proxy
    rows = []
    for b in reversed(data.get("bars") or []):
        try:
            rows.append({"date": str(b["t"])[:10],
                         "o": float(b["o"]), "h": float(b["h"]),
                         "l": float(b["l"]), "c": float(b["c"]),
                         "v": (float(b.get("v") or 0) or None)})
        except (KeyError, TypeError, ValueError):
            continue
    return rows, proxy


def _alpaca_live(symbols):
    """backup 腿:Alpaca 批量 snapshot → {SYM: live_row}(FMP quote 缺席票用)。
    现场 0817 版 snapshot 端点收编;含盘后 latestTrade/latestQuote 字段。"""
    key, sec = _load_alpaca_keys()
    syms = [str(s).upper() for s in (symbols or []) if s]
    syms = [(_ALPACA_INDEX_PROXY.get(s, s), s) for s in syms]
    real = sorted({r for r, _ in syms if re.fullmatch(r"[A-Z]{1,5}", r)})
    if not (key and sec) or not real:
        return {}
    out = {}
    for i in range(0, len(real), 40):
        chunk = real[i:i + 40]
        url = ("https://data.alpaca.markets/v2/stocks/snapshots?symbols="
               + ",".join(chunk))
        req = urllib.request.Request(
            url, headers={**UA, "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
                data = json.loads(r.read().decode())
        except Exception as e:
            _log_skip("quote_layer.alpaca_live", ",".join(chunk[:3]), e)
            continue
        for rsym in chunk:
            snap = data.get(rsym) or {}
            bar = snap.get("dailyBar") or snap.get("prevDailyBar") or {}
            prev = snap.get("prevDailyBar") or {}
            try:
                row = {"date": str(bar.get("t") or "")[:10],
                       "o": float(bar["o"]), "h": float(bar["h"]),
                       "l": float(bar["l"]), "c": float(bar["c"]),
                       "v": (float(bar.get("v") or 0) or None),
                       "prev_close_live": (float(prev["c"]) if prev.get("c") is not None else None),
                       "_src": "alpaca"}
            except (KeyError, TypeError, ValueError):
                continue
            for want, orig in syms:
                if want == rsym:
                    out[orig] = dict(row, _proxy=(rsym if orig != rsym else None))
    return out


def _fmp_quote(symbols):
    """FMP quote → {SYM: 行}。按符号类路由(stock/index/commodity 各自定版端点):
    stock 类定版 legacy 时保留批量;其余单票走路由;类级探路全败一次响亮,
    同类其余票不再连环(V6 案:指数/商品 402 连环刷 skips 的根修)。"""
    global _FMP_BATCH_OK
    out = {}
    syms = [str(s).upper() for s in (symbols or []) if s]
    if not syms or not _fmp_key():
        return out

    def eat(data):
        for r in (data if isinstance(data, list) else [data]):
            if isinstance(r, dict):
                s = str(r.get("symbol") or "").upper()
                if s:
                    out[s] = r

    by_cls = {}
    for s in syms:
        by_cls.setdefault(_fmp_class(s), []).append(s)
    st = by_cls.pop("stock", [])
    if st:
        fam = _fmp_route_load().get("quote:stock")
        if fam in (None, "legacy") and _FMP_BATCH_OK and len(st) > 1:
            try:
                for i in range(0, len(st), 50):
                    eat(json.loads(_fmp_get("/quote/" + urllib.parse.quote(",".join(st[i:i + 50]), safe=","))))
                if _fmp_route_load().get("quote:stock") != "legacy":
                    _FMP_ROUTE["quote:stock"] = "legacy"
                    _fmp_route_save()
                st = []
            except Exception as e:
                _FMP_BATCH_OK = False
                msg = _http_err_text(e) if isinstance(e, urllib.error.HTTPError) else str(e)
                _log_skip("fmp.quote_batch", ",".join(syms[:3]), "批量被拒,退单票: %s" % msg)
        for s in st:
            try:
                eat(_fmp_call_routed("quote", s, _fmp_quote_url))
            except RuntimeError as e:
                _log_skip("fmp.quote", s, e)
                if "本班停用" in str(e) and "全候选失败" not in str(e):
                    break
            except Exception as e:
                _log_skip("fmp.quote", s, e)
    for cls, group in by_cls.items():
        for s in group:
            try:
                eat(_fmp_call_routed("quote", s, _fmp_quote_url))
            except RuntimeError as e:
                _log_skip("fmp.quote", s, e)
                if "本班停用" in str(e) and "全候选失败" not in str(e):
                    break
            except Exception as e:
                _log_skip("fmp.quote", s, e)
    return out


def _live_row_from_fmp(q):
    """FMP quote 行 → 今日 bar(缺 O/H/L 用现价补,如实反映盘初形态未成)。"""
    try:
        c = float(q.get("price"))
    except (TypeError, ValueError):
        return None
    def f(k):
        try:
            v = float(q.get(k))
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None
    ts = q.get("timestamp")
    day = ""
    try:
        dt = datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc)
        day = (dt.astimezone(_ET).date() if _ET else dt.date()).isoformat()
    except (TypeError, ValueError, OSError):
        day = trading_date().isoformat()
    return {"date": day, "o": f("open") or c, "h": f("dayHigh") or c,
            "l": f("dayLow") or c, "c": c,
            "v": f("volume"), "prev_close_live": f("previousClose"), "_src": "fmp",
            "mcap": f("marketCap")}   # v3.26:市值随行(legacy/stable /quote 均有该字段)


def _merge_live(rows, live):
    if not live:
        return rows
    if rows and rows[-1]["date"] == live["date"]:
        return rows[:-1] + [live]
    if not rows or live["date"] > rows[-1]["date"]:
        return rows + [live]
    return rows


def now_et():
    """ET 当前时刻(与 trading_date 同一时钟源;测试可覆盖)。"""
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-4)))


def _history(sym, need_date=None):
    """历史日线唯一入口:缓存(新鲜且主源血统)→ FMP → Theta(仅 stock 类)→
    Alpaca backup(代理序列独立键)→ 代理/陈旧缓存(响亮)→ []。
    backup 血统的新鲜缓存每班先试一次主源升级(新鲜度按来源分级)。"""
    cls = _fmp_class(sym)
    rows, src_ = _cache_load(sym)
    need = need_date or prev_trading_day(trading_date()).isoformat()
    fresh = bool(rows) and rows[-1].get("date", "") >= need
    # v3.29.2:盘中拉到的当日部分 bar 不算终盘——收盘后(≥16:05 ET)必须重拉一次;盘中每 PARTIAL_REFRESH_S(默认 1800)重拉
    if fresh:
        fts = _cache_fetched_ts(sym)
        if _bar_is_partial(rows[-1].get("date"), fts):
            ne = now_et()
            same_day = ne.date().isoformat() == rows[-1].get("date")
            if not same_day or (ne.hour, ne.minute) >= (16, 5) or (int(ne.timestamp()) - fts) >= int(os.getenv("PARTIAL_REFRESH_S", "1800")):
                fresh = False
    backup_blood = src_.startswith(("alpaca", "theta"))
    if fresh and not (backup_blood and _fmp_key() and sym not in _FMP_UPGRADE_TRIED):
        return rows, "cache"
    if _fmp_key():
        _FMP_UPGRADE_TRIED.add(sym)
        fresh_rows = _fmp_history(sym)
        if fresh_rows:
            _cache_save(sym, fresh_rows, "fmp")
            return fresh_rows, "fmp"
        if fresh:
            return rows, "cache"
    if cls == "stock":
        th = _theta_history(sym)
        if th:
            _cache_save(sym, th, "theta")
            return th, "theta"
    if cls != "commodity":   # Alpaca 无商品
        ab, proxy = _alpaca_history(sym)
        if ab:
            _cache_save(sym, ab, "alpaca", proxy=proxy)
            if proxy:
                return ab, "alpaca:%s" % proxy
            return ab, "alpaca"
    if rows:
        print("[fetchers] %s 全源失败,退陈旧缓存(至 %s,血统 %s)" % (sym, rows[-1].get("date"), src_ or "unknown"))
        return rows, "cache-stale:%s" % (src_ or "unknown")
    if cls == "index":
        proxy = _ALPACA_INDEX_PROXY.get(sym)
        if proxy:
            prows, _psrc = _cache_load(sym, key="%s__proxy_%s" % (sym, proxy))
            if prows:
                print("[fetchers] %s 全源失败,退 %s 代理缓存(独立键,如实标注)" % (sym, proxy))
                return prows, "cache-proxy:%s" % proxy
    return [], "none"


def _rsi14(closes):
    """Wilder RSI14(确定性;<15 根返回 None)。时机过滤器,非方向信号。v3.8。"""
    if len(closes) < 15:
        return None
    gains = losses = 0.0
    for i in range(1, 15):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    ag, al = gains / 14, losses / 14
    for i in range(15, len(closes)):
        ch = closes[i] - closes[i - 1]
        ag = (ag * 13 + max(ch, 0.0)) / 14
        al = (al * 13 + max(-ch, 0.0)) / 14
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)


def _tape_from_ohlc(o, h, l, c, pc):
    close_loc = round((c - l) / (h - l), 2) if h > l else None
    chg_pct = round((c / pc - 1) * 100, 2) if pc else None
    tape = ""
    if pc is not None and close_loc is not None:
        tape = ("冲高回落" if (h > pc and close_loc < 0.4)
                else ("强势收高" if close_loc > 0.8 and c > pc else ""))
    return close_loc, chg_pct, tape


def _derive(name, rows, source_label):
    """升序日线 → 引擎全字段读数(v3.19-3.22 全员:Alpaca 过渡层曾静默丢
    vol_x20/on20/in20/_rets20,此处整族复活;公式与 v3.23 引擎逐字一致)。"""
    if len(rows) < 2:
        return None
    opens = [r["o"] for r in rows]
    closes = [r["c"] for r in rows]
    vols = [r.get("v") for r in rows]
    last, prev = rows[-1], rows[-2]
    o, h, l, c = last["o"], last["h"], last["l"], last["c"]
    pc = prev["c"]
    close_loc, chg_pct, tape = _tape_from_ohlc(o, h, l, c, pc)
    day = last.get("date") or ""
    d = {"name": name, "ticker": name, "date": day, "Date": day,
         "open": o, "high": h, "low": l, "close": c, "Close": str(round(c, 4)),
         "chg_pct": chg_pct,
         "chg5_pct": round((c / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else None,
         "mom20_pct": round((c / closes[-21] - 1) * 100, 2) if len(closes) >= 21 else None,
         "high52_dist_pct": round((c / max(closes) - 1) * 100, 2) if closes else None,
         "rsi14": _rsi14(closes),
         # ④隔夜/日内 20 日分解:T+0 纯日内结构必须直面的读数
         "on20_pct": (round(sum(opens[i] / closes[i - 1] - 1
                                for i in range(len(closes) - 20, len(closes))) * 100, 2)
                      if len(closes) >= 21 else None),
         "in20_pct": (round(sum(closes[i] / opens[i] - 1
                                for i in range(len(closes) - 20, len(closes))) * 100, 2)
                      if len(closes) >= 21 else None),
         # ①量比:末根量 / 前20日均量(放量的实测定义)
         "vol_x20": (round(vols[-1] / (sum(v for v in vols[-21:-1] if v) /
                                       max(1, len([v for v in vols[-21:-1] if v]))), 2)
                     if vols and vols[-1] and any(vols[-21:-1]) else None),
         # ②相关性收敛的原料:末20日收益序列(引擎内用;prompt 侧由 _slim_raw 剥除)
         "_rets20": ([round(closes[i] / closes[i - 1] - 1, 4)
                      for i in range(len(closes) - 20, len(closes))]
                     if len(closes) >= 21 else None),
         # v3.26 质量地板实测基:价格=末根收盘;20 日平均成交额=前 20 根 close×volume 均值
         # (末根为当日/盘中未收盘 bar,不计;样本 <5 根 = 无实测,None 不装数);市值随 live 行
         "price": c,
         "last_bar_date": rows[-1].get("date"),   # v3.28.2:末根日期(趋势榜覆盖率自证用)
         "dist_high20_pct": (round((c / max(r["h"] for r in rows[-20:]) - 1) * 100, 2) if len(rows) >= 5 and max(r["h"] for r in rows[-20:]) else None),   # v3.29 F2
         # v3.28 趋势读数:最近 5 根中收涨根数(对前一根)、10 日涨幅
         "up5": sum(1 for i in range(max(1, len(rows) - 5), len(rows)) if rows[i]["c"] > rows[i - 1]["c"]) if len(rows) >= 2 else None,
         "chg10_pct": (round((c / rows[-11]["c"] - 1) * 100, 2) if len(rows) >= 11 and rows[-11]["c"] else None),
         "adv20_usd": (round(sum(r["c"] * r["v"] for r in rows[-21:-1] if r.get("v") and r.get("c"))
                             / len([r for r in rows[-21:-1] if r.get("v") and r.get("c")]))
                       if len([r for r in rows[-21:-1] if r.get("v") and r.get("c")]) >= 5 else None),
         "adv20_days": len([r for r in rows[-21:-1] if r.get("v") and r.get("c")]),
         "mcap_b": (round(last["mcap"] / 1e9, 2) if last.get("mcap") else None),
         "close_loc": close_loc, "source": source_label,
         "feed": alpaca_feed(), "feed_label": feed_ah_label()}
    d["tape_flag"] = tape or ""
    if ":" in (source_label or ""):
        d["proxy"] = source_label.split(":", 1)[1]
    return d


def quote_layer_snapshot(symbols, *, with_rsi=True):
    """快照缝 v3.24:FMP 批量 quote + 缓存历史 → 全字段读数;
    FMP 缺席票逐票落 Alpaca backup;双失败响亮入 skip,不装数。
    with_rsi=False:跳过历史(全宇宙扫描防拖死),仅出 quote 核心字段。
    换更好的数据 API 只换本函数与 _history 内脏——爬虫/引擎/渲染零改动。"""
    syms = [str(s).upper() for s in (symbols or []) if s]
    out = {}
    todo = [s for s in syms if s not in _QUOTE_MEMO]
    quotes = _fmp_quote(todo)
    missing_live = [s for s in todo if s not in quotes]
    alp_live = _alpaca_live(missing_live) if missing_live else {}
    for sym in syms:
        if sym in _QUOTE_MEMO:
            out[sym] = dict(_QUOTE_MEMO[sym])
            continue
        live = None
        src = "fmp"
        if sym in quotes:
            live = _live_row_from_fmp(quotes[sym])
        if live is None and sym in alp_live:
            live = alp_live[sym]
            src = "alpaca:%s" % live["_proxy"] if live.get("_proxy") else "alpaca"
        rows, hist_src = _history(sym) if with_rsi else ([], "quote-only")
        rows = _merge_live(list(rows), live)
        if len(rows) < 2 and live and live.get("prev_close_live"):
            pcl = live["prev_close_live"]
            rows = [{"date": "", "o": pcl, "h": pcl, "l": pcl, "c": pcl, "v": None}, live]
        label = src if live is not None else hist_src
        d = _derive(sym, rows, label)
        if d is None:
            _log_skip("quote_layer", sym, "FMP+Alpaca 双失败,无缓存")
            continue
        _QUOTE_MEMO[sym] = dict(d)
        out[sym] = d
    return out


def history_snapshot(symbols, need_date=None):
    """v3.28:只用缓存/历史日线出读数(不打 quote、不进 _QUOTE_MEMO)——全宇宙趋势扫描用,
    末根=最近一根已收盘日线;need_date=缓存最新 bar 须 ≥ 此日期否则重拉(晚班要当日终盘)。"""
    out = {}
    for sym in [str(s).upper() for s in (symbols or []) if s]:
        rows, hist_src = _history(sym, need_date=need_date)
        d = _derive(sym, list(rows), hist_src)
        if d is None:
            continue
        out[sym] = d
    return out


def fetch_screener_universe(cache_path=None, ttl_s=20 * 3600):
    """v3.28(BMNR 案:FMP 涨幅榜按单日 % 排、最活跃榜按股数排,连涨一周 +35% 的 $1B/日大票两榜都进不了):
    全市场普通股宇宙,FMP stable /company-screener 一次调用(她档位 8-25 实测 200 键齐),日缓存。
    定义:非 ETF/基金、在交易、NYSE/NASDAQ/AMEX、price≥POOL_PRICE_FLOOR、当日 price×volume≥5e7(粗地板,
    精地板 adv20≥POOL_ADV_FLOOR_USD 在快照后算)。返回 [symbol],失败返 [] 并入 skip(不装数)。"""
    cache_path = cache_path or os.path.join(os.path.dirname(PRICES_DIR), "state", "universe_screener.json")
    try:
        doc = json.load(open(cache_path, encoding="utf-8"))
        if time.time() - float(doc.get("ts", 0)) < ttl_s and doc.get("symbols"):
            return list(doc["symbols"])
    except Exception:
        pass
    key = _fmp_key()
    if not key:
        _log_skip("screener_universe", "-", "无 FMP key")
        return []
    pf = pool_price_floor()
    q = {"limit": 10000, "isEtf": "false", "isFund": "false", "isActivelyTrading": "true",
         "priceMoreThan": int(pf), "exchange": "NYSE,NASDAQ,AMEX", "apikey": key}
    url = _FMP_STABLE_BASE + "/company-screener?" + urllib.parse.urlencode(q)
    try:
        _fmp_tick()
        rows = json.loads(_get(url))
    except Exception as e:
        _log_skip("screener_universe", "-", "screener 失败:%s" % str(e)[:120])
        return []
    if not isinstance(rows, list) or len(rows) < 500:
        _log_skip("screener_universe", "-", "screener 回包异常/截断 n=%s" % (len(rows) if isinstance(rows, list) else "?"))
        return []
    syms, seen, vol0 = [], set(), 0
    for r in rows:
        try:
            sym = str(r.get("symbol") or "").upper()
            if not re.fullmatch(r"[A-Z]{1,5}", sym) or sym in seen:
                continue
            if r.get("isEtf") or r.get("isFund") or r.get("isActivelyTrading") is False:
                continue
            if str(r.get("exchangeShortName") or "").upper() not in ("NYSE", "NASDAQ", "AMEX"):
                continue
            px, vol = float(r.get("price") or 0), float(r.get("volume") or 0)
            if px < pf:
                continue
            # v3.28.1(戌 8-25 现场抓:screener 回 BMNR volume=0,粗筛 price×volume 把它误杀——这版就是为它建的):
            # volume 为 0/缺 = 该字段不可信,放行,交给 history_snapshot 的 adv20 精地板(那才是实测)
            if vol > 0 and px * vol < 5e7:
                continue
            if vol <= 0:
                vol0 += 1
            seen.add(sym); syms.append(sym)
        except Exception:
            continue
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        json.dump({"ts": time.time(), "n": len(syms), "raw_n": len(rows), "volume0_passed": vol0, "symbols": syms},
                  open(cache_path, "w", encoding="utf-8"))
        print("[fetchers] screener 宇宙 %d/%d(volume=0 放行 %d 票,由 adv20 精地板定)" % (len(syms), len(rows), vol0))
    except Exception:
        pass
    return syms


def quote_layer_bars(symbol, limit=260):
    """个股日线收盘缝(FMP 主源→Alpaca backup,经缓存)。换 API 只改 _history 内脏。"""
    rows, _src = _history(str(symbol or "").upper())
    return [r["c"] for r in rows][-max(int(limit or 260), 15):]


class quote_layer:
    """v3.16§⑦ 换源唯一缝:snapshot(syms) / bars(sym)。v3.24 内脏 = FMP 主 + Alpaca backup。"""
    snapshot = staticmethod(quote_layer_snapshot)
    bars = staticmethod(quote_layer_bars)


def alpaca_snapshots(symbols):
    """兼容旧名 → quote_layer.snapshot(v3.16§⑦ 缝;内脏已换 FMP 主源)。"""
    return quote_layer.snapshot(symbols)


def alpaca_daily_closes(symbols, limit=260):
    """兼容旧名 → quote_layer.bars 批量。"""
    out = {}
    for sym in [str(s).upper() for s in (symbols or []) if s]:
        seq = quote_layer.bars(sym, limit=limit)
        if len(seq) >= 15:
            out[sym] = seq
        elif seq:
            _log_skip("quote_layer.bars", sym, "closes=%d(<15, RSI null)" % len(seq))
    return out


def data_plane_banner():
    """启动横幅:当班数据源实况。stooq 已移除,不回退。"""
    ak, asec = _load_alpaca_keys()
    alp = "在位" if (ak and asec) else "未配置"
    if _fmp_key():
        return ("FMP 主源(预算 %d/日,当日已用 %d)· Theta 第二源=%s · Alpaca backup=%s · %s · stooq 已移除"
                % (int(os.getenv("FMP_DAILY_BUDGET", "250")), fmp_calls_today(), "在线" if _theta_up() else "未起(跳过)", alp, feed_ah_label()))
    if ak and asec:
        return "⚠ FMP_API_KEY 未配置——本班全线退 Alpaca backup(指数=ETF 代理);请补 .env"
    return "⚠ FMP 与 Alpaca 均未配置——tape 全线无主路径(stooq 已移除,不回退)"


# ---- 符号映射(引擎 _stooq_daily 兼容缝 + 指数真符号回岗) ----
_INDEX_MAP = {"^spx": "^GSPC", "^ndq": "^IXIC", "^vix": "^VIX", "rsp.us": "RSP",
              "hyg.us": "HYG", "lqd.us": "LQD"}


def _sym_map(sym, name=""):
    """stooq 形符号 → quote_layer 符号。pltr.us→PLTR;指数→FMP 真指数符号。"""
    s = (sym or "").strip().lower()
    if s in _INDEX_MAP:
        return _INDEX_MAP[s]
    if s.endswith(".us"):
        return s[:-3].upper()
    if s.startswith("^"):
        return s.upper()
    if re.fullmatch(r"[A-Za-z]{1,5}", s or ""):
        return s.upper()
    n = (name or "").strip().upper()
    if re.fullmatch(r"[A-Z]{1,5}", n):
        return n
    return None


def _stooq_daily(sym, name, skip_src):
    """兼容缝:引擎原 stooq 日线调用 → quote_layer(FMP 主源)。字段对齐引擎全员。"""
    ticker = _sym_map(sym, name)
    if not ticker:
        _log_skip(skip_src, sym or name, "no ticker map")
        return None
    snaps = quote_layer_snapshot([ticker], with_rsi=True)
    it = snaps.get(ticker)
    if not it:
        _log_skip(skip_src, ticker, "quote_layer miss(FMP+Alpaca)")
        return None
    d = dict(it)
    d["name"] = name or ticker
    return d


# ============================================================================
# 十二爬虫(tape 走 quote_layer;事件/日历/盘后/流动性 = Nasdaq/官方零 key 端点不动)
# ============================================================================

def fetch_treasury_yields():
    """财政部日收益率曲线(官方,无 key)。"""
    def go():
        y = datetime.date.today().year
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
               f"daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve&_format=csv")
        rows = _get(url).strip().splitlines()
        head = rows[0].split(","); last = rows[1].split(",")
        return [{"field": h, "value": v} for h, v in zip(head, last)]
    return _wrap("treasury_yields", go)


def _fred_via_api(key: str) -> list:
    out = []
    for sid in ("UNRATE", "FEDFUNDS", "CPIAUCSL"):
        u = ("https://api.stlouisfed.org/fred/series/observations?series_id=%s"
             "&api_key=%s&file_type=json&sort_order=desc&limit=2" % (sid, key))
        obs = json.loads(_get(u))["observations"]
        out.append({"series": sid, "latest": obs[0], "prev": obs[1] if len(obs) > 1 else None,
                    "via": "fred_api"})
    return out


def _macro_via_bls_nyfed() -> list:
    """零 key 回退:BLS 失业率/CPI + NY Fed EFFR/SOFR(利率代理,非 FRED FEDFUNDS 本体)。"""
    out = []
    body = json.dumps({
        "seriesid": ["LNS14000000", "CUSR0000SA0"],
        "startyear": str(datetime.date.today().year - 1),
        "endyear": str(datetime.date.today().year),
    }).encode()
    req = urllib.request.Request(
        "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        data=body,
        headers={**UA, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
        payload = json.loads(r.read().decode("utf-8", "replace"))
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError("BLS status=%s" % payload.get("status"))
    alias = {"LNS14000000": "UNRATE", "CUSR0000SA0": "CPIAUCSL"}
    for s in (payload.get("Results") or {}).get("series") or []:
        sid = alias.get(s.get("seriesID"), s.get("seriesID"))
        rows = s.get("data") or []
        if not rows:
            _log_skip("fred_macro", sid, "BLS empty"); continue
        latest, prev = rows[0], (rows[1] if len(rows) > 1 else None)
        out.append({
            "series": sid,
            "latest": {"date": "%s-%s" % (latest.get("year"), latest.get("period")),
                       "value": latest.get("value"), "periodName": latest.get("periodName")},
            "prev": ({"date": "%s-%s" % (prev.get("year"), prev.get("period")),
                      "value": prev.get("value")} if prev else None),
            "via": "bls_public",
        })
    # 利率:NY Fed EFFR(优先) / SOFR
    try:
        j = json.loads(_get("https://markets.newyorkfed.org/api/rates/all/latest.json",
                            headers={"Accept": "application/json"}))
        rates = j.get("refRates") or []
        effr = next((x for x in rates if x.get("type") == "EFFR"), None)
        sofr = next((x for x in rates if x.get("type") == "SOFR"), None)
        pick = effr or sofr
        if pick and pick.get("percentRate") is not None:
            out.append({
                "series": "FEDFUNDS" if effr else "SOFR",
                "latest": {"date": pick.get("effectiveDate"),
                           "value": str(pick.get("percentRate"))},
                "prev": None,
                "via": "nyfed",
                "note": "EFFR/SOFR 代理联邦基金读数(非 FRED FEDFUNDS 月频系列)",
            })
        else:
            _log_skip("fred_macro", "EFFR/SOFR", "nyfed missing percentRate")
    except Exception as e:
        _log_skip("fred_macro", "nyfed", e)
    if not out:
        raise RuntimeError("BLS/NYFed macro empty")
    return out


def fetch_fred():
    """宏观三件套:优先 FRED API key;缺 key 或失败 → BLS+NY Fed 零 key 回退。"""
    key = os.getenv("FRED_API_KEY", "").strip()
    def go():
        if key:
            try:
                return _fred_via_api(key)
            except Exception as e:
                _log_skip("fred_macro", "fred_api", e)
        return _macro_via_bls_nyfed()
    return _wrap("fred_macro", go)


def fetch_edgar_recent():
    """EDGAR 全文检索:近两日 8-K/425(并购信号高发表格)。官方,需 UA。
    检索窗随交易日锚定(时间语义家族收尾:UTC 机器晚班不漂"明天")。"""
    def go():
        base = trading_date()
        frm = (base - datetime.timedelta(days=2)).isoformat()
        u = ("https://efts.sec.gov/LATEST/search-index?q=%22merger%20agreement%22&forms=8-K"
             f"&startdt={frm}&enddt={base.isoformat()}")
        try:
            data = json.loads(_get(u))
        except Exception as e:
            _log_skip("edgar_ma_8k", "api", e)
            return []
        hits = data.get("hits", {}).get("hits", [])
        out = []
        for h in hits:
            src = h.get("_source", {})
            names = src.get("display_names") or ["?"]
            out.append({
                "company": names[0],
                "form": src.get("file_type"),
                "filed": src.get("file_date")
            })
        return out
    return _wrap("edgar_ma_8k", go)


def fetch_fda_press():
    """FDA 新闻 RSS(批准/announce 高发)。官方,无 key。"""
    def go():
        xml = _get("https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml")
        items = []
        for chunk in xml.split("<item>")[1:]:
            t = chunk.split("<title>")[1].split("</title>")[0] if "<title>" in chunk else "?"
            d = chunk.split("<pubDate>")[1].split("</pubDate>")[0] if "<pubDate>" in chunk else ""
            items.append({"title": t.strip()[:200], "date": d.strip()})
        return items
    return _wrap("fda_press", go)


def fetch_commodities():
    """油/金:FMP 商品端点主源(CLUSD≈WTI 期货连续 / GCUSD≈COMEX 金)——真商品回岗;
    免费档若拒符号 → USO/GLD ETF 代理并在 note/proxy 明标(不装现货)。stooq 已移除。"""
    def go():
        plan = (("WTI", "CLUSD", "USO", "USO ETF proxy for WTI crude env — not CL futures"),
                ("GOLD", "GCUSD", "GLD", "GLD ETF proxy for gold env — not XAU spot"))
        out = []
        for name, fsym, psym, pnote in plan:
            snaps = quote_layer_snapshot([fsym]) if _fmp_key() else {}
            it = snaps.get(fsym)
            if it and it.get("chg_pct") is not None:
                d = dict(it); d["name"] = name; d["proxy"] = fsym
                out.append(d)
                continue
            snaps = quote_layer_snapshot([psym])
            it = snaps.get(psym)
            if it:
                d = dict(it); d["name"] = name; d["proxy"] = psym; d["note"] = pnote
                out.append(d)
            else:
                _log_skip("commodities", fsym, "FMP 商品+ETF 代理双失败")
        return out
    return _wrap("commodities", go)


_INDEX_PLAN = (("SP500", "^GSPC"), ("NASDAQ", "^IXIC"), ("VIX", "^VIX"),
               ("RSP", "RSP"), ("HYG", "HYG"), ("LQD", "LQD"))


def fetch_indices():
    """爬虫#3:真指数(FMP ^GSPC/^IXIC/^VIX)+ RSP 广度 + HYG/LQD 信用金丝雀。
    链=quote_layer(FMP 主/Theta/Alpaca backup),Yahoo 兜底已摘除(Lyra 2026-08-17:
    质量差不用,FMP 付费档全接)。三大指数缺任一=响亮 skip+横幅降级,不找替身。"""
    def go():
        snaps = quote_layer_snapshot([sym for _, sym in _INDEX_PLAN])
        out = []
        for name, sym in _INDEX_PLAN:
            it = snaps.get(sym)
            if it:
                d = dict(it); d["name"] = name
                out.append(d)
            else:
                _log_skip("indices", sym, "quote_layer miss(Yahoo 已摘除,无兜底)")
        have = {x["name"] for x in out}
        missing = [n for n in ("SP500", "NASDAQ", "VIX") if n not in have]
        if missing:
            print("[fetchers] ⚠ 指数缺口 %s——FMP/Alpaca 双失,本班降级如实呈现" % ",".join(missing))
        return out
    return _wrap("indices", go)


# v3.6 累加:对冲腿 + 资金迁徙目的地(cls=hedge|rotation)
_HEDGE_PLAN = (
    ("GLD", "hedge"), ("SLV", "hedge"), ("OXY", "hedge"), ("USO", "hedge"),
    ("TLT", "hedge"), ("UUP", "hedge"),
    ("FXI", "rotation"), ("KWEB", "rotation"), ("EWZ", "rotation"),
    ("EWJ", "rotation"), ("EEM", "rotation"), ("BABA", "rotation"),
)


def fetch_hedge_assets():
    """爬虫#8:对冲+迁徙资产——quote_layer 唯一路径(FMP 主/Alpaca backup)。"""
    def go():
        snaps = quote_layer_snapshot([s for s, _ in _HEDGE_PLAN])
        out = []
        for sym, cls in _HEDGE_PLAN:
            it = snaps.get(sym)
            if not it:
                _log_skip("hedge_assets", sym, "quote_layer miss")
                continue
            d = dict(it); d["name"] = sym; d["cls"] = cls
            out.append(d)
        if len(out) < 4:
            _log_skip("hedge_assets", "plan", "legs<%d(FMP+Alpaca 双弱)" % len(out))
        return out
    return _wrap("hedge_assets", go)


def fetch_sectors():
    """爬虫#12:板块 tape(SPDR 11 + SMH)——quote_layer(FMP 主/Alpaca backup)。"""
    def go():
        plan = [("XLK", "XLK科技"), ("XLC", "XLC通信"), ("XLY", "XLY可选消费"),
                ("XLP", "XLP必选消费"), ("XLE", "XLE能源"), ("XLF", "XLF金融"),
                ("XLV", "XLV医疗"), ("XLI", "XLI工业"), ("XLB", "XLB材料"),
                ("XLRE", "XLRE地产"), ("XLU", "XLU公用"), ("SMH", "SMH半导体")]
        snaps = quote_layer_snapshot([p[0] for p in plan])
        out = []
        for sym, name in plan:
            it = snaps.get(sym)
            if it:
                d = dict(it); d["name"] = name
                out.append(d)
            else:
                _log_skip("sectors", sym, "quote_layer miss")
        return out
    return _wrap("sectors", go)


def fetch_fear_greed():
    """爬虫#9:CNN Fear & Greed(公开 dataviz 端点,零 key)——
    贪婪极值 + 指数冲高回落 = 拉高出货语境的情绪腿;端点若变响亮入 skip。"""
    def go():
        try:
            data = json.loads(_get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                                   {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                                    "Accept": "application/json",
                                    "Referer": "https://www.cnn.com/markets/fear-and-greed"}))   # v3.25:418 反爬对策,失败仍响亮入 skip
        except Exception as e:
            _log_skip("fear_greed", "graphdata", e)
            return []
        fg = data.get("fear_and_greed") or {}
        if not fg:
            _log_skip("fear_greed", "graphdata", "empty fear_and_greed")
            return []
        score = fg.get("score")
        if isinstance(score, str):
            try:
                score = float(score)
            except ValueError:
                score = None
        return [{"score": score, "rating": fg.get("rating"),
                 "prev_close": fg.get("previous_close"),
                 "prev_1w": fg.get("previous_1_week"), "prev_1m": fg.get("previous_1_month")}]
    return _wrap("fear_greed", go)


def fetch_earnings_calendar():
    """爬虫#10:Nasdaq 财报日历——上一交易日+今起5日。
    热日(昨+今)不设 15/80 cap——DOCS(~$4B,+68% AH)等中盘暴动否则被掐(patch 判例);
    未来日维持 15;源级 wrap 1200(≥800 门禁)以免热日全量再被吞。
    integrated v1:seen_days 防重复日。"""
    def go():
        out = []
        base = trading_date()
        days = [prev_trading_day(base)] + [base + datetime.timedelta(days=k) for k in range(5)]
        # 热日解封:movers/amc_tonight 原料日;巨头扎堆日中盘暴动段必须可见
        hot = {days[0], base}
        seen_days = set()
        for day_d in days:
            day = day_d.isoformat()
            if day in seen_days:
                continue
            seen_days.add(day)
            try:
                raw = json.loads(_get(
                    "https://api.nasdaq.com/api/calendar/earnings?date=" + day,
                    {"Accept": "application/json"},
                ))
                rows = (((raw or {}).get("data") or {}).get("rows")) or []
                def cap(r):
                    ds = "".join(ch for ch in (r.get("marketCap") or "") if ch.isdigit())
                    return int(ds) if ds else 0
                rows = sorted(rows, key=cap, reverse=True)
                if day_d not in hot:
                    rows = rows[:15]
                for r in rows:
                    out.append({
                        "symbol": r.get("symbol"),
                        "name": (r.get("name") or "")[:40],
                        "date": day,
                        "when": r.get("time"),
                        "marketCap": r.get("marketCap"),
                    })
            except Exception as e:
                _log_skip("earnings_calendar", day, e)
        return out
    return _wrap("earnings_calendar", go)


def _parse_money(txt):
    t = (txt or "").replace(",", "").replace("$", "").strip()
    if not t:
        return None
    mult = 1.0
    if t[-1:].upper() in ("T", "B", "M", "K"):
        mult = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}[t[-1].upper()]
        t = t[:-1]
    try:
        val = float(t) * mult
        if val != val:  # NaN check
            return None
        return val
    except ValueError:
        return None


def fetch_afterhours(symbols):
    """按需(晚班):Nasdaq quote info 盘后/延时报价(零 key,流动性闸同源)——
    为 amc_tonight 名单取实测盘后涨跌,打掉"stooq 无盘后"的旧边界(DOCS +68% 案例)。
    secondaryData 缺失 = 无盘后读数,如实置 None,不编。
    仅晚班调用;盘中调用时 secondary 非盘后价,ah_chg_pct 语义不成立。"""
    def go():
        out = []
        for sym in symbols:
            got = None
            try:
                raw = json.loads(_get("https://api.nasdaq.com/api/quote/%s/info?assetclass=stocks" % sym,
                                      {"Accept": "application/json"}))
                d = (raw or {}).get("data") or {}
                pri = d.get("primaryData") or {}
                sec = d.get("secondaryData") or {}
                p = _parse_money(pri.get("lastSalePrice"))
                x = _parse_money(sec.get("lastSalePrice"))
                # v3.25.4(8-20 BULL 反向读数案,戌抓获 v3.25.3 宣言未落地):
                # 盘后涨跌优先直取端点自算 secondaryData.percentageChange——不再跨
                # primary/secondary 两字段自己拼公式(深夜字段语义疑翻转,自拼即反向);
                # 端点缺该字段才回落自算兜底。双时戳+原始两价全落盘=语义定案材料。
                ahp = None
                pc = str(sec.get("percentageChange") or "").strip()
                if pc and pc not in ("--", "N/A"):
                    try:
                        ahp = round(float(pc.replace("%", "").replace("+", "")), 2)
                        if "-" in pc and ahp > 0:
                            ahp = -ahp
                    except ValueError:
                        ahp = None
                comp = round((x / p - 1) * 100, 2) if (x and p) else None
                conflict = (ahp is not None and comp is not None
                            and ((ahp > 0) != (comp > 0) or abs(ahp - comp) > 3))
                if conflict:
                    # 双算冲突绊线(8-20 BULL 案机械化):端点自算与本地自算方向相反或
                    # 差>3pp = 字段语义不可信,读数不采信不发布,两值+双时戳全录响亮。
                    _log_skip("afterhours", sym,
                              "盘后读数双算冲突不采信 endpoint=%+.2f%% computed=%+.2f%% (close_asof=%s ah_asof=%s)"
                              % (ahp, comp, pri.get("lastTradeTimestamp"), sec.get("lastTradeTimestamp")))
                    ahp = None
                if ahp is None and comp is not None and not conflict:
                    ahp = comp   # 兜底自算(端点缺字段且无冲突证据时)
                if p:
                    got = {"symbol": sym, "close": p, "ah_last": x, "ah_chg_pct": ahp,
                           "ah_conflict": bool(conflict),
                           "ah_pct_src": ("endpoint" if pc and pc not in ("--", "N/A") else "computed"),
                           "close_asof": pri.get("lastTradeTimestamp"),
                           "asof": sec.get("lastTradeTimestamp")}
            except Exception as e:
                _log_skip("afterhours", sym, e)
                continue
            if got:
                out.append(got)
            else:
                _log_skip("afterhours", sym, "no secondaryData/price fields")
        return out
    return _wrap("afterhours", go)


def fetch_ticker_liquidity(symbols):
    """爬虫#11(按需,Lyra 批 2026-08-06):Nasdaq summary 端点查市值/日均量——
    流动性闸的牙。候选出现才查,不进夜间轮询;股票查不到回退 ETF assetclass;
    仍查不到 = None(不装数),失败响亮入 skip。"""
    def go():
        out = []
        for sym in symbols:
            item = None
            for ac in ("stocks", "etf"):
                try:
                    raw = json.loads(_get("https://api.nasdaq.com/api/quote/%s/summary?assetclass=%s" % (sym, ac),
                                          {"Accept": "application/json"}))
                    sd = ((raw or {}).get("data") or {}).get("summaryData") or {}
                    mc = _parse_money((sd.get("MarketCap") or {}).get("value"))
                    av = _parse_money((sd.get("AverageVolume") or {}).get("value"))
                    if mc or av:
                        item = {"symbol": sym, "assetclass": ac,
                                "mcap_b": round(mc / 1e9, 2) if mc else None,
                                "avg_vol": int(av) if av else None}
                        break
                except Exception:
                    continue
            if item:
                out.append(item)
            else:
                _log_skip("liquidity_gate", sym, "no data in stocks/etf assetclass")
        return out
    return _wrap("liquidity_gate", go)


def fetch_polymarket():
    """Polymarket 事件赔率(Gamma 公开 API,无 key)。读数规则:市场隐含概率≠真实概率——
    薄市场不可靠、UMA 结算风险、对冲盘含风险溢价(类比 IV 的 VRP)。流动性地板挡薄市场。"""
    # 词界匹配:裸子串会误伤(award 含 war、corporate 含 rate——被功能测试抓获)
    _EVENT_RX = re.compile(
        r"\b(fed|rates?|fomc|recession|inflation|cpi|gdp|tariffs?|crash|correction"
        r"|s&p|sp ?500|nasdaq|stocks?|markets?|treasury|yields?|oil|opec|gold|bitcoin"
        r"|etf|shutdown|default|banks?|nuclear|strikes?|wars?|invasion"
        r"|china|hong ?kong|taiwan|brazil|india|japan|yuan|renminbi|pboc|boj"
        r"|emerging markets?)\b", re.I)
    def go():
        u = ("https://gamma-api.polymarket.com/markets"
             "?closed=false&order=volume24hr&ascending=false&limit=100")
        data = json.loads(_get(u))
        out, n_top = [], 0
        for mkt in data:
            try:
                vol = float(mkt.get("volume24hr") or 0)
                if vol < 50000:
                    continue                      # 地板挡薄市场,属设计不属异常,不入 skip
                q = (mkt.get("question") or "")[:160]
                is_event = bool(_EVENT_RX.search(q))
                if not is_event:
                    if n_top >= 12:               # 非事件类只留头部热度,事件类(宏观/市场/地缘)全收
                        continue
                    n_top += 1
                prices = mkt.get("outcomePrices")
                if isinstance(prices, str):
                    prices = json.loads(prices)
                if not prices:
                    _log_skip("polymarket_odds", q or "?", "no outcome prices")
                    continue
                out.append({"q": q, "bucket": "event" if is_event else "top",
                            "implied": prices, "vol24h": round(vol),
                            "ends": (mkt.get("endDate") or "")[:10]})
            except Exception as e:
                _log_skip("polymarket_odds", mkt.get("question", "?"), e)
                continue
        return out
    return _wrap("polymarket_odds", go)


# 十二爬虫全员(#11 liquidity_gate 按需;#12 sectors)· tape=quote_layer(FMP 主/Alpaca backup)
def _industry_cache_path():
    return os.path.join(os.path.dirname(_fmp_route_file()), ".industry_map.json")


def industry_lookup(syms):
    """行业标签查询(数据自聚热簇的分组键,替代手写主题表——2026-08-21 Lyra:
    禁写死范围,热点由数据自己聚)。FMP profile 端点族自探定版;每票终身缓存
    (行业极少变),仅新面孔发请求。失败的票标 industry=None,不阻塞。"""
    try:
        cache = json.load(open(_industry_cache_path(), encoding="utf-8"))
    except Exception:
        cache = {}
    if not _fmp_key():
        return {s: cache.get(s) for s in syms}
    route = _fmp_route_load()
    dirty = False
    for sym in syms:
        # v3.26.1:缓存项必须带 is_etf(ETF 不入池的硬判据);旧缓存缺该键或 None(旧版把 ETF
        # 空行业行当失败存 None)的票重查一次
        if isinstance(cache.get(sym), dict) and cache[sym].get("is_etf") is not None:
            continue
        cands = [_fmp_base() + "/profile/" + sym,
                 _FMP_STABLE_BASE + "/profile?symbol=" + sym]
        fam = route.get("profile")
        # 定版键=完整前缀 URL,精确前缀命中优先(戌 8-24 抓:旧裁剪裁到 …/stable
        # 两候选都匹配,二跑仍先打路径形 404;现按 fam 整串 startswith 精确分排)
        hit = [c for c in cands if fam and c.startswith(fam)]
        ordered = hit + [c for c in cands if c not in hit]
        got = None
        for u in ordered[:2]:
            try:
                raw = json.loads(_get(u + ("&" if "?" in u else "?") + "apikey=" + _fmp_key()))
                row = raw[0] if isinstance(raw, list) and raw else (raw if isinstance(raw, dict) else None)
                # ETF 的 profile 行业/板块常为空——按 isEtf/isFund 键在场也算有回包(legacy 与 stable
                # profile 均带 isEtf/isFund 字段);两键都不在 = 类型未证(None,候选池按未证不入)
                if row and (row.get("industry") or row.get("sector") or "isEtf" in row or "isFund" in row):
                    ie = (bool(row.get("isEtf")) or bool(row.get("isFund"))) \
                        if ("isEtf" in row or "isFund" in row) else None
                    mc = row.get("marketCap") or row.get("mktCap")
                    got = {"industry": row.get("industry"), "sector": row.get("sector"), "is_etf": ie,
                           "mktcap_b": (round(float(mc) / 1e9, 3) if mc else None)}   # v3.29.1:F1 换手率的市值兜底
                    if route.get("profile") != u.split(sym)[0]:
                        route["profile"] = u.split(sym)[0]
                        _fmp_route_save()
                    break
            except Exception:
                continue
        cache[sym] = got
        dirty = True
    if dirty:
        try:
            json.dump(cache, open(_industry_cache_path(), "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
    return {s: cache.get(s) for s in syms}


def fetch_most_active():
    """爬虫#13(2026-08-21,crypto 板块三日连涨零覆盖案):最活跃榜=热资金直测。
    movers 榜抓单日暴动(top20 常被 +30% 小票占满),COIN/MARA/HOOD 型每天 +5-8%
    的稳步资金流进不了它——但成交最活跃榜必有它们。端点族自探定版(V6 判例),
    price≥3,cap 30。"""
    def go():
        if not _fmp_key():
            raise RuntimeError("FMP_API_KEY 未配置(most_active 依赖付费档)")
        # 端点候选按 FMP 官方文档实证(2026-08-21 守恒查证):legacy=/api/v3/actives
        # (官方 README 在册;/stock_market/actives 为守恒误推,降为第三候选防站点变体),
        # stable=/most-actives(官方 stable 文档 Top Traded Stocks API)。首个出数定版。
        urls = [_fmp_base() + "/actives", _FMP_STABLE_BASE + "/most-actives",
                _fmp_base() + "/stock_market/actives"]
        route = _fmp_route_load()
        rk = "movers:actives"
        fam = route.get(rk)
        ordered = ([fam] if fam in urls else []) + [u for u in urls if u != fam]
        errs, rows = [], None
        for u in ordered:
            try:
                raw = json.loads(_get(u + ("&" if "?" in u else "?") + "apikey=" + _fmp_key()))
                if isinstance(raw, list) and raw:
                    rows = raw
                    if route.get(rk) != u:
                        route[rk] = u
                        _fmp_route_save()
                    break
            except Exception as e:
                errs.append("%s -> %s" % (u.split("?")[0], str(e)[:90]))
        if rows is None:
            raise RuntimeError("most_active 两族全败:" + " | ".join(errs))
        out = []
        for r in rows:
            try:
                sym = (r.get("symbol") or r.get("ticker") or "").upper()
                px = float(r.get("price") or 0)
                chg = r.get("changesPercentage") or r.get("changePercentage") or r.get("changes")
                chg = float(str(chg).replace("%", "").replace("+", "")) if chg not in (None, "") else None
                if sym and px >= 3:
                    out.append({"symbol": sym, "price": px, "chg_pct": chg})
            except Exception:
                continue
        # _wrap 契约=返回扁平列表(2026-08-21 端到端抓获:dict 形状在 _wrap 切片处崩)
        return out[:30]
    return _wrap("most_active", go)


def fetch_market_movers():
    """爬虫#12(Lyra 拍板 2026-08-20,MRNA+143%/比特币板块/TEM 全盲案):全市场异动扫描。
    FMP gainers/losers 榜(非仅财报票)——|chg|≥10% 或榜单前列的个股进 raw,
    晚报复盘 watch 并入。端点族不猜:legacy 与 stable 候选逐个实弹,首个出数
    按 movers:方向 定版落盘 .fmp_route 跨班续用(V6 判例);全败=本班响亮停用。
    过滤:price≥3(防仙股噪音),每侧 cap 20。"""
    def go():
        if not _fmp_key():
            raise RuntimeError("FMP_API_KEY 未配置(movers 扫描依赖付费档)")
        cands = {
            "gainers": [_fmp_base() + "/stock_market/gainers",
                        _FMP_STABLE_BASE + "/biggest-gainers"],
            "losers": [_fmp_base() + "/stock_market/losers",
                       _FMP_STABLE_BASE + "/biggest-losers"],
        }
        route = _fmp_route_load()
        out = []
        for side, urls in cands.items():
            rk = "movers:%s" % side
            fam = route.get(rk)
            ordered = ([fam] if fam in urls else []) + [u for u in urls if u != fam]
            errs, rows = [], None
            for u in ordered:
                try:
                    data = json.loads(_fmp_get(u))
                    if isinstance(data, list) and data:
                        rows = data
                        if route.get(rk) != u:
                            route[rk] = u
                            _fmp_route_save()
                            print("[fetchers] fmp 路由定版 %s" % rk)
                        break
                    errs.append("空回包")
                except urllib.error.HTTPError as e:
                    errs.append(_http_err_text(e))
                except Exception as e:
                    errs.append(str(e)[:120])
            if rows is None:
                _log_skip("market_movers", side, "全候选失败: " + " | ".join(errs))
                continue
            kept = 0
            for r in rows:
                try:
                    sym = str(r.get("symbol") or "").upper()
                    px = float(r.get("price") or 0)
                    chg = r.get("changesPercentage")
                    chg = float(str(chg).strip("%()")) if chg is not None else None
                    if not re.fullmatch(r"[A-Z]{1,5}", sym) or px < 3 or chg is None:
                        continue
                    out.append({"symbol": sym, "side": side, "price": px,
                                "chg_pct": round(chg, 2), "name": str(r.get("name") or "")[:40]})
                    kept += 1
                    if kept >= 50:   # v3.26:20→50/侧(引擎渲染仍 cap 24,候选池地板筛)
                        break
                except Exception:
                    continue
        return out
    return _wrap("market_movers", go)


ALL = [fetch_treasury_yields, fetch_fred, fetch_indices, fetch_edgar_recent,
       fetch_fda_press, fetch_commodities, fetch_polymarket, fetch_hedge_assets,
       fetch_fear_greed, fetch_earnings_calendar, fetch_sectors, fetch_market_movers, fetch_most_active]


def run_all():
    SKIPS.clear()
    _QUOTE_MEMO.clear()
    print("[fetchers] " + data_plane_banner())
    res = [f() for f in ALL]
    if _fmp_key():
        print("[fetchers] FMP 当日用量 %d/%s(记账不设闸)" % (fmp_calls_today(), os.getenv("FMP_DAILY_BUDGET", "250")))
    return res
PKG_EOF_004
cat > 'scout_agent.py' <<'PKG_EOF_005'
#!/usr/bin/env python3
"""scout_agent.py —— Scout Agent v3.25(DS 决策官 · 三班制+BMO 伏击,守恒手写)
合流(v3.15 判例,两支并集零取舍):
  守恒支线 v3.17-3.23:四槽卡/趋势引擎/量能·隔夜日内/Grid 降噪/账本卫生/影子 lane
  现场支线 v3.16.x(verify 契约全员回岗):think=False / emit_aether_scout /
  rsi14_tape / tape_check / 晚班源清单+lint 硬闸 / EXPANDED-GLM review / et_now_hm /
  amc cap 30 / yday 4000 / RSI 禁自估
数据层:FMP 主源 → ThetaData 第二源 → Alpaca backup(fetchers v3.24),stooq 已移除。
四班(v3.25,Lyra 拍板 2026-08-19):morning 6:45(不含财报,带交班)/ midday 10:40
(定位复核+AMC 初筛)/ earnings 12:35(开卷财报班:今晚 AMC + 次日 BMO 双伏击)/
evening 9pm(三班合并复盘+明日弹药)。
建议 ≠ 自动信号:DS 出的是给 Lyra 看的决策官作业,Lyra 自己拍板买不买。
"""
from __future__ import annotations
import argparse, datetime, html, json, os, re, sys, urllib.error, urllib.request


def _load_env_file():
    """读脚本目录 .env(KEY=VAL)进环境,不覆盖已有值。v3.24:必须先于 import fetchers
    与下方常量——DEEPSEEK_API_KEY/CONSOLE_KEY/OUT 均为 import 期快照,晚于此处加载的
    .env 全是死键(8-17 手动重跑 key 不生效 + 写错目录双坑的共同根)。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(p):
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()

import fetchers
import factors

DS_BASE = os.getenv("DEEPSEEK_BASE", "https://api.deepseek.com")
DS_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
CONSOLE = os.getenv("CONSOLE_URL", "http://localhost:8610")
OWS = os.getenv("OWS_URL", "http://localhost:8620")
GW = os.getenv("GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
WB = os.getenv("WORKBENCH_URL", "http://127.0.0.1:8515").rstrip("/")
# OUT 默认=脚本所在目录(装哪跑哪)——~/grid-scout 死默认曾致手动重跑写错根(8-17,
# 与 land/verify 硬编码 Projects/demo/grid-scout 的双根陷阱就此拆除);env SCOUT_OUT 仍最高。
OUT = os.getenv("SCOUT_OUT", os.path.dirname(os.path.abspath(__file__)))


def _http(url, body=None, headers=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    # SSL 族收尾:fetchers._get 与本函数是全部两条网缝,同挂 certifi 上下文(8-17 根因)
    with urllib.request.urlopen(req, timeout=timeout, context=fetchers._ssl_context()) as r:
        return json.loads(r.read().decode())


# ---- workstation 数据联动 ----
def fetch_workstation_state():
    try:
        dates = _http(OWS + "/api/dates", timeout=5)
        if not dates:
            return None
        d = _http(OWS + "/api/day/" + dates[-1], timeout=5)
        ws = {"date": dates[-1], "underlying": d["snap"]["underlying"],
              "spot": d["snap"]["spot"], "net_gex": d["gex"]["net_gex_musd_per_1pct"],
              "gamma_flip": d["gex"]["gamma_flip"], "ivp": d["features"]["ivp"],
              "vrp": d["features"]["vrp20"], "source": d["snap"].get("source")}
        if str(ws["source"] or "").startswith("synthetic"):
            print("[scout] workstation 仅合成演示数据(%s)——不作数,不喂 DS" % ws["source"])
            return None
        return ws
    except Exception as e:
        print("[scout] workstation(:8620) 不可达:", e)
        return None


def yesterday_raw(today):
    """按日期前缀取上一交易日最新落盘。
    旧实现 f < today+'.json' 有洞:'-HHMM.json' 字典序 < '.json',
    今日自己的重跑后缀文件会被当成"昨日对比"。"""
    try:
        rawdir = os.path.join(OUT, "raw")
        cand = [f for f in os.listdir(rawdir) if f.endswith(".json") and f[:10] < today]
        if cand:
            last_day = max(f[:10] for f in cand)
            pick = max((f for f in cand if f[:10] == last_day),
                       key=lambda f: os.path.getmtime(os.path.join(rawdir, f)))
            return json.load(open(os.path.join(rawdir, pick), encoding="utf-8"))
    except Exception:
        pass
    return None


def _slim_raw(payload, budget=None):
    """prompt 供数瘦身(v3.24):剥引擎私有键(_rets20 等,20 组浮点×30 资产≈5KB 纯噪声),
    预算 18000(env RAW_PROMPT_CHARS)——旧 6000 按源序切,polymarket(概率词唯一合法
    来源)/财报日历未来日(S2a run-up 原料)/sectors 排在刀口后,从未进过 DS 视野。"""
    budget = budget or int(os.getenv("RAW_PROMPT_CHARS", "18000"))
    slim = []
    for src_ in payload.get("results", payload.get("sources", [])) or []:
        items = [({k: v for k, v in it.items() if not str(k).startswith("_")}
                  if isinstance(it, dict) else it) for it in src_.get("items", [])]
        slim.append({**{k: v for k, v in src_.items() if k != "items"}, "items": items})
    return json.dumps({"results": slim, "skips": (payload.get("skips") or [])[:12]},
                      ensure_ascii=False)[:budget]


# ---- DS 决策官 prompt(v3.2 池化:大盘方向+池内提名) ----
_SHIFT_TITLE = {"morning": "晨会交易任务单", "midday": "盘中复核单", "earnings": "财报班任务单"}
_SHIFT_CLOCK = {
    "morning": "(晨班定时 9:45 ET=开盘后约 15 分钟;手动重跑以钟点为准)",
    "midday": "(盘中班定时 13:40 ET;手动重跑以钟点为准)",
    "earnings": "(财报班定时 15:35 ET=收盘前约 25 分钟;手动重跑以钟点为准)"}
_SHIFT_DATA_DESC = {"morning": "隔夜数据 + 盘初 tape", "midday": "盘中 tape 与今晨在案腿",
                    "earnings": "近全日 tape 与财报日历(开卷:当日两班数据已在手)"}
_SHIFT_TAPE_NOTE = {
    "morning": "indices/hedge_assets 的当日行是盘初部分K线(开盘~15分钟,非收盘),\nchg_pct 是盘初对昨收,tape_flag/close_loc 按盘初形态解读,不当全日形态用;",
    "midday": "当日行是盘中K线(开盘~4小时,非收盘),chg_pct 是盘中对昨收,\ntape_flag/close_loc 按盘中形态解读,不当全日形态用;",
    "earnings": "当日行已接近全日K线(收盘前约25分钟),chg_pct 接近全日涨跌,\nclose_loc 接近收盘形态,可当日内定型读;"}


def _s2_section(shift):
    """S2 槽分班文本(v3.25 三班制,Lyra 拍板 2026-08-19:06:45 班不含财报)。"""
    if shift in ("morning", "midday"):
        return ("S2 AMC 初筛卡(v3.25.6,Lyra 拍板 2026-08-20:S2 不再占位空槽):\n"
                "   amc_tonight 名单非空时本槽必须出实质卡(empty=false)——内容=名单前三点名\n"
                "   (按 earn_score 序)+逐票双杀预检(引擎 dk_risk/tier/earn_why 引用)+一句话初筛意见+初步方向倾向;\n"
                "   note 必须以\"AMC 初筛观察,不建仓\"开头(复盘按此标记不计命中),\n"
                "   entry_window_pst 写\"观察——建仓窗在 12:45 财报班\";\n"
                "   amc_tonight 名单为空的日子本槽才空槽(empty_reason=\"今日无 AMC\");\n"
                "   持仓腿纪律不变:财报伏击/持仓/手册在 12:45 财报班;\n"
                "   T+0 动量豁免(v3.25.3):当日出财报的票若盘中动量显著(market_movers/名单可见),\n"
                "   可入 S1/S3 出 T+0 动量卡——当日收盘前强制清仓,禁持过财报,\n"
                "   note 必须写\"T+0 财报票,收盘前清仓\"")
    return ("S2 财报伏击·今晚 AMC(财报班主攻位一):amc_tonight 名单择一,~12:50 PST 尾盘买入,\n"
            "   持过财报,次日盘初按结果处置(gap-and-go 续持/开盘即走);earnings_note 必须\n"
            "   含\"持过财报,IV crush 风险自担\"字样(次晨交班块靠\"持过财报\"识别过夜腿);\n"
            "   三档全摆硬规则(v3.25.3,Lyra 拍板 2026-08-20:机器不藏强票,选择权在交易员):\n"
            "   - 强票档(引擎 dk_risk=true,chg5>15% 或 rsi>75):照常出卡,强制标注\"双杀风险位\",\n"
            "     evidence 必须写双杀双向情景(冲高续涨与利好出尽下杀两个方向都给参照价带)+仓位提示;\n"
            "     放弃条件必须给盘后止损参照;\n"
            "   - 温和档(tier=run-up):财报前动量正、未过热,吃惯性;\n"
            "   - 超跌档(tier=oversold,chg5<-2%):财报前超跌,博利空出尽反弹(WOLF/JBSS 型);\n"
            "   三档各自评估、择优并排,rank_reason 写清档位对比与选档理由,买哪张交易员拍板;\n"
            "   尾盘形态硬规则(v3.27,8-25 INTU 案:当日 -2.92%、loc 0.17 收在最低仍被点成 call 持过财报,盘后 -7%):\n"
            "   amc_tonight 已按引擎 earn_score(因子分 0–100)排,earn_why 逐因子可查;call 只做 earn_score≥40 的票,\n"
            "   当日≤-1% 且 loc<0.5 的票点 call = 引擎作废;三档之上先看形态,再看档位;\n"
            "   资金确认硬规则(v3.27.1,Lyra:不在 FMP top mover 榜的不收):S2/S4 call 腿的票必须在当日\n"
            "   FMP 涨幅榜或最活跃榜(收涨)上(名单行 fmp_board=true),否则引擎作废;\n"
            "   质量地板硬规则(COTY 案后立,先于一切档位;v3.26 起为引擎级:amc_tonight 名单已是地板后幸存者,\n"
            "   筛除者在 floor_rejected.amc_tonight 逐票带条款;名单外点名 = 引擎作废卡,禁点):\n"
            "   price<$10 或 20 日成交额<地板 或无实测 禁入(无接盘仙股;PICS 案);\n"
            "   共识 Reduce/Sell 级、指引撤回、重大诉讼缠身的票禁入;evidence 必须给资金/量能实据\n"
            "   (实测量能读数或明确资金流向叙据,禁\"期权活跃\"式估计);\n"
            "   宁空勿弱硬规则:无过地板且证据充分的候选 = 出空槽卡(empty_reason 写筛除过程),\n"
            "   禁止为填槽选弱票——空槽优于弱腿;\n"
            "   无合格 AMC 标的时本槽回落 run-up 腿:upcoming_earnings 名单(未来 1-8 个交易日,days_out=1 为明日盘后出,\n"
            "   引擎已附读数)择一吃预期消化段,公布前必须离场(手册第二步);质量地板同样适用;\n"
            "   已出结果的财报票(今晨 BMO/昨夜 AMC gap)不属本槽——由 movers 硬闸强制显式处理,\n"
            "      够强则进 S1;\n"
            "   evidence 硬规则:必须引用所属板块当日读数(sector_leaders/sector_laggards 的 chg_pct/mom20),\n"
            "      候选板块与 sector_leaders 背离时必须在 rank_reason 写一句解释(为何逆板块仍做)")


def _s4_section(shift):
    base = ("S4 引擎位:由跨资产引擎读数驱动——领涨板块龙头、迁徙腿(divergence 证实)或\n"
            "   对冲腿(按 regime),evidence 必须引用引擎数字")
    if shift != "earnings":
        return base
    return ("S4 财报伏击·明日 BMO(财报班主攻位二;v3.25 新腿,EL 案根治):\n"
            "   bmo_tomorrow 名单(明日盘前出结果,引擎已附读数)择一,~12:50 PST 尾盘买入,\n"
            "   持过夜至明晨出数,明晨盘初按结果处置;earnings_note 必须含\"持过财报,\n"
            "   IV crush 风险自担\";三档全摆/质量地板/宁空勿弱三条硬规则与 S2 完全同判例\n"
            "   (强票档亮牌不禁入、超跌档合法、引擎地板 price<$10/成交额<地板/无实测 与 Reduce 共识禁入、\n"
            "   空槽优于弱腿;bmo_tomorrow 名单已是地板后幸存者,名单外点名 = 引擎作废卡);\n"
            "   无合格 BMO 标的时本槽回落引擎位\n"
            "   (领涨板块龙头/迁徙腿/对冲腿,evidence 引用引擎数字)\n"
            "   过夜敞口规则(默认,Lyra 可改):S2 与 S4 两条伏击腿只择一执行——两卡并排给出,\n"
            "   rank/rank_reason 写清优先序与对比理由,买哪条交易员拍板;两条都建=过夜敞口翻倍,禁默认;\n"
            "   evidence 硬规则:必须引用所属板块当日读数(sector_leaders/sector_laggards 的 chg_pct/mom20),\n"
            "      候选板块与 sector_leaders 背离时必须在 rank_reason 写一句解释(为何逆板块仍做)")


def _movers_gate(shift):
    if shift == "earnings":
        return ("主菜优先级(堵\"抓小众漏大鱼\",TEAM 案例后立):\n"
                "- 引擎 earnings_movers 榜首 |chg_pct|≥8% 的标的必须显式处理——进 candidates 评估,\n"
                "  或进 rejected 写明理由;禁止无痕跳过\n")
    return "板块对齐(主菜优先级同源规则):\n"


def _earnings_rulebook(shift):
    if shift != "earnings":
        return ("财报手册本班停用——财报伏击/持仓腿在 12:45 财报班;当日财报票盘中动量可走\n"
                "T+0 豁免(收盘前强制清仓,禁持过夜)。候选若 5 个交易日内撞财报,仍须在\n"
                "earnings_note 写明日期/BMO 或 AMC(信息披露)。")
    return """财报两步手册(earnings_calendar 采集必须核对;候选撞财报必须在 earnings_note 声明):
- 第一步·财报/重大消息当日:禁开盘第一根追入——高 IV + 双向扫损 = 多空双杀;
  合法入场 = IV crush 落地后、盘初区间(约首30分钟)方向突破确认再进,0DTE 此时才合法
- 第二步·财报前 run-up(公布前 1-8 个交易日;days_out=1 即明日盘后出,只有一个交易日的窗):可做预期抢跑 call,买"预期+IV 双升"
  (vega 顺风);硬规则 = 财报公布前必须离场,赚 run-up 不赌事件;
  今日 AMC 出财报的标的,T+0 收盘前清仓(本来就是纪律,此处双重锁死)
- 第三步·财报次日(昨夜 AMC 已出结果,今晨 gap):IV 已 crush——单腿 call 的黄金窗口之一;
  gap-and-go = 盘初 30 分钟站稳开盘价上方再追;首 30 分钟回补 gap 过半 = fade,放弃做多;
  方向已被结果定调,禁逆结果抄底/摸顶
- 候选 5 个交易日内有财报 → earnings_note 写明日期/BMO 或 AMC/采用哪条手册;无则写"无"
今晚 AMC 规则(引擎 amc_tonight 名单必须核对,读数已附 rsi14/chg5_pct):
- 名单内标的走 S2 尾盘伏击腿(~12:50 PST 买入持过财报)或不做;
  除 S2/S4 伏击腿外禁持仓过财报;dk_risk=true 强票必须亮"双杀风险位"牌(不禁入,风险叙据齐备交拍板)
- 名单已按引擎 earn_score 降序(尾盘形态分,earn_why 逐项可查;不是市值序);前三按分逐票评估,
  未点名须在 rejected 或正文给一句理由;earn_score<40(因子分 0–100)的票禁做 call;
  引擎硬闸:call 点名当日≤-1% 且 loc<0.5 的票 = 作废卡(8-25 INTU 案),put 镜像同判
明日 BMO 规则(引擎 bmo_tomorrow 名单必须核对,读数已附 rsi14/chg5_pct):
- 名单内标的走 S4 BMO 伏击腿或不做;dk_risk 亮牌规则同 AMC;
- 名单已按 earn_score 降序(因子分 0–100);前三按分逐票评估,未点名须给一句理由;earn_score<40 禁做 call
未来财报 run-up(引擎 upcoming_earnings,未来 1-8 个交易日,days_out 逐票标注,cap 12,全票附读数):
- 作 S2 回落位供数;有预期消化段证据的票优先;公布前必须离场"""


_MIN_CANDS_RULE = (
    "候选下限硬规则(v3.25.6,Lyra 拍板 2026-08-20\"每跑一轮必须三个候选以上,拍板买不买的是我\"):\n"
    "- 每轮 candidates 非空卡≥3(四槽至少三个实质卡,空槽≤1);\n"
    "- 空槽唯一合法理由=质量地板不过(引擎地板 price<$10 或 20 日成交额<地板 或无实测/Reduce-Sell 共识/\n"
    "  指引撤回/重大诉讼);引擎作废的卡自动计入 no_candidate_reason(条款可审);\n"
    "- 禁止用\"动量不显著\"\"默认收敛\"\"不硬凑\"\"超卖不追空\"作为空槽或否决候选存在的理由——\n"
    "  这些是时机/方向判断,写进对应卡的入场条件与放弃条件,不是不出卡的理由;\n"
    "- S1 主池:趋势对齐+当日有动量+流动性过闸=必须出卡,禁\"默认收敛\";\n"
    "- S3 事件:8-K/FDA/异动榜命中+流动性过闸=必须出卡;超卖是时机过滤(入场条件写回踩确认),\n"
    "  不是方向否决;\n"
    "- 质量地板一条不松(防 COTY 弱票填槽):地板过+有证据=出卡,买不买交易员拍板;\n"
    "- 兜底:某轮真无合格候选(<3)时,必须输出 no_candidate_reason 字段,逐票写清被地板筛除的\n"
    "  标的与筛除条款,列数≥3 才算数——禁止无痕全空。")


def _shift_block(shift, todays):
    parts = []
    if shift == "morning":
        parts.append("昨夜交班义务(v3.25):引擎读数 handover 块 = 昨夜过夜伏击腿与昨日 watch 的盘初实测。"
                     "overnight_legs 必须首屏逐腿处置(gap-and-go 续持/开盘即走,写进 macro.logic 或对应候选);"
                     "watch_tape 有显著变化(|chg_pct|≥3%)的必须点名;昨日战绩 rejected_review 里 "
                     "flag_misskill=true(被否却涨>2%)的必须一句话复盘误杀原因。")
        parts.append("本班纪律:不出财报持仓腿——AMC/BMO 伏击、run-up 在 12:45 财报班;"
                     "当日财报票盘中动量走 T+0 豁免(可入 S1/S3,收盘前强制清仓,禁持过夜)。")
    elif shift == "midday":
        parts.append("本班定位(盘中复核班):①逐腿复核今晨在案腿(见下方在案腿)——持有/止损/离场校正,"
                     "写进对应槽 note 或 conclusion;②主池/事件按候选下限硬规则正常出卡(全视野);"
                     "③今晚 AMC 初筛(见 S2 说明)。新卡入场窗以本班时点起算。")
    else:
        parts.append("本班定位(财报班,开卷):当日数据已全。主攻两腿 = S2 今晚 AMC 伏击 + S4 明日 BMO 伏击,"
                     "入场窗同为 12:50-12:55 PST 尾盘;两腿并排、只择一执行(过夜敞口规则见 S4);"
                     "upcoming_earnings(1-8 日窗,days_out=1 为明日盘后出)为 S2 回落位供数。今晨/盘中在案腿只做收尾提示(13:00 收盘硬平仓),不重复出卡。"
                     "S1/S3 本班 = 明晨预排观察卡(v3.26,8-24 案:本班距收盘 15 分钟,DS 曾出 PATH 10 分钟 0DTE 刮单——禁):"
                     "S1 从 candidate_pool 按分取(全日 K 线已定型,是次日晨会最好的预排材料),S3 取 8-K/FDA 事件票;"
                     "两卡 note 必须以\"明晨预排,不建仓\"开头,entry_window_pst 写\"明晨 06:45 班盘初确认后\","
                     "expiry 写\"明晨定\",禁 0DTE、禁今日尾盘入场;预排卡复盘进 watch 不计命中。")
    if shift in ("morning", "midday", "earnings"):
        parts.append(_MIN_CANDS_RULE)   # evening=复盘班不出候选卡,不挂(2026-08-21 范围审定)
        parts.append("晚报调优的效力边界(2026-08-24 立):prev_review 里的调优段仅供参考——"
                     "其中的机械阈值类内容(RSI 数值闸/新禁入条件/入场区间)一律无效,"
                     "在册规则以本 prompt 条款为准;晚报无立法权,新增规则只能由 Lyra 拍板入 prompt。"
                     "调优段里的观察点/降权建议可参考,但每一票仍按本班在册条款独立评估。")
    if todays:
        parts.append("今日已出班次在案腿:" + json.dumps(todays, ensure_ascii=False)[:1600])
    return "\n".join(parts)


def load_fault_lines_snapshot(today):
    """S1 缝(戌现场施工 2026-08-24 回流):读 inbox/factor_snapshot.json 的 fault_lines 块,
    渲染成事实行字符串。DS prompt 标"结构参考,非信号"。
    返回 (fact_str, block_dict);无文件或无断层位 → ("", {})。"""
    inbox = os.path.join(OUT, "inbox", "factor_snapshot.json")
    if not os.path.isfile(inbox):
        return "", {}
    try:
        payload = json.loads(open(inbox, encoding="utf-8").read())
    except Exception:
        return "", {}
    block = payload.get("fault_lines") or {}
    if not block.get("available"):
        return "", block
    syms = block.get("symbols") or []
    if not syms:
        return "", block
    lines = ["[断层热力 · 结构参考,非信号 · %s]" % block.get("date", today)]
    for s in syms:
        sym = s.get("symbol")
        parts = []
        f1 = s.get("F1_gamma_flip")
        if f1 is not None:
            parts.append("F1 gamma翻转@%s" % f1)
        f2 = s.get("F2_oi_walls") or {}
        cw = f2.get("call") or []
        pw = f2.get("put") or []
        if cw:
            parts.append("F2 call墙%s" % cw)
        if pw:
            parts.append("F2 put墙%s" % pw)
        mp = s.get("F2_max_pain")
        if mp is not None:
            parts.append("max_pain@%s" % mp)
        f3 = s.get("F3_gap_edge")
        if f3:
            parts.append("F3 gap边[%s,%s]" % (f3.get("lower"), f3.get("upper")))
        f4 = s.get("F4_iv_inversion") or {}
        if f4 and f4.get("inverted"):
            parts.append("F4 IV倒挂(ratio=%s)" % f4.get("ratio"))
        if s.get("near_fault"):
            parts.append("⚠盘前贴断层")
        if parts:
            lines.append("%s: %s" % (sym, " · ".join(parts)))
    if len(lines) <= 1:
        return "", block
    return "\n".join(lines), block


def build_trading_prompt(raw, ws, yday, cross=None, prev=None, shift="morning", todays=None, fault_lines=""):
    _fl = ("\n断层热力(结构参考,非信号):\n" + fault_lines + "\n") if fault_lines else ""
    return f"""你是交易台的首席决策官。当前 {fetchers.et_now_hm()} ET
{_SHIFT_CLOCK[shift]},
基于{_SHIFT_DATA_DESC[shift]}给出清晰的分析作业
(这是给交易员参考的分析,交易员自己拍板执行,不是自动下单)。
观察宇宙(2026-08-06 扩定,三层):
A. S&P 500 与 Nasdaq 成分池(主池,不是 SPY/QQQ 两只 ETF)
B. 事件驱动个股不限成分——8-K 并购/FDA 等隔夜证据命中的美股可点名,但必须过流动性闸:
   大中盘、期权活跃;小盘或期权价差宽的宁可不点,T+0 会死在价差上
C. 海外 ADR 巨头(BABA/PDD/JD/TSM/NVO 级别)——迁徙或自身事件驱动时可点,
   时差跳空风险写进 abandon
每个候选必须填 liquidity 字段:一句话说明流动性为何扛得住 T+0。
读数口径提醒:{_SHIFT_TAPE_NOTE[shift]}
昨日完整形态看晚报与昨日采集。

隔夜采集:{_slim_raw(raw)}
工作站读数(GEX/特征):{json.dumps(ws, ensure_ascii=False) if ws else "工作站无可用实弹数据(不可达或仅合成数据),基于隔夜数据判断"}
昨日采集(对比用):{json.dumps(yday, ensure_ascii=False)[:2000] if yday else "无"}
跨资产引擎读数(确定性,判断必须引用):{json.dumps(cross, ensure_ascii=False) if cross else "无"}
昨日战绩(确定性复盘,必须引用):{json.dumps(prev, ensure_ascii=False) if prev else "无(首日或昨日无产出)"}
{_fl}
交易风格偏置(硬约束):交易员主做 T+0 单腿 CALL,当日了结。
- 策略默认形态 = 单腿 CALL,到期选 0DTE 或最近可用到期,必须给 t0_exit(当日平仓纪律)
- PUT 仅当看空证据明确时才提,并在 evidence 写清依据;禁止多腿组合;禁止编造权利金/报价
候选硬规则:每个候选必须锚定隔夜采集中的具体条目,逐条给出处;禁止凭训练记忆点名。
四槽股票卡制(2026-08-07 Lyra 定;candidates 必须恰好 4 条,slot 1-4 各一,
全部 单腿 CALL · T+0):
S1 主池·引擎候选池(v3.26,2026-08-24 案:六眼只当参考、S1 由 DS 自由挑,挑出热簇里 +1.77% 的
   PATH 做 10 分钟 0DTE,最活跃+🔥团的 BMNR 没进卡):候选视野 = 引擎 candidate_pool——
   七眼并集(异动榜/最活跃/🔥同频团/🔥热簇/连涨/自选/趋势榜)只决定谁进宇宙;排序 = 六因子核 0–100
   (F1 资金密度=换手率 / F2 趋势 / F3 尾盘形态 / F4 距财报天数 / F5 期权 γ/|θ| 不对称性 / F6 风险扣分;score_why 逐因子可查)
   →逐票实测→硬地板(price≥${fetchers.pool_price_floor():g}、
   20 日成交额≥${fetchers.pool_adv_floor_usd() / 1e6:.0f}M 实测,无实测不入池)→透明计分(score_why 逐项可查)→按分排序;
   禁止只在板块 ETF 成分逻辑内选,sector_leaders 只作背景;
   硬规则:①S1 ticker 必须在 candidate_pool 内(池外点名引擎盖章"视野外");
   ②池前三(按 score)必须逐票评估——入卡,或 rejected 一句话理由(趋势不对齐/RSI 过热/追高
   均为合法理由),禁无痕跳过;ETF 已由引擎硬排不入池(IV 结构不适合单腿 call),S1/S3 点名
   ETF = 引擎作废卡;③rank_reason 引用该票 score 与 score_why;
   ④候选池为空时本槽空槽,empty_reason 引用 pool_rejected 的筛除条款;
   ⑤flags 含"追高风险"/"过热"的票入场条件必须写回踩确认;
   优选距 52 周高 <5% 强势票(high52_dist_pct);trend_regime=下降趋势 时
   做多降杠杆表述并写明逆势理由,或让位防守
{_s2_section(shift)}
S3 事件:8-K 重大文件(EX-2.x 并购/资产/重大合同)或 FDA approval——
   必须过流动性实测闸(liquidity_check 过闸);无够格标的宁可空槽,禁硬凑小票
{_s4_section(shift)}
每槽无合格标的 → 该槽输出 {{"slot": N, "empty": true, "empty_reason": "一句话"}};
四槽必须全部出现,禁止缺槽
排名(rank 1-4 跨四槽):趋势对齐(trend_regime/板块20日动量/52周高邻近)>
证据强度(引擎实测读数)> 时机贴近度(距入场窗)> 流动性 > 上行空间;
每卡 rank_reason 一句话引用具体读数;breadth_20d_spread<0(巨头独舞)时
广度确认缺失要在大盘 logic 里写明
时间窗硬规则:每卡 entry_window_pst / exit_window_pst 必填,给具体 PST 时段
(如 "7:15-7:45 突破确认入场" / "11:30 未达标离场,12:50 硬平仓"),禁"视情况"。
量能硬规则:入场条件里凡"放量"必须引用实测 vol_x20(≥1.5 才算放量;无读数写明"量能无实测");
隔夜/日内硬规则:index_session_split 直面 T+0 结构——日内 20 日分量为负的体制,
S1/S4 日内做多降杠杆表述并写明;隔夜分量显著为正时 S2(b) 伏击腿(唯一吃隔夜的腿)
排名可升,rank_reason 必须引用该读数;
风险预警硬规则:risk_alerts 非空必须逐条回应,写进大盘 logic 或 hedge.basis,禁无视。
对冲硬规则(hedge 段永不空白——"没信号什么都不写"被禁止):
- 用跨资产引擎读数 + fear_greed 评估风险,先定 regime,写进 distribution_risk + basis
- 风险 中/高 → 必须按下表给 1-2 条对冲腿;风险 低 → note 写明依据(不许留空)
对冲分级手册(按 regime 选工具,用错工具比不对冲更糟):
- regime=轮动/拉高出货(股冲高回落或收跌,但 GLD/油有买盘):
  GLD/SLV/OXY/USO 单腿 call,T+0 纪律照旧
- regime=全线下跌(engine liquidation_watch=true:风险资产≥5/6 收跌+VIX≥+8%):
  黄金原油也在跌——商品 call 不是对冲,禁用。工具切换为:
  ①指数单腿 PUT(SPY/QQQ;对冲工具不受候选宇宙池化令限制)
  ②VIXY 单腿 call——流动性挤兑日唯一确定被买的是波动率
  ③UUP call(现金涌向美元);TLT 仅当 tlt_chg_pct>0(flight-to-quality 被证实)才可用,
    利率冲击型下跌里 TLT 同跌,禁用
  ④"减仓/空仓也是对冲"是合法结论——但必须写成结论,不许留白
  ⑤IV 代价必须写:恐慌日买 put/VIX call 是在 IV 高位买保险,strategy 里写明
    隔夜 vol crush 风险与 t0_exit
- regime=资金迁徙(海外)(SP500 收跌但 rotation_divergence 非空——资金不会消失只会转移):
  海外腿可用:FXI/KWEB(中国)、EWZ(巴西)、EWJ(日本)、EEM(新兴)、BABA 单腿 call,
  evidence 必须引用 rotation_leaders 的具体涨跌数字;
  YINN(3x 中国)仅限 T+0 决不隔夜——杠杆 ETF 日内重置损耗,拿隔夜是给做市商送钱;
  美股时段的中国 ETF/ADR 交易的是"明天的亚洲",隔夜跳空风险必须写进 abandon
- 护栏一:全线下跌日(liquidation_watch=true)禁点海外腿——global margin call 无避风港,
  新兴市场 beta 更高、流动性更差,挤兑日跌更狠
- 护栏二:rotation_divergence 为空时同禁海外腿——没有分化读数就没有迁徙证据
- evidence 锚定引擎读数与 hedge_assets/fear_greed 数字,禁编报价
{_earnings_rulebook(shift)}
{_movers_gate(shift)}- 候选所属板块应与引擎 sector_leaders 对齐;背离必须在排名理由里解释
- 热簇·数据自聚(引擎 theme_heat):当日榜单标的按行业标签自动聚簇,非预设名单——
  hot=true 的簇=钱正往那个行业走,成员(实测涨跌已附)是 S1/S3 一等候选源
- 同频簇(引擎 comove_clusters):极大团——簇内任意两成员近 10 日收益 ρ≥0.7,
  "两两都在动"而非"在同一个朋友圈"(传递串链不成簇);hot=≥2 名资金确认+当日
  中位数与六成成员同时达标;跨行业标签自然合流;成员与热簇成员同等逐票必评
- 最活跃榜(引擎 most_active):成交最活跃=热资金所在,稳步流(+3~8%)在这里不在暴动榜
- 连涨榜(引擎 streak_board):近 3 日 ≥2 次上榜=趋势型资金流,movers 尖峰榜的盲区
- 全市场异动榜(引擎 market_movers,非仅财报):|chg_pct|≥10% 的标的必须在 macro.logic 或
  conclusion 点名成因与板块含义;事件驱动个股可入 S3 评估(过流动性闸);禁止无痕跳过
战绩与 RSI 硬规则:
- 昨日方向错的腿,今日同逻辑再点必须写明"昨日同逻辑失误 + 今日为何不同";
  滚动命中率 <50% → 整体压低置信度表述
- RSI14 是时机过滤器不是方向信号:候选 rsi14>70 禁追高,入场条件必须写回踩确认;
  rsi14<30 禁追空 put(超卖反抽);对冲腿同规
- 禁止自估 RSI:rsi14 一律引用引擎实测(rsi14_tape/各资产读数);无读数写明"RSI 无实测",
  禁凭走势口算;引擎会给每条腿盖 tape_check 实测章与你的叙述并排对质
数字纪律(机构级;违者视为编造):
- 一切绝对数字(价位/市值/百分比)必须能在本 prompt 的采集读数中逐一找到,
  并标明来源;找不到 → 只许相对表述(昨收/盘初高点/前日低点),禁止精确小数价位
- 大盘 key_levels 同规:引擎只有日线读数、没有盘中报价——禁止给精确指数点位,
  一律相对位表述
- 概率用词("上行概率高""65%")必须带来源(polymarket 具体市场/引擎读数);无源禁用
- 市值/期权活跃度若无采集来源,liquidity 里必须写明"估计,无实测来源"

{_shift_block(shift, todays)}

只输出一个 JSON 对象——不要 markdown、不要代码围栏、不要 JSON 之外的任何文字。schema:
{{"macro": {{"sp500_bias": "看涨|看跌|中性震荡", "nasdaq_bias": "看涨|看跌|中性震荡",
  "confidence": "高|中|低", "logic": "引用 indices/收益率/VIX/赔率读数的推理",
  "key_levels": "大盘关键位——相对表述(昨收/盘初高低点),无盘中报价禁精确点位"}},
 "candidates": [{{"slot": 1, "slot_name": "主池|财报|事件|引擎位", "empty": false,
   "empty_reason": "仅 empty=true 时填",
   "rank": 1, "rank_reason": "一句话,引用引擎实测读数",
   "ticker": "", "direction": "call|put",
   "evidence": [{{"source": "edgar|fda|earnings_movers|sectors|indices|macro", "item": "条目摘要", "why": "为何构成驱动"}}],
   "key_levels": "该标的阻力/支撑及依据",
   "liquidity": "一句话:市值/期权活跃度为何扛得住 T+0",
   "strategy": {{"type": "单腿 call", "strike_logic": "行权价选择逻辑(不编报价)",
     "expiry": "0DTE|本周五|最近到期", "entry_condition": "入场触发条件",
     "entry_window_pst": "具体 PST 时段", "exit_window_pst": "具体 PST 时段+硬平仓点",
     "stop": "止损条件", "abandon": "作废条件",
     "earnings_note": "5个交易日内财报:日期/BMO或AMC/采用哪条手册;无则写无",
     "t0_exit": "当日平仓纪律"}}}}],
 "no_candidate_reason": "candidates 为空时的证据核查结论,否则空串",
 "rejected": [{{"ticker": "", "reason": "一句话淘汰理由(候选漏斗可审;考虑过但没入选的,最多3条)"}}],
 "hedge": {{"distribution_risk": "高|中|低", "regime": "轮动|资金迁徙(海外)|全线下跌|无明显风险",
   "basis": "引用跨资产引擎/fear_greed/hedge_assets 读数的依据",
   "legs": [{{"ticker": "GLD|SLV|OXY|USO|TLT|UUP|VIXY|SPY|QQQ|FXI|KWEB|EWZ|EWJ|EEM|BABA|YINN", "direction": "call|put",
     "evidence": [{{"source": "hedge_assets|fear_greed|indices|macro", "item": "读数", "why": "为何对冲"}}],
     "strategy": {{"type": "单腿 call", "strike_logic": "", "expiry": "0DTE|本周五|最近到期",
       "entry_condition": "", "stop": "", "abandon": "", "t0_exit": ""}}}}],
   "note": "风险低暂不对冲时写明依据;永不空白"}},
 "data_gaps": [{{"item": "", "status": "", "handling": ""}}],
 "conclusion": "一句话结论"}}
禁止"具体视情况而定""谨慎操作"等无效废话。全部值用中文,单值≤60字——整份 JSON 必须在输出限额内完整收尾。"""


def build_evening_prompt(raw, yday, cross=None, review=None, inventory=None, today=None):
    if today:
        _iso = _next_trading_day(today)
        ntd = "%s(周%s)" % (_iso, "一二三四五六日"[datetime.date.fromisoformat(_iso).weekday()])
    else:
        ntd = "下一交易日"
    return f"""你是交易台参谋。当前 {fetchers.et_now_hm()} ET(收盘后;今日 AMC 财报已披露)。
日历纪律:下一交易日 = {ntd}(周末/隔日自动换算,联邦假日请自行核对)。全篇前瞻表述
一律写"下一交易日({ntd})",禁止裸用"明日/明晨/明天"——周五晚报写"明晨"实指周一,
歧义已出过事故。
调优边界:调优段只准提观察点、降权建议、复核请求;禁止立机械阈值新规
(RSI 数值闸/禁入条件/入场区间等)——那是把时机判断写成规则,立法权在 Lyra,
晚报建议不会也不应被晨会当作在册条款执行。
候选/地板/ETF 纪律(与白班同判,v3.26.3):下一交易日弹药、run-up 点名、过夜腿讨论只准在
candidate_pool(引擎候选池,已过地板按分排序,score_why 逐项)与地板后的 amc_tonight/bmo_tomorrow/
upcoming_earnings 内点名;floor_rejected / pool_rejected 里的票只可作"已被引擎地板筛除(条款)"一笔带过,
禁当过夜腿/弹药/跟进对象;ETF(IBIT/BITO/TSLL/SOXL 类)禁作候选与"值得盯"对象(对冲工具除外);
amc_results_health 是盘后读数健康态(k/n 出数+缺数原因),缺数只讲事实,禁猜盘后涨跌。
写今日收盘复盘 + 下一交易日弹药,给交易员看:
1. 今日要闻与并购/FDA/事件催化(带出处)
2. 隔夜→今日的赔率变化(Polymarket)
3. 明日日历(FDA/到期/财报/事件)
4. 明日值得盯的方向与关键位(分析,非指令)
5. 风险雷达(黑天鹅/机构拉高出货/全线下跌排查,永不留空):逐项核对——
   跨资产引擎读数(liquidation_watch、tape_flags、vix_chg_pct)、fear_greed 极值、
   hedge_assets 异动、polymarket bucket=event 赔率突变;
   财报异动榜(earnings_movers/earnings_calendar)有 |chg|≥8% 者必须点名讲清楚;
   今晚 AMC:amc_tonight 即财报"已出结果"者名单(晚班时点已全部披露)——逐个点名,
   一律用已出结果叙事(涨跌/超预期与否按 amc_results 实测讲);
   禁止出现"若超预期/待公布/今晚将出"类未出语气;
   amc_results 是实测盘后涨跌(Nasdaq 报价,时点快照)——|盘后|≥8% 者必须重点讲清,
   但盘后快照只述事实,禁止据此对持仓腿下成败结论(盘后薄量摆动大,深夜字段语义待定案);
   过夜腿成败以次晨交班块处置窗实测为准,
   并给明晨财报次日手册路径(gap-and-go/fade、IV 已 crush);
   amc_results 里没有读数的标的只讲事实,仍禁编数字;
   命中拉高出货 → 点名并给商品对冲方向(GLD/SLV/OXY/USO);
   命中资金迁徙(rotation_divergence 非空)→ 点名领涨海外腿(引用 rotation_leaders 数字),
   给 FXI/KWEB/EWZ/EWJ/EEM/BABA 方向,YINN 注明仅 T+0;
   命中全线下跌(liquidation_watch=true)→ 明写"商品 call 不是对冲、海外也不是避风港",
   给指数 PUT/VIXY/UUP 方向与"减仓也是对冲";未命中则明写"今日未见"
6. 晨会复盘与明日调优(复盘读数必须逐腿引用,方向命中口径=收盘对昨收):
   逐腿讲对错与原因假设;rejected_review 里 flag_misskill=true 的被否方案逐个点评
   (过滤器是否误杀,规则要不要修);给明日晨会具体调优——哪些逻辑降权、
   入场条件怎么改、RSI 时机过滤怎么用;明日/本周财报名单点名,标注 run-up 机会(run-up 仅限未来交易日;
   今日已出结果者不属 run-up);复盘读数 watch 段(amc/movers 观察名单,不计命中率)
   逐个过一遍是否需要明日跟进
数字纪律同晨会:绝对数字必须有采集来源并标明,无源用相对表述;概率词必须带来源。
源清单纪律:下方「采集源清单(权威·事实行)」是采集状态的唯一事实——禁止把 ok=true 的源
说成 SSL 失败/被墙/缺失;某源确实 ok=false 时按清单口径讲,不夸大范围。
采集源清单(权威·事实行):
{inventory or "(本班未生成清单)"}
复盘读数(确定性):{json.dumps(review, ensure_ascii=False) if review else "今日无晨会腿可复盘"}
跨资产引擎读数:{json.dumps(cross, ensure_ascii=False) if cross else "无"}
今日采集:{_slim_raw(raw)}
昨日对比:{json.dumps(yday, ensure_ascii=False)[:4000] if yday else "无"}
禁用短语:好的/综上所述/总而言之/需要注意的是/希望有帮助/如有需要——直接说事。
用 markdown,严格以 ## 分节(要闻催化/赔率变化/明日日历/明日方向/风险雷达/晨会复盘与明日调优),
每节内用短段落或列表,不要糊成整段。用中文,给数字给出处,不写废话。"""


def shadow_call(prompt):
    """D3 影子决策官(Lyra 批 2026-08-15;默认关,.env 配 SHADOW_MODEL 即开):
    同一份案卷并行出一份影子 JSON,只落盘不渲染,review 文件 -glm 后缀分账,
    与主 lane 账本互不污染;失败绝不阻塞主班,响亮记录。20 日账本判谁坐正位。"""
    model = os.getenv("SHADOW_MODEL")
    if not model:
        return None
    try:
        r = _http((os.getenv("SHADOW_BASE") or DS_BASE) + "/chat/completions",
                  {"model": model, "max_tokens": int(os.getenv("DS_MAX_TOKENS", "12000")),
                   "think": False,   # Ollama 长单不关 think 会 finish=length 空正文(8-17 同族)
                   "messages": [{"role": "user", "content": prompt}]},
                  {"Authorization": "Bearer " + (os.getenv("SHADOW_KEY")
                                                 or os.getenv("DEEPSEEK_API_KEY", "").strip() or "")})
        return r["choices"][0]["message"]["content"]
    except Exception as e:
        print("[scout] 影子 lane 失败(不阻塞主班):", str(e)[:200])
        return None


def ds_call(prompt):
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()   # 调用期读取:.env/plist 均生效(死键族收尾)
    if not key:
        raise SystemExit(
            "[scout] DEEPSEEK_API_KEY 未配置。\n"
            "  1) platform.deepseek.com 注册取 key,填 .env 或 plist\n"
            "  2) curl -s %s/models -H 'Authorization: Bearer $DEEPSEEK_API_KEY' 验模型名\n"
            "  3) 实况名与默认 %s 不符则设 DEEPSEEK_MODEL(本机 Ollama:DEEPSEEK_BASE 指 11434)"
            % (DS_BASE, DS_MODEL))
    payload = {"model": DS_MODEL, "max_tokens": int(os.getenv("DS_MAX_TOKENS", "12000")),
               "think": False,   # Ollama(deepseek-v4-pro:cloud)必需;官方 OpenAI 兼容端忽略未知字段
               "messages": [{"role": "user", "content": prompt}]}
    headers = {"Authorization": "Bearer " + key}
    # 5xx 重试 + 空内容兜底(戌现场施工 2026-08-24 回流;2026-08-20 晚报 500 根因:单发无重试)
    import time as _t, socket as _sock
    last_err = None
    # v3.26.3(戌 8-24 抓:今晨 6:45 DS 超时 120s 崩班,html 没覆盖):超时 env DS_TIMEOUT 默认 420s
    # (12000-16000 token 输出实测常超 120s),超时类异常再试一次;仍败向上抛,由 main 接住落失败标记
    to = int(os.getenv("DS_TIMEOUT", "420"))
    for attempt in range(3):
        try:
            r = _http(DS_BASE + "/chat/completions", payload, headers, timeout=to)
            content = r.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
            if content.strip():
                return content
            if attempt == 0:
                payload.pop("think", None)
                print("[scout] ds 空内容,去 think 重试")
                continue
            print("[scout] ds 空内容(第 %d 次),继续重试" % (attempt + 1))
        except Exception as e:
            last_err = e
            code = getattr(e, "code", None)
            if code and 500 <= code < 600 and attempt < 2:
                print("[scout] ds HTTP %d,退避重试(%d/3)" % (code, attempt + 1))
                _t.sleep(2 * (attempt + 1))
                continue
            is_to = isinstance(e, (_sock.timeout, TimeoutError)) or \
                isinstance(getattr(e, "reason", None), (_sock.timeout, TimeoutError)) or "timed out" in str(e)
            if is_to and attempt == 0:
                print("[scout] ds 超时(%ds),重试一次" % to)
                continue
            raise
    if last_err:
        raise last_err
    return ""


def cross_asset_summary(payload):
    """确定性跨资产读数(数字出引擎,解读归 DS)。
    全线下跌体制判据:6 只风险资产(SP500/NASDAQ/GLD/SLV/OXY/USO)≥5 收跌
    且 VIX 单日 ≥ +8%——此时黄金原油同跌,商品 call 不构成对冲。
    v3.8 修复:run_all 落盘键是 results,此前只读 sources——引擎在现网从未吃到数据,
    liquidation_watch/迁徙读数一直空转(自测喂了手搓 schema,没走 main 形状,守恒之过)。"""
    m = {}
    for src in payload.get("results", payload.get("sources", [])):
        if src.get("source") in ("indices", "hedge_assets"):
            for it in src.get("items", []):
                if isinstance(it, dict) and it.get("name"):
                    m[it["name"]] = it
    risk = ["SP500", "NASDAQ", "GLD", "SLV", "OXY", "USO"]
    downs = [n for n in risk if n in m and (m[n].get("chg_pct") or 0) < 0]
    vix = (m.get("VIX") or {}).get("chg_pct")
    rot = {n: v for n, v in m.items() if v.get("cls") == "rotation"}
    spx_chg = (m.get("SP500") or {}).get("chg_pct") or 0
    leaders = sorted(((n, v.get("chg_pct")) for n, v in rot.items()
                      if v.get("chg_pct") is not None), key=lambda x: -x[1])[:3]
    out = {"risk_assets_down": downs, "down_count": len(downs), "of": len(risk),
           "vix_chg_pct": vix,
           "tlt_chg_pct": (m.get("TLT") or {}).get("chg_pct"),
           "uup_chg_pct": (m.get("UUP") or {}).get("chg_pct"),
           "tape_flags": {n: m[n]["tape_flag"] for n in m if m[n].get("tape_flag")},
           "rotation_leaders": [{"name": n, "chg_pct": c} for n, c in leaders],
           "sector_leaders": [], "sector_laggards": [],
           # 分化=资金迁徙迹象:美股收跌而海外腿收涨(数字出引擎,解读归 DS)
           "rotation_divergence": ([n for n, v in rot.items() if (v.get("chg_pct") or 0) > 0]
                                   if spx_chg < 0 else []),
           "liquidation_watch": len(downs) >= 5 and (vix or 0) >= 8.0}
    sec = []
    for src in payload.get("results", payload.get("sources", [])):
        if src.get("source") == "sectors":
            sec = [x for x in src.get("items", []) if isinstance(x, dict) and x.get("chg_pct") is not None]
    # v3.19:轮动排名以 20 日动量为主键(单日涨跌是噪声不是趋势——机构没人拿一天定轮动)
    sec.sort(key=lambda x: -(x.get("mom20_pct") if x.get("mom20_pct") is not None else x["chg_pct"]))
    def _srow(x):
        return {"name": x["name"], "chg_pct": x["chg_pct"], "mom20_pct": x.get("mom20_pct"),
                "high52_dist_pct": x.get("high52_dist_pct")}
    out["sector_leaders"] = [_srow(x) for x in sec[:3]]
    out["sector_laggards"] = [_srow(x) for x in sec[-3:]] if len(sec) >= 3 else []
    spx_m = (m.get("SP500") or {}).get("mom20_pct")
    ndq_m = (m.get("NASDAQ") or {}).get("mom20_pct")
    rsp_m = (m.get("RSP") or {}).get("mom20_pct")
    out["trend_regime"] = ("上升趋势" if (spx_m or 0) > 0 and (ndq_m or 0) > 0 else
                           "下降趋势" if (spx_m or 0) < 0 and (ndq_m or 0) < 0 else "混沌震荡") \
                          if (spx_m is not None and ndq_m is not None) else None
    # 广度差:等权 RSP 20日动量 − SP500 20日动量;>0=普涨参与广,<0=少数巨头独舞
    out["breadth_20d_spread"] = round(rsp_m - spx_m, 2) if (rsp_m is not None and spx_m is not None) else None
    out["index_mom20"] = {"SP500": spx_m, "NASDAQ": ndq_m, "RSP": rsp_m}
    # rsi14_tape:核心资产 RSI/tape 实测清单(verify 契约;DS 禁自估的引擎供数面)
    out["rsi14_tape"] = [{"name": n, "rsi14": (m.get(n) or {}).get("rsi14"),
                          "close_loc": (m.get(n) or {}).get("close_loc"),
                          "tape_flag": (m.get(n) or {}).get("tape_flag") or ""}
                         for n in ("SP500", "NASDAQ", "VIX", "GLD", "USO", "TLT")]
    # ④隔夜/日内 20 日分解(指数级)
    out["index_session_split"] = {n: {"overnight20_pct": m[n].get("on20_pct"),
                                      "intraday20_pct": m[n].get("in20_pct")}
                                  for n in ("SP500", "NASDAQ") if n in m}
    # ②相关性收敛(参数验证期:阈值 0.75 只读上卡,不接任何闸——Lyra 2026-08-07 排序令)
    def _corr(a, b):
        n = min(len(a), len(b))
        a, b = a[-n:], b[-n:]
        ma, mb = sum(a) / n, sum(b) / n
        va = sum((x - ma) ** 2 for x in a); vb = sum((x - mb) ** 2 for x in b)
        if va == 0 or vb == 0:
            return None
        return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / ((va * vb) ** 0.5)
    rets = {n: m[n].get("_rets20") for n in risk if n in m and m[n].get("_rets20")}
    ks, pair = list(rets), []
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            c_ = _corr(rets[ks[i]], rets[ks[j]])
            if c_ is not None:
                pair.append(c_)
    out["risk_corr20"] = round(sum(pair) / len(pair), 2) if pair else None
    # 风险预警(确定性,alerts 非空 DS 必须逐条回应)
    alerts = []
    if out["risk_corr20"] is not None and out["risk_corr20"] > 0.75:
        alerts.append("相关性收敛 %.2f>0.75(挤兑前兆;参数验证期,只读不接闸)" % out["risk_corr20"])
    hy, lq = (m.get("HYG") or {}).get("mom20_pct"), (m.get("LQD") or {}).get("mom20_pct")
    out["credit_20d_spread"] = round(hy - lq, 2) if (hy is not None and lq is not None) else None
    if out["credit_20d_spread"] is not None and out["credit_20d_spread"] < -1.0:
        alerts.append("信用预警 HYG−LQD 20日 %+.1f%%(垃圾债跑输投级)" % out["credit_20d_spread"])
    defs = [x.get("mom20_pct") for x in sec
            if x.get("name", "").startswith(("XLP", "XLU")) and x.get("mom20_pct") is not None]
    if defs and spx_m is not None:
        dr = round(sum(defs) / len(defs) - spx_m, 2)
        out["defensive_rot_20d"] = dr
        if dr > 0:
            alerts.append("防御轮动 %+.1f%%(XLP/XLU 20日跑赢大盘)" % dr)
    vixm = (m.get("VIX") or {}).get("mom20_pct")
    if vixm is not None and vixm > 25:
        alerts.append("VIX 20日动量 %+.0f%%(波动率体制抬升)" % vixm)
    out["risk_alerts"] = alerts
    return out


def _review_files():
    b = os.path.join(OUT, "briefs")
    if not os.path.isdir(b):
        return []
    return sorted(f for f in os.listdir(b) if f.endswith("-review.json"))


_FLOOR_BAN_WORDS = ("默认收敛", "动量不显著", "不硬凑", "超卖不追空")


def apply_candidate_floor(ds, shift):
    """规则 B 代码闸(v3.25.7 重建+v3.25.8 补 earnings;evening 复盘班不挂):
    三种违例只盖章(_floor_violation 进 json+skips),不改 DS 的卡。
    ①非空卡<3 且 no_candidate_reason 缺失或列票<3;②空槽>1;③空槽理由用禁词。"""
    if shift not in ("morning", "midday", "earnings") or not isinstance(ds, dict):
        return ds
    cands = ds.get("candidates") or []
    nonempty = [c for c in cands if not c.get("empty")]
    empties = [c for c in cands if c.get("empty")]
    v = []
    if len(nonempty) < 3:
        ncr = str(ds.get("no_candidate_reason") or "")
        listed = len(re.findall(r"[A-Z]{1,5}", ncr))
        if listed < 3:
            v.append("非空卡 %d<3 且 no_candidate_reason 未逐票列筛除(仅 %d 票)" % (len(nonempty), listed))
    if len(empties) > 1:
        v.append("空槽 %d>1" % len(empties))
    for c in empties:
        hit = [w for w in _FLOOR_BAN_WORDS if w in str(c.get("empty_reason") or "")]
        if hit:
            v.append("slot%s 空槽理由用禁词%s" % (c.get("slot"), hit))
    if v:
        ds["_floor_violation"] = v
        for x in v:
            print("[scout] 候选下限违例(盖章不改卡):", x)
    return ds


def _floor_clause(row):
    """质量地板判据(v3.26,引擎级,三处同判:财报名单/候选池/DS 点名)。
    row 带 price / adv20_usd(fetchers._derive 实测:价格=末根收盘;成交额=前 20 根 close×volume 均值)。
    返回 None=过地板,否则一句筛除条款。无实测 = 不过(不装数):没有成交额读数的票不进推荐。"""
    pf, af = fetchers.pool_price_floor(), fetchers.pool_adv_floor_usd()
    px, adv = row.get("price"), row.get("adv20_usd")
    if px is None:
        return "无价格实测"
    if px < pf:
        return "price $%.2f<$%g 地板" % (px, pf)
    if adv is None:
        return "20日成交额无实测(样本%s根<5)" % (row.get("adv20_days") if row.get("adv20_days") is not None else "?")
    if adv < af:
        return "20日成交额 $%.0fM<$%.0fM 地板" % (adv / 1e6, af / 1e6)
    return None


def floor_earnings_lists(cross):
    """财报三名单过引擎地板(v3.26,PICS 案:$5 级 AMC 票靠"名单前三须点名"规则被 DS 点成 S2 RANK 2,
    流动性"无实测"照样出卡)。amc_tonight / bmo_tomorrow / upcoming_earnings 就地改为幸存者,
    筛除者进 cross["floor_rejected"][名单] 逐票带条款(渲染/复盘可审,不无痕)。"""
    rej = cross.setdefault("floor_rejected", {})
    board = fmp_board_syms(cross)   # v3.27.1:FMP 当日涨榜/最活跃榜(收涨)= 资金确认
    for k in ("amc_tonight", "bmo_tomorrow", "upcoming_earnings"):
        rows = cross.get(k)
        if not isinstance(rows, list):
            continue
        keep, drop = [], []
        for x in rows:
            if not isinstance(x, dict):
                keep.append(x)
                continue
            cl = _floor_clause(x)
            if cl:
                drop.append({"symbol": x.get("symbol"), "clause": cl, "price": x.get("price")})
            else:
                x["fmp_board"] = x.get("symbol") in board      # v3.29:只标记(资金已由 F1 计),不再加分
                keep.append(x)
        cross[k] = _sort_earn(keep)
        rej[k] = drop
    return cross


def fmp_board_syms(cross):
    """FMP 当日"钱的榜":涨幅榜(gainers 侧)∪ 最活跃榜中当日收涨者。Lyra 2026-08-25:测出来的票不在 FMP top mover 榜
    = 不收。作为财报 call 腿的硬门与名单加分的判据;两榜都失败时返回空集(下游作废条款会写明"榜缺失")。"""
    out = set()
    for x in (cross.get("market_movers") or []):
        if isinstance(x, dict) and x.get("side") == "gainers" and x.get("symbol"):
            out.add(str(x["symbol"]).upper())
    for x in (cross.get("most_active") or []):
        if isinstance(x, dict) and x.get("symbol") and (x.get("chg_pct") or 0) > 0:
            out.add(str(x["symbol"]).upper())
    for x in (cross.get("trend_board") or []):      # v3.28:自算趋势榜同为"钱的榜"
        if isinstance(x, dict) and x.get("symbol"):
            out.add(str(x["symbol"]).upper())
    return out


_TREND_CAP = 20


def regime_and_kelly(payload):
    """v3.29:VIX → 仓位档(满/半/停,只显示);复盘账本最近 20 份 → Kelly 分数(只显示)。"""
    m = {}
    for src in payload.get("results", payload.get("sources", [])):
        if src.get("source") in ("indices", "hedge_assets"):
            for it in src.get("items", []):
                if isinstance(it, dict) and it.get("name"):
                    m[it["name"]] = it
    vix = m.get("VIX") or {}
    tier, why = factors.regime_tier(vix.get("price") or vix.get("last"), vix.get("chg_pct"))
    hits = misses = 0
    try:
        files = sorted(f for f in os.listdir(os.path.join(OUT, "briefs")) if f.endswith("-review.json"))[-20:]
        for f in files:
            doc = json.load(open(os.path.join(OUT, "briefs", f), encoding="utf-8"))
            for leg in doc.get("legs") or []:
                if leg.get("hit") is True: hits += 1
                elif leg.get("hit") is False: misses += 1
    except Exception:
        pass
    frac, note = factors.kelly_fraction(hits, misses)
    return {"tier": tier, "why": why, "kelly_fraction": frac, "kelly_note": note, "hits": hits, "misses": misses}


def earnings_days_map(cross):
    """symbol → 距下一财报交易日数(0=今日 AMC,1=明日 BMO,其余按 upcoming days_out);F4 用。"""
    m = {}
    for x in (cross.get("amc_tonight") or []):
        if isinstance(x, dict) and x.get("symbol"):
            m[x["symbol"]] = 0
    for x in (cross.get("bmo_tomorrow") or []):
        if isinstance(x, dict) and x.get("symbol"):
            m.setdefault(x["symbol"], 1)
    for x in (cross.get("upcoming_earnings") or []):
        if isinstance(x, dict) and x.get("symbol") and x.get("days_out") is not None:
            m.setdefault(x["symbol"], int(x["days_out"]))
    return m


def _f5_cache_path(key):
    return os.path.join(OUT, "state", "f5-%s.json" % key)


def f5_batch(snaps, symbols, *, allow_afterhours=False):
    """F5:对一批候选取 Theta ATM call 的 gamma/|theta|,批内百分位。
    盘中 = 实时快照;盘外 = 读 16:45 盘后快照班落的 state/f5-<最近收盘日>.json(昨收 γ/|θ|,带 stale 标),
    两者都无 → None(因子缺,权重归一化,不装数)。返回 (sub_by_sym, raw_by_sym, source)。"""
    raws, source = {}, "live"
    if fetchers.is_rth_now() or allow_afterhours:
        for s_ in symbols:
            d = snaps.get(s_) or {}
            g = fetchers.theta_atm_call_greeks(s_, d.get("price"), allow_afterhours=allow_afterhours)
            raws[s_] = factors.f5_options_ratio(g)
    else:
        key = _last_closed_session(fetchers.trading_date().isoformat())
        try:
            doc = json.load(open(_f5_cache_path(key), encoding="utf-8"))
            cached = doc.get("ratios") or {}
            raws = {s_: cached.get(s_) for s_ in symbols}
            source = "eod:" + key
        except Exception:
            raws = {s_: None for s_ in symbols}
            source = "none"
    return factors.f5_options_batch(raws), raws, source


def f5_persist(key, raws, details=None):
    """盘后快照班(19:45 ET,当日快照仍在)把候选并集的 γ/|θ| 落盘,供次晨盘前/晚班趋势榜回退。"""
    try:
        os.makedirs(os.path.dirname(_f5_cache_path(key)), exist_ok=True)
        json.dump({"key": key, "ratios": raws, "details": details or {}, "n": sum(1 for v in raws.values() if v is not None)},
                  open(_f5_cache_path(key), "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def _last_closed_session(today, now_et=None):
    """趋势榜的键:最近一根已收盘日线的日期。判据 = ET 时刻是否已过 *today 这一天* 的 16:05,不是"现在几点"——
    21:00 PST 晚班的 ET 墙钟是次日 00:xx,trading_date 仍是 today;按"几点"判会把键错标成前一天
    (v3.28.2 自审抓获:那样晚班算的是昨日榜,次晨 06:45 又得重算 1200 票,"晚班算晨班共用"落空)。
    晚班(ET 次日 00:xx)→ today;次晨 06:45(ET 09:45,trading_date=次日)→ prev(次日)= today:同一键,零 GET。"""
    now_et = now_et or fetchers.now_et()
    cutoff = datetime.datetime.combine(datetime.date.fromisoformat(today), datetime.time(16, 5), tzinfo=now_et.tzinfo)
    if now_et >= cutoff:
        return today
    return fetchers.prev_trading_day(datetime.date.fromisoformat(today)).isoformat()


def trend_board(today):
    """v3.28(Lyra 2026-08-25:BMNR 涨了快一周从来不在榜上——FMP 涨幅榜按单日 % 排,壳票 +80% 占满;最活跃榜按
    股数排,$300 的票 $2B 成交额也进不了;两榜天生看不见"每天 +3%、连涨一周、成交额十亿"的趋势票):
    第七只眼,自算,不靠 FMP 榜——宇宙 = FMP screener 全市场普通股(日缓存)→ 历史日线快照(不打 quote,
    缓存新鲜零 GET)→ 硬地板(price/adv20,与候选池同判)→ 趋势分(整数,逐项落 json)→ cap 20。
    趋势分:近 5 日收涨 ≥4 根 +2(≥3 根 +1)/ 5 日 +5~+40% +2((2,5) +1;>40% +1 标追高)/ 10 日 ≥+10% +1 /
    RSI 55–80 +1(>85 -1)/ 放量 vol_x20≥1.2 +1 / 距 52 周高 ≥-10% +1 / 末根收高位 loc≥0.6 +1 / 末根收涨 +1;
    入榜最低 5 分(至少三路信号)。结果按 最近已收盘日 键落 state/trend_board-<日>.json,同日各班共用。
    可证伪:宇宙抓取失败 → 榜空并 skip 有条款;全宇宙不过地板 → 榜空;单日暴涨壳票不进(地板);连涨但成交额不足不进。"""
    key = _last_closed_session(today)
    path = os.path.join(OUT, "state", "trend_board-%s.json" % key)
    try:
        doc = json.load(open(path, encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("board"), list):
            return doc["board"], doc.get("universe_n", 0), doc.get("rejected_n", 0)
    except Exception:
        pass
    universe = fetchers.fetch_screener_universe()
    if not universe:
        return [], 0, 0
    snaps = fetchers.history_snapshot(universe, need_date=key)   # 缓存最新 bar 必须 ≥ 键日,否则重拉(晚班拉当日终盘)
    # 覆盖率自证:末根日期 = 键日的票占比。FMP 若尚未发布当日 EOD(晚班 00:xx ET 可能撞上),快照仍是前一日——
    # 此时算出的榜不得以当日键落盘,否则次晨读到的是陈榜且不会重算;不落盘、榜照用、日志响亮
    dated = sum(1 for d in snaps.values() if d.get("last_bar_date") == key)
    coverage = dated / max(1, len(snaps))
    board, rejected = [], 0
    # v3.29:趋势榜 = 因子核的趋势视角——F2(趋势子分)≥ TREND_F2_MIN(默认 60)且总分 ≥ TREND_MIN_SCORE(默认 55);
    # F5 盘外为空(晚班算),F4 用 upcoming 名单缺席时为 None——都按"因子缺"归一化,不装数
    min_score = int(os.getenv("TREND_MIN_SCORE", "55"))
    f2_min = float(os.getenv("TREND_F2_MIN", "60"))
    ind = fetchers.industry_lookup([s_ for s_ in universe if snaps.get(s_) and not _floor_clause(snaps[s_])])   # 只查过地板的票
    f5_sub, f5_raw, f5_src = f5_batch(snaps, [s_ for s_ in universe if snaps.get(s_) and not _floor_clause(snaps[s_])][:60])
    for sym in universe:
        d = snaps.get(sym)
        if not d or _floor_clause(d):
            rejected += 1
            continue
        info = ind.get(sym) if isinstance(ind.get(sym), dict) else {}
        if d.get("mcap_b") is None and info.get("mktcap_b"):
            d["mcap_b"] = info["mktcap_b"]
        if info.get("is_etf") is not False:            # 趋势榜同样禁 ETF/类型未证(screener 已粗筛,此处终判)
            rejected += 1
            continue
        fs = factors.score(d, f5_sub=f5_sub.get(sym), f5_raw=f5_raw.get(sym))
        f2 = fs["subs"].get("F2_trend")
        if f2 is not None and f2 >= f2_min and fs["score"] >= min_score:
            flags = []
            if (d.get("chg5_pct") or 0) > 40: flags.append("追高风险")
            if (d.get("rsi14") or 0) > 85: flags.append("过热")
            board.append({"symbol": sym, "trend_score": fs["score"], "trend_why": fs["why"], "subs": fs["subs"],
                          "price": d.get("price"), "chg5_pct": d.get("chg5_pct"), "chg10_pct": d.get("chg10_pct"),
                          "up5": d.get("up5"), "rsi14": d.get("rsi14"), "vol_x20": d.get("vol_x20"),
                          "adv20_musd": round((d.get("adv20_usd") or 0) / 1e6, 1), "flags": flags,
                          "asof": d.get("last_bar_date") or key})
        else:
            rejected += 1
    board.sort(key=lambda p: (-p["trend_score"], -(p["adv20_musd"] or 0), -(p["chg5_pct"] or 0)))
    board = board[:_TREND_CAP]
    print("[scout] 趋势榜键 %s:快照 %d/%d 末根=键日(覆盖 %.0f%%)" % (key, dated, len(snaps), coverage * 100))
    if coverage >= 0.5:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            json.dump({"key": key, "universe_n": len(universe), "rejected_n": rejected, "coverage": round(coverage, 3), "board": board},
                      open(path, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
    else:
        print("[scout] 趋势榜:当日 EOD 覆盖不足 50%%(FMP 未发布?),本次不落盘,下一班重算")
        fetchers._log_skip("trend_board", key, "当日 EOD 覆盖 %.0f%% <50%%,未落盘" % (coverage * 100))
    return board, len(universe), rejected


_POOL_CAP = 12


def candidate_pool(cross):
    """引擎候选池(v3.26,Lyra 2026-08-24:"冒烟测试的结果就没有到 Top Mover 榜?"):
    此前六眼(movers/最活跃/热簇/同频簇/连涨/自选)只作"参考"喂 DS,S1 由 DS 自由挑——
    8-24 财报班挑了热簇里 +1.77% 的 PATH 做 10 分钟 0DTE,BMNR(最活跃+🔥团)没进卡。
    现改确定性:宇宙=六眼并集 → 逐票实测(quote_layer 缓存)→ 硬地板(price/20 日成交额)→
    透明计分(每分一眼可查)→ 排序 cap 12。S1 只能从池内取,池前三必须逐票评估。
    计分(整数,score_why 逐项落 json):最活跃榜且当日收涨 +3(钱的直接测量;未收涨只 +1 并标"当日未收涨")/
    🔥同频团成员 +2 / 🔥热簇成员 +1 / 异动榜 +1 / 当日 +2%~+20% +2,(0,2%) +1,>20% +2 并标"追高风险" /
    连涨榜 +1 / 距 52 周高 <5% +1 / close_loc≥0.7 +1 / vol_x20≥1.5 +1 / 自选 +1;
    rsi14>75 只标"过热"不扣分(机器不藏强票)。同分按 20 日成交额降序(流动性优先),再按当日涨幅。
    可证伪:宇宙全不过地板→池空且筛除逐票有条款;无读数票不进池;收跌的最活跃巨头不占前排。"""
    eyes = {}

    def see(sym, tag):
        s = str(sym or "").upper()
        if re.fullmatch(r"[A-Z]{1,5}", s):
            eyes.setdefault(s, set()).add(tag)

    for x in (cross.get("market_movers") or []):
        if isinstance(x, dict) and x.get("side") == "gainers":
            see(x.get("symbol"), "异动")
    for x in (cross.get("most_active") or []):
        if isinstance(x, dict):
            see(x.get("symbol"), "最活跃")
    for c in (cross.get("comove") or []):
        if c.get("hot"):
            for mm in (c.get("members") or []):
                see(mm.get("symbol"), "同频🔥")
    for t in (cross.get("theme_heat") or []):
        if t.get("hot"):
            for mm in (t.get("members") or []):
                see(mm.get("symbol"), "热簇🔥")
    for s in (cross.get("streak_board") or []):
        see(s, "连涨")
    for x in (cross.get("watchlist") or []):
        see(x.get("symbol") if isinstance(x, dict) else x, "自选")
    for t in (cross.get("trend_board") or []):      # v3.28 第七只眼:自算趋势榜(BMNR 案)
        see(t.get("symbol") if isinstance(t, dict) else t, "趋势🔥")
    universe = sorted(eyes)
    if not universe:
        return [], [], 0
    snaps = fetchers.quote_layer_snapshot(universe, with_rsi=True)
    # v3.26.1(Lyra 2026-08-24:"不可以进池…IV 200% & IV 你选哪个"):ETF 硬排——最活跃榜常年
    # 被 IBIT/BITO/TSLL/SOXL 占位,BMNR/ASST/CRCL 型高 IV 单票被挤出;判据=profile isEtf/isFund
    # (同一 profile 端点,industry_lookup 终身缓存);类型未证(profile 无回包/无该键)同样不入,响亮
    ind = fetchers.industry_lookup(universe)
    pool, rejected = [], []
    edays = earnings_days_map(cross)
    # v3.29:先过准入(ETF/读数/地板),再对幸存者批量取 F5(Theta 快照,盘外为空→因子缺)
    survivors = []
    for s in universe:
        d = snaps.get(s)
        info = ind.get(s) if isinstance(ind.get(s), dict) else {}
        if info.get("is_etf") is False and d and not _floor_clause(d):
            survivors.append(s)
    f5_sub, f5_raw, f5_src = (f5_batch(snaps, survivors[:40]) if survivors else ({}, {}, "none"))
    for s in universe:
        d = snaps.get(s)
        tags = eyes[s]
        info = ind.get(s) if isinstance(ind.get(s), dict) else {}
        if d and d.get("mcap_b") is None and info.get("mktcap_b"):
            d["mcap_b"] = info["mktcap_b"]          # v3.29.1:quote 缺市值时用 profile 市值(F1 换手率不退成交额档)
        ie = info.get("is_etf")
        if ie is True:
            rejected.append({"symbol": s, "clause": "ETF 不入池(IV 结构不适合单腿 call)", "eyes": sorted(tags)})
            continue
        if ie is None:
            rejected.append({"symbol": s, "clause": "类型未证(profile 无 isEtf 回包),不入池", "eyes": sorted(tags)})
            continue
        if not d:
            rejected.append({"symbol": s, "clause": "quote_layer 无读数(FMP+Alpaca miss)",
                             "eyes": sorted(tags)})
            continue
        cl = _floor_clause(d)
        if cl:
            rejected.append({"symbol": s, "clause": cl, "price": d.get("price"), "eyes": sorted(tags)})
            continue
        chg = d.get("chg_pct")
        # v3.29:六因子核(factors.py),眼睛只决定谁进宇宙,不再各自加分——"来自哪张榜"不是经济因子
        fs = factors.score(d, days_to_earnings=edays.get(s), f5_sub=f5_sub.get(s), f5_raw=f5_raw.get(s))
        flags = []
        rsi = d.get("rsi14")
        if rsi is not None and rsi > 75:
            flags.append("RSI%.0f过热" % rsi)
        if (d.get("chg5_pct") or 0) > 40:
            flags.append("追高风险")
        if chg is not None and chg <= 0 and "最活跃" in tags:
            flags.append("当日未收涨")
        if fs["missing"]:
            flags.append("缺" + "/".join(k[:2] for k in fs["missing"]))
        elif f5_src.startswith("eod:"):
            flags.append("F5昨收")
        pool.append({"symbol": s, "score": fs["score"], "score_why": fs["why"], "subs": fs["subs"], "eyes": sorted(tags),
                     "price": d.get("price"), "chg_pct": chg,
                     "adv20_musd": round((d.get("adv20_usd") or 0) / 1e6, 1),
                     "mcap_b": d.get("mcap_b"), "rsi14": rsi, "close_loc": d.get("close_loc"),
                     "vol_x20": d.get("vol_x20"), "high52_dist_pct": d.get("high52_dist_pct"),
                     "chg5_pct": d.get("chg5_pct"), "days_to_earnings": edays.get(s), "flags": flags})
    # v3.29:入池最低分 POOL_MIN_SCORE(0–100 因子分,默认 45);低分票进筛除行带 score_why,不无痕
    min_score = int(os.getenv("POOL_MIN_SCORE", "45"))
    weak = [p for p in pool if p["score"] < min_score]
    for p in weak:
        rejected.append({"symbol": p["symbol"], "clause": "score %d<%d 入池最低分(%s)" % (p["score"], min_score, p["score_why"]),
                         "price": p["price"], "eyes": p["eyes"]})
    pool = [p for p in pool if p["score"] >= min_score]
    pool.sort(key=lambda p: (-p["score"], -(p["adv20_musd"] or 0), -(p["chg_pct"] or 0)))
    return pool[:_POOL_CAP], rejected, len(universe)


def apply_quality_floor(data, shift, cross):
    """DS 点名过引擎地板(v3.26,代码闸,会改卡——此前三闸只盖章,PICS 无实测照出卡):
    ① 非空候选卡逐票实测(quote_layer memo,tape_check 已预热零增量)——price<地板 /
       20 日成交额<地板 / 无实测 = 卡作废:改 empty=true,empty_reason 带 ticker+条款,
       原卡整份存 _floor_killed,并列 ds["_floor_kills"];no_candidate_reason 追加逐票条款
       (规则 B"空槽唯一合法理由=质量地板"由此可审);
    ② S1 视野核对:ticker 不在 candidate_pool = 盖章 _pool_check="视野外点名"(不作废,
       机器不藏强票;DS 违反"S1 池内取"的事实留痕);
    ③ 财报班 S2/S4:ticker 必须在地板后的 amc_tonight/bmo_tomorrow/upcoming_earnings 名单内,
       否则作废(财报腿必须日历实证;名单外 = 训练记忆点名或已被地板筛除);
    ④ 财报班 S1/S3 = 明晨预排观察卡:note 前缀"明晨预排,不建仓"由引擎补齐(复盘按此不计命中)。
    对冲腿不过本闸(工具白名单另有规则)。"""
    if shift not in ("morning", "midday", "earnings") or not isinstance(data, dict):
        return data
    cands = data.get("candidates") or []
    pool_syms = {p.get("symbol") for p in (cross.get("candidate_pool") or []) if isinstance(p, dict)}
    earn_syms = set()
    for k in ("amc_tonight", "bmo_tomorrow", "upcoming_earnings"):
        earn_syms |= {(x.get("symbol") if isinstance(x, dict) else x) for x in (cross.get(k) or [])}
    kills = []
    live = [str(c.get("ticker") or "").upper() for c in cands
            if isinstance(c, dict) and not c.get("empty") and c.get("slot") in (1, 3)]
    ind = fetchers.industry_lookup([t for t in live if re.fullmatch(r"[A-Z]{1,5}", t)]) if live else {}
    for c in cands:
        if not isinstance(c, dict) or c.get("empty"):
            continue
        t = str(c.get("ticker") or "").upper()
        slot = c.get("slot")
        if not re.fullmatch(r"[A-Z]{1,5}", t):
            # v3.26.3(戌 8-24 抓:"PICS,TUYA,GRRR"逗号票绕过质量闸——闸只认单票,并一起就跳过):
            # 非单一代码一律作废,一卡一票
            clause = "非单一代码 '%s'(逗号票/格式错),一卡一票,整卡作废" % t[:30]
            kills.append({"slot": slot, "ticker": t[:30], "clause": clause})
            killed = dict(c)
            c.clear()
            c.update({"slot": slot, "slot_name": killed.get("slot_name"), "empty": True,
                      "empty_reason": "引擎地板作废 %s:%s" % (t[:30], clause), "_floor_killed": killed})
            print("[scout] 引擎地板作废 S%s %s:%s" % (slot, t[:30], clause))
            continue
        d = (fetchers.quote_layer_snapshot([t], with_rsi=True) or {}).get(t)
        if not d:
            clause = "quote_layer 无读数(FMP+Alpaca miss)"
        else:
            clause = _floor_clause(d)
            c["floor_check"] = {"price": d.get("price"),
                                "adv20_musd": (round(d["adv20_usd"] / 1e6, 1) if d.get("adv20_usd") else None),
                                "verdict": clause or "过地板"}
        if clause is None and slot in (1, 3):   # v3.26.1:S1/S3 点名 ETF = 作废(池已硬排,DS 绕不过)
            ie = (ind.get(t) or {}).get("is_etf") if isinstance(ind.get(t), dict) else None
            if ie is True:
                clause = "ETF 不入候选(IV 结构不适合单腿 call;对冲/迁徙工具走 hedge 腿)"
        if clause is None and shift == "earnings" and slot in (2, 4) and t not in earn_syms:
            clause = "不在引擎财报名单(地板后 amc/bmo/run-up 三单),财报腿禁名单外点名"
        if clause is None and d:
            # v3.27(8-25 INTU 案:引擎量到 日-2.92% loc0.17 印在卡上,卡照发,盘后 -7%):
            # 方向与尾盘形态错配 = 作废。call:当日 ≤-1% 且 loc<0.5;put:当日 ≥+1% 且 loc>0.5。
            # 阈值 env TAPE_VETO_CHG / TAPE_VETO_LOC;盘中班用的是盘中读数,同判(动量不做逆势票)
            vc = float(os.getenv("TAPE_VETO_CHG", "1.0")); vl = float(os.getenv("TAPE_VETO_LOC", "0.5"))
            chg_, loc_ = d.get("chg_pct"), d.get("close_loc")
            dirn = str(c.get("direction") or "").lower()
            if chg_ is not None and loc_ is not None:
                if dirn == "call" and chg_ <= -vc and loc_ < vl:
                    clause = "形态错配:call 不做弱势收低票(日%+.2f%%, loc %.2f)" % (chg_, loc_)
                elif dirn == "put" and chg_ >= vc and loc_ > vl:
                    clause = "形态错配:put 不做强势收高票(日%+.2f%%, loc %.2f)" % (chg_, loc_)
        if clause is None and shift == "earnings" and slot in (2, 4) and str(c.get("direction") or "").lower() == "call":
            board = fmp_board_syms(cross)
            if t not in board:   # v3.27.1(Lyra 8-25:不在 FMP top mover 榜的不收)
                clause = ("不在当日榜(FMP 涨幅榜/最活跃收涨/自算趋势榜),财报 call 腿无资金确认"
                          + ("" if board else ";且本班三榜为空(源失败),不装数"))
        if clause:
            kills.append({"slot": slot, "ticker": t, "clause": clause})
            killed = dict(c)
            c.clear()
            c.update({"slot": slot, "slot_name": killed.get("slot_name"), "empty": True,
                      "empty_reason": "引擎地板作废 %s:%s" % (t, clause),
                      "_floor_killed": killed})
            print("[scout] 引擎地板作废 S%s %s:%s" % (slot, t, clause))
            continue
        if slot == 1 and pool_syms and t not in pool_syms:
            c["_pool_check"] = "视野外点名(不在引擎候选池,规则=S1 池内取)"
        if shift == "earnings" and slot in (1, 3):
            note = str(c.get("note") or "")
            if "明晨预排" not in note:
                c["note"] = ("明晨预排,不建仓;" + note) if note else "明晨预排,不建仓"
    if kills:
        data["_floor_kills"] = kills
        extra = "; ".join("%s(%s)" % (k["ticker"], k["clause"]) for k in kills)
        ncr = str(data.get("no_candidate_reason") or "")
        data["no_candidate_reason"] = (ncr + "; " if ncr else "") + "[引擎地板作废] " + extra
    return data


def _scout_bark(shift, today, ds):
    """班次 Bark 推送(戌 8-21 现场加,守恒回流重写:certifi 上下文替代 unverified)。
    推:班次+日期+非空卡数+候选 ticker+违例。DOCTOR_BARK_URL 未配置=静默跳过。"""
    url = os.getenv("DOCTOR_BARK_URL", "").strip().rstrip("/")
    if not url or not isinstance(ds, dict):
        return
    try:
        cands = ds.get("candidates") or []
        ne = [c for c in cands if not c.get("empty")]
        tickers = ",".join((c.get("ticker") or "?") for c in ne) or "无"
        vio = ds.get("_floor_violation") or []
        title = "[SCOUT] %s %s 非空卡%d" % (shift, today, len(ne))
        body = "候选:%s" % tickers + (";违例:%s" % "|".join(vio)[:200] if vio else "")
        import urllib.parse
        full = "%s/%s/%s?group=scout-brief" % (url, urllib.parse.quote(title), urllib.parse.quote(body))
        req = urllib.request.Request(full, method="GET")
        with urllib.request.urlopen(req, timeout=10, context=fetchers._ssl_context()) as r:
            r.read()
        print("[scout] 班次 bark 已推")
    except Exception as e:
        print("[scout] 班次 bark 失败(不阻塞):", str(e)[:120])


def _sight_watch_syms(cross):
    """全视野器官的 watch 汇入(复盘跟踪,不计命中)。"""
    syms = set()
    for t in (cross.get("theme_heat") or []):
        if t.get("hot"):
            syms |= {m["symbol"] for m in t.get("members", []) if m.get("symbol")}
    syms |= set(cross.get("streak_board") or [])
    for c in (cross.get("comove") or []):
        if c.get("hot"):
            syms |= {mm["symbol"] for mm in c.get("members", []) if mm.get("symbol")}
    return syms


def build_review(date, suffix=""):
    """确定性复盘(晚班 21:00 跑,拿全日K线):读当日晨会 json,逐腿取收盘涨跌/
    close_loc/RSI14,判方向命中。口径如实:收盘对昨收判定,非盘中入场路径复现。"""
    # v3.25:三班合并复盘——当日 morning/midday/earnings 各班在案腿全部进复盘,
    # 腿按 (ticker,direction) 去重取首见;影子 lane(suffix)仅晨班,口径不变。
    shifts = ("morning", "midday", "earnings") if not suffix else ("morning",)
    docs = []
    for sh in shifts:
        p = os.path.join(OUT, "briefs", "%s-%s%s.json" % (date, sh, suffix))
        if os.path.exists(p):
            try:
                docs.append((sh, json.load(open(p, encoding="utf-8"))))
            except Exception:
                pass
    if not docs:
        return None
    # v3.16 合流:watch 名单(amc_tonight/movers/bmo)结构性进复盘——TEAM 零复盘痕迹的根修;
    # 仅观察,不计命中率
    wset = set()
    legs = []
    seen = set()
    rejected_all = []
    for sh, doc in docs:
        ds = doc.get("ds") or doc
        eng = doc.get("_engine") or {}
        for k in ("amc_tonight", "earnings_movers", "bmo_tomorrow", "market_movers",
                  "most_active", "watchlist"):
            wset |= {((x.get("symbol") if isinstance(x, dict) else x) or "").upper()
                     for x in (eng.get(k) or [])}
        wset |= _sight_watch_syms(eng)   # 热主题成员+streak 榜进复盘 watch(v3.25.8)
        for l in (ds.get("candidates") or []):
            note_all = "%s %s" % (l.get("note") or "", (l.get("strategy") or {}).get("note") or "")
            if "AMC 初筛观察" in note_all or "明晨预排" in note_all:   # v3.26:财报班预排卡同判
                w0 = str(l.get("ticker") or "").upper()
                if re.fullmatch(r"[A-Z]{1,5}", w0):
                    wset.add(w0)          # 初筛观察卡:进 watch,不进命中账(v3.25.6)
                continue
            key = ("c", (l.get("ticker") or "").upper(), (l.get("direction") or "call").lower())
            if key in seen:
                continue
            seen.add(key)
            legs.append(dict(l, _src="candidate", _shift=sh))
        for l in ((ds.get("hedge") or {}).get("legs") or []):
            key = ("h", (l.get("ticker") or "").upper(), (l.get("direction") or "call").lower())
            if key in seen:
                continue
            seen.add(key)
            legs.append(dict(l, _src="hedge", _shift=sh))
        rejected_all += (ds.get("rejected") or [])
    watch = sorted(w for w in wset if re.fullmatch(r"[A-Z]{1,5}", w))
    out = []
    for l in legs:
        t = (l.get("ticker") or "").upper()
        if l.get("empty") or not t:
            continue          # 空槽卡合法,静默跳过
        if not re.fullmatch(r"[A-Z]{1,5}", t):
            print("[scout] 复盘跳过非常规代码:", t)
            continue
        d = fetchers._stooq_daily(t.lower() + ".us", t, "review")
        if not d:
            continue
        direction = (l.get("direction") or "call").lower()
        chg = d.get("chg_pct") or 0
        out.append({"ticker": t, "direction": direction, "src": l.get("_src", "candidate"),
                    "shift": l.get("_shift", "morning"),
                    "chg_pct": d.get("chg_pct"),
                    "close_loc": d.get("close_loc"), "rsi14": d.get("rsi14"),
                    "hit": chg > 0 if direction == "call" else chg < 0})
    rej_out = []
    rej_seen = set()
    for r0 in rejected_all:
        if (r0.get("ticker") or "").upper() in rej_seen:
            continue
        rej_seen.add((r0.get("ticker") or "").upper())
        t = (r0.get("ticker") or "").upper()
        if not re.fullmatch(r"[A-Z]{1,5}", t or ""):
            continue
        d0 = fetchers._stooq_daily(t.lower() + ".us", t, "review_rejected")
        if d0:
            chg0 = d0.get("chg_pct")
            rej_out.append({"ticker": t, "chg_pct": chg0, "reason": r0.get("reason"),
                            "flag_misskill": (chg0 or 0) > 2.0})   # 被否却涨>2% = 疑误杀,晚报必点评
    if not out:
        return None
    cand = [x for x in out if x.get("src", "candidate") == "candidate"]
    nh = sum(1 for x in cand if x["hit"])
    rev = {"date": date, "legs": out, "rejected_review": rej_out,
           "watch": watch,
           "hit": "%d/%d" % (nh, len(cand)) if cand else "0/0",
           "hit_rate": round(nh / len(cand), 2) if cand else None,
           "basis": "收盘对昨收判定方向命中(仅候选腿计入;对冲腿分账;watch 段仅观察不计命中率);非盘中入场路径复现"}
    os.makedirs(os.path.join(OUT, "briefs"), exist_ok=True)
    with open(os.path.join(OUT, "briefs", "%s-review%s.json" % (date, suffix)), "w", encoding="utf-8") as f:
        json.dump(rev, f, ensure_ascii=False, indent=1)
    return rev


def load_prev_review(today):
    # v3.22 同族第二处:rolling 已滤周末,此处不滤则周一"昨日战绩"仍会拿周六遗留假账
    files = [f for f in _review_files() if f[:10] < today
             and datetime.date.fromisoformat(f[:10]).weekday() < 5]
    if not files:
        return None
    return json.load(open(os.path.join(OUT, "briefs", files[-1]), encoding="utf-8"))


def rolling_summary(upto_incl):
    # v3.22:滚动剔除周末日期文件(历史遗留假腿自动失效),且只统计候选腿
    files = [f for f in _review_files() if f[:10] <= upto_incl
             and datetime.date.fromisoformat(f[:10]).weekday() < 5][-5:]
    tot = hit = 0
    for fn in files:
        r = json.load(open(os.path.join(OUT, "briefs", fn), encoding="utf-8"))
        for l in r.get("legs") or []:
            if l.get("src", "candidate") != "candidate":
                continue
            tot += 1
            hit += 1 if l.get("hit") else 0
    return {"days": len(files), "legs": tot,
            "hit_rate_pct": round(100 * hit / tot, 1) if tot else None} if files else None


def earnings_movers(payload, today):
    """确定性财报异动榜(堵 TEAM 案例:昨夜 AMC 暴涨 31% 晨会却推原油):
    昨日 AMC + 今日 BMO 财报名单逐个取盘初 tape,按 |chg| 排序前8——
    最大 catalyst 从此结构性可见,数字出引擎解读归 DS。"""
    yd = fetchers.prev_trading_day(datetime.date.fromisoformat(today)).isoformat()   # 跳周末:周一看上周五 AMC
    syms = []
    for src in payload.get("results", payload.get("sources", [])):
        if src.get("source") == "earnings_calendar":
            for it in src.get("items", []):
                sym = (it.get("symbol") or "").upper()
                if not re.fullmatch(r"[A-Z]{1,5}", sym):
                    continue
                d, when = it.get("date"), (it.get("when") or "")
                if d == yd and "after" in when:
                    syms.append((sym, "昨日AMC"))
                elif d == today and "pre" in when:
                    syms.append((sym, "今日BMO"))
    out = []
    # 中游 cap 20→30:上游热日解封后此处仍 20 = 盲区挪层(同族第三处,守恒补刀);
    # 30 次 stooq 取数是上限兜底,榜单仍只出前 8
    for sym, tag in syms[:30]:
        r = fetchers._stooq_daily(sym.lower() + ".us", sym, "earnings_movers")
        if r and r.get("chg_pct") is not None:
            out.append({"symbol": sym, "when": tag, "chg_pct": r["chg_pct"],
                        "vol_x20": r.get("vol_x20"),
                        "close_loc": r.get("close_loc"), "rsi14": r.get("rsi14")})
    out.sort(key=lambda x: -abs(x["chg_pct"]))
    return out[:8]


def amc_tonight(payload, today):
    """确定性名单:今日 AMC(今晚盘后出财报)——晨会时财报未出,不进 movers 硬闸;
    显式喂 DS 供手册第二步(run-up)评估,并上引擎卡。日历本身按市值排序,取前10。"""
    out = []
    for src in payload.get("results", payload.get("sources", [])):
        if src.get("source") == "earnings_calendar":
            for it in src.get("items", []):
                sym = (it.get("symbol") or "").upper()
                if it.get("date") == today and "after" in (it.get("when") or "") \
                        and re.fullmatch(r"[A-Z]{1,5}", sym):
                    out.append(sym)
    # "已出结果者"的判定 = 名单本身(21:00 PST 跑晚班时今日 AMC 基本已全部披露)。
    # 禁止从数据里"侦测谁出了结果"——stooq 没有那个信号,任何侦测都是编。
    # 以后的窗口不要在这里加机制(隔壁 Fable 定,守恒盖章)。
    # v3.16.2 合流:cap 15→30——TEAM 型中盘曾被裁在名单口上(verify 契约)
    out = out[:30]
    # v3.18:逐票附实测读数(rsi14/5日累计涨幅)——S2(b) 尾盘伏击与双杀排除的数据基
    rich = []
    for sym in out:
        r = fetchers._stooq_daily(sym.lower() + ".us", sym, "amc_tonight")
        rich.append(_leg_tier({"symbol": sym, "rsi14": (r or {}).get("rsi14"),
                     "chg5_pct": (r or {}).get("chg5_pct"), "chg_pct": (r or {}).get("chg_pct"),
                     "price": (r or {}).get("price"), "adv20_usd": (r or {}).get("adv20_usd"),
                     "close_loc": (r or {}).get("close_loc"), "vol_x20": (r or {}).get("vol_x20"),
                     "chg10_pct": (r or {}).get("chg10_pct"), "up5": (r or {}).get("up5"),
                     "dist_high20_pct": (r or {}).get("dist_high20_pct"), "mcap_b": (r or {}).get("mcap_b"),
                     "days_out": 0}))
    return _sort_earn(rich)   # v3.27:尾盘形态分排序,不按市值


def _leg_tier(row):
    """伏击名单档位标注(v3.25.3):run-up(chg5>0)/oversold(chg5<-2,WOLF/JBSS 型)/flat;
    dk_risk=双杀风险位(chg5>15 或 rsi>75)——v3.25.3 起不再机械禁入,亮牌交 Lyra 拍板。
    v3.27(2026-08-25 INTU 案:名单按市值序,DS 点了当日 -2.92%、loc 0.17 收在最低的 INTU 做持过财报 call,
    盘后 -7%;同名单 SMTC 当日 +5.4% 收高没被点)——名单改按 earn_score 排,尾盘形态是财报腿的全部论据:
    收高位 loc≥0.7 +2 / loc<0.3 -2;当日 ≥+1% +1 / ≤-1% -2;5 日 +2~+15% +1 / <-5% -1;
    rsi14 50-70 +1 / >75 -1 / <40 -1;放量 vol_x20≥1.3 且当日收涨 +1;dk_risk -1。earn_why 逐项落 json。"""
    c5, rsi = row.get("chg5_pct"), row.get("rsi14")
    row["tier"] = ("oversold" if (c5 is not None and c5 < -2)
                   else ("run-up" if (c5 is not None and c5 > 0) else "flat"))
    row["dk_risk"] = bool((c5 is not None and c5 > 15) or (rsi is not None and rsi > 75))
    # v3.29:财报名单同一因子核(F4 = days_out;当日 AMC = 0 只准预排);0–100
    fs = factors.score(row, days_to_earnings=row.get("days_out"))
    row["earn_score"], row["earn_why"], row["subs"] = fs["score"], fs["why"], fs["subs"]
    return row


def _sort_earn(rows):
    """财报名单排序:earn_score 降序,同分按 20 日成交额降序(v3.27,替代市值序)。"""
    return sorted(rows, key=lambda x: (-(x.get("earn_score") if x.get("earn_score") is not None else -99),
                                       -(x.get("adv20_usd") or 0)))


def _next_trading_day(today):
    d = datetime.date.fromisoformat(today) + datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d.isoformat()


def bmo_tomorrow(payload, today):
    """确定性名单:明日 BMO(明晨盘前出财报)——v3.25 新腿名单源(Lyra 拍板 2026-08-19,
    EL 案根治:吃 BMO 票只能前一日尾盘买入持过夜)。when 实值按 V6 取证:
    time-pre-market / time-after-hours / time-not-supplied——匹配 pre-market,不猜别名。
    日历本身按市值排序,cap 30,逐票附实测读数(双杀排除的数据基)。"""
    nd = _next_trading_day(today)
    out = []
    for src_ in payload.get("results", payload.get("sources", [])):
        if src_.get("source") == "earnings_calendar":
            for it in src_.get("items", []):
                sym = (it.get("symbol") or "").upper()
                if it.get("date") == nd and "pre-market" in (it.get("when") or "") \
                        and re.fullmatch(r"[A-Z]{1,5}", sym):
                    out.append(sym)
    out = list(dict.fromkeys(out))[:30]
    rich = []
    for sym in out:
        r = fetchers._stooq_daily(sym.lower() + ".us", sym, "bmo_tomorrow")
        rich.append(_leg_tier({"symbol": sym, "rsi14": (r or {}).get("rsi14"),
                     "chg5_pct": (r or {}).get("chg5_pct"), "chg_pct": (r or {}).get("chg_pct"),
                     "price": (r or {}).get("price"), "adv20_usd": (r or {}).get("adv20_usd"),
                     "close_loc": (r or {}).get("close_loc"), "vol_x20": (r or {}).get("vol_x20"),
                     "chg10_pct": (r or {}).get("chg10_pct"), "up5": (r or {}).get("up5"),
                     "dist_high20_pct": (r or {}).get("dist_high20_pct"), "mcap_b": (r or {}).get("mcap_b"),
                     "days_out": 1}))
    return _sort_earn(rich)   # v3.27:尾盘形态分排序,不按市值


def upcoming_earnings(payload, today):
    """确定性名单:未来 1-8 个交易日财报(run-up 窗)——S2a 腿的引擎供数。
    EL 案根修第二半:EL 08-15 起就在日历(V2 取证),但该腿此前只有 prompt 规则、
    没有引擎名单,数百行原始日历被 _slim_raw 预算裁剪,DS 结构性看不见。
    v3.26.2(NVDA 周案,Lyra"财报再好好测"):旧版整日剔除次一交易日——次日 BMO 归 bmo_tomorrow
    没错,但次日 AMC 票(周二班看周三盘后的 NVDA)三张名单都不在,财报班结构性看不见;
    现只剔除次日 pre-market,次日 AMC/未注明作 1 日 run-up 入名单,days_out 逐票标注
    (1 = 明日盘后出,只有一个交易日的 run-up 窗,公布前必须离场)。
    市值降序 cap 12,全票附实测读数(付费档+缓存)。"""
    d = datetime.date.fromisoformat(today)
    win, step = {}, d
    for k in range(1, 9):
        step = datetime.date.fromisoformat(_next_trading_day(step.isoformat()))
        win[step.isoformat()] = k
    nd = _next_trading_day(today)
    rows = []
    for src_ in payload.get("results", payload.get("sources", [])):
        if src_.get("source") == "earnings_calendar":
            for it in src_.get("items", []):
                sym = (it.get("symbol") or "").upper()
                dt, when = it.get("date"), (it.get("when") or "")
                if dt in win and re.fullmatch(r"[A-Z]{1,5}", sym):
                    if dt == nd and "pre-market" in when:
                        continue                   # 次日 BMO 归 bmo_tomorrow 腿
                    mc = fetchers._parse_money(it.get("marketCap")) or 0
                    rows.append({"symbol": sym, "date": dt, "when": when,
                                 "days_out": win[dt], "_mc": mc})
    # v3.26.2:近窗(days_out≤2,可执行的 run-up 窗)全保留,远窗(3-8 日)按市值另取 6——旧版整体
    # 按市值 cap 12,远窗巨头把明日盘后的中盘(OKTA 型)挤出名单;反向也不许:近窗塞满时远窗巨头
    # (BABA d4 型)整段消失。两窗各自有座位;地板在 floor_earnings_lists 再筛
    rows.sort(key=lambda x: (x["days_out"] > 2, -x["_mc"]))
    seen, out, far = set(), [], 0
    for x in rows:
        if x["symbol"] in seen:
            continue
        if x["days_out"] > 2:
            if far >= 6:
                continue
            far += 1
        seen.add(x["symbol"])
        out.append({k: v for k, v in x.items() if k != "_mc"})
    for x in out:   # v3.26:全票实测(付费档+缓存;地板要每票有价格/成交额读数)
        r = fetchers._stooq_daily(x["symbol"].lower() + ".us", x["symbol"], "upcoming_earnings")
        x.update({"rsi14": (r or {}).get("rsi14"), "chg5_pct": (r or {}).get("chg5_pct"),
                  "price": (r or {}).get("price"), "adv20_usd": (r or {}).get("adv20_usd"),
                  "chg_pct": (r or {}).get("chg_pct"), "close_loc": (r or {}).get("close_loc"),
                  "vol_x20": (r or {}).get("vol_x20"), "chg10_pct": (r or {}).get("chg10_pct"),
                  "up5": (r or {}).get("up5"), "dist_high20_pct": (r or {}).get("dist_high20_pct"),
                  "mcap_b": (r or {}).get("mcap_b")})
        _leg_tier(x)
    return _sort_earn(out)    # v3.27:近窗内按尾盘形态分排(days_out 仍逐票带)


def theme_heat(payload):
    """热簇·数据自聚(2026-08-21 二版,Lyra:禁写死范围——"万一下周热点不在这里了呢"。
    一版手写五主题表已拆除。热点由数据自己聚:
    宇宙 = 当日 movers 涨侧 ∪ most_active(自带实测涨跌)→ FMP profile 行业标签分组
    (industry_lookup 终身缓存)→ 同行业 ≥2 票且平均涨 ≥2%,或 ≥3 票且 ≥1.2% = 热簇。
    下周热点换到稀土/航运/生科,簇自己浮出来,零人工维护。cross 键名沿用 theme_heat。"""
    # 读法对齐 fetchers 真实落盘形状(顶层 items;movers 条目带 side)——
    # 2026-08-21 端到端首跑抓获:初版按想象形状读 data.gainers,真管线拿空。
    # 2026-08-24 现场首晚案:最活跃榜失败时簇宇宙只剩 movers 微盘尖峰,壳公司
    # +355% 挂🔥冒充"钱在流入"。修:①movers 侧 price≥5 才入簇宇宙(壳票出局,
    # movers 渲染行本身不受影响);②🔥资格必须资金确认——簇内至少一名成员在
    # 最活跃榜(成交额=钱的直接测量);最活跃榜空/失败=当班无簇可获🔥,不装。
    rows, actives_set = {}, set()
    for r in (payload.get("results") or []):
        if not r.get("ok"):
            continue
        if r.get("source") == "market_movers":
            for x in (r.get("items") or []):
                if (x.get("side") == "gainers" and x.get("symbol")
                        and x.get("chg_pct") is not None and (x.get("price") or 0) >= 5):
                    rows[x["symbol"]] = float(x["chg_pct"])
        elif r.get("source") == "most_active":
            for x in (r.get("items") or []):
                if x.get("symbol") and x.get("chg_pct") is not None:
                    rows.setdefault(x["symbol"], float(x["chg_pct"]))
                    actives_set.add(x["symbol"])
    if not rows:
        return []
    ind = fetchers.industry_lookup(sorted(rows))
    groups = {}
    for sym, chg in rows.items():
        tag = (ind.get(sym) or {}).get("industry") or (ind.get(sym) or {}).get("sector")
        if not tag:
            continue
        groups.setdefault(tag, []).append({"symbol": sym, "chg_pct": round(chg, 2)})
    out = []
    for tag, members in groups.items():
        chgs = [mm["chg_pct"] for mm in members]
        avg = round(sum(chgs) / len(chgs), 2)
        n = len(members)
        money = any(mm["symbol"] in actives_set for mm in members)
        out.append({"theme": tag, "n": n, "avg_chg": avg,
                    "up_ratio": round(sum(1 for c in chgs if c > 0) / n, 2),
                    "hot": bool(money and ((n >= 2 and avg >= 2.0) or (n >= 3 and avg >= 1.2))),
                    "money_confirmed": money,
                    "members": sorted(members, key=lambda mm: mm["chg_pct"], reverse=True)})
    out.sort(key=lambda t: (t["hot"], t["n"], t["avg_chg"]), reverse=True)
    return out[:12]


def _pearson(a, b):
    n = min(len(a), len(b))
    if n < 6:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb)


def _max_cliques(nodes, edges):
    """Bron–Kerbosch(带枢轴):极大团枚举。宇宙 ~40 节点,规模无忧。"""
    out = []
    def bk(R, P, X):
        if not P and not X:
            if len(R) >= 3:
                out.append(set(R))
            return
        pivot = max(P | X, key=lambda v: len(edges[v] & P), default=None)
        for v in list(P - (edges[pivot] if pivot else set())):
            bk(R | {v}, P & edges[v], X & edges[v])
            P = P - {v}
            X = X | {v}
    bk(set(), set(nodes), set())
    return out


def comove_clusters(payload):
    """同频簇(2026-08-24 四版,三路云审后收刀:GLM 主刀+DS 语义+Kimi 堵连坐)。
    立法:"这些票在一起动"=两两都在动,不是"在同一个朋友圈"(DS 语)——
    连通分量是传递闭包,FSTB 能靠中间人挂上 NVDA,已废。现定义:
    · 簇 = 极大团(clique):任意两成员 10 日日收益 ρ≥0.7,贪心取不相交团;
    · cohesion = 团内全对全 ρ 均值(团定义下无隐藏对,不再虚报);
    · money = ≥2 名成员在最活跃榜(单只常驻巨头不再一人连坐确认全簇,Kimi 案);
    · hot = money 且 当日中位数 chg≥1.5% 且 ≥60% 成员 chg≥1.5%(均值废,
      FSTB +2021% 单票拉爆均值案);
    · members 全量入 json,渲染截断必须响亮标 k/n(展示层禁撒谎)。
    可证伪不变:链式不成簇、无共振输出空、不相关同 sector 被拒。"""
    rows, actives_set = {}, set()
    for r in (payload.get("results") or []):
        if not r.get("ok"):
            continue
        if r.get("source") == "market_movers":
            for x in (r.get("items") or []):
                if (x.get("side") == "gainers" and x.get("symbol")
                        and x.get("chg_pct") is not None and (x.get("price") or 0) >= 5):
                    rows[x["symbol"]] = float(x["chg_pct"])
        elif r.get("source") == "most_active":
            for x in (r.get("items") or []):
                if x.get("symbol") and x.get("chg_pct") is not None:
                    rows.setdefault(x["symbol"], float(x["chg_pct"]))
                    actives_set.add(x["symbol"])
    if len(rows) < 3:
        return []
    rets, rho = {}, {}
    for sym in sorted(rows):
        try:
            closes = fetchers.quote_layer_bars(sym, limit=13) or []
        except Exception:
            closes = []
        if len(closes) >= 8:
            rets[sym] = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))][-10:]
    syms = sorted(rets)
    edges = {s: set() for s in syms}
    for i, a in enumerate(syms):
        for b in syms[i + 1:]:
            r_ = _pearson(rets[a], rets[b])
            rho[(a, b)] = r_
            if r_ is not None and r_ >= 0.7:
                edges[a].add(b)
                edges[b].add(a)
    cliques = _max_cliques(syms, edges)
    def _coh(c):
        cs = sorted(c)
        ps = [rho.get((a, b)) or rho.get((b, a)) or 0
              for i2, a in enumerate(cs) for b in cs[i2 + 1:]]
        return round(sum(ps) / len(ps), 2) if ps else None
    cliques.sort(key=lambda c: (len(c), _coh(c) or 0), reverse=True)
    used, clusters = set(), []
    for c in cliques:
        if c & used:
            continue
        used |= c
        members = sorted(({"symbol": x, "chg_pct": rows[x]} for x in c),
                         key=lambda mm: mm["chg_pct"], reverse=True)
        chgs = sorted(mm["chg_pct"] for mm in members)
        med = chgs[len(chgs) // 2] if len(chgs) % 2 else (chgs[len(chgs) // 2 - 1] + chgs[len(chgs) // 2]) / 2
        share = sum(1 for v in chgs if v >= 1.5) / len(chgs)
        money = sum(1 for mm in members if mm["symbol"] in actives_set) >= 2
        ind = fetchers.industry_lookup(sorted(c))
        clusters.append({"n": len(c), "cohesion": _coh(c),
                         "avg_chg": round(sum(chgs) / len(chgs), 2),
                         "med_chg": round(med, 2), "share_up": round(share, 2),
                         "money": money,
                         "hot": bool(money and med >= 1.5 and share >= 0.6),
                         "industries": sorted({((ind.get(x) or {}).get("industry") or "?") for x in c}),
                         "members": members})
    clusters.sort(key=lambda c: (c["hot"], c["n"], c["med_chg"]), reverse=True)
    return clusters[:3]


def most_active_health(payload):
    """最活跃榜健康态(2026-08-24 立):失败/空必须在渲染里响亮报出,禁静默——
    资金确认腿断了要让人一眼看见,不能让簇段拿垃圾冒充信号。"""
    for r in (payload.get("results") or []):
        if r.get("source") == "most_active":
            if r.get("ok") and (r.get("items") or []):
                return None
            return r.get("error") or "ok 但空列表"
    return "raw 中无 most_active 源(爬虫未跑?)"


def most_active(payload):
    """最活跃榜提取(爬虫#13):热资金直测,cap 24。读法=fetchers 真实落盘顶层 items。"""
    for r in (payload.get("results") or []):
        if r.get("source") == "most_active" and r.get("ok"):
            return (r.get("items") or [])[:24]
    return []


def update_streaks(today, movers_rows, active_rows):
    """连涨/连续上榜账本:movers 榜抓尖峰抓不到三日稳步流(8-21 案),
    落盘每日榜单符号,近 3 日出现 ≥2 次者=streak 榜,补趋势盲区。"""
    p = os.path.join(OUT, "state", "movers_history.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        hist = json.load(open(p, encoding="utf-8"))
    except Exception:
        hist = {}
    hist[today] = sorted({(m.get("symbol") or "").upper()
                          for m in (movers_rows or []) + (active_rows or [])
                          if (m.get("chg_pct") or 0) > 0 and m.get("symbol")})
    hist = {k: hist[k] for k in sorted(hist)[-10:]}
    try:
        json.dump(hist, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        print("[scout] streak 账本写盘失败(不阻塞):", str(e)[:100])
    cnt = {}
    for d in sorted(hist)[-3:]:
        for s in hist.get(d, []):
            cnt[s] = cnt.get(s, 0) + 1
    return sorted([s for s, c in cnt.items() if c >= 2])


def load_watchlist():
    """交易员自选名单(可选附加层,非视野主体):ROOT/watchlist.txt 一行一票。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.txt")
    if not os.path.exists(p):
        return []
    try:
        return [l.strip().upper() for l in open(p, encoding="utf-8")
                if l.strip() and not l.strip().startswith("#")][:30]
    except Exception:
        return []


def market_movers(payload):
    """全市场异动榜提取(v3.25.2,Lyra 拍板 2026-08-20):raw market_movers 源 →
    |chg| 降序 cap 24。所有班消费:引擎行渲染 + DS prompt 申明 + 晚班复盘 watch 并入。
    MRNA/TEM/比特币板块型非财报大涨从此在数据层与每班视野内。"""
    rows = []
    for src_ in payload.get("results", payload.get("sources", [])):
        if src_.get("source") == "market_movers":
            for it in (src_.get("items") or []):
                if it.get("symbol") and it.get("chg_pct") is not None:
                    rows.append({"symbol": it["symbol"], "side": it.get("side"),
                                 "chg_pct": it["chg_pct"], "price": it.get("price"),
                                 "name": it.get("name")})
    rows.sort(key=lambda x: -abs(x["chg_pct"]))
    seen, out = set(), []
    for x in rows:
        if x["symbol"] in seen:
            continue
        seen.add(x["symbol"])
        out.append(x)
        if len(out) >= 24:
            break
    return out


def build_handover(today, prev):
    """昨夜交班块(v3.25 F1):过夜伏击腿 + 昨日 watch 的盘初实测。
    过夜腿识别 = 昨日各班 brief 候选里 earnings_note/note 含"持过财报"且非空槽。
    V1/复盘案根修:唯一合法过夜例外此前没有次日强制跟踪义务,ZTO 持过财报次日无人交班。"""
    legs, watch = [], []
    try:
        bdir = os.path.join(OUT, "briefs")
        files = [f for f in os.listdir(bdir)
                 if re.match(r"\d{4}-\d{2}-\d{2}-(morning|midday|earnings)\.json$", f)] if os.path.isdir(bdir) else []
        prev_days = sorted({f[:10] for f in files if f[:10] < today})
        pd = prev_days[-1] if prev_days else None
        if pd:
            for sh in ("morning", "midday", "earnings"):
                p = os.path.join(bdir, "%s-%s.json" % (pd, sh))
                if not os.path.exists(p):
                    continue
                try:
                    ds = (json.load(open(p, encoding="utf-8")) or {}).get("ds") or {}
                except Exception:
                    continue
                for c in (ds.get("candidates") or []):
                    st = c.get("strategy") or {}
                    note = "%s %s" % (st.get("earnings_note") or c.get("earnings_note") or "",
                                      c.get("note") or "")
                    t = str(c.get("ticker") or "").upper()
                    if t and not c.get("empty") and "持过财报" in note and re.fullmatch(r"[A-Z]{1,5}", t):
                        legs.append({"ticker": t, "from": "%s %s" % (pd, sh)})
    except Exception as e:
        print("[scout] 交班块构建异常(不阻塞):", e)
    if prev:
        watch = [w for w in (prev.get("watch") or []) if re.fullmatch(r"[A-Z]{1,5}", str(w))][:15]
    syms = sorted({l["ticker"] for l in legs} | set(watch))[:18]
    snaps = fetchers.quote_layer.snapshot(syms) if syms else {}

    def row(t):
        d = snaps.get(t) or {}
        return {"symbol": t, "chg_pct": d.get("chg_pct"), "rsi14": d.get("rsi14"),
                "close_loc": d.get("close_loc")}
    return {"overnight_legs": [dict(l, **row(l["ticker"])) for l in legs],
            "watch_tape": [row(t) for t in watch],
            "rule": "过夜腿必须首屏处置(gap-and-go 续持/开盘即走);watch 显著变化必须点名"}


def load_today_shifts(today, before):
    """当日已出班次的在案腿摘要——供盘中/财报班复核(v3.25)。"""
    order = ["morning", "midday", "earnings"]
    out = {}
    for sh in order[:order.index(before)] if before in order else []:
        p = os.path.join(OUT, "briefs", "%s-%s.json" % (today, sh))
        if not os.path.exists(p):
            continue
        try:
            ds = (json.load(open(p, encoding="utf-8")) or {}).get("ds") or {}
        except Exception:
            continue
        out[sh] = {"candidates": [{"ticker": c.get("ticker"), "slot": c.get("slot"),
                                   "direction": c.get("direction"), "empty": bool(c.get("empty"))}
                                  for c in (ds.get("candidates") or [])],
                   "conclusion": ds.get("conclusion")}
    return out


def afterhours_symbols(cross, today):
    """盘后查询名单(v3.25.2 COTY 案,v3.26.3 改地板后):amc_tonight 幸存者 ∪ 当日各班非空候选腿;
    "明晨预排"观察卡与 AMC 初筛卡不查(不是持仓腿)。"""
    syms = {(x["symbol"] if isinstance(x, dict) else x) for x in (cross.get("amc_tonight") or [])}
    for sh in ("morning", "midday", "earnings"):
        p_ = os.path.join(OUT, "briefs", "%s-%s.json" % (today, sh))
        if not os.path.exists(p_):
            continue
        try:
            for c in ((json.load(open(p_, encoding="utf-8")) or {}).get("ds") or {}).get("candidates") or []:
                t_ = str(c.get("ticker") or "").upper()
                note = "%s %s" % (c.get("note") or "", (c.get("strategy") or {}).get("note") or "")
                if t_ and not c.get("empty") and re.fullmatch(r"[A-Z]{1,5}", t_) \
                        and "明晨预排" not in note and "AMC 初筛观察" not in note:
                    syms.add(t_)
        except Exception:
            pass
    return {x for x in syms if x and re.fullmatch(r"[A-Z]{1,5}", str(x))}


def afterhours_health(ah, syms, skips):
    """盘后读数健康态(v3.26.3,戌 8-24 抓 amc_results 仍空):出数 k/n + 原因分布——
    21:00 PST 晚班 = 00:00 ET,Nasdaq 盘后 secondaryData 常已收(8-20 压库项),空要响亮报原因。"""
    items = (ah or {}).get("items") or []
    got = sum(1 for i in items if i.get("ah_chg_pct") is not None)
    reasons = {}
    for i in items:   # 端点有回包但盘后字段空(secondaryData=null)的票不进 skips,从条目自身判
        if i.get("ah_chg_pct") is None:
            key = "no secondaryData" if i.get("ah_last") is None else ("双算冲突" if i.get("ah_conflict") else "盘后字段空")
            reasons[key] = reasons.get(key, 0) + 1
    for k in skips or []:
        if k.get("source") == "afterhours":
            r = str(k.get("reason") or "")
            key = ("no secondaryData" if "secondaryData" in r else "双算冲突" if "冲突" in r
                   else "HTTP/网络" if any(w in r for w in ("HTTP", "URL", "urlopen", "SSL", "timed", "Errno")) else r[:30])
            reasons[key] = reasons.get(key, 0) + 1
    if not (ah or {}).get("ok", True) and (ah or {}).get("error"):
        reasons.setdefault("源级失败", 0); reasons["源级失败"] = 1
    txt = "实时 %d/%d 出数" % (got, len(syms))
    if reasons:
        txt += ";缺数原因:" + ",".join("%s×%d" % kv for kv in sorted(reasons.items(), key=lambda kv: -kv[1]))
    if got == 0:
        txt += "(时点 00:00 ET 已过盘后窗——用 --mode afterhours 16:45 PST 快照可补,见 README)"
    return txt


def _afterhours_snapshot_path(today):
    return os.path.join(OUT, "state", "afterhours-%s.json" % today)


def load_afterhours_snapshot(today):
    """晚班优先吃 16:45 PST 盘后快照(--mode afterhours 落盘);无则 None(回落实时取)。"""
    try:
        doc = json.load(open(_afterhours_snapshot_path(today), encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("items"), list):
            return doc
    except Exception:
        pass
    return None


def run_afterhours_snapshot(payload, today):
    """--mode afterhours(v3.26.3):16:45 PST(=19:45 ET,Nasdaq 盘后窗内)取 amc_tonight(地板后)∪
    当日候选腿的盘后读数落 state/afterhours-日.json,21:00 晚班优先消费。不调 DS,不写简报,不进账本。
    plist 模板 com.grid.afterhours-snap.plist.new 随包,是否 load 由 Lyra 拍板。"""
    cross = {"amc_tonight": amc_tonight(payload, today)}
    floor_earnings_lists(cross)
    syms = afterhours_symbols(cross, today)
    if not syms:
        print("[scout] afterhours 快照:今日无盘后名单"); return None
    n0 = len(fetchers.SKIPS)
    ah = fetchers.fetch_afterhours(sorted(syms)[:24])
    doc = {"asof": datetime.datetime.now().astimezone().isoformat(), "ok": bool(ah.get("ok")),
           "error": ah.get("error"), "symbols": sorted(syms), "items": ah.get("items") or [],
           "skips": fetchers.SKIPS[n0:], "health": afterhours_health(ah, syms, fetchers.SKIPS[n0:])}
    os.makedirs(os.path.dirname(_afterhours_snapshot_path(today)), exist_ok=True)
    json.dump(doc, open(_afterhours_snapshot_path(today), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[scout] afterhours 快照落盘 %s:%s" % (_afterhours_snapshot_path(today), doc["health"]))
    # v3.29.1:F5 昨收缓存——当日快照 19:45 ET 仍在(文档:午夜 ET 重置),取 候选并集 的 ATM call γ/|θ| 落盘,
    # 次晨盘前池与晚班趋势榜回退用(标 F5昨收)。并集 = 盘后名单 ∪ 当日趋势榜 ∪ 当日三班候选池
    f5_syms = set(syms)
    try:
        tb_doc = json.load(open(os.path.join(OUT, "state", "trend_board-%s.json" % today), encoding="utf-8"))
        f5_syms |= {t["symbol"] for t in (tb_doc.get("board") or [])}
    except Exception:
        pass
    for shift_ in ("morning", "midday", "earnings"):
        try:
            bd = json.load(open(os.path.join(OUT, "briefs", "%s-%s.json" % (today, shift_)), encoding="utf-8"))
            f5_syms |= {p["symbol"] for p in ((bd.get("_engine") or {}).get("candidate_pool") or [])}
        except Exception:
            pass
    f5_syms = sorted(f5_syms)[:80]
    snaps5 = fetchers.quote_layer_snapshot(f5_syms, with_rsi=False) if f5_syms else {}
    _, raws5, _ = f5_batch(snaps5, f5_syms, allow_afterhours=True)
    f5_persist(today, raws5)
    print("[scout] F5 昨收缓存 %s:%d/%d 票出数" % (_f5_cache_path(today), sum(1 for v in raws5.values() if v is not None), len(f5_syms)))
    return doc


def persist_skips(raw_path, payload):
    """引擎期 skips 回写 raw(v3.25;V1 案根修):采集期落盘后,afterhours/tape_check/
    movers 等引擎期取数的 skips 只存在内存——ZTO 盘后缺数曾无迹可查。"""
    try:
        payload["skips"] = fetchers.SKIPS
        json.dump(payload, open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        print("[scout] skips 回写失败(不阻塞):", e)


def apply_liquidity_gate(data):
    """确定性流动性闸(爬虫#11):候选+对冲腿逐个实测市值/日均量,盖 liquidity_check 章。
    引擎只盖章不删卡——未过闸红标,买不买拍板在 Lyra(主频原则)。
    地板 env LIQ_MCAP_FLOOR_B,默认 $2.0B。"""
    legs = list(data.get("candidates") or []) + list((data.get("hedge") or {}).get("legs") or [])
    syms = sorted({(l.get("ticker") or "").upper() for l in legs
                   if re.fullmatch(r"[A-Z]{1,5}", (l.get("ticker") or "").upper())})
    if not syms:
        return data
    res = fetchers.fetch_ticker_liquidity(syms)
    m = {i["symbol"]: i for i in (res.get("items") or [])}
    floor = fetchers.LIQ_MCAP_FLOOR_B
    for l in legs:
        i = m.get((l.get("ticker") or "").upper())
        if not i:
            l["liquidity_check"] = {"mcap_b": None, "floor_b": floor,
                                    "verdict": "无实测——DS 的 liquidity 按估计对待"}
        else:
            ok = i["mcap_b"] is not None and i["mcap_b"] >= floor
            l["liquidity_check"] = {"mcap_b": i["mcap_b"], "avg_vol": i.get("avg_vol"), "floor_b": floor,
                                    "verdict": "过闸" if ok else ("未过闸(<$%.1fB)——谨慎,拍板在 Lyra" % floor)}
    return data


def apply_tape_check(data):
    """v3.16.2 合流:引擎给每条候选/对冲腿盖 tape_check 实测章(rsi14/close_loc/
    tape_flag/chg),与 DS 叙述并排对质——RSI 禁自估的引擎侧牙。只盖章不删卡,拍板在 Lyra。
    读数走 quote_layer 缓存,候选票多已在 movers/amc 预热,近零增量调用。"""
    legs = list(data.get("candidates") or []) + list((data.get("hedge") or {}).get("legs") or [])
    for l in legs:
        t = (l.get("ticker") or "").upper()
        if l.get("empty") or not re.fullmatch(r"[A-Z]{1,5}", t or ""):
            continue
        d = fetchers._stooq_daily(t.lower() + ".us", t, "tape_check")
        l["tape_check"] = ({"rsi14": d.get("rsi14"), "close_loc": d.get("close_loc"),
                            "tape_flag": d.get("tape_flag") or "", "chg_pct": d.get("chg_pct")}
                           if d else {"verdict": "无实测(FMP/Theta/Alpaca 三源 miss)"})
    return data


def emit_aether_scout(day, mode, title, data, cross, body_text=""):
    """AETHER 事件流 emit(verify 契约:morning/evening 主路径各一次)。payload 形状
    对齐 scout_land_option.emit(source=aether · kind=aether_scout_brief)。
    gateway(:8501)不可达 = 响亮记录不阻塞——emit 是账本镜像,不是班次前置。"""
    payload = {"date": day, "mode": mode, "title": title,
               "body": (body_text or "")[:2000],
               "brief_path": os.path.join(OUT, "briefs", "%s-%s.html" % (day, mode)),
               "via": "scout_agent",
               "structured": ({"_engine": cross, "ds": data} if data is not None else None),
               "liquidation_watch": bool((cross or {}).get("liquidation_watch")),
               "amc_tonight": (cross or {}).get("amc_tonight")}
    blob = json.dumps({"source": "aether", "kind": "aether_scout_brief",
                       "payload": payload}, ensure_ascii=False).encode()
    try:
        req = urllib.request.Request(GW + "/store/events", data=blob,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15, context=fetchers._ssl_context()) as r:
            print("[scout] aether emit", r.status, "(%s)" % mode)
    except Exception as e:
        print("[scout] aether emit 失败(不阻塞):", str(e)[:160])


def source_inventory(payload):
    """采集源清单(权威·事实行)——逐源 ok=true/false + 条数 + 错因。
    晚报叙事关于采集状态的最高权威是本清单(v3.16.4 契约):DS 不得伪称 SSL/缺失。"""
    rows = []
    for src_ in payload.get("results", payload.get("sources", [])) or []:
        flag = "ok=true" if src_.get("ok") else "ok=false"
        err = "" if src_.get("ok") else (" · " + str(src_.get("error") or "")[:80])
        rows.append("%s %s n=%d%s" % (src_.get("source"), flag, len(src_.get("items") or []), err))
    return "\n".join(rows)


_CLAIM_FAIL_RX = r"(失败|被墙|不可用|抓取不到|无法访问|超时|SSL|证书|中断|全灭|未采集|拿不到|断连)"


def lint_evening_source_claims(text, payload):
    """确定性 lint(v3.16.4):晚报叙事把 ok=true 的源说成失败/SSL——以清单为准就地重写
    并记账。只纠源状态谎言,永不碰数字/引用/风险提示(与 Grid 降噪同规)。"""
    fixes = []
    ok_sources = [str(s.get("source")) for s in
                  (payload.get("results", payload.get("sources", [])) or []) if s.get("ok")]
    for name in ok_sources:
        rx = re.compile(r"^.*%s.*%s.*$" % (re.escape(name), _CLAIM_FAIL_RX), re.M)
        text, n = rx.subn("(叙述与采集清单冲突,已按事实行纠正:%s ok=true)" % name, text)
        if n:
            fixes.append("%s×%d" % (name, n))
    if fixes:
        text += ("\n\n---\n[源清单 lint:纠正伪称失败 %s;事实行(最高权威)=采集源清单,"
                 "见 prompt 附录]" % ",".join(fixes))
    return text


def evening_ds_with_lint(prompt, payload):
    """晚班出稿链:DS → Grid 降噪 → 源清单 lint。事实行(最高权威)后置硬闸——
    prompt 纪律是软约束,这里是牙。"""
    return lint_evening_source_claims(denoise(ds_call(prompt)), payload)


def expanded_evening_review(date, final_md):
    """晚报 EXPANDED-GLM review(v3.16.5 契约:8501 · scout-review-日 · glm52_cloud)。
    路由/字段取自现场 verify 契约;gateway 不可达或空回 = 响亮记录不阻塞晚班。
    v3.25.2 回流 b286083(现场热修,8/19 五连崩修复):走 WB(8515 b11)签名转发,
    body 带 task(>500 字符触发 GLM cloud substrate),回包取 final,落盘后同步 store。"""
    scout_expanded_memory_node = "scout-review-%s" % date
    # v3.26.3(戌 8-24 抓:包装径 9000 字撞网关 8000 字闸,EXPANDED 直接失败):任务字数 env
    # EXPANDED_TASK_CHARS 默认 8000;网关拒绝时把 HTTP 码+正文前 200 字打出来,不再只有"失败"
    _cap = int(os.getenv("EXPANDED_TASK_CHARS", "8000"))
    body = {"lane": "scout_evening",
            "cloud_backend": "glm52_cloud",
            "memory_node": scout_expanded_memory_node,
            "persist": True,
            "task": (final_md or "")[:_cap],
            "messages": [
                {"role": "system", "content": "Scout 晚报 EXPANDED review。中文 Markdown,不编报价。"},
                {"role": "user", "content": (final_md or "")[:_cap]},
            ]}
    try:
        blob = json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request(WB + "/gateway/task/expanded", data=blob,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=300, context=fetchers._ssl_context()) as r:
            res = json.loads(r.read().decode())
        txt = (res.get("final") or res.get("content") or "").strip()
        if txt:
            p = os.path.join(OUT, "briefs", "%s-evening-glm-review.md" % date)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w", encoding="utf-8").write(txt)
            print("[scout] EXPANDED-GLM review 落盘:", p)
            sys_content = "Scout 晚报 EXPANDED review。中文 Markdown,不编报价。"
            store_msgs = [
                {"role": "user", "content": sys_content + "\n\n" + (final_md or "")[:_cap], "surface": "grid-app"},
                {"role": "assistant", "content": txt, "surface": "grid-app"},
            ]
            try:
                sreq = urllib.request.Request(
                    GW + "/store/conversations/" + scout_expanded_memory_node + "/messages",
                    data=json.dumps(store_msgs, ensure_ascii=False).encode(),
                    headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(sreq, timeout=30, context=fetchers._ssl_context()) as sr:
                    sr.read()
                print("[scout] EXPANDED-GLM review 已同步 store node:", scout_expanded_memory_node)
            except Exception as se:
                print("[scout] EXPANDED-GLM review store 同步失败(不阻塞):", str(se)[:120])
        else:
            print("[scout] EXPANDED-GLM review 空回(响亮记录,不阻塞)")
        return txt or None
    except urllib.error.HTTPError as e:
        try:
            _body = e.read().decode(errors="replace")[:200]
        except Exception:
            _body = ""
        print("[scout] EXPANDED-GLM review 失败(不阻塞):HTTP %s %s | task %d 字(闸 %d) | 正文:%s"
              % (e.code, e.reason, len((final_md or "")[:_cap]), _cap, _body))
        return None
    except Exception as e:
        print("[scout] EXPANDED-GLM review 失败(不阻塞):", str(e)[:160])
        return None


# ———— Grid 纪律降噪层(2026-08-08 入库;定义在 v3.25.2 出包时丢失、带病五版,
# 2026-08-23 现场晚报 NameError 后补回 v3.25.0 原文——verify 自此加全局名可解析检查)————
_NOISE_RX = [
    re.compile(r"^(好的|明白了|当然)[,,]?[^\n]{0,24}(如下|分析)[::]?\s*$", re.M),
    re.compile(r"^(总的来说|总而言之|综上所述|整体而言|需要注意的是|值得一提的是|值得注意的是)[,,::]\s*", re.M),
    re.compile(r"希望(以上|这些)?(内容|分析|信息)?(对你|对您)?有(所)?帮助[。!!]?"),
    re.compile(r"如(有|果)(其他)?(需要|问题|疑问)[^。\n]{0,20}[。!!]?"),
    re.compile(r"^(首先|其次|最后)[,,]我们(来|再)?(看|分析)一?下?[::]?\s*", re.M),
]


def denoise(text):
    """晚报降噪:确定性删废话短语,合并多余空行;命中即记账入文末。"""
    n0, hits = len(text or ""), 0
    for rx in _NOISE_RX:
        text, k = rx.subn("", text)
        hits += k
    text = re.sub(r"\n{3,}", "\n\n", text)
    if hits:
        text += "\n\n---\n[Grid 纪律降噪:删 %d 处废话,%d→%d 字]" % (hits, n0, len(text))
    return text


def _extract_json(text):
    """从 DS 回复抽 JSON(容忍围栏/前后杂讯);抽不出返回 None,上游响亮降级。"""
    t = text or ""
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(t[i:j + 1])
        except Exception:
            return None
    return None


# ---- 渲染层(DESIGN_SPEC 同源 token;卡片式简报,不再糊墙) ----
BRIEF_CSS = """
:root{--bg:#07090e;--panel:rgba(17,22,34,.78);--line:rgba(126,148,190,.13);
--ink:#e3eaf6;--dim:#8a97ad;--faint:#5a6478;--gold:#e2b95f;--grn:#57d19e;
--red:#ef5f79;--f1:12px;--f2:14px;--f3:16px;--f6:28px;
--sans:-apple-system,"PingFang SC","Hiragino Sans GB",sans-serif;
--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;padding:0 0 60px;background:var(--bg);color:var(--ink);font:var(--f2)/1.65 var(--sans)}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
header{position:sticky;top:0;display:flex;gap:12px;align-items:center;height:48px;padding:0 14px;
background:rgba(7,9,14,.92);border-bottom:1px solid var(--line);z-index:5}
header h1{font:700 var(--f3) var(--mono);letter-spacing:.18em;margin:0}
header .sub{color:var(--faint);font-size:var(--f1)}
.banner{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:12px;padding:9px 14px;
border:1px solid var(--line);border-radius:10px;background:rgba(11,15,24,.72);font-size:var(--f1)}
.banner b{font-size:var(--f2)}
section{margin:0 12px 14px}
h2{font-size:var(--f1);color:var(--dim);letter-spacing:.12em;margin:18px 2px 8px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.badge{display:inline-block;border:1px solid var(--grn);color:var(--grn);border-radius:999px;
padding:2px 12px;font:var(--f1) var(--mono)}
.tick{display:flex;gap:12px;align-items:center;margin:8px 0 2px}
.tick .sym{font:700 var(--f6) var(--mono);letter-spacing:.04em}
.pill{border:1.5px solid var(--grn);color:var(--grn);border-radius:999px;padding:2px 14px;font:600 var(--f2) var(--mono)}
.pill.put{border-color:var(--red);color:var(--red)}
.kv{display:flex;justify-content:space-between;gap:14px;padding:4px 0;font-size:var(--f2);
border-bottom:1px dashed rgba(126,148,190,.08)}
.kv:last-child{border:0}
.kv b{color:var(--dim);font-weight:500;white-space:nowrap}
.kv span{text-align:right}
details{margin-top:10px}
summary{cursor:pointer;color:#7ea6e8;font-size:var(--f2)}
.ev{border-left:2px solid var(--line);padding:6px 0 6px 12px;margin:8px 0}
.ev .src{color:var(--gold);font:var(--f1) var(--mono)}
.ev .why{color:var(--dim);font-size:var(--f1)}
.empty{border:1px dashed var(--line);border-radius:12px;padding:20px;color:var(--dim);text-align:center;line-height:1.8}
table{width:100%;border-collapse:collapse;font-size:var(--f1)}
th{color:var(--dim);text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);font-weight:500}
td{padding:5px 8px;border-bottom:1px solid rgba(126,148,190,.06);vertical-align:top}
p{margin:7px 0}
footer{margin:24px 12px 0;color:var(--faint);font-size:10px;font-family:var(--mono)}
"""


def _esc(x):
    return html.escape(str(x if x is not None else ""))


def _cand_card(c, tag, badge="SCOUT"):
    d = (c.get("direction") or "call").lower()
    st = c.get("strategy") or {}
    evs = "".join(
        '<div class="ev"><div class="src">%s</div><div>%s</div><div class="why">%s</div></div>'
        % (_esc(e.get("source", "")), _esc(e.get("item", "")), _esc(e.get("why", "")))
        for e in (c.get("evidence") or [])) or '<div class="ev">(无证据条目——按硬规则本卡不应存在)</div>'
    lc = c.get("liquidity_check") or {}
    lc_txt = (("$%.2fB · %s" % (lc["mcap_b"], lc.get("verdict", ""))) if lc.get("mcap_b") is not None
              else lc.get("verdict"))
    tc = c.get("tape_check") or {}
    tc_txt = (tc.get("verdict") if "verdict" in tc else
              ("RSI %s · loc %s · 日%s%%%s" % (tc.get("rsi14"), tc.get("close_loc"),
               tc.get("chg_pct"), (" · " + tc["tape_flag"]) if tc.get("tape_flag") else ""))
              if tc else None)
    rows = [("排名理由", c.get("rank_reason")),
            ("形态", st.get("type")), ("行权价逻辑", st.get("strike_logic")),
            ("到期", st.get("expiry")), ("入场条件", st.get("entry_condition")),
            ("入场窗(PST)", st.get("entry_window_pst")), ("出场窗(PST)", st.get("exit_window_pst")),
            ("止损", st.get("stop")), ("作废条件", st.get("abandon")),
            ("财报", st.get("earnings_note")), ("流动性(DS)", c.get("liquidity")),
            ("流动性实测(引擎)", lc_txt),
            ("RSI/tape 实测(引擎)", tc_txt),
            ("地板实测(引擎)", (("$%s · 20日成交额 $%sM · %s" % (fc.get("price"), fc.get("adv20_musd"), fc.get("verdict")))
                            if (fc := (c.get("floor_check") or {})) else None)),
            ("视野核对(引擎)", c.get("_pool_check")),
            ("T+0 平仓", st.get("t0_exit")), ("关键位", c.get("key_levels"))]
    kvs = "".join('<div class="kv"><b>%s</b><span>%s</span></div>' % (l, _esc(v)) for l, v in rows if v)
    return ('<div class="card"><span class="badge">%s %s</span>'
            '<div class="tick"><span class="sym">%s</span><span class="pill%s">%s</span></div>%s'
            '<details><summary>展开解析(证据出处)</summary>%s</details></div>'
            % (badge, _esc(tag), _esc((c.get("ticker") or "?").upper()),
               " put" if d == "put" else "", d.upper(), kvs, evs))


def _render_structured(date, data):
    m = data.get("macro") or {}
    cands = data.get("candidates") or []
    gaps = data.get("data_gaps") or []
    hd = data.get("hedge") or {}
    risk = hd.get("distribution_risk") or "—"
    rc = {"高": "var(--red)", "中": "var(--gold)", "低": "var(--grn)"}.get(risk, "var(--dim)")
    out = ['<div class="banner"><b>晨会交易任务单</b><span class="num">%s</span>'
           '<span>SP500 <b>%s</b></span><span>NASDAQ <b>%s</b></span><span>置信 <b>%s</b></span>'
           '<span>出货风险 <b style="color:%s">%s</b></span></div>'
           % (_esc(date), _esc(m.get("sp500_bias", "—")), _esc(m.get("nasdaq_bias", "—")),
              _esc(m.get("confidence", "—")), rc, _esc(risk))]
    out.append('<section><h2>一 · 大盘方向</h2><div class="card">'
               '<div class="kv"><b>逻辑</b><span>%s</span></div>'
               '<div class="kv"><b>关键位</b><span>%s</span></div></div></section>'
               % (_esc(m.get("logic", "")), _esc(m.get("key_levels", ""))))
    if cands:
        SLOTS = {1: "主池", 2: "财报", 3: "8-K/FDA", 4: "引擎位"}
        cs = sorted(cands, key=lambda c: (c.get("rank") or 9, c.get("slot") or 9))
        cells = []
        for c in cs:
            sl, sn = c.get("slot"), (c.get("slot_name") or SLOTS.get(c.get("slot"), ""))
            if c.get("empty"):
                cells.append('<div class="empty">S%s %s · 今日空槽'
                             '<br><span style="font-size:var(--f1)">%s</span></div>'
                             % (_esc(sl), _esc(sn), _esc(c.get("empty_reason", ""))))
            else:
                cells.append(_cand_card(c, date, "S%s·RANK %s" % (sl or "?", c.get("rank") or "?")))
        out.append('<section><h2>二 · 四槽股票卡(全部 单腿 CALL · T+0)</h2>%s</section>' % "".join(cells))
    else:
        out.append('<section><h2>二 · 池内候选</h2><div class="empty">今日池内无事件驱动候选'
                   '<br><span style="font-size:var(--f1)">%s</span></div></section>'
                   % _esc(data.get("no_candidate_reason", "")))
    rej = data.get("rejected") or []
    if rej:
        out.append('<section><h2>二·附 · 已淘汰候选(漏斗可审)</h2><div class="card">%s</div></section>'
                   % "".join('<div class="kv"><b>%s</b><span>%s</span></div>'
                             % (_esc(r.get("ticker")), _esc(r.get("reason"))) for r in rej))
    kills = data.get("_floor_kills") or []
    if kills:   # v3.26:DS 点名被引擎地板作废——票与条款一行可审,不无痕
        out.append('<section><h2>二·附 · 引擎地板作废(DS 点名未过地板,不出卡)</h2><div class="card">%s</div></section>'
                   % "".join('<div class="kv"><b>S%s %s</b><span>%s</span></div>'
                             % (_esc(k.get("slot")), _esc(k.get("ticker")), _esc(k.get("clause"))) for k in kills))
    hcard = ('<div class="card"><div class="kv"><b>风险评估</b>'
             '<span style="color:%s">%s</span></div>'
             '<div class="kv"><b>依据</b><span>%s</span></div>%s</div>'
             % (rc, _esc(risk), _esc(hd.get("basis", "")),
                ('<div class="kv"><b>说明</b><span>%s</span></div>' % _esc(hd.get("note"))) if hd.get("note") else ""))
    out.append('<section><h2>三 · 对冲(拉高出货/黑天鹅雷达)</h2>%s%s</section>'
               % (hcard, "".join(_cand_card(l, date, "HEDGE") for l in (hd.get("legs") or []))))
    if gaps:
        out.append('<section><h2>四 · 数据缺失与矛盾标注</h2><div class="card"><table>'
                   '<tr><th>项目</th><th>状态</th><th>处理</th></tr>%s</table></div></section>'
                   % "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                             % (_esc(g.get("item")), _esc(g.get("status")), _esc(g.get("handling")))
                             for g in gaps))
    if data.get("conclusion"):
        out.append('<section><h2>五 · 结论</h2><div class="card">%s</div></section>'
                   % _esc(data.get("conclusion")))
    return "".join(out)


def _md_fallback(text):
    """markdown → 分节 HTML(晚报常规路径;晨会 JSON 解析失败的降级路径)。不再糊墙。"""
    out, buf = [], []
    def flush():
        if buf:
            out.append("<p>%s</p>" % "<br>".join(buf)); buf.clear()
    for ln in (text or "").splitlines():
        t = ln.strip()
        if not t or t == "---":
            flush(); continue
        if t.startswith("#"):
            flush(); out.append("<h2>%s</h2>" % _esc(t.lstrip("#").strip()))
        else:
            e = _esc(t)
            e = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e)
            buf.append(e)
    flush()
    return '<section><div class="card">%s</div></section>' % "".join(out)


def _engine_card(cross):
    if not cross:
        return ""
    liq = cross.get("liquidation_watch")
    downs = ",".join(cross.get("risk_assets_down") or []) or "无"
    flags = ";".join("%s=%s" % kv for kv in (cross.get("tape_flags") or {}).items()) or "无"
    leaders = " · ".join("%s %+.2f%%" % (x.get("name"), x.get("chg_pct"))
                          for x in (cross.get("rotation_leaders") or []) if x.get("chg_pct") is not None) or "无读数"
    div = ",".join(cross.get("rotation_divergence") or []) or "无"
    rows = [("风险资产收跌", "%s / %s(%s)" % (cross.get("down_count"), cross.get("of"), downs)),
            ("VIX 日变动", "%s%%" % cross.get("vix_chg_pct")),
            ("TLT / UUP", "%s%% / %s%%" % (cross.get("tlt_chg_pct"), cross.get("uup_chg_pct"))),
            ("资金迁徙(海外领涨)", leaders),
            ("迁徙分化(美股跌而其涨)", div),
            ("tape flags", flags),
            ("全线下跌判据", "触发——商品 call 不是对冲,海外也不是避风港" if liq else "未触发")]
    if cross.get("regime"):      # v3.29:宏观只进仓位档(Fable C#4),不进选股
        rg = cross["regime"]
        rows.append(("仓位档(宏观 regime,只作仓位不选股)", "%s —— %s;Kelly:%s" % (rg.get("tier"), rg.get("why"), rg.get("kelly_note"))))
    if "trend_board" in cross:   # v3.28:自算趋势榜(不是 FMP 榜)
        tb = cross.get("trend_board") or []
        if tb:
            rows.append(("趋势榜(自算·全市场,因子分 F1资金/F2趋势/F3形态/F4事件/F5期权)", " · ".join(
                "%s %d[%s]%s" % (t["symbol"], t["trend_score"], t.get("trend_why", ""), ("⚠" + ",".join(t["flags"])) if t.get("flags") else "")
                for t in tb[:8])))
        else:
            rows.append(("趋势榜(自算)", "空——宇宙 %s 票(screener 失败=0)或全未过地板/最低分" % cross.get("trend_universe_n", "?")))
    # v3.26 引擎候选池:确定性排序独立于 DS 落屏——强票在不在池里、为何进不了,一行可查
    if "candidate_pool" in cross:
        pool = cross.get("candidate_pool") or []
        prej = cross.get("pool_rejected") or []
        if pool:
            rows.append(("引擎候选池(地板后·分[眼]·$%gM/20日)" % (fetchers.pool_adv_floor_usd() / 1e6), " · ".join(
                "%s %d分[%s]%s" % (p["symbol"], p["score"], "/".join(p.get("eyes") or []),
                                   ("⚠" + ",".join(p["flags"])) if p.get("flags") else "")
                for p in pool)))
        else:
            rows.append(("引擎候选池", "空——宇宙 %s 票全未过地板或无读数(见筛除行);S1 依规空槽"
                         % cross.get("pool_universe_n", "?")))
        if prej:
            rows.append(("候选池筛除(引擎地板)", "%d 票:" % len(prej) + " · ".join(
                "%s(%s)" % (r["symbol"], r["clause"]) for r in prej[:10]) + ("…" if len(prej) > 10 else "")))
    fr = cross.get("floor_rejected") or {}
    for k_, label_ in (("amc_tonight", "今晚财报·地板筛除"), ("bmo_tomorrow", "明日BMO·地板筛除"),
                       ("upcoming_earnings", "run-up·地板筛除")):
        if fr.get(k_):
            rows.append((label_, " · ".join("%s(%s)" % (r["symbol"], r["clause"]) for r in fr[k_][:8])
                         + ("…(共%d)" % len(fr[k_]) if len(fr[k_]) > 8 else "")))
    movers = " · ".join("%s %+.1f%%(%s%s)" % (x["symbol"], x["chg_pct"], x["when"],
                         (",量%.1fx" % x["vol_x20"]) if x.get("vol_x20") else "")
                         for x in (cross.get("earnings_movers") or [])[:4]) or None
    if movers:
        rows.append(("财报异动(昨AMC/今BMO)", movers))
    if cross.get("amc_tonight"):
        def _amcfmt(x):
            if isinstance(x, str):
                return x
            hot = (x.get("chg5_pct") or 0) > 15 or (x.get("rsi14") or 0) > 75
            es = x.get("earn_score")
            return x.get("symbol", "?") + ("⚠" if hot else "") + ("(%d)" % es if es is not None else "")
        rows.append(("今晚财报(AMC,因子分 0–100,<40 禁 call,⚠=双杀风险位)",
                     " · ".join(_amcfmt(x) for x in cross["amc_tonight"][:6])))
    if cross.get("market_movers"):
        th = cross.get("theme_heat") or []
        if th:
            rows.append(("热簇·数据自聚(hot=钱在流入)", " · ".join(
                "%s(%d)%s avg%+.1f%%" % (t["theme"][:16], t["n"], "🔥" if t["hot"] else "",
                t["avg_chg"]) for t in th[:6])))
        ma = cross.get("most_active") or []
        if ma:
            rows.append(("最活跃榜(热资金)", " · ".join(
                "%s%s" % (x["symbol"], ("%+.1f%%" % x["chg_pct"]) if x.get("chg_pct") is not None else "")
                for x in ma[:10])))
        else:
            rows.append(("最活跃榜(热资金)", "⚠ 失败:%s——簇无资金确认,本班不发🔥"
                         % (cross.get("_ma_err") or "未知")))
        cm = cross.get("comove") or []
        if cm:
            def _cm_line(c):
                shown = c["members"][:8]
                tail = "" if len(c["members"]) <= 8 else "…(示%d/%d)" % (len(shown), c["n"])
                return "%s[团%d·ρ%s]%s中位%+.1f%%:%s%s" % ("🔥" if c["hot"] else "", c["n"],
                    c.get("cohesion", "?"), "$" if c["money"] else "", c["med_chg"],
                    " ".join(mm["symbol"] for mm in shown), tail)
            rows.append(("同频簇(两两ρ≥0.7·团)", " · ".join(_cm_line(c) for c in cm)))
        sb = cross.get("streak_board") or []
        if sb:
            rows.append(("连涨/连续上榜(3日≥2现)", " · ".join(sb[:14])))
        wlr = cross.get("watchlist") or []
        if wlr:
            rows.append(("自选名单(实测)", " · ".join(
                "%s%s" % (x["symbol"], ("%+.1f%%" % x["chg_pct"]) if x.get("chg_pct") is not None else "")
                for x in wlr[:14])))
        rows.append(("全市场异动(|chg|≥10%,非仅财报)", " · ".join(
            "%s%+.1f%%" % (x["symbol"], x["chg_pct"]) for x in cross["market_movers"][:8])))
    if cross.get("bmo_tomorrow"):
        def _bmofmt(x):
            hot = (x.get("chg5_pct") or 0) > 15 or (x.get("rsi14") or 0) > 75
            es = x.get("earn_score")
            return x.get("symbol", "?") + ("⚠" if hot else "") + ("(%d)" % es if es is not None else "")
        rows.append(("明日财报(BMO 伏击名单,因子分 0–100,⚠=双杀风险位)",
                     " · ".join(_bmofmt(x) for x in cross["bmo_tomorrow"][:6])))
    if cross.get("upcoming_earnings"):
        rows.append(("未来 1-8 日财报(run-up 窗,d=交易日)", " · ".join(
            "%s(%s d%s)" % (x["symbol"], (x.get("date") or "")[5:], x.get("days_out", "?")) for x in cross["upcoming_earnings"][:8])))
    ho = cross.get("handover") or {}
    if ho.get("overnight_legs"):
        rows.append(("昨夜过夜腿(必须首屏处置)", " · ".join(
            "%s %s" % (x["symbol"], ("%+.2f%%" % x["chg_pct"]) if x.get("chg_pct") is not None else "无读数")
            for x in ho["overnight_legs"])))
    if ho.get("watch_tape"):
        rows.append(("昨日 watch 盘初", " · ".join(
            "%s %s" % (x["symbol"], ("%+.1f%%" % x["chg_pct"]) if x.get("chg_pct") is not None else "—")
            for x in ho["watch_tape"][:10])))
    if cross.get("amc_results"):
        rows.append(("盘后异动(实测)", " · ".join(
            "%s %+.1f%%" % (x["symbol"], x["ah_chg_pct"]) for x in cross["amc_results"][:5])))
    if cross.get("amc_results_health"):   # v3.26.3:盘后 0 出数必须响亮报原因,不留空
        rows.append(("盘后读数健康态", cross["amc_results_health"]))
    if cross.get("trend_regime"):
        rows.append(("趋势体制(20日)", "%s · 广度差 %s%%(等权−市值权;负=巨头独舞)"
                     % (cross["trend_regime"], cross.get("breadth_20d_spread", "—"))))
    ssp = cross.get("index_session_split") or {}
    if ssp:
        rows.append(("隔夜/日内(20日)", " · ".join(
            "%s 隔夜%+.1f%%/日内%+.1f%%" % (n, v.get("overnight20_pct") or 0, v.get("intraday20_pct") or 0)
            for n, v in ssp.items())))
    if cross.get("risk_alerts") is not None:
        base = "corr %s · 信用 %s%%" % (cross.get("risk_corr20", "—"), cross.get("credit_20d_spread", "—"))
        rows.append(("风险预警", ("; ".join(cross["risk_alerts"]) + "(" + base + ")")
                     if cross["risk_alerts"] else "无(" + base + ")"))
    sl = cross.get("sector_leaders") or []
    sg = cross.get("sector_laggards") or []
    if sl:
        def _sfmt(x):
            m20 = x.get("mom20_pct")
            return "%s %s(日%+.1f%%)" % (x["name"], ("%+.1f%%/20d" % m20) if m20 is not None else "—", x["chg_pct"])
        rows.append(("板块轮动(20日动量主键)", "领:%s · 尾:%s"
                     % (" ".join(_sfmt(x) for x in sl), " ".join(_sfmt(x) for x in sg))))
    pr = cross.get("prev_review") or cross.get("today_review")
    if pr:
        rows.append(("战绩 %s" % (pr.get("date") or ""),
                     "%s 命中 · 滚动%s日 %s%%" % (pr.get("hit", "—"),
                     (pr.get("rolling") or {}).get("days", "—"),
                     (pr.get("rolling") or {}).get("hit_rate_pct", "—"))))
    kvs = "".join('<div class="kv"><b>%s</b><span>%s</span></div>' % (l, _esc(v)) for l, v in rows)
    return '<section><h2>〇 · 跨资产引擎读数(确定性)</h2><div class="card">%s</div></section>' % kvs


def render_brief_html(date, mode, data, raw_text, cross=None):
    warn = ""
    if (cross or {}).get("liquidation_watch"):
        warn = ('<div class="banner" style="border-color:var(--red)">'
                '<b style="color:var(--red)">全线下跌 WATCH</b>'
                '<span>风险资产 %s/%s 收跌 · VIX %s%% · 商品 call 不是对冲</span></div>'
                % (_esc(cross.get("down_count")), _esc(cross.get("of")), _esc(cross.get("vix_chg_pct"))))
    if data is None and mode in ("morning", "midday", "earnings"):   # v3.26.3:失败必须上脸,禁留昨日页
        warn += ('<div class="banner" style="border-color:var(--red)"><b style="color:var(--red)">本班无有效作业</b>'
                 '<span>DS 无 JSON 产出——原因见下方正文;卡片缺席不是"今日无候选"</span></div>')
    body = warn + _engine_card(cross) + (_render_structured(date, data) if data else _md_fallback(raw_text))
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"/>'
            '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
            '<title>SCOUT · %s · %s</title><style>%s</style></head><body>'
            '<header><h1>SCOUT</h1><span class="sub">%s · %s · 数据as-of %s · 参谋作业,Lyra 拍板</span></header>'
            '%s<footer>build scout v3.29 · 六因子核+准入闸+自算趋势榜 · 三班制+BMO伏击+FMP路由 · FMP主源+Theta+Alpaca backup · emit/tape_check/rsi14_tape/源清单lint/EXPANDED-GLM · 影子lane · 账本卫生 · Grid降噪 · 四槽卡 · ET锚定 · '
            '渲染:_render_structured/_cand_card/_md_fallback</footer></body></html>'
            % (mode.upper(), _esc(date), BRIEF_CSS, mode, _esc(date),
               {"morning": "盘初 ~9:45 ET(当日行为部分K线)",
                "midday": "盘中 ~13:40 ET(当日行为盘中K线)",
                "earnings": "尾盘 ~15:35 ET(近全日K线)"}.get(mode, "收盘(全日K线)"), body))


def render_console(title, body, date, mode, data=None, cross=None):
    """DS 作业进 console 落档(work_log 入魂器);console 不可达则本地落盘。"""
    payload_doc = ("[DS 决策官作业·JSON(GLM review/编译直接吃)] "
                   + json.dumps(data, ensure_ascii=False)[:8000]) if data else \
                  ("[DS 决策官作业,存档] " + body[:8000])
    try:
        ck = os.getenv("CONSOLE_KEY", "").strip()   # 调用期读取(死键族收尾)
        if not ck:
            raise RuntimeError("CONSOLE_KEY 未配置")
        t = _http(CONSOLE + "/api/tasks",
                  {"workspace": "trade", "title": title, "owner_node": "deepseek_lane",
                   "risk_level": "read", "io_contract": payload_doc},
                  {"X-Console-Key": ck})
        print("[scout] console 任务 DS#%s(work_log 入魂器)" % t.get("task_id"))
    except Exception as e:
        print("[scout] console 不可达(%s)→ 本地落盘" % e)
    bdir = os.path.join(OUT, "briefs")
    os.makedirs(bdir, exist_ok=True)
    bp = os.path.join(bdir, "%s-%s.md" % (date, mode))
    with open(bp, "w", encoding="utf-8") as f:
        f.write("# %s\n\n%s\n" % (title, body))
    hp = os.path.join(bdir, "%s-%s.html" % (date, mode))
    with open(hp, "w", encoding="utf-8") as f:
        f.write(render_brief_html(date, mode, data, body, cross))
    if data is not None:
        with open(os.path.join(bdir, "%s-%s.json" % (date, mode)), "w", encoding="utf-8") as f:
            json.dump({"_engine": cross, "ds": data}, f, ensure_ascii=False, indent=1)
    print("[scout] 落盘:", bp, "+", hp, "(+json)" if data is not None else "")


def main():
    ap = argparse.ArgumentParser(description="Scout Agent v3(DS 决策官)")
    ap.add_argument("--mode", choices=["evening", "morning", "midday", "earnings", "afterhours"], default="evening")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--review", choices=["expanded", "off"], default="expanded",
                    help="晚班 EXPANDED-GLM review(v3.16.5;8501 不可达自动跳过)")
    a = ap.parse_args()
    # .env 已在模块顶加载(先于 import fetchers 与常量——死键族根治,勿移回此处)
    today = fetchers.trading_date().isoformat()   # v3.12:ET 锚定,机器时区无关
    # v3.22 账本卫生:周末不出班——launchd 七天都跑,周六日 stooq 返回的是周五K线,
    # 曾造成同一根K线三记入账(JPM/FCX 案例,命中率虚高 67.9%→去重 62.5%)
    if datetime.date.fromisoformat(today).weekday() >= 5:
        print("[scout] %s 非交易日——不出班不写复盘(账本卫生;节假日仍为已知边界)" % today)
        return
    os.makedirs(os.path.join(OUT, "raw"), exist_ok=True)
    raw_path = os.path.join(OUT, "raw", today + ".json")

    if (a.skip_fetch or a.mode == "afterhours") and os.path.exists(raw_path):
        payload = json.load(open(raw_path, encoding="utf-8"))
        print("[scout] --skip-fetch 复用", raw_path)
    else:
        results = fetchers.run_all()
        payload = {"results": results, "skips": fetchers.SKIPS}
        if os.path.exists(raw_path):
            raw_path = raw_path.replace(".json", "-" + datetime.datetime.now().strftime("%H%M") + ".json")
        json.dump(payload, open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        ok = sum(1 for r in payload["results"] if r["ok"])
        print("[scout] %s 源成功 %d/%d → %s" % (today, ok, len(payload["results"]), raw_path))
        for b in payload["results"]:
            if not b["ok"]:
                print("   ✗", b["source"], b.get("error", ""))

    if a.dry_run:
        print("[scout] --dry-run 止步于采集"); return
    if a.mode == "afterhours":
        run_afterhours_snapshot(payload, today); return

    yday = yesterday_raw(today)
    cross = cross_asset_summary(payload)
    if cross.get("liquidation_watch"):
        print("[scout] 引擎:全线下跌判据触发", cross)
    if a.mode in ("morning", "midday", "earnings"):
        shift = a.mode
        if shift == "earnings":
            # 财报班(开卷):四件套全上——movers 硬闸 / 今晚 AMC / 明日 BMO / 1-8 日 run-up
            cross["earnings_movers"] = earnings_movers(payload, today)
            cross["amc_tonight"] = amc_tonight(payload, today)
            cross["bmo_tomorrow"] = bmo_tomorrow(payload, today)
            cross["upcoming_earnings"] = upcoming_earnings(payload, today)
        else:
            # v3.25.6:morning/midday 都算 amc_tonight——S2 初筛卡名单源(观察不建仓,
            # 非财报持仓腿,与 2026-08-19"6:45 不含财报腿"拍板不冲突)
            cross["amc_tonight"] = amc_tonight(payload, today)
        cross["market_movers"] = market_movers(payload)
        cross["most_active"] = most_active(payload)
        cross["_ma_err"] = most_active_health(payload)
        cross["theme_heat"] = theme_heat(payload)
        cross["comove"] = comove_clusters(payload)
        cross["streak_board"] = update_streaks(today, cross["market_movers"], cross["most_active"])
        _wl = load_watchlist()
        if _wl:
            cross["watchlist"] = [dict({"symbol": s}, **(fetchers._stooq_daily(s.lower() + ".us", s, "watchlist") or {})) for s in _wl]
        # v3.26:确定性候选池(六眼→实测→地板→计分)+ 财报三名单过地板,先于 DS 看见
        cross["regime"] = regime_and_kelly(payload)
        cross["trend_board"], cross["trend_universe_n"], cross["trend_rejected_n"] = trend_board(today)
        print("[scout] 趋势榜 %d(宇宙 %d):%s" % (len(cross["trend_board"]), cross["trend_universe_n"],
              " ".join("%s(%d)" % (t["symbol"], t["trend_score"]) for t in cross["trend_board"][:6]) or "空"))
        cross["candidate_pool"], cross["pool_rejected"], cross["pool_universe_n"] = candidate_pool(cross)
        floor_earnings_lists(cross)
        print("[scout] 候选池 %d/%d 过地板:%s" % (len(cross["candidate_pool"]), cross["pool_universe_n"],
              " ".join("%s(%d)" % (p["symbol"], p["score"]) for p in cross["candidate_pool"][:6]) or "空"))
        prev = load_prev_review(today)
        if prev:
            prev["rolling"] = rolling_summary(prev["date"])
            cross["prev_review"] = {k: prev.get(k) for k in
                                    ("date", "hit", "rolling", "watch", "rejected_review")
                                    if prev.get(k) is not None}
        if shift == "morning":
            cross["handover"] = build_handover(today, prev)
        todays = load_today_shifts(today, shift)
        title = "Scout %s · %s" % (_SHIFT_TITLE[shift], today)
        ws = fetch_workstation_state()
        prompt = build_trading_prompt(payload, ws, yday, cross, prev, shift=shift, todays=todays,
                                      fault_lines=(load_fault_lines_snapshot(today)[0] if shift == "morning" else ""))
        ds_err = ""
        try:
            body = ds_call(prompt)
        except SystemExit:
            raise
        except Exception as e:   # v3.26.3:超时/网络类失败不崩班——失败标记+html 必须覆盖昨日页
            body, ds_err = "", "DS 调用失败(%s)" % str(e)[:120]
            print("[scout]", ds_err)
        data = _extract_json(body) if (body or "").strip() else None
        if data is None:
            hint = (ds_err or "DS 空正文(finish=length/未关 think 类,8-17 案)") if not (body or "").strip() \
                else "疑输出截断,查 DS_MAX_TOKENS" if body.lstrip().startswith("{") \
                else "DS 未按 schema"
            body = body or ("[scout] 本班 DS 无有效产出:" + hint)
            print("[scout] 晨会单 JSON 解析失败(%s)——降级文本渲染,json 落失败标记(land 拒吃口)" % hint)
            os.makedirs(os.path.join(OUT, "briefs"), exist_ok=True)
            with open(os.path.join(OUT, "briefs", "%s-%s.json" % (today, shift)), "w", encoding="utf-8") as f:
                json.dump({"_engine": cross, "ds": {"_parse_failed": True, "hint": hint}},
                          f, ensure_ascii=False, indent=1)
        else:
            data = apply_liquidity_gate(data)
            data = apply_tape_check(data)
            data = apply_quality_floor(data, shift, cross)   # v3.26:会改卡(地板作废),先于下限盖章
            data = apply_candidate_floor(data, shift)
        render_console(title, body, today, shift, data, cross)
        emit_aether_scout(today, shift, title, data, cross, body)
        _scout_bark(shift, today, data if isinstance(data, dict) else {})
        persist_skips(raw_path, payload)
        sbody = shadow_call(prompt) if shift == "morning" else None
        if sbody is not None:
            sdata = _extract_json(sbody)
            with open(os.path.join(OUT, "briefs", "%s-morning-glm.json" % today), "w", encoding="utf-8") as f:
                json.dump({"_engine": cross, "ds": sdata if sdata is not None else {"_parse_failed": True}},
                          f, ensure_ascii=False, indent=1)
            print("[scout] 影子 lane 落盘:%s-morning-glm.json(%s)"
                  % (today, "JSON ok" if sdata is not None else "解析失败已标记"))
    else:
        # 雷达第5项供数:晚报 prompt 一直令 DS 核对 earnings_movers,旧版 evening 从未计算(对空气核对)
        cross["earnings_movers"] = earnings_movers(payload, today)
        cross["market_movers"] = market_movers(payload)
        cross["most_active"] = most_active(payload)
        cross["_ma_err"] = most_active_health(payload)
        cross["theme_heat"] = theme_heat(payload)
        cross["comove"] = comove_clusters(payload)
        cross["streak_board"] = update_streaks(today, cross["market_movers"], cross["most_active"])
        _wl = load_watchlist()
        if _wl:
            cross["watchlist"] = [dict({"symbol": s}, **(fetchers._stooq_daily(s.lower() + ".us", s, "watchlist") or {})) for s in _wl]
        cross["amc_tonight"] = amc_tonight(payload, today)
        # v3.26.3(戌 8-24 抓:晚报没吃候选池和财报地板——闸只挂白班,晚报仍把 PICS 当过夜腿、
        # 仍叫人看 IBIT/BITO):晚班同一套纪律——候选池(明日弹药视野)+ 三名单过地板
        cross["bmo_tomorrow"] = bmo_tomorrow(payload, today)
        cross["upcoming_earnings"] = upcoming_earnings(payload, today)
        cross["regime"] = regime_and_kelly(payload)
        cross["trend_board"], cross["trend_universe_n"], cross["trend_rejected_n"] = trend_board(today)   # 晚班算,次晨共用
        cross["candidate_pool"], cross["pool_rejected"], cross["pool_universe_n"] = candidate_pool(cross)
        floor_earnings_lists(cross)
        # v3.25.2(COTY 案):盘后查询名单 = amc_tonight(地板后)∪ 当日各班非空候选腿(预排卡除外)
        ah_syms = afterhours_symbols(cross, today)
        if ah_syms:
            snap = load_afterhours_snapshot(today)
            if snap:
                ah, cross["amc_results_health"] = snap, ("盘后快照 %s:%d/%d 出数" % (
                    snap.get("asof", "?")[11:16], sum(1 for i in snap.get("items") or [] if i.get("ah_chg_pct") is not None), len(ah_syms)))
            else:
                n0 = len(fetchers.SKIPS)
                ah = fetchers.fetch_afterhours(sorted(ah_syms)[:24])
                cross["amc_results_health"] = afterhours_health(ah, ah_syms, fetchers.SKIPS[n0:])
            cross["amc_results"] = sorted(
                [i for i in (ah.get("items") or []) if i.get("ah_chg_pct") is not None],
                key=lambda x: -abs(x["ah_chg_pct"]))
            print("[scout] 盘后读数:", cross["amc_results_health"])
        rev = build_review(today)
        build_review(today, "-glm")   # 影子 lane 分账复盘(无影子文件则静默跳过)
        if rev:
            rev["rolling"] = rolling_summary(today)
            cross["today_review"] = {"date": today, "hit": rev["hit"], "rolling": rev["rolling"]}
        inv = source_inventory(payload)
        prompt = build_evening_prompt(payload, yday, cross, rev, inv, today=today)
        body = evening_ds_with_lint(prompt, payload)
        render_console("Scout 晚报复盘 · " + today, body, today, "evening", None, cross)
        if a.review == "expanded":
            expanded_evening_review(today, body)
        emit_aether_scout(today, "evening", "Scout 晚报复盘 · " + today, None, cross, body)
        persist_skips(raw_path, payload)


if __name__ == "__main__":
    main()
PKG_EOF_005
chmod +x scout_agent.py 2>/dev/null || true
cat > '.tmp_006' <<'PKG_EOF_006'
#!/usr/bin/env python3
"""Scout Agent · 本机装包后门禁(失败非零退出)。v3.24 增补 FMP/Theta 三项。

装任何 scout_agent_install*.sh 进本目录后必须跑通本脚本,才算部署完成。
禁止口头「已装好」——只认本门禁绿。

门禁项:
  1) 代码: Ollama 路径 think=false
  2) 代码: emit_aether_scout 存在且 morning/evening 主路径调用
  3) 代码: Alpaca/SSL/日历 wrap≥800 / amc_tonight 非 [:15]
  4) 代码: cross_asset_summary 产出 rsi14_tape
  5) 代码: v3.16 晚班(et_now_hm 钟点 / 已出叙事 / run-up 仅未来日 / review.watch)
  6) 实况: 今日 AMC 日历非空;若日历含 TEAM 则 amc_tonight 必须含 TEAM
  7) 实况: rsi14_tape 至少 SP500+NASDAQ 有非空 rsi14
  8) 实况: GATEWAY /store 可达(emit 前置)

用法:
  cd /Users/ciciwang/Projects/demo/grid-scout
  python3 verify_scout_deploy.py
  python3 verify_scout_deploy.py --skip-live   # 仅静态代码闸
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

FAILS: list[str] = []
OKS: list[str] = []


def _fail(msg: str) -> None:
    FAILS.append(msg)
    print("  FAIL ", msg)


def _ok(msg: str) -> None:
    OKS.append(msg)
    print("  OK   ", msg)


def gate_static_code() -> None:
    print("[1] 静态代码闸")
    sa_path = os.path.join(HERE, "scout_agent.py")
    fe_path = os.path.join(HERE, "fetchers.py")
    sa = open(sa_path, encoding="utf-8").read()
    fe = open(fe_path, encoding="utf-8").read()

    # think=false for Ollama
    if re.search(r'body\s*\[\s*["\']think["\']\s*\]\s*=\s*False', sa) or re.search(
        r'["\']think["\']\s*:\s*False', sa
    ):
        _ok("ds_call 含 think=False")
    else:
        _fail("ds_call 未强制 think=False(Ollama 长单会空正文)")

    # emit wired
    if "def emit_aether_scout" not in sa:
        _fail("缺少 emit_aether_scout")
    elif sa.count("emit_aether_scout(") < 3:  # def + morning + evening
        _fail("emit_aether_scout 未在 morning/evening 主路径各调一次")
    else:
        _ok("emit_aether_scout 已接线 morning+evening")

    # rsi14_tape
    if 'out["rsi14_tape"]' in sa or "rsi14_tape" in sa:
        _ok("cross 含 rsi14_tape")
    else:
        _fail("cross_asset_summary 未产出 rsi14_tape")

    # amc cap not stuck at 15 (v3.16.2 返回 dict 列表,截断在 out=out[:N])
    m = re.search(r"out\s*=\s*out\[:(\d+)\]", sa)
    if not m:
        m = re.search(r"def amc_tonight[\s\S]+?return out\[:(\d+)\]", sa)
    if not m:
        _fail("amc_tonight 未找到名单截断 out[:N]")
    else:
        n = int(m.group(1))
        if n < 30:
            _fail("amc_tonight cap=%d(<30)——TEAM 等中盘会被裁" % n)
        else:
            _ok("amc_tonight cap=%d" % n)
    if 'tape_check' in sa and 'RSI/tape 实测(引擎)' in sa:
        _ok("v3.16.2 tape_check + 候选卡 RSI 行")
    else:
        _fail("缺 tape_check 盖章或 RSI/tape 实测行")
    if "禁止自估 RSI" in sa and "yday, ensure_ascii=False)[:4000]" in sa:
        _ok("晨会 RSI 禁自估 + 晚班 yday 截断4000")
    else:
        _fail("晨会 RSI 硬规则或 yday[:4000] 未按 v3.16.2")

    # fetchers local path
    if "def _ssl_context" not in fe:
        _fail("fetchers 缺 _ssl_context(certifi)")
    else:
        _ok("fetchers._ssl_context")
    if "def alpaca_snapshots" not in fe or "def alpaca_daily_closes" not in fe:
        _fail("fetchers 缺 Alpaca snapshots/bars(本机 stooq 被墙时 rsi14 必空)")
    else:
        _ok("fetchers Alpaca snapshots + daily_closes(RSI)")
    if "class quote_layer" in fe and "def quote_layer_snapshot" in fe and "ALPACA_KEY_ID" in fe:
        _ok("v3.16§⑦ quote_layer + ALPACA_KEY_ID 别名")
    else:
        _fail("缺 quote_layer 缝或 ALPACA_KEY_ID 别名(v3.16§⑦)")
    if "feed_ah_label" in fe and "data_plane_banner" in fe:
        _ok("feed 档标签 + 数据层横幅")
    else:
        _fail("缺 feed_ah_label / data_plane_banner")
    if "800 if source" not in fe and "earnings_calendar" not in fe:
        _fail("earnings_calendar 源级 wrap 未升到可容纳热日+今日")
    elif re.search(r"800 if source\s*==\s*[\"']earnings_calendar[\"']", fe):
        _ok("earnings_calendar wrap≥800")
    else:
        # soft: look for cap =
        if "earnings_calendar" in fe and "800" in fe:
            _ok("earnings_calendar wrap 含 800")
        else:
            _fail("earnings_calendar wrap 仍可能是 40/240——会吞今日 AMC")

    # v3.24 数据链三项(FMP 主源→Theta 第二源→Alpaca backup,Lyra 拍板 2026-08-17)
    if "def _fmp_history" in fe and "def _history" in fe and "FMP_API_KEY" in fe:
        _ok("v3.24 FMP 主源缝(_fmp_history/_history)")
    else:
        _fail("缺 FMP 主源缝——数据链未按 2026-08-17 拍板落地")
    if "_theta_history" in fe and "THETA_BASE" in fe:
        _ok("v3.24 Theta 第二源(探活跳过式,不强迫起容器)")
    else:
        _fail("缺 Theta 第二源链位")
    if "PRICES_DIR" in fe and "fmp_calls_today" in fe:
        _ok("v3.24 K线缓存 + FMP 调用记账(免费档 250/日)")
    else:
        _fail("缺 prices/ 缓存或 FMP 记账——调试重跑日会烧穿配额")

    # v3.16 晚班三处
    if "et_now_hm()" in sa and "收盘后;今日 AMC 财报已披露" in sa:
        _ok("晚班 prompt 含 ET et_now_hm 钟点")
    else:
        _fail("晚班缺 et_now_hm(收盘后;今日 AMC 财报已披露)")

    if (
        "def source_inventory" in sa
        and ("采集源清单(权威·" in sa or "采集源清单(权威)" in sa)
        and "ok=true" in sa
    ):
        _ok("晚班源清单纪律(禁伪称 SSL/缺失)")
    else:
        _fail("晚班缺 source_inventory / 采集源清单纪律")
    if (
        "def lint_evening_source_claims" in sa
        and "def evening_ds_with_lint" in sa
        and "事实行(最高权威" in sa
    ):
        _ok("晚班源清单硬闸 v3.16.4(事实行+lint 重写)")
    else:
        _fail("晚班缺 v3.16.4 lint_evening_source_claims / evening_ds_with_lint")
    if (
        "def expanded_evening_review" in sa
        and "/gateway/task/expanded" in sa
        and "scout_expanded_memory_node" in sa
        and "scout-review-" in sa
        and "cloud_backend" in sa
        and "glm52_cloud" in sa
        and 'a.review == "expanded"' in sa
    ):
        _ok("晚报 EXPANDED-GLM review v3.16.5(8515→8501 · scout-review-日)")
    else:
        _fail("晚报缺 expanded_evening_review / scout-review-日 / glm52_cloud 接线")
    if '财报"已出结果"者名单' in sa or "已出结果" in sa and "若超预期" in sa and "禁止出现" in sa:
        _ok("晚班 §5 AMC 已出叙事(禁若超预期)")
    else:
        _fail("晚班 §5 未按 v3.16 已出叙事改写")
    if "今日已出结果者不属 run-up" in sa and '"watch"' in sa:
        _ok("晚班 §6 run-up 仅未来日 + build_review.watch")
    else:
        _fail("晚班缺 v3.16 run-up 边界或 review.watch")

    # ---- v3.25 三班制 + BMO 伏击 + FMP 路由 ----
    if '"midday"' in sa and '"earnings"' in sa and "choices=" in sa:
        _ok("v3.25 --mode 含 midday/earnings")
    else:
        _fail("v3.25 --mode choices 缺 midday/earnings")
    if (
        "def bmo_tomorrow" in sa
        and "def upcoming_earnings" in sa
        and "def build_handover" in sa
        and "def persist_skips" in sa
    ):
        _ok("v3.25 新引擎器官(bmo_tomorrow/upcoming_earnings/build_handover/persist_skips)")
    else:
        _fail("v3.25 缺新引擎器官")
    if "pre-market" in sa and "time-after-hours" in sa.lower() or "pre-market" in sa:
        _ok("v3.25 BMO 名单按 when 含 pre-market 匹配")
    else:
        _fail("v3.25 BMO 名单未按实值 time-pre-market 匹配")
    if (
        "def _fmp_call_routed" in fe
        and "FMP_RATE_PER_MIN" in fe
        and ".fmp_route" in fe
        and "_FMP_STABLE_BASE" in fe
    ):
        _ok("v3.25 FMP 端点路由器(自探定版+节流)")
    else:
        _fail("v3.25 fetchers 缺 FMP 端点路由器")
    if "_cache_save" in fe and "__proxy_" in fe:
        _ok("v3.25 缓存带血统(src 记账+代理独立键)")
    else:
        _fail("v3.25 缺缓存血统")
    if "def fetch_market_movers" in fe and "def market_movers" in sa and "biggest-gainers" in fe:
        _ok("v3.25.2 全市场异动扫描(源+引擎)")
    else:
        _fail("v3.25.2 缺全市场异动扫描")
    if 'WB + "/gateway/task/expanded"' in sa and '"task": (final_md or "")[:_cap]' in sa and "EXPANDED_TASK_CHARS" in sa:
        _ok("v3.25.2 expanded review b286083 形制(WB+task+final;v3.26.3 task 字数走 EXPANDED_TASK_CHARS 默认 8000)")
    else:
        _fail("v3.25.2 expanded review 形制回滚(缺 WB/task)")
    if "def fetch_most_active" in fe and "def theme_heat" in sa and "industry_lookup" in fe:
        _ok("v3.25.8 全视野器官(最活跃榜+热簇数据自聚)")
    else:
        _fail("v3.25.8 缺全视野器官")
    if "THEMES = {" not in sa:
        _ok("v3.25.8 无手写主题表(热点数据自聚)")
    else:
        _fail("手写主题表残留(2026-08-21 Lyra 禁令:禁写死范围)")
    if "def update_streaks" in sa and "streak_board" in sa:
        _ok("v3.25.8 连涨账本")
    else:
        _fail("v3.25.8 缺连涨账本")
    if "def apply_candidate_floor" in sa and 'apply_candidate_floor(data, shift)' in sa:
        _ok("v3.25.7/8 候选下限代码闸挂载")
    else:
        _fail("候选下限纯 prompt 零核查(v3.25.6 复审①回滚)")
    if '"morning", "midday", "earnings"' in sa.split("def apply_candidate_floor")[1][:400] and "禁止只在板块 ETF" in sa:
        _ok("v3.25.8 earnings 入下限+S1 全视野改写")
    else:
        _fail("v3.25.8 范围/S1 改写回滚")
    if "def _scout_bark" in sa and "group=scout-brief" in sa:
        _ok("v3.25.8 班次 bark 回流(戌 L1524)")
    else:
        _fail("v3.25.8 班次 bark 未回流(下包将踩掉现场热修)")
    if "本班默认不建新仓" not in sa:
        _ok("v3.25.7 midday 矛盾清除")
    else:
        _fail("midday 默认收敛矛盾残留(v3.25.6 复审①)")
    # 全局名可解析(2026-08-23 _NOISE_RX 案:定义丢五版,冒烟没走 evening 链,NameError
    # 现场首炸。此检查静态杀全族:两模块每个函数字节码引用的全局名必须可解析)
    import importlib, builtins, types, dis
    _bad = []
    for _modname in ("scout_agent", "fetchers"):
        try:
            _mod = importlib.import_module(_modname)
        except Exception as _e:
            _bad.append("%s import 失败:%s" % (_modname, str(_e)[:80]))
            continue
        for _fname in dir(_mod):
            _fn = getattr(_mod, _fname)
            if isinstance(_fn, types.FunctionType) and _fn.__module__ == _modname:
                for _ins in dis.get_instructions(_fn):
                    if _ins.opname == "LOAD_GLOBAL":
                        _n = _ins.argval
                        if not hasattr(_mod, _n) and not hasattr(builtins, _n):
                            _bad.append("%s.%s 引用未定义全局名 %s" % (_modname, _fname, _n))
    if _bad:
        _fail("全局名不可解析:" + " | ".join(sorted(set(_bad))[:6]))
    else:
        _ok("全局名可解析(两模块全函数字节码扫描)")
    if "money_confirmed" in sa and "actives_set" in sa and "本班不发🔥" in sa:
        _ok("v3.25.10 热簇资金确认+失败响亮自证")
    else:
        _fail("v3.25.10 资金确认/自证缺失(壳公司冒充热簇案回滚)")
    if "def _next_trading_day" in sa and "晚报无立法权" in sa:
        _ok("v3.25.10 日历纪律+晚报效力边界")
    else:
        _fail("v3.25.10 日历/立法边界缺失")
    if ("def comove_clusters" in sa and 'cross["comove"]' in sa and "def _max_cliques" in sa
            and "med_chg" in sa and ">= 2" in sa.split("def comove_clusters")[1][:6000]):
        _ok("v3.25.15 同频簇=极大团+中位hot+双名资金确认(三路云审刀)")
    else:
        _fail("同频簇团定义缺失(朋友圈案回滚:连通分量/均值hot/单名连坐)")
    if "def sector_flow" not in sa:
        _ok("sector 永真桶已拆净")
    else:
        _fail("sector_flow 永真桶残留(2026-08-24 Lyra 否决)")
    if ("def load_fault_lines_snapshot" in sa and "fault_lines=(load_fault_lines_snapshot" in sa
            and "退避重试" in sa and "去 think 重试" in sa):
        _ok("v3.25.12 戌四处回流(断层读取器/晨会接线/ds 韧性)")
    else:
        _fail("戌四处回流缺失(下包将踩掉现场施工)")
    # ---- v3.26(2026-08-24 财报班垃圾案:PICS $5 无实测出卡 / PATH 十分钟 0DTE / BMNR 落榜)----
    if ("def candidate_pool" in sa and 'cross["candidate_pool"]' in sa and "def apply_quality_floor" in sa
            and "apply_quality_floor(data, shift, cross)" in sa and "def floor_earnings_lists" in sa
            and "floor_earnings_lists(cross)" in sa and "adv20_usd" in fe and "def pool_price_floor" in fe):
        _ok("v3.26 引擎候选池+质量地板代码闸挂载(实测 price/adv20_usd)")
    else:
        _fail("v3.26 候选池/地板闸缺失(六眼只当参考、DS 自由挑、无实测照出卡案回滚)")
    if "price<$5" not in sa and "floor_rejected" in sa and "_floor_kills" in sa:
        _ok("v3.26 财报名单地板后供 DS+作废可审($5 prompt 文字规则已废)")
    else:
        _fail("v3.26 名单地板/作废留痕缺失或 $5 纯 prompt 规则残留")
    if sa.count("明晨预排") >= 3 and "禁 0DTE、禁今日尾盘入场" in sa:
        _ok("v3.26 财报班 S1/S3=明晨预排(prompt+代码前缀+复盘不计命中)")
    else:
        _fail("v3.26 财报班预排缺失(收盘前 15 分钟 0DTE 刮单案回滚)")
    if "kept >= 50" in fe and '120 if source == "market_movers"' in fe:
        _ok("v3.26 movers 抓取 50/侧(真流动 +15% 票被壳票挤出前 20 的盲区)")
    else:
        _fail("v3.26 movers 抓取 cap 回滚到 20")
    if "ETF 不入池" in sa and '"is_etf"' in fe and "ETF 不入候选" in sa:
        _ok("v3.26.1 ETF 硬排(profile isEtf;池+S1/S3 点名两处)")
    else:
        _fail("v3.26.1 ETF 硬排缺失(最活跃榜 ETF 占池、高 IV 单票被挤案回滚)")
    if "def _sort_earn" in sa and '"earn_score"' in sa and "形态错配" in sa and "TAPE_VETO_CHG" in sa and "按市值)未点名" not in sa:
        _ok("v3.27 财报名单按尾盘形态分排+方向/形态错配作废(8-25 INTU 案)")
    else:
        _fail("v3.27 尾盘形态分/错配作废缺失(弱势收低票持过财报 call 案回滚)")
    if "def fmp_board_syms" in sa and "不在当日榜" in sa and os.path.exists(os.path.join(HERE, "acceptance_fmp_board.py")):
        _ok("v3.27.1 财报 call 腿必须在当日榜(资金确认)+ 名单 fmp_board 标记 + 现场验收脚本在场")
    else:
        _fail("v3.27.1 榜硬门/验收脚本缺失(Lyra:不在 top mover 榜的不收)")
    if ("def trend_board(" in sa and '"趋势🔥"' in sa and "def fetch_screener_universe" in fe
            and "def history_snapshot" in fe and '"up5"' in fe and 'cross.get("trend_board")' in sa):
        _ok("v3.28 自算趋势榜(第七只眼,BMNR 案:FMP 两榜天生看不见连涨大票)")
    else:
        _fail("v3.28 趋势榜缺失(连涨一周的趋势票再次隐形)")
    if "if vol > 0 and px * vol < 5e7" in fe and "volume0_passed" in fe:
        _ok("v3.28.1 screener volume=0 放行(BMNR volume=0 被粗筛误杀案)")
    else:
        _fail("v3.28.1 screener 粗筛仍会误杀 volume=0 的票")
    if "def _last_closed_session(today, now_et=None)" in sa and "def now_et" in fe and "need_date=key" in sa and "coverage >= 0.5" in sa and '"last_bar_date"' in fe:
        _ok("v3.28.2 趋势榜时钟(晚班键=当日、次晨同键零重算)+ 当日 EOD 覆盖自证(不足不落盘)")
    else:
        _fail("v3.28.2 趋势榜时钟/覆盖自证缺失(晚班算昨榜、次晨重算 1200 票案)")
    fp = os.path.join(HERE, "factors.py")
    fx = open(fp, encoding="utf-8").read() if os.path.isfile(fp) else ""
    old_rules = [k for k in ("最活跃+3", "趋势榜+3", "同频团+2", "热簇+1", "近52周高+1", "收高位+1", "FMP榜+2") if k in sa]
    if (fx and "FACTOR_BUDGET" in fx and "def score(" in fx and "import factors" in sa and "factors.score(" in sa
            and not old_rules and "/v3/option/snapshot/greeks/all" in fe and "def regime_and_kelly(" in sa):
        try:
            sys.path.insert(0, HERE); import factors as _f
            n_f = len(_f.FACTORS); ok_budget = n_f <= _f.FACTOR_BUDGET
        except Exception as exc:
            n_f, ok_budget = -1, False
        if ok_budget:
            _ok("v3.29 六因子核(factors.py,%d 因子 ≤ 预算 %d)替代手写规则;F5 Theta greeks 端点按官方文档;仓位档/Kelly 只显示" % (n_f, _f.FACTOR_BUDGET))
        else:
            _fail("v3.29 因子数超预算(过拟合危险区)")
        if "def f5_persist(" in sa and "allow_afterhours=True" in sa and '"mktcap_b"' in fe and 'info.get("mktcap_b")' in sa:
            _ok("v3.29.1 F5 盘后缓存(16:45 班落盘,盘前/晚班回退标 F5昨收)+ profile 市值兜底 F1")
        else:
            _fail("v3.29.1 F5 缓存/市值兜底缺失(盘前 F5 全缺、F1 退成交额档案)")
        if "def _bar_is_partial(" in fe and '"fetched_ts"' in fe and "PARTIAL_REFRESH_S" in fe:
            _ok("v3.29.2 盘中拉到的当日部分 bar 收盘后重拉(INTU 8-25 行 O 对 H/L/C 不对案)")
        else:
            _fail("v3.29.2 部分 bar 当终盘案回滚(prices 缓存被盘中快照污染)")
    else:
        _fail("v3.29 因子核缺失或手写规则回流:%s" % (old_rules or "factors.py/接线缺"))
    if ('"days_out"' in sa and 'if dt == nd and "pre-market" in when' in sa and "far >= 6" in sa):
        _ok("v3.26.2 run-up 单收次日 AMC(d1)+近远窗各自座位(NVDA 周二盲区案)")
    else:
        _fail("v3.26.2 run-up 单次日 AMC 盲区回滚(周二班看不见周三盘后 NVDA)")
    # ---- v3.26.3(戌 8-24 晚报审:晚报纪律/逗号票/晨会超时/GLM 闸/盘后空)----
    _ev = sa.split("        # 雷达第5项供数")[1][:4000] if "        # 雷达第5项供数" in sa else ""
    if "candidate_pool(cross)" in _ev and "floor_earnings_lists(cross)" in _ev and "amc_results_health" in sa:
        _ok("v3.26.3 晚班吃候选池+三名单地板+盘后健康态")
    else:
        _fail("v3.26.3 晚班未挂候选池/地板(晚报仍拿 PICS 当过夜腿案回滚)")
    if "逗号票" in sa and "一卡一票" in sa:
        _ok("v3.26.3 逗号票作废(非单一代码绕闸案)")
    else:
        _fail("v3.26.3 逗号票绕闸未堵")
    if "DS_TIMEOUT" in sa and "DS 调用失败(" in sa and "本班无有效作业" in sa and '"afterhours"' in sa and "def run_afterhours_snapshot" in sa:
        _ok("v3.26.3 DS 超时可调+失败落页+afterhours 快照班")
    else:
        _fail("v3.26.3 晨会超时崩班/盘后快照缺失")


def gate_live() -> None:
    print("[2] 实况闸(采日历+指数 RSI + gateway)")
    # load .env lightly
    envp = os.path.join(HERE, ".env")
    if os.path.isfile(envp):
        for ln in open(envp, encoding="utf-8"):
            s = ln.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

    import fetchers
    import scout_agent as sa

    sa.OUT = HERE
    fetchers.SKIPS.clear()

    cal = fetchers.fetch_earnings_calendar()
    if not cal.get("ok"):
        _fail("earnings_calendar ok=False: %s" % (cal.get("error") or "?"))
        today_amc = []
        team_in_cal = False
    else:
        today = fetchers.trading_date().isoformat()
        items = cal.get("items") or []
        today_amc = [
            (it.get("symbol") or "").upper()
            for it in items
            if str(it.get("date") or "")[:10] == today
            and "after" in (it.get("when") or "").lower()
            and re.fullmatch(r"[A-Z]{1,5}", (it.get("symbol") or "").upper())
        ]
        team_in_cal = "TEAM" in today_amc
        if not today_amc:
            _fail("今日 AMC 日历为空(检查 wrap/热日/日期锚)")
        else:
            _ok("今日 AMC 日历 n=%d" % len(today_amc))

        payload = {"results": [cal]}
        amc = sa.amc_tonight(payload, today)
        amc_syms = [
            (x.get("symbol") if isinstance(x, dict) else x) or ""
            for x in (amc or [])
        ]
        amc_syms = [s.upper() for s in amc_syms]
        # v3.16.2: 带读数(至少一票有 chg_pct)
        if amc and isinstance(amc[0], dict) and any(
            isinstance(x, dict) and x.get("chg_pct") is not None for x in amc
        ):
            _ok("amc_tonight 带 Alpaca 读数(chg_pct)")
        elif amc:
            _fail("amc_tonight 未带 chg_pct 读数(v3.16.2)")
        if team_in_cal and "TEAM" not in amc_syms:
            _fail("日历含今日 AMC TEAM 但 amc_tonight 无 TEAM(cap/过滤)")
        elif team_in_cal:
            _ok("TEAM ∈ amc_tonight(日历有今日 AMC)")
        else:
            _ok("今日日历无 TEAM——跳过 TEAM 专检(名单仍须非空)")
            if not amc:
                _fail("amc_tonight 为空")

    # RSI via indices+hedge
    idx = fetchers.fetch_indices()
    hed = fetchers.fetch_hedge_assets()
    payload2 = {"results": [r for r in (idx, hed) if r]}
    cross = sa.cross_asset_summary(payload2)
    tape = cross.get("rsi14_tape") or []
    by = {x.get("name"): x.get("rsi14") for x in tape if isinstance(x, dict)}
    need = ("SP500", "NASDAQ")
    missing = [n for n in need if by.get(n) is None]
    if missing:
        _fail("rsi14_tape 缺实测: %s (现 %s)" % (missing, by))
    else:
        _ok("rsi14_tape SP500=%s NASDAQ=%s" % (by.get("SP500"), by.get("NASDAQ")))

    # FMP key(主源无弹 = 全链退 backup,响亮)
    if os.getenv("FMP_API_KEY", "").strip():
        _ok("FMP_API_KEY 在位(主源有弹)")
    else:
        _fail("FMP_API_KEY 未配置——主源无弹,全班退 Theta/Alpaca backup")

    # gateway reachable for emit
    gw = os.getenv("GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")
    try:
        req = urllib.request.Request(gw + "/health", method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            if 200 <= resp.status < 300:
                _ok("gateway %s/health 可达(emit 前置)" % gw)
            else:
                _fail("gateway health status=%s" % resp.status)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        _fail("gateway 不可达,emit 必失败: %s" % e)


def main() -> int:
    ap = argparse.ArgumentParser(description="Scout 本机装包后门禁")
    ap.add_argument("--skip-live", action="store_true", help="只跑静态代码闸")
    a = ap.parse_args()
    print("=== verify_scout_deploy · %s ===" % HERE)
    gate_static_code()
    if not a.skip_live:
        gate_live()
    else:
        print("[2] 实况闸 SKIP(--skip-live)")
    print("---")
    print("OK %d · FAIL %d" % (len(OKS), len(FAILS)))
    if FAILS:
        print("门禁未过——禁止宣称部署完成。失败项:")
        for f in FAILS:
            print("  -", f)
        return 1
    print("门禁通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PKG_EOF_006
if [ -f 'verify_scout_deploy.py' ]; then
  echo "[install] 保留既有 verify_scout_deploy.py(Cursor 侧资产,替换与否 Lyra/Cursor 拍板,不覆盖);新模板→verify_scout_deploy.py.new"
  mv .tmp_006 verify_scout_deploy.py.new
else
  mv .tmp_006 verify_scout_deploy.py
fi
# ———— 自检自跑:不用人当 QA(v3.25:先检后跑,重跑不改写账本) ————
python3 - <<'SELFCHECK'
import datetime, json, os, subprocess, sys
# .env 装载走 python(v3.24:bash 端 `. ./.env` 在 set -e 下会被 .env 非法行杀死安装)
if os.path.exists(".env"):
    for _l in open(".env", encoding="utf-8"):
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            k, v = _l.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
try:
    import py_compile
    py_compile.compile("scout_agent.py", doraise=True)
    py_compile.compile("fetchers.py", doraise=True)
except Exception as e:
    print("❌ 编译失败(带这行来找守恒):", e); raise SystemExit(0)
print("✓ 编译自检过")
vp = "verify_scout_deploy.py" if os.path.exists("verify_scout_deploy.py") else "verify_scout_deploy.py.new"
r = subprocess.run([sys.executable, vp, "--skip-live"], capture_output=True, text=True)
if r.returncode == 0:
    tail = (r.stdout or "").strip().splitlines()[-2:-1] or ["?"]
    print("✓ 门禁静态闸(%s):%s" % (vp, tail[0]))
else:
    print("❌ 门禁静态闸未过(%s)——禁止宣称部署完成,输出末6行:" % vp)
    print("\n".join((r.stdout + r.stderr).strip().splitlines()[-6:]))
if not os.getenv("DEEPSEEK_API_KEY"):
    print("⚠️ 当前 shell 无 DS key,跳过重渲检查——定时班(plist/.env 带 key)下一班自动生效")
    raise SystemExit(0)
try:
    import fetchers; today = fetchers.trading_date().isoformat()
except Exception:
    today = datetime.date.today().isoformat()
if datetime.date.fromisoformat(today).weekday() >= 5:
    print("⚠️ 非交易日,跳过重渲检查(账本卫生)"); raise SystemExit(0)
if not os.path.exists(os.path.join("raw", today + ".json")):
    print("⚠️ 今日无 raw(未到班或首装),跳过重渲——下一班自动生效"); raise SystemExit(0)
hp = os.path.join("briefs", today + "-morning.html")
jp = os.path.join("briefs", today + "-morning.json")
def _ok():
    if not (os.path.exists(jp) and os.path.exists(hp)):
        return False
    try:
        if (json.load(open(jp, encoding="utf-8")).get("ds") or {}).get("_parse_failed"):
            return False
    except Exception:
        return False
    return "一 · 大盘方向" in open(hp, encoding="utf-8").read()
if _ok():
    print("✅ 今晨产物完好,不重跑 DS(重跑=改写账本:复盘对象必须是早上那份)")
    raise SystemExit(0)
def run(extra=None):
    return subprocess.run([sys.executable, "scout_agent.py", "--mode", "morning", "--skip-fetch"],
                          capture_output=True, text=True, env=dict(os.environ, **(extra or {})))
r = run()
if "疑输出截断" in (r.stdout + r.stderr):
    r = run({"DS_MAX_TOKENS": "16000"})
print("✅ 今晨已重渲,卡片已回:刷新页面即可" if _ok() else
      "❌ 未恢复,自诊(原样带来,勿自行分析):\n" + "\n".join((r.stdout + r.stderr).strip().splitlines()[-6:]))
SELFCHECK
# v3.28.1:自归档(戌 8-25:仓里没有本版安装脚本副本,对账少一份落盘)
cp -f "$SELF_PATH" "./scout_agent_install_v3_29_2.sh" 2>/dev/null && echo "[install] 安装脚本已归档 ./scout_agent_install_v3_29_2.sh" || true
echo ""; echo "✓ Scout Agent v3.29.2: $(pwd) — 首跑 python3 scout_agent.py --mode morning;门禁 python3 verify_scout_deploy.py"

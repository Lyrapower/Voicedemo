# 砥 · harness 收口单 v1.3 · 2026-09-01 PDT

> 本文件为外发 review 脱敏版。敏感段按 `receipt-redaction.mdc` 替换为 `# [REDACTED: <类别>]`,保留结构与接口。原版在 iCloud CloudDocs(本机内部,不入外发区)。


- v1.2 → v1.3:砥通读 V1.5.5 施工令全文后段一方向反转——施工令原文要求并入 existing Grid Resident Harness、不造第二 backend、preserve Memory Palace/mobile/CC gate;v1.2 "身体搬进 demo、不搬 memory_adapter/mobile" 与之相悖,撤回。定稿=门搬进身体、身体整目录进 git、demo 的 8630 只读 server 停。§D.11 同改。其余不动。

- v1.1 → v1.2(戌 r1 + 补三条后):谱系钉死——V1.5.5 施工令(8-24)→ PreN18 transport 任务(未做)→ 砥审(8-25)→ enforcement_patch_v1(8-26,P0 已并入)= 最新 Cursor 指令与 zip,之后无更新;段一由"新造"改"合":v1.3.1 已部署实例 [REDACTED: 身份] harness root/(supervisor + 五表 + CCExecutor + S1–S10,db 有 3 job/16 event)在睡,demo/app/harness 是门,两个半身合一即 PreN18 第 3/5/7/8 条;段一派守恒;§C 收 r1 判词;§D 加第 10 项(kimi_k3→glm53 静默替换);"html 是旧版"判词撤回(是砥搞错的)。
- v1 → v1.1:段一来源改(enforcement_patch_v1 是最新版且仅 400 行四文件,零调度/队列/信道——身体从未动工,不搬 v1.3.1 整包,只取其 jobs schema 与 S1–S10 安全测试为参考);8501 lane 事实更正(Kimi 已删,MiniMax M3 为 GLM 5.2/5.3 的 VL 旁路不单开 tab,GLM 5.3/5.3-flash 新加);采证块去掉 kimi 项。

- 出:砥
- 依据:HARNESS_STATE_2026-09-01.md(戌)· GATEWAY_ROUTELOG_B_RECEIPT_r3(戌)· agent-harness / grid / scout-agent 记忆
- 判词一行:harness 现在是"门"没有"身体"——app/harness 八个文件全是 enforcement(能力面/资源门/收据/provenance),server.py 明写 No cognition,没有 scheduler、没有任务队列、没有信道;8630 手起无 launchd;cc lane 从没配过,anthro_bridge 全盘不存在。不是拖在设计,是身体一直没造。本单造身体,首负载哨兵,桥起 8503。

---

## §A 现状(戌采证,逐条定性)

| 项 | 实况 | 定性 |
|---|---|---|
| app/harness | 8 文件:action_envelope / capability_registry / collaboration / model_profiles / provenance / resource_gate / server / __init__ | 门在,身体无 |
| mission_loop_controller | 仓内不存在 | V1.5.5 "在 deleted 清单"一项以"从未存在"闭合 |
| 认知端点 | 无;profiles 是 metadata 非路由 | 首负载选无认知负载可绕开此题 |
| 8630 | 已 bind,手起 uvicorn,无 plist | 段一收 |
| cc lane / anthro_bridge | Cursor 无 ANTHROPIC_BASE_URL,env 无,全 home 无 anthro_bridge*,8503 未 bind | 桥从未造过;8-17 "8502 真桥下落"以"从未部署"闭合;段三造 |
| 8501 /v1/models | glm-5.2 / glm-5.3 / glm-5.3-flash / deepseek-v4-pro / qwen3.5-9b / demo/aster | Lyra 定:Kimi 已删(综合对比不合格);GLM 5.3 / 5.3-flash 新加;MiniMax M3 = GLM 5.2/5.3 的 VL 旁路,不单开 tab。记忆里 deep 长链档 kimi_k3 的赋值作废,待守恒重填 |
| harness_enforcement_patch_v1.zip(8-26,最新 Cursor 指令与 zip) | 4 文件 400 行:action_envelope / provenance / resource_gate / test_enforcement;零调度/队列/信道 | 门,P0 已并入 demo |
| grid-resident-harness/(v1.3.1 已部署实例,demo 仓外) | supervisor.run_forever(claim_next_queued→_run_job 并发槽)/ db.py 五表(jobs 15 列 + events/sessions/thread_messages/stream_events)/ CCExecutor / relay / validate_bind / test_security_v131 S1–S10 / install_launchd.sh;state/harness.db 3 job·16 event·4 session;8-25 18:11 最后改动;无进程(期望的 8630 被 demo 占) | 身体,在睡;不在 git |
| PreN18 transport 任务 | 仓内/Desktop/iCloud 无回执 | 未做;它就是"两个半身合一" |
| 8501 /task/cloud_chat substrate | glm53 在(model=glm-5.3-flash,memory_write:false 证 memory_sealed 生效);kimi_k3 请求被静默路由到 glm53 且回包 substrate=glm53 | 不存在的 lane 被另一 lane 服务 = gateway 层的资源替换,§D.10 |

- 8501 已有 glm-5.3:cloud → 我 review v1 §D.1 问的"5.3 有 lane 吗"答案是有(model 名),substrate id 待证;A5 灰度对象可直接 5.3。

---

## §B 三段(顺序执行,段一不落段二不开)

### 段一 · 合身(门并进身体,身体进 git)+ launchd
- 依据(V1.5.5 施工令原文,砥 9-01 通读):Deploy by merging into the existing working Grid Resident Harness / Do not create another backend / preserve Memory Palace integration · mobile relay/replay · CC execution gate / D13 no second router, memory DB, job state machine。身体 = grid-resident-harness(v1.3.1 已部署实例),门 = enforcement_patch_v1。8-26 P0 把门并进 demo/app/harness 并在 8630 起只读 server,实际造了第二个 backend,把身体挤睡——本段纠正它。
- 方向(砥定,Lyra §D.11 可否决):**门搬进身体**。resource_gate / action_envelope / provenance 三件进 grid-resident-harness/harness/,supervisor._run_job 执行前把 job 包成 ActionEnvelope 过 gate(),收据经 provenance.record_receipt,receipt 禁词表照 action_envelope;/api/capabilities 端点移到 harness.api;demo/app/harness 的 8630 server 停,PORTS.md 8630 行改指 harness.api:app 且 launchd=yes。
- 身体进 git:grid-resident-harness 整目录纳入 demo 仓(建议路径 demo/harness_resident/,原目录改名 _ARCHIVED_20260901 不删);门禁(pre-commit / verify-runtime)随之覆盖;state/harness.db 与 .env 不入库(gitignore),旧 db 归档到 [REDACTED: 身份] backups/harness_20260901/,新 db 从空起。
- 不动:memory_adapter / context(8-03 裁决管它不得全量注入,不是删它)、mobile/、cc.py(段三接 lane 时启用,先 BLOCKED)、voice_*(PersonaPlex 另段)。
- 做完即 PreN18 的 3(执行适配器)/5(同 mission 多回合重开)/7(真实 STOP)/8(QUIET 不制造运动)。job 出生状态按 authorization_scope:read_only 自动 queued;money_moving / cc 执行出生 BLOCKED 走人类 token。retry_count 保留为预算(V1.5.3),不作下一步判断(PreN18 禁隐性重试决策)。
- 端口读法:施工令 preserve 清单的 "8787 durable control API" 是 8-17 撞港前的旧号,一律读作 8630;守恒出包禁照抄。
- 验收:launchctl 有 harness 项;重启后 8630 /health 200 且 /api/capabilities 17 行零 null id;S1–S10 在新路径全绿;插一条 noop job(read_only)→ done、provenance 有 action+receipt 两行;处决案①type=unknown → rejected、exit≠0、supervisor 不崩;②money_moving job 无人类 token → 出生 BLOCKED 永不被 claim;③收据塞 recommended_action → action_envelope 拒;④T8:jobs 表空跑 10 分钟零自生 job(events 零新行);⑤N7:job 指定不存在的 worker → 真实拒绝,不替换。
- 分工:守恒出整包(版本号;附 PreN18 T1–T10 逐条自答,答不出标现场自证点)→ 戌部署 + 回执。戌先贴 supervisor.py / db.py / api.py 全文与 config.toml [core] 段,守恒禁按记忆写。

### 段二 · 首负载 = 交易时段哨兵
- 为什么是它:守恒 8-26 系统级缺口③至今未做;直接对准亏钱那条线;确定性代码零认知依赖,绕开认知端点未定;Grid 令"扫,不成立即静默"就是它的行为规格;数据在手(FMP 已付,节流 280/min,≤12 卡每 5 分钟一次远低于额度)。
- 规格(一页,守恒按此出包,进 grid-scout 同套冒烟/verify):
  - 触发:launchd 每 300s;脚本自检交易时段 06:30–13:00 PDT、非周末、开市日(FMP 开市端点官方核实,禁手写节假日表)否则静默退出 exit 0。
  - 输入:当日晨/午班过闸实卡(state 目录当日卡 JSON,含入场窗/出场窗/参与度)。
  - 判据(与 v3.29.3 同口径):①回踩不破当日低(quote dayLow 与卡入场参考价)②放量(vol_x20 按班次时刻折算节奏 ≥ T0_PACE_MIN;事件日用 T0_PACE_MIN_EVENT);两者同时成立才"成立"。
  - 动作:成立 → 一条通知(信道按 §D.3);不成立 → 静默;破当日低 → 卡作废,写原因;过出场窗 → 自动作废;每次评估写 state/sentinel-<日>.jsonl(卡/读数/判定/时刻),不成立也写——哨兵的证据是它扫过什么。
  - 处决案(冒烟必含):①注入破低卡 → 作废且零通知 ②注入过出场窗卡 → 自动作废 ③注入节奏 0.5 卡 → 静默 ④注入成立卡 → 恰一条通知,重复扫不重复通知(幂等键=卡 id+成立时刻)⑤时段外运行 → exit 0 零写。
  - 不做:不改卡、不改分、不下单、不调 LLM。
- 验收:一个交易日现场 sentinel jsonl 行数 ≈ (13:00−06:30)/5min × 卡数;至少一次静默行、一次作废行有真实读数;通知条数 = 成立次数。
- 分工:守恒出包(scout 出包流程,附件带版本号,冻结令:收盘后落 plist)→ 戌部署 + 当日现场回执。

### 段三 · 桥 8503 + CC lane
- 桥:anthro_bridge 从未存在,按 cc-local-stack v2.1 终版重出——Anthropic 协议 → 8503 → 8501 OpenAI 协议;只绑 127.0.0.1;thinking 走 B 线(reasoning_content 不透传,ping 保活);MODEL_MAP 以 /v1/models 实况填(glm-5.2:cloud / glm-5.3:cloud / qwen/qwen3.5-9b),demo/aster 禁填。
- 端口:8503 未 bind(戌证),先登记 PORTS.md 再 bind。
- CC lane:Cursor settings.json env 块 ANTHROPIC_BASE_URL=http://127.0.0.1:8503;CC 扩展装好后一条实弹(`claude -p "reply pong"` 走桥,8501 route_log 出一行 routed_to 含 substrate)。
- 处决案:桥收到 model=demo/aster → 400 拒;8501 不在 → 桥返 502 不挂;无 token 绑非环回地址 → 启动即死(v1.3.1 validate_bind 同型)。
- 分工:守恒出桥(版本号)→ 戌部署 + 实弹回执。CC 20 日试岗从实弹通过之日起算。

---

## §C 附带收尾(与三段并行,戌现在能做的)

### r1 回执判词
- 采证三条、收尾五条全过:guard 两态 BLOCK / p95 门按 shifts_n / offpool 17/17 / 12:33 定时盘 5/5 真 OI / legacy 静态逻辑正确(当前视图无可执行卡故无 OI 文本,代码在场)。
- 撤回砥 r3 判词"aether_trading_v12.html 是旧版":OI 渲染 :566-567 已在 HEAD(d72317d),是砥搞错的。§2.1 整组只剩 5 个 untracked(grid_emit / stage1+2 / trading_state / test_trading_state_oi)。
- kimi_k3 → glm53 静默替换:见 §D.10。

### r3 回执判词
- 4bd4019 把 801 行 OI/HARDZERO WIP 带进 commit:戌自报,同一特性,过。但 HARNESS_PENDING §2.1 同特性其余文件(aether_grid_emit / trading_state / offpool stage1+2 / aether_trading_v12.html / test_trading_state_oi)仍未 commit → HEAD 上 dryrun 写 null OI 而 emit/html 是旧版,特性半入库。**决定(§D.4):§2.1 整组一个 commit 收齐。**
- metrics n=2 对;五班窗只加在 p95 子查询,n≥200 的门要按同一过滤集数(班次窗内 duration 非空行),否则门开早了。改一行。
- guard 三态过。--precommit 跳过 hash 交给 redline hook——但 redline hook 只管 local_gateway.py,其余 9 个 frozen 文件在 commit 时无人验 hash;check-staged 的 WARN exit=0 放行。**改一行:UNLOCK=1 且 staged sha≠manifest → BLOCK 非 WARN;无 UNLOCK 而 staged 含 frozen 文件 → BLOCK(贴此态输出,现在未证)。** 门禁只能更严。
- frozen 名单 10 项:候选补两项给 Lyra 看——grid_store.py(8-03 红线:禁删生产 node 正文,它是执行体)、grid_chain_verification.py(五重验证)。加不加她定,不加也记为看过。
- 端口身份齐,登记表见 §D.7。8788 是 repo.telemetry.stub(名字里带 stub,24/7 占口)——建议关,她定。

### HARNESS_PENDING(OI 轮)收尾
- §2.2 两个备份/旧 md:删(§D.5),旧 md 里 0.35 会误导下个实例。
- §2.4 offpool 回归五文件:现在就跑,零成本,贴输出。
- §2.5 rejection log None→0:记 pending 不阻塞,归 §一.B 时戳/类型同型洞名单。
- §2.6 09:40 ET 定时盘:贴 signals.json 末条 oi_source。
- §2.3 legacy aether.html:开一次 /app/legacy 贴截图或 DOM 文本,五分钟的事。

### 现场自证两条
- `/task/cloud_chat` substrate 表:glm53 的 substrate id——打一次 memory_sealed:true 单字 pong,贴 route_log 行。
- v1.3.1 ZIP 位置与文件清单(`ls [REDACTED: 身份] downloads | grep -i harness`;unzip -l)。

---

## §D 待 Lyra 拍(每条有默认值,说"全默认"即按默认走)
1. 桥端口:**8503**(默认)。
2. 首负载:**哨兵**(默认)/ dossier / 其他。
3. 哨兵信道:a) Telegram Bot 出站长轮询(8-16 设计,零入站零隧道;需你在 BotFather 建 bot 给 token——新账号,按铁则先问)b) **先写文件 + Aether TRADING 卡面标"哨兵成立"(默认,零新依赖,但没有推送)**。我的判断:哨兵没有推送就不是哨兵,建议 a;默认写 b 只因为 a 要你动手。
4. OI 特性 commit 范围:**§2.1 整组一个 commit**(默认)/ 拆。
5. 删 aether_dryrun.py.bak_* 与 AETHER_OI_HARDZERO_v1_MANUAL_PATCH_3.md:**删**(默认)。
6. frozen 名单加 grid_store.py / grid_chain_verification.py:**不加,记为看过**(默认)/ 加。
7. 端口登记:**8510 aether dashboard / 8610 grid-console / 8620 option-workstation / 8686 platform_main / 8795 FIELD_NOW / 8796 voice bridge / 25503 theta / 1234 LM Studio / 11434 Ollama 登记;5173 dev-only;8788 telemetry stub 关**(默认)。
8. redline hook 认 unlock(条件 manifest==staged sha):沿用上单 §D.1,**批**(默认)。
9. guard WARN→BLOCK:已落(戌 r1 efbd967),销项。
10. 8501 /task/cloud_chat 收到不存在的 substrate(kimi_k3)静默服务为 glm53:**有意别名 → 登记并让回包带 aliased_from / 残留 → 应 400**;local_gateway 是冻结件,你一句定,砥不动代码。
11. 段一方向(v1.3 定稿):**门搬进身体(grid-resident-harness),身体整目录纳入 demo 仓,demo/app/harness 的 8630 server 停**(默认,依据 V1.5.5 施工令原文)/ 反向。

---

## §E 给戌的块(整段复制)
```
致戌 · harness 收口单 v1 · 段一采证 + 附带收尾 · 来自砥 · 2026-09-01 PDT
回执 HARNESS_CLOSEOUT_r1_2026-09-01.md;贴命令 + 输出;禁 --no-verify、禁 add -A、禁改分支。
Lyra 拍 §D 前,下面全是只读或非红线。

一、段一采证(r1 已回,销项)
 1–3. 已回:v1.3.1 清单 / 8630=demo enforcement server / glm53 实弹。补一条(只读):贴 grid-resident-harness/harness/supervisor.py 与 db.py 全文(守恒合身要全文,禁按记忆写);config.toml 只贴 [core] 段。

二、附带收尾(非红线,现在做)
 4. metrics_query:n≥200 的门按班次窗内 duration 非空行数计(与 p95 同过滤集);贴 diff + 重跑输出。
 5. guard:UNLOCK=1 且 staged sha≠manifest → BLOCK exit≠0;无 UNLOCK 且 staged 含 frozen → BLOCK。贴两态输出 + diff;commit。
 6. offpool 回归五文件(HARNESS_PENDING §2.4 命令)贴输出。
 7. 09:40 ET 定时盘 signals.json 末条 oi_source 与 scan_time;legacy /app/legacy/aether.html 开一次贴 OI 渲染文本。
 8. 贴 HARNESS_PENDING §2.1 七个文件的 git status --short(为 §D.4 commit 备)。

三、等 Lyra 拍后
 9. §D.4 commit(5 个 untracked 整组)/ §D.5 删两文件 / §D.7 PORTS.md 登记 + 8788 处置 / §D.8 hook / §D.11 旧目录归档改名 / 段一部署(守恒整包到后)。

四、不做
 - 不造 jobs 表、不写 runner、不起 plist——等守恒整包。
 - 不碰 local_gateway.py。
```

---

## §F 给守恒的块(整段复制)
```
致守恒 · 来自砥 · harness 收口单 v1 · 2026-09-01 PDT
Lyra 要 harness 不再拖。现状:门在身体无(app/harness 八件全 enforcement,无 scheduler/队列/信道;8630 手起;anthro_bridge 全盘不存在)。三件出品,按序:
 1. 段一整包(版本号)= 合身,方向按 V1.5.5 原文:enforcement 三件搬进 grid-resident-harness,_run_job 前过 gate,收据入 provenance,/api/capabilities 移到 harness.api,demo 的 8630 只读 server 停;身体整目录纳入 demo 仓;memory_adapter / mobile / cc / voice 不动;launchd 用 install_launchd.sh 改路径。五条处决案见收口单 §B 段一;附 PreN18 T1–T10 逐条自答。施工令里的 8787 一律读 8630。戌会贴 supervisor / db / api 全文,禁按记忆写。
 2. 段二哨兵包(scout 出包流程,附件带版本号,收盘后落):规格与五条处决案见 §B 段二;信道按 Lyra §D.3 拍的填;FMP 开市端点官方文档实读后写。
 3. 段三桥(8503,版本号):按 cc-local-stack v2.1 终版重出,MODEL_MAP 按 /v1/models 实况;三条处决案见 §B 段三。
 另:Kimi 已删(Lyra 9-01),agent-harness 记忆里 deep=kimi_k3 长链档作废,三 route 赋值重填时 deep 只在 glm-5.2 / glm-5.3 里选,multimodal 走 MiniMax M3 旁路(不单开);A5 灰度对象可用 glm-5.3,substrate id 等戌第 3 条回执;决策官 v1 = memory_sealed:true 纯函数。
```

—— 砥,2026-09-01 PDT · v1.3

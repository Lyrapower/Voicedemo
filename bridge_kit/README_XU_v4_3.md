# 戌执行包 · 8630/BRIDGE 线 · v4.3 · 2026-09-10 PDT(替代 v1–v4.2;本文只给戌)

附件:`bridge_kit_v4_3_2026-09-10.tgz`(8 模块 + 3 条命令 + 67 处决案,零依赖,3.9 语法)。v4.2→v4.3 加三条命令:`site_probe.py`(§1 现状核对一条命令出报告)、`wire_verify.py`(接线后只读自证,PASS/FAIL 带证据)、`dry_run.sh`(整个接线顺序一条命令跑完,沙箱假 repo 已跑通 DRY_RUN_OK)。v4.1→v4.2 修 Astra 对源码抓出的四洞:搜索没传 EGRESS 校验器即拒(不再放行);月计数文件损坏 → 拒不归零;输入流真半行(无换行)隔离、不算已见、下一行不粘连,完整性以 ingested= 判;重试 deadline 不重复扣、Retry-After 为等待下限。另加:配额锁内原子预留(4 进程 cap=1 只 1 个拿到、4×25 increment 无丢)、回链按字段解析(note 里冒充 seed_hash 不算)。

## 抬头
- 沙箱跑过:`python3 bridge_kit/selfcheck.py` → **67 passed / 0 failed / 0 errors / 67 run**;`dry_run.sh` 对假 repo 全程 DRY_RUN_OK(数 testsRun 不数行);`e2e_synthetic.py` → E2E_SYNTHETIC_OK;tgz 重解压复跑同结果。
- 官方文档查过:Ollama web_search(docs.ollama.com);Theta v3 端点/参数/错误码/快照清空/at_time(docs.thetadata.us);Brave 端点(api-dashboard.search.brave.com);Google CSE 已关新客户、Bing API 已退役。
- 够不着:她机器上的 repo / 8630 / 8501 / H1 / Theta / Ollama 账户额度。真机全部按 §2 由戌贴证据。
- 不签任何"真机已通"。

## 0 · 九问对账
1 桥 A grid_inbound.py · 2 桥 B h1_job_block.py · 3 theta_probe.py · 4 tool_hints + web_search_ollama(主)/brave(备) · 5 cloud_slot.py · 6 §2.6 · 7 lane_for_job · 8 §2.8 · 9 §2.9

## 1 · 现状核对(一条命令,贴输出原文)
```
python3 bridge_kit/site_probe.py --repo . --egress EGRESS.md --gateway local_gateway.py \
  --stream <Grid 输入流文件> --h1 <H1 解析模块> --theta-src <v6.1 目录> --config-8501 <8501 config>
```
只读。报告含:HEAD/脏树、gateway 是否读输入流、三 jid 是否已在流里、H1 分路③、v6.1 的 Theta 版本口径、8501 槽数、EGRESS 五行、三把 key 有无(不报值)、8630 /api/missions、/tools、本机 11434 是否代理 web_search、Theta mdds。够不着的项写 NOT_REACHABLE/NOT_FOUND。给不出的路径参数留空,报告里是 NOT_GIVEN。

## 2 · 施工(每段一 commit,贴 hash)

### 2.A 桥 A(`grid_inbound.py`)
1. receipts.jsonl 落地 hook 加 `InboundWriter(stream_path).write(receipt)`;stream_path=§1 第 2/3 条查出的 Grid 输入流文件;字段名不同在 hook 映射。
2. 一条命令跑完回填+自证:`bash bridge_kit/dry_run.sh <receipts.jsonl> <Grid 输入流> . EGRESS.md local_gateway.py`(selfcheck → site_probe → 回填两次 → wire_verify → e2e),贴全部输出;末行须 DRY_RUN_OK,wire_verify 的 overall 须 PASS(A1 每条收据在流里 / A2 无重复键 / A3 无半行 / A4 三 jid 在 / B1 回链字段可解析)。
3. gateway 组上下文若不读输入流:**只出 diff 贴全文,不落**,归 Lyra 一字。
4. 真机验收只正向:wire_verify PASS + Lyra 问 Grid。负向案全在 fixture。

### 2.B 桥 B(`h1_job_block.py`)
1. H1 保留自己的解析器 → dict 交 `compile_job(payload, origin, block_text)`;缺项 CompileError 回退不进 8630。类型/范围/授权检查(R03 §四 2)在 8630 gate,不在编译器。
2. create_mission 落 origin/seed_hash;收据 `attach_lineage`;job.lane 由 mission.lane 写入(R13)。
3. 管道自证:`e2e_synthetic.py` 沙箱同款贴 OK;synthetic 块投真 H1 → **停在 proposed**,贴 /api/missions 行;放行归 Lyra 一键(§4.1);跑完贴收据行与 `verify_roundtrip`。
4. 处决案:缺 `bounds.stop` 的块 → 不出现在 /api/missions。

### 2.3 option 472(`theta_probe.py`)
贴 J-0f9f 真实请求原文;在她机器跑 `python3 bridge_kit/theta_probe.py SYMBOL EXP STRIKE RIGHT` 贴 verdict。`TIME_WINDOW_SNAPSHOT_EMPTY` → 影子账记 `unsettled:market_closed`;**结算用原市场日 at_time/quote 重取**(v6.1 若已有 at_time 路径贴出,没有则该项停在"需 v6.2",不由本包补)。`PARAM_*` → 贴取参代码行改。不猜 ATM,不下单。

### 2.4 搜索(`tool_hints.py` + `web_search_ollama.py` 主 / `web_search_brave.py` 备)
- web.fetch 入口 `check_web_fetch_url`(grants Search2 → INVALID_TOOL_CALL);ok 收据 `annotate_semantic`。
- web.search:`search_with_fallback(q, [("ollama",…),("brave",…)])`;两个 provider 的 `search()` 第 4 参是 EGRESS 校验函数,**必传**(None=拒);无 key/无 EGRESS 行/计数文件损坏都不出网;`MonthlyCounter.reserve(cap)` 锁内预留;key 不进收据。
- 四项分验:transport(api.github.com/zen 正文)/ challenge 判(DDG 页 semantic=challenge)/ 搜索 schema(投 `electron` n_results≥1 每条有 url)/ catalog POST(grants 200)。
- 真机处决案:去 env 投一条 → SEARCH_UNAVAILABLE 且出网日志零行;cap=1 并投两条 → 恰一条出网;进程重启 n_used 不归零;把计数文件写坏 → SEARCH_QUOTA_COUNTER_CORRUPT 且零出网。

### 2.5 云槽(`cloud_slot.py`)
supervisor 云 worker 派发包 `CloudSlot(max_running=<§1 第 6 条>)` + `run_with_backoff(...)`(默认 base 5s cap 120s max_attempts 6 deadline 600s)。验收:并投 3 条云 job → 本进程并发≤上限、每 job 恰发一次、无 RETRY_EXHAUSTED;8501 的 429 数只贴不判。共享上限/租约记库存。

### 2.6 Flash
先贴 8501 对 glm53 的真实协议(finish_reason / tool_calls / content / reasoning 字段);分类:空正文+合法 tool_calls=工具轮(正常);空正文无工具 → 按 finish_reason=length/stop/provider_error 记;不双写参数、不擅开 thinking;截断夹具用确定性 fixture 不用 num_predict=64。lane 改按 §2.4/R13。

### 2.8 commit
只 add 本窗与本包路径,不 `-A`;拆不开的贴 diff 不提交;每段一 hash;push 归 Lyra。

### 2.9 option.shadow 工具
GET /tools schema 行 + handler 注册 + permission=shadow/read_only + 一次真 dispatch 的结构化收据;模型问答只附作体验。

## 3 · 处决案(沙箱 67 绿;真机待:2.A.4 正向、2.B.3、2.B.4、2.4 三条、2.5、2.9)

## 4 · 停点(只这几处停,其余按默认走)
- 2.A.3 gateway diff:只出不落。
- 2.B.3 synthetic mission:停在 proposed,页面放行归 Lyra。
- 2.4 OLLAMA_API_KEY 不在 env:web.search 走 SEARCH_UNAVAILABLE 继续,其余不等。
- 2.3 若 v6.1 无 at_time 路径:标"需 v6.2",不自补。
- 四类(端口/目录改删/花钱密钥/新出网源)与损坏级硬停。

## 5 · 终回执格式(只一份)
抬头:模型 id / 窗口是否 summarize / 实际加载 revision。§1 十条原样;§2 各段:命令→输出→一句判定(绿/红/够不着)+hash;生产与 fixture 分栏;搜索 provider 与真实消耗;A/B、GLM→Grid、DeepSeek→Grid 分别判。不回问。硬停只四类+损坏级。

落款:迹,2026-09-10 PDT。给戌。

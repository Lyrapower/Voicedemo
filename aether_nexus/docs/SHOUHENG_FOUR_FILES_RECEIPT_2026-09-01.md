# 守恒四份采证回执 · 2026-09-01 20:10 PDT

> 砥修正档 1 后,守恒要的四份。local_gateway.py 一字未出。四份原文已读全,关键结论如下;#3/#4 全文在 iCloud CloudDocs,本回执引路径 + 关键段。

---

## 1. memory_adapter.py 写入接口签名(def + docstring)

**文件**:`grid-resident-harness/harness/memory_adapter.py:148-191`

```python
async def write_turn(
    self,
    *,
    session_id: str,
    role: str,
    content: str,
    source_surface: str,
    worker: str,
) -> dict[str, Any]:
    """
    Optional external write-through.

    gateway_owned: 8501 / your existing path already persists memory.
    external: POST write_path exactly once from the harness.
    none: operational thread remains durable locally, no external write.
    """
```

**行为**:
- 仅当 `cfg.write_mode == "external"` 才发 POST;`gateway_owned` / `none` 直接返回 `{"attempted": False, "mode": ...}` 不外写。
- payload:`{subject_id, session_id, role, content, source_surface, worker}` → POST `cfg.write_path`。
- `cfg.required=False` 时失败返 `{"ok": False, "error": ...}` 不抛;`required=True` 时抛。
- 返回 receipt:`{attempted, ok, mode, domain, receipt|error}`。

**结论**:写入接口是 `write_turn`,keyword-only 参数,external 模式才外写一次。8-03 裁决管它"不得全量注入"(见 §4)。

---

## 2. api.py /api/capabilities 响应 schema —— 关键发现

**文件**:`grid-resident-harness/harness/api.py`(全文已读,363 行)

### 发现:`harness/api.py` 里**没有** `/api/capabilities` 端点

`api.py` 定义的端点(全部):
| 端点 | 方法 |
|---|---|
| `/` | GET |
| `/health` | GET |
| `/jobs` `/jobs/{id}` `/jobs/{id}/requeue` | GET/POST |
| `/sessions` `/sessions/{id}` `/sessions/{id}/message` `/sessions/{id}/context-preview` | GET/POST |
| `/sessions/{id}/{pause,resume,cancel,approve,reject}` | POST |
| `/events` `/ws/events` `/events/voice` | GET/WS/POST |

**无 `/api/capabilities`。**

### 但 8630 实况在跑 `/api/capabilities`(17 行)

```
curl 127.0.0.1:8630/api/capabilities → 200, 17 capabilities
{"routing_policy":"GRID_CHOOSES","registry_role":"MAP_NOT_DRIVER",
 "capabilities":[{"capability_id":"crypto.rwa.scan_public",...},...]}
```

### 结论:跑 8630 的不是这个 api.py

8630 的 `/api/capabilities` 来自 **`demo/app/harness/server.py`**(enforcement "门"),不是 `grid-resident-harness/harness/api.py`("身体")。这正是 HARNESS CLOSEOUT DI v1.3 §B 段一判的"门在身体无 / 造了第二个 backend"——8630 被 demo 的 enforcement server 占着,身体在睡。

### v1.3 决定(HARNESS CLOSEOUT §B 段一 + §D.11)

- `/api/capabilities` 端点**移到 `harness.api`**(grid-resident-harness)
- `demo/app/harness` 的 8630 只读 server **停**
- PORTS.md 8630 行改指 `harness.api:app` 且 `launchd=yes`

### `/api/capabilities` 响应 schema(8630 实况)

```json
{
  "routing_policy": "GRID_CHOOSES",
  "registry_role": "MAP_NOT_DRIVER",
  "capabilities": [
    {
      "capability_id": "crypto.rwa.scan_public",
      "provider": "local_scanner",
      "kind": "tool",
      "permission": "read_only",
      "status": "declared",
      "produces": ["scan_receipt","evidence_candidates"],
      "notes": ""
    }
    // ... 共 17 条
  ]
}
```

字段:`routing_policy` / `registry_role` / `capabilities[]`(每条 `capability_id` / `provider` / `kind` / `permission` / `status` / `produces[]` / `notes`)。

---

## 3. HARNESS_CLOSEOUT_DI_v1_3 全文(判词文档)

**路径**:`[REDACTED: 身份] iCloud CloudDocs/HARNESS CLOSEOUT DI v1 3 2026-09-01.md`(16KB,全文已读)

### 关键判词

- **谱系**:V1.5.5 施工令(8-24)→ PreN18 transport 任务(未做)→ 砥审(8-25)→ enforcement_patch_v1(8-26,P0 已并入)= 最新 Cursor 指令与 zip,之后无更新。
- **现状判词一行**:harness 现在是"门"没有"身体"——`app/harness` 八个文件全是 enforcement(能力面/资源门/收据/provenance),`server.py` 明写 No cognition,没有 scheduler、没有任务队列、没有信道;8630 手起无 launchd;cc lane 从没配过,anthro_bridge 全盘不存在。**不是拖在设计,是身体一直没造。**
- **段一方向(v1.3 反转)**:**门搬进身体**。resource_gate / action_envelope / provenance 三件进 `grid-resident-harness/harness/`,`supervisor._run_job` 执行前过 `gate()`,收据经 `provenance.record_receipt`;`/api/capabilities` 移到 `harness.api`;demo 的 8630 只读 server 停;身体整目录纳入 demo 仓。
- **段二**:首负载 = 交易时段哨兵(launchd 300s,06:30–13:00 PDT,确定性代码零认知依赖)。
- **段三**:桥 8503 + CC lane(anthro_bridge 按 cc-local-stack v2.1 重出,MODEL_MAP 按 /v1/models 实况,demo/aster 禁填)。
- **§D 待 Lyra 拍**:11 条,每条有默认值。§D.10 = kimi_k3→glm53 静默替换(有意别名→登记带 aliased_from / 残留→应 400);§D.11 = 段一方向(默认:门搬进身体)。
- **§E 给戌的块**:段一采证 + 附带收尾(r1 判词 / metrics n≥200 门 / guard WARN→BLOCK / offpool 回归 / 09:40 定时盘 / legacy aether.html / §2.1 七文件 git status)。
- **§F 给守恒的块**:三件出品(段一整包 / 段二哨兵包 / 段三桥),禁按记忆写,戌贴 supervisor/db/api 全文。

### r1/r3 回执判词(§C)
- r1:采证三条、收尾五条全过;撤回"aether_trading_v12.html 是旧版"(OI 渲染 :566-567 已在 HEAD,是砥搞错的)。
- r3:4bd4019 把 801 行 OI/HARDZERO WIP 带进 commit 过;但 §2.1 整组其余文件仍未 commit → 特性半入库,决定 §D.4 整组一个 commit 收齐。metrics n≥200 门要按班次窗内 duration 非空行数计。guard WARN→BLOCK 已落(efbd967)。

---

## 4. 8-03 裁决原文(历史决定)

**正本**:`SYSTEM_SIMPLIFY_MEMORY_COHERENCE_2026-08-03.md`(iCloud Downloads,全文已读)
**认定依据**:HARNESS CLOSEOUT §B 段一引"8-03 裁决管它不得全量注入" → 该文 §2.7 / §10.2 含"砍「全量注入」话术"裁决,匹配。

### 关键裁决(管 memory_adapter / context 不得全量注入)

**§2.2 注入契约(必须写进 UI)**:
| 层 | 内容 | 不是 |
|---|---|---|
| L1 对话窗 | 最近 15 轮 **且** ≤10k tok;超限裁最旧**对** | 全历史 |
| L1b 工作日志 | 最近约 5 条 `[工作日志]`,占 10k 预算,不占 15 轮计数 | 对话正文 |
| L2 召回 | 冷库词法 top-4,≤2k,标题标"检索注入非对话窗" | 全量 dump |
| L3 冷库 | store/archive 保留 | 自动等于"模型记得" |

**§2.7 记忆简化裁决**:
| 裁决 | 内容 |
|---|---|
| **留 Mem-A 双魂** | Cloud 魂(console+b11 Cloud)· Studio 魂(仅 STUDIO)· UI 标注魂+预算 |
| **砍** | 「全量注入」话术;8515 Cloud sqlite 心智;`/task/candidate` 假记忆;agent 写生产 node |
| **未批准不做** | Mem-B 全球一魂;跨魂自动"你还记得 STUDIO" |

**§10.2 建议去掉**:`/task/candidate` 假记忆块 / epoch 硬删生产正文 / hash-only after_turn 当"记忆层" / chat 接 SemanticMapper / 平行"总管"chat 壳。

**§14 一句话**:多个入口共用"记忆"一词,却指向不同 store、不同预算、不同删除策略。先定魂与注入契约并写进 UI,再砍面——否则每一轮"修复"都在制造下一轮失忆。

### 与本次四份的交点
- memory_adapter `write_turn`(§1)受 §2.7"砍全量注入"管——external 写一次可,但注入模型侧不得全量 dump。
- api.py 无 `/api/capabilities`(§2)正是 v1.3 §B 段一要纠正的"门在身体无"。
- b11 STUDIO(`workbench-b11`)与 Grid(`field-particle`)不同魂——§2.1 魂器地图明列"不与 Cloud 共享""≠ b11"。本次 HARNESS_PENDING §5 的"打通"挂起,与此裁决一致(未批一魂前不合并)。

---

## 状态

- **未动代码**:四份全只读;未改 `gateway.py` / `api.py` / `memory_adapter.py` / `local_gateway.py`。
- **未碰红线**:local_gateway.py 一字未出;harness 三件只读。
- **#3/#4 全文**:在 iCloud CloudDocs(路径见上),本回执引关键段;需我把全文复制进 `aether_nexus/docs/` 说一声。


—— 戌,2026-09-01 PDT

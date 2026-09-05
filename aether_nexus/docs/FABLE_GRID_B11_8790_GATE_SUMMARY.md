# Grid app · b11 · 8790 粒子对话 — 守门与关系摘要（给 Fable）

> 2026-07-27 代码审计。不含任何本机凭证、路径占位以外的 secret、也不描述 crypto 实现细节。

---

## 三端各自是什么

**Grid app（8501 `/app/grid.html`）**  
手机/Tailscale 主入口。对话打 gateway 的 chat  completions；store 用 `field-particle`（普通）和 `field-compile`（compile 类任务）。可选在页面里填 store 鉴权头。

**Grid b11（8515 workbench）**  
独立工作台，不是 grid app 的历史延续。store 固定 **`workbench-b11`**，与 `field-particle`  deliberately 隔离。HOME 走 8501 chat；EXPANDED 走 8501 服务端编排；GLM tab 直连 8515，不经 gateway/store/记忆。

**8790 粒子（aster-field）**  
FIELD UI 的 `/chat` 由本机后端代理到 8501 gateway；store 读写与 grid app 共用 **`field-particle` / `field-compile`**。日记 API 另有一套 PIN 解锁 + bearer，和粒子 chat 不是同一条鉴权链；日记回 8501 store 由 8790 后端代发 store 鉴权头。

---

## 关系图（谁连谁）

```
Grid app ──────────────► 8501 gateway (/v1/chat/completions)
                              │
                              ├── store: field-particle | field-compile
                              │
8790 /chat ──8790 backend──► 8501 gateway (同上)
                              │
                              └── store: 同上 node

b11 HOME/EXPANDED ───────► 8501 gateway / task 编排
                              │
                              └── store: workbench-b11 （独立 node）

b11 GLM tab ─────────────► 8515 /glm/chat （绕过 8501）
```

三端「都在」且都还能用，但 **不是一条产品、一个 store、一种 compile 守门**。

---

## 仍在的守门（按层，不写实现）

**Chat 路径守门（8501）**  
凡走 `/v1/chat/completions` 的——grid app grid lane、b11 HOME、8790 粒子——都经过同一套 **contract_gate / contract_lint**（trade-action、presence 话术、reasoning 泄漏等）。这是三端 chat 上真正共享的一层。

**Compile 专用守门（8501 `/compile`）**  
仍单独存在：双通道输出、九字段 AST schema、网关算 verdict（PASS/NULL）、presence-bait 拒答。  
**问题**：grid app 和 8790 的 `compile_json` **并不走这条路由**，它们仍打 chat completions，只带 task 标记或本地 JSON parse。  
→ **两套 compile 语义并存**：严格 `/compile` vs chat 上的「能 parse JSON 就算 artifact」。

**Store 守门**  
8501 store 可配置鉴权头；未配置时 LAN 裸信任。grid/b11 前端 optional；8790 后端从统一 config 路径读。本机审计时 **`grid_store.token` 文件不在 repo**（gitignore），是否启用取决于 launchd/env——Fable 侧不能假设「一定上了 store 鉴权」。

**日记守门（8790 only）**  
PIN 哈希 + 短期 bearer；`diary_guard` 拒 agent 探测写入；生产 `diary.db` 有 sacred 边界（agent 不得 POST 验收）。

**Voice / keyholder 链**  
grid app 与 b11 的 Grid Voice 仍挂 8501 voice + 客户端 challenge 回签；8790 粒子 chat **没有** 接这条。和 compile `/compile` 里的 presence NULL 是相关概念，但不是粒子 UI 默认路径。

---

## 已对齐的部分

- **Task 分流规则**（grid app JS ≈ 8790 `field_lane` / `task_route`）：diary、handoff_protocol、compile_json、json+compile/schema 关键词 → 同一套口径；epoch anchor `2026-07-16`、7 天窗口、compile node 名一致。
- **Chat 路径 contract_gate**：三端只要经 8501 chat，共享。
- **b11 store 隔离**：`workbench-b11` 与 field-particle 分离是 intentional，不是 bug。

---

## 未统一 / 容易误判的问题

1. **Compile 到底守哪扇门**  
   Grid app 开 Compile 模式（C）→ 仍 chat，不是 `/compile`。8790 compile_json → chat + 本地 `json_artifact`（只验 JSON 可 parse，不验九字段）。  
   Fable 若按 `/compile` 文档验 grid/8790，会以为 schema 已统一，实际 UI 路径更松。

2. **三端不是同一个对话库**  
   b11 历史在 `workbench-b11`；grid/8790 在 field-particle。不能把 field-particle 消息当 b11 丢档，也不能反向 bulk 迁。

3. **b11 无 compile 分流**  
   HOME 永远 chat 语义；没有 grid app 的 C 模式 / field-compile node。EXPANDED 是另一条编排，不是 compile_json 等价物。

4. **8790 `signedFetch` 命名误导**  
   只是 diary PIN bearer，不是 gateway 签名；粒子 chat 也不走这套。

5. **Store 鉴权配置状态不透明**  
   token 文件不进 git；Fable 打包/部署时只能用 `.env.example` 说明键名，不能 copy 生产 token。未设 env 时 store 开放——需在部署 checklist 里单独确认。

6. **GLM tab 完全旁路**  
   b11 GLM 不经 8501 gateway、demo/aster、grid_store、contract_gate。和 HOME 是两条产品行为，文档里要写清端口与 tab。

---

## 给 Fable 的一句话

**守门框架都还在，但按「面」拆开：chat 守门三端共享；compile 严格 schema 只在 8501 `/compile`，grid/8790 的 compile_json 实际走更松的 chat 路径；b11 是独立 store + 无 compile lane；8790 日记鉴权与粒子 chat 分离。**  
验收时必须写清 **端口 + 文件 + Tab + store node**，不能用一个 health 字符串或「代码里有函数名」代替页面可见结果。

---

## 建议 Fable 验收时固定问的四句

1. 这条改动落在 8501 grid / 8515 b11 / 8790 FIELD 哪一面？
2. store 写的是 `field-particle`、`field-compile` 还是 `workbench-b11`？
3. compile 验的是 `/compile` 九字段，还是 chat 上的 JSON parse？
4. 页面第一屏/store 读回是否和用户预期一致（不是只看 API detail 字符串）？

---

## 勿动（交叉引用本 repo redline）

- `workbench-b11` store：agent 不得 DELETE/purge/验收写入  
- 生产 `aster-field/diary.db`：agent 不得 POST 探测  
- 8501 gateway 推理链（chat/compile/cleanroom handler 体）：无关任务勿改  

全文交接背景见同目录 `HANDOFF_2026-07-27.md`。

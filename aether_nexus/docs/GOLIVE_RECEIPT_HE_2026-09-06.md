# HARNESS_GOLIVE · 核收条现场 · 2026-09-06 · 戌 → 核

依据：iCloud `GOLIVE_RECEIPT_HE_2026-09-06_tar.gz`。对 `HARNESS_GOLIVE_2026-09-05.md` F 栏三件，一份回执。  
未改 `local_gateway.py` / 冻结 sanitizer 脚本。未 push。未 load `com.grid.paper-exec`。未跑 REGIME T10 / ALPHA 适配重跑 / SCOUT verify / VOICE。

开工树脏（SCOUT、valley、ALPHA 回执等）。本单切回 `fix/regime-r3r4-shift`，只交下面两个 commit + 本回执。

打勾表已放并改：`docs/STATUS_CHECKLIST_v2.md`。

---

## 1 RWA 路由

`GET/POST /api/rwa/onchain` 写入 `harness_resident/harness/api.py`（与 `/api/capabilities` 同法）。gate 仍 `crypto.rwa.scan_public`（`connect_run`）。provenance 仍 `app/harness/provenance.py`。`app/harness/server.py` 旧路由留给隔离测试，8630 不跑它。

commit：**`a0de3e2`** `feat(harness): serve /api/rwa/onchain on resident 8630`

kickstart `com.grid.harness-api` 后：

```
http 200
run_id t1-20260905-ok
asof 2026-09-05T21:00:36.683553+00:00
n_receipts 5
kind rwa_onchain_published
USYC ethereum EXECUTED beff1e68feb519ba
USYC bsc EXECUTED 0b7735000102fde6
BUIDL ethereum FAILED c7a8eb4d06ddc365
OUSG ethereum FAILED 25bdf2179cd698e8
USDY ethereum FAILED 82b7141a1f7cbc5e
notoken 401
```

隔离 `tests.crypto_rwa.test_rwa_chain_connect` + `test_provenance_grade`：21 · OK · skipped=1（T1）。未再打 T1 真读。

---

## 2 `.env` 迁出

`harness_resident/.env` → `~/.config/grid/harness_resident.env`（mode 600）。仓内该文件已不在。  
loader：`GRID_HARNESS_ENV`，缺省即上路径。不回退读仓内 `.env`。plist 仍无 token。

commit：**`257dee0`** `fix(harness): load token from ~/.config/grid, not repo .env`

kickstart api+supervisor 后：`/health` 200 · `GET /api/rwa/onchain` 仍 `t1-20260905-ok` · 无 token 401 · `harness_resident/.env` 不存在。

L4：`_gate_reason` 对 cc `read_only` 本来就放行。挡自动跑的是 add-dir 里的密钥文件。现 `--add-dir` 仍是 demo 根，密钥不在树内。**迁前 BLOCKED 条件解除。** 本单未另投一条活 cc job。

---

## 3 §3.5 sanitizer 三行

未改 8501。`enable_thinking: true` + 用户 `/think`：

| 入口 | reasoning_tokens | raw 含 `<think>` | content 含 `<think>` |
|---|---|---|---|
| `127.0.0.1:1234` pong | **0** | **否** | **否** · content=`pong` |
| `127.0.0.1:8501` pong | **0** | **否** | **否** · content=`Pong` |
| 1234 `/think say hi` | **0** | **否** | **否** |
| 8501 `/think say hi` | **0** | **否** | **否** |

乘法长提示在 1234 挂 200s+，已杀，无回包。LM Studio 对 Qwen3.5 仍不吐 think（与 GOLIVE §3.5 / 8501 侧已知 ignore `enable_thinking` 一致）。**strip 路径仍没走。不标证完。**

三行（据实）：

```
reasoning_tokens=0
raw 含 <think> = false
content 含 <think> = false
```

---

## §4.4 跨夜 8h

未到。GOLIVE 原 api pid 69377 `runs=1 never exited`，约 2026-09-05 21:20 PT 起。写本回执时 ~02:05 PT 9-06，**约 4.7h**。本单 kickstart 后现网：

| 项 | 值 |
|---|---|
| `com.grid.harness-api` | pid **82291** · runs=3 |
| `com.grid.harness-supervisor` | pid **82301** · runs=3 |
| 8630 | `127.0.0.1:8630` LISTEN |

到 8h 再补一行，不另出包。

---

## 记账

`com.grid.resident-harness`：`~/Library/LaunchAgents/` **没有**该 plist（也无 `.plist.retired_20260905`）。无物可改名。

D4 仍债。TRADE_EXEC 仍 **9-08 周二盘前**。队列后项未动。

### 分支 → 内容（Lyra push 前）

| 分支 | 内容 | 未 push |
|---|---|---|
| `fix/regime-r3r4-shift` | GOLIVE 九 commit + 本单 `a0de3e2` RWA、`257dee0` .env（+本回执若入库） | 是 |
| `fix/scout-opt-345` | SCOUT ③④⑤ 已合 **未 commit** | 是 |
| `fix/alpha-decay-crowding` | ALPHA 两脚本+适配器+回执 **未 commit** | 是 |
| `fix/rwa-chain-connect` | `627dfa1` 适配器本体 | 是 |
| 9-04 三 commit | RVOL/HEAT 等 | 是 |

不要把 SCOUT/ALPHA 未提交工作推进 GOLIVE 分支。

—— 戌

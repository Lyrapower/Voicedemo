# RWA_CHAIN_CONNECT · 2026-09-05

**戌 → 溯** · 签名：戌  
源包：iCloud `RWA CHAIN CONNECT PKG v1.md`（Aster GPT 审阅席；溯补 3 条已并入）  
分支：`fix/rwa-chain-connect` · 未 push

真实运行 **NOT YET ACCEPTED**（手起 `:8630` 仍是旧进程，新路由 404）。接线本身已落到同一 FastAPI app + 平台消费入口。

---

## A 当前实际状态

### 9-02 缺口 vs 本批

| 项 | 状态 |
|---|---|
| Phase 1–3 reader→provenance、`CONFIDENCE_TO_GRADE`、只降不升 | **已在**（复用，未再写第二套 to_receipt） |
| GRID_VOICE Lane B | **撤**；本包取代 |
| G1 真实接线 | 本批：`read_with_receipt` / `connect_run` / `POST /api/rwa/onchain` |
| G2 等级适配 | 本批：`grade_fact` + `node_ownership` |
| G3 派生写入校验 | 本批：`derived_from` 子不得超父 |
| 旧 generator 当链上事实 | 本批：`/ui/crypto` 事实入口改吃 published；旧卡标 webpage_archive |
| G4 lane 可见性 | **未做**（`crypto.rwa.scan_public` 仍对所有 lane 可见） |
| G5 / G7 / G8 | **未纳入** |
| G9 官方地址 | 不阻断。BUIDL / OUSG / USDY `address=None` 拒读不猜 |
| G6 RPC | 仍只 Alchemy / QuickNode / Ankr；EGRESS 最小登记。未列 vendor → 停 |

### §八

代码引用 **契约 v1.3**（`provenance.py` / reader）。仓库内无独立 §八 原文文件 → **等级资格未验收**，不重写定义。

本机 RPC 角色（只报名，不贴 URL/key）：`ETH_RPC_URL` Alchemy · `ETH_RPC_URL_2` QuickNode · `BSC_RPC_URL` Ankr · `BSC_RPC_URL_2` 无。三者 = `third_party`，上限 `witnesses_agree`。名称本身不证明 attested。

---

## B 改动

路径：已认证 context → gate(`crypto.rwa.scan_public`) → `rwa_onchain_reader` → 每资产/链一张 `FactualReceipt` → 现有 `provenance.record_receipt` → `state/rwa_onchain_published.json` → 消费者。

| 文件 | 作用 |
|---|---|
| `app/crypto_rwa/rwa_chain_connect.py` | 适配器（新） |
| `app/harness/server.py` | `GET/POST /api/rwa/onchain`（仍 :8630，不新端口） |
| `app/harness/provenance.py` | `derived_from` 子不得超父 |
| `app/crypto_rwa/rwa_onchain_reader.py` | `--connect --mission --origin`；裸 `--provenance` 标 DIAGNOSTIC |
| `app/platform_main.py` | `_load_onchain_live` + `/ui/crypto/onchain.json`；旧卡 `webpage_archive` |
| `templates/workspace.html` | 链上事实区；旧卡标参考、不作 fallback |
| `EGRESS.md` | alchemy / quiknode.pro / ankr 三行（拍板 2026-08-26） |
| `tests/crypto_rwa/test_rwa_chain_connect.py` | T2–T6 隔离；T1 需 `RWA_T1_LIVE=1` |

旧路径：generator 仍服务 pack 按钮（infrastructure-map 等），**不再**当 RWA 链上事实源。CLI 发明 mission hash 的聚合 emit 保留给 Phase 1 测试，不是生产入口。

Python.org 3.13 本机 `ssl cafile=None`。适配器在未设 `SSL_CERT_FILE` 时指向 certifi，**不**关校验。

---

## C 运行

### T2–T6（隔离）

```
python3 -m unittest tests.crypto_rwa.test_rwa_chain_connect tests.harness.test_provenance_grade -v
```

`Ran 21 tests` · **OK (skipped=1)** · T1 默认 skip。Phase 1–3 reader 脚本仍绿。

### T1 真读

```
RWA_T1_LIVE=1 RWA_T1_RUN_ID=t1-20260905-ok python3 -m unittest tests.crypto_rwa.test_rwa_chain_connect.T1LiveHarness -v
```

`OK` · 3.029s（fresh process）。

第一条成功 receipt（USYC ethereum）：

| 字段 | 值 |
|---|---|
| receipt_id | `beff1e68feb519ba` |
| status | EXECUTED |
| supply_units | **36868107.6** · decimals 6 · total_supply 36868107603338 |
| block | `0x18b6951` |
| observed_at | 2026-09-05T21:00:34.561655+00:00 |
| grade | witnesses_agree · confidence dual · node_ownership third_party |
| vendors | alchemy + quicknode（未打印 URL） |

USYC bsc：receipt `0b7735000102fde6` · supply **2270937727.95** · witness_only / single · Ankr only。

消费端（同一进程 TestClient，非手起旧 8630）：

- `GET /api/rwa/onchain` → 同 run `t1-20260905-ok`、同 receipt_id / supply / asof
- `GET /ui/crypto/onchain.json` → 同 receipt_id
- `GET /ui/crypto` HTML 含 `beff1e68feb519ba` + “reference only”

`curl http://127.0.0.1:8630/api/rwa/onchain` → **404**（手起 uvicorn 未载新路由）。重跑命令在载入本分支后：

```
curl -sS http://127.0.0.1:8630/api/rwa/onchain
```

早期 `t1-20260905` / `-ssl` / `-live` 曾被 mock 泄漏或缺 CA 写成失败/假数；**以 `t1-20260905-ok` 为准**。旧行未删（provenance 只增）。

---

## D 数据限制

- BUIDL / OUSG / USDY：无地址 → FAILED，supply/NAV 皆 null
- BSC：单源 Ankr，不进 dual 栏
- 本轮 NAV oracle **absent**（不回退 par；usd 不装数）。跨链 NAV 无依据
- 发布缓存标 `last_success`，`stale=true`，**不标 now**
- lane 裁剪未做（溯补 1）
- 不把限制藏进总额：无“已核实美元总和”

---

## E 判定

| 项 | 判定 |
|---|---|
| 接线实现 | 已落；一 commit |
| T1 FastAPI 入口 + 真 RPC + 平台读回 | **过**（TestClient / `/ui/crypto`） |
| T1 手起 `:8630` HTTP | **BLOCKED**（旧进程 404） |
| T2–T6 | 过（隔离副本，未改坏生产链语义） |
| §八 attested 资格 | **未验收**（无原文；本机无 self_hosted 证明） |
| 整包 ACCEPTED | **否** |
| G4–G8 | **不能写成已完成** |

---

## F 下一步

1. 重载手起 `:8630`（`uvicorn app.harness.server:app --host 127.0.0.1 --port 8630`）后再 curl；**不要**为此装 launchd（PORTS 仍写 session only）
2. 契约 §八 原文到手后再验 attested 资格
3. G9 官方地址（BUIDL / OUSG / USDY）另列
4. NAV oracle 本轮未读到：另核，不在本包猜
5. G4–G8：无，除非溯另开

无平台第二步。未 push。

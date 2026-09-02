# §E 收尾回执 · 2026-09-01 20:27 PDT

> 戌执行 HARNESS_CLOSEOUT_DI_v1_3 §E「附带收尾」。逐条贴命令 + 输出原文;未动 local_gateway.py;未造 jobs 表/runner/plist。

---

## §E.5 guard WARN→BLOCK —— 已落(销项)

commit `efbd967` `guard+metrics: WARN→BLOCK(unlocked+staged sha≠manifest) + p95 门按 shifts_n`。r3 判词销项,不重做。

---

## §E.4 metrics n≥200 门 —— 已落(销项)

`grid-sovereign-runtime/gateway/metrics_query_gateway_routelog_metrics_v1.sh`:
- `:46-47` `COUNT(*) AS n` 与 `(SELECT COUNT(*) FROM shifts) AS shifts_n` 分开
- `:37-44` `shifts` CTE 只取五班窗(06:45/10:40/12:35/16:45/21:00 PDT 各 ±10 min)内 `duration_ms` 非空行
- `:52-56` p95 从 `shifts` 取,`OFFSET (SELECT COUNT(*) * 95 / 100 FROM shifts)`
- `:65-66` 注释明写「p95 门按 shifts_n(五班窗内 duration 非空行数,与 p95 同过滤集),不是 n」

r3 判词「改一行」已在 `efbd967` 一并落。销项。

---

## §E.6 offpool 回归五文件 —— 17/17 PASS

**命令**(HARNESS_PENDING §2.4 原命令用 `python -m unittest`,但五文件是 pytest 风格(`def test_*` + monkeypatch/tmp_path fixture),venv 无 pytest → 0 tests ran;改用系统 `python3 -m pytest`):

```bash
cd aether_nexus && python3 -m pytest test_offpool_mandatory_pick test_offpool_daemon test_offpool_lane_config test_offpool_prompt_whitelist test_offpool_ab_stats -q
```

**输出原文**:
```
.................                                                        [100%]
17 passed in 0.84s
```

**结论**:17/17 PASS。§2.4 命令的 `unittest` 写法对 pytest 风格无效(记为同型洞:§2.4 命令需更正为 `python3 -m pytest`,venv 应装 pytest)。

---

## §E.7 09:40 ET 定时盘 + legacy aether.html OI 渲染 —— GAP

### 7a. signals.json 不存在

全盘 `find . ~/Projects -name "signals.json"` → 0 命中。§2.6 引的 `signals.json` 文件名**过时/不存在**。

### 7b. 实际 scan 输出 candidates.json

```bash
python3 -c "import json;d=json.load(open('aether_nexus/state/candidates.json'));..."
```
**输出原文**:
```
scan_timestamp: 2026-09-01T15:33:33        # = 08:33 PDT,非 09:40 ET(13:40 UTC)
top source: dryrun_sp500
rows count: 5
row0 keys: ['symbol','name','sector','underlying_price','expiry','strike','option_price','bid','ask','spread_pct','delta','gamma','theta','theta_ratio','iv','volume','premium_dollars','score','source','scan_mode','price_source']
row0 oi_source: None | open_interest: None
oi_source 分布: {'None': 5}
```

**关键 GAP**:
1. 最新 scan 是 `2026-09-01T15:33:33Z`(08:33 PDT),**不是 09:40 ET**(13:40 UTC)→ 09:40 ET 定时盘**没跑**
2. 5 行 rows **全无 `oi_source` / `open_interest` 字段**(row keys 里根本没有这两列)→ OI join 未进 emit 路径
3. `oi_source 分布: {'None': 5}` —— 不是 `alpaca_contracts`,也不是 `missing`,是**字段不存在**

### 7c. nexus-dryrun 未在跑

```bash
launchctl list | grep -iE "aether|nexus|dryrun"   # 空
ps aux | grep -i "aether_dryrun\|nexus-dryrun"     # 空
```
nexus-dryrun launchd **未加载**、无进程。今早 kickstart 过的已退出,定时未持久化。

### 7d. aether.html OI 渲染代码在场

`grid-sovereign-runtime/gateway/static/aether.html`:
- `:1054` `const oi=r.open_interest!=null?\`OI ${esc(String(r.open_interest))}\`:"";`
- `:1680` 同上(第二处渲染点)

代码在场(r1 判词「:566-567 已在 HEAD」指认此处逻辑),`open_interest!=null` 才显示 OI 文本。当前数据 `open_interest=None` → **无 OI 文本可显示**(与 r1 判词「当前视图无可执行卡故无 OI 文本」一致)。

### 7 结论

- 09:40 ET 定时盘**未落地**(launchd 未装、signals.json 不存在)
- OI join **未进 scan emit 路径**(candidates.json rows 无 oi_source/open_interest 字段)—— OI 代码可能在 dryrun 写 null,但 emit/html 路径未带(与 r3 判词「特性半入库:HEAD 上 dryrun 写 null OI 而 emit/html 是旧版」一致)
- **待 §D.4 整组 commit 收齐 emit/trading_state 后,再起 09:40 ET 定时盘验 oi_source=alpaca_contracts**

---

## §E.8 §2.1 五文件 git status —— 仍 untracked(等 §D.4)

```bash
git status --short aether_nexus/aether_grid_emit.py aether_nexus/offpool_coach/stage1_mechanical.py aether_nexus/offpool_coach/stage2_payload_builder.py aether_nexus/trading_state.py aether_nexus/test_trading_state_oi.py
```
**输出原文**:
```
?? aether_nexus/aether_grid_emit.py
?? aether_nexus/offpool_coach/stage1_mechanical.py
?? aether_nexus/offpool_coach/stage2_payload_builder.py
?? aether_nexus/test_trading_state_oi.py
?? aether_nexus/trading_state.py
```
5 个 untracked,等 §D.4 拍后整组一个 commit 收齐。

---

## §E.1补 supervisor.py / db.py / config.toml [core] —— 已贴

见同目录 `HARNESS_SUPERVISOR_DB_CONFIG_RECEIPT_2026-09-01.md`(supervisor.py 16KB + db.py 12KB + config.toml [core] 段全文,敏感扫描 0 命中,给守恒合身用)。

---

## §E 总状态

| 项 | 状态 |
|---|---|
| §E.5 guard WARN→BLOCK | 已落 `efbd967` |
| §E.4 metrics n≥200 门 | 已落 `efbd967` |
| §E.6 offpool 回归 | 17/17 PASS(系统 pytest;§2.4 命令 unittest 写法无效,记同型洞) |
| §E.7 09:40 定时盘 + legacy OI | **GAP**:定时盘未跑、signals.json 不存在、OI 未进 emit 路径;待 §D.4 |
| §E.8 §2.1 五文件 | 5 untracked,等 §D.4 |
| §E.1补 supervisor/db/config | 已贴(单独回执) |

**未动代码**(只读采证 + 回执);**未碰红线**(local_gateway.py 一字未出);**未起 plist/runner**。

**等 Lyra 拍 §D**(§D.4 commit 整组 / §D.5 删两文件 / §D.7 PORTS.md / §D.8 hook / §D.11 归档 / 段一部署)后继续。

—— 戌,2026-09-01 PDT

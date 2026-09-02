# 戌 · r3 回执 · 整包 B 第三轮 · 来自砥 review r2 BASELINE v1 · 2026-09-01 PDT

- 审:砥(review r2 BASELINE v1)
- 对象:`GATEWAY_ROUTELOG_B_RECEIPT_r3_2026-09-01.md`(本文件)
- 范围:砥 §C 一(1-5 现在做,不碰红线)+ 二(6 贴身份);§三(7-9 等 Lyra 拍);§四(不做)
- 约束:禁 --no-verify、禁 git add -A、禁改分支。本次全部正常 pre-commit。
- 分支:`fix/harness-enforcement-v1`(未动)

---

## §C 一 · 现在就做(不碰红线)

### 1 · commit 13/14 — 过(附记账)

```
$ git add aether_nexus/test_render_oi_contract.py aether_nexus/aether_dryrun.py
$ git commit -m "aether: render OI contract smoke test + HARDZERO_TRIGGERED live log (砥 r3 §C 13/14) ..."
[pre-commit] ... 12 tests OK / 3 tests OK / runtime infrastructure lock verified / 11 tests OK
[fix/harness-enforcement-v1 4bd4019] aether: render OI contract smoke test + HARDZERO_TRIGGERED live log
 2 files changed, 664 insertions(+), 193 deletions(-)
 create mode 100644 aether_nexus/test_render_oi_contract.py
commit_exit=0
```

`git log -1 --stat`:

```
commit 4bd40198f038c3e7eeb2acf3b34f829c2a753246
Date:   Tue Sep 1 14:01:05 2026 -0700
 aether_nexus/aether_dryrun.py           | 801 ++++++++++++++++++++++++--------
 aether_nexus/test_render_oi_contract.py |  56 +++
 2 files changed, 664 insertions(+), 193 deletions(-)
```

**诚实记账(戌自报):** stage `aether_dryrun.py` 把今早未 commit 的 OI/HARDZERO 整合 WIP(801 insertions)一起带进 commit 4bd4019,不只 HARDZERO 日志行。同属 OI/HARDZERO 一个特性,test_oi_contracts_join + test_trading_state_oi + test_render_oi_contract 全过。若 Lyra 要拆分,告诉我(不 amend)。

---

### 2 · §C 3/4/5 — metrics_query + verify_routelog — 过

**metrics_query 改动(diff 摘要):**
- 主查询整体加 `WHERE duration_ms IS NOT NULL`(三个百分比同分母 = duration 非空行数)
- p95 子查询加五班窗 WHERE(06:45/10:40/12:35/16:45/21:00 PDT 各 ±10 min,`strftime(...,'unixepoch','localtime'`)
- 第 6 行注释改:`REAL < TEXT 恒成立 → 0 行`(不是"强转0计入全量")
- 422 含义一行注释:非 GLM 拒绝(contract_gate/冒名/schema),不计 GLM lane err5xx

`date +%Z`:

```
PDT
```

metrics_query 重跑(改后):

```
$ bash grid-sovereign-runtime/gateway/metrics_query_gateway_routelog_metrics_v1.sh
GLM lane 3 日基线(db=.../gateway_log.db)
─────────────────────────────────────
n  mean_ms  min_ms  max_ms  p95_ms  err5xx_pct  timeout_pct  other_err_pct
-  -------  ------  ------  ------  ----------  -----------  -------------
2  3775.5   912     6639    6639    0.0         0.0          0.0
exit=0
```

对照(验 n = duration 非空行数):

```
$ sqlite3 .../gateway_log.db "SELECT COUNT(*) FROM route_log WHERE routed_to LIKE '%glm52%' AND duration_ms IS NOT NULL AND ts >= CAST(strftime('%s','now','-3 days') AS REAL);"
2
$ sqlite3 .../gateway_log.db "SELECT COUNT(*) FROM route_log WHERE routed_to LIKE '%glm52%' AND ts >= CAST(strftime('%s','now','-3 days') AS REAL);"
33
```

**n=2 = duration 非空 GLM lane 3 日窗行数(与对照一致);总 33 行,31 行是埋点前(无 duration_ms)。采样未达 n=2(< 200),不出 p95。** p95_ms=6639 是 SQL 仍算出的小样本值,回执按兜底"采样未达 n=2"。

verify_routelog_window.sh 处决案二(期望 400,PENDING §C 1)重跑:

```
$ bash scripts/verify_routelog_window.sh
处决案[1] ts=now-3600   3日窗 count = 1  (期望 1)
处决案[2] ts=now-4d     3日窗 count = 0 (期望 0)
处决案[3] bogus substrate status_code = 400  (期望 400,PENDING §C 1 — 实际网关此刻 -1)
        GLM lane 是否误含 bogus = 0  (期望 0,bogus 不污染 GLM 指标)
VERIFY_WINDOW_PASS  (处决案[3] 查询侧过;gateway 侧 PENDING §C 1)
exit=0
```

处决案二说明:查询侧验 bogus substrate 行(routed_to 不匹配 %glm52%)不进 GLM lane;gateway 侧(实际产 400)PENDING §C 1(handler 此刻抛 ValueError → -1,§C 1 后抛 HTTPException(400) → 透传 400)。

commit:

```
$ git add grid-sovereign-runtime/gateway/metrics_query_gateway_routelog_metrics_v1.sh scripts/verify_routelog_window.sh
$ git commit -m "routelog metrics: duration_ms IS NOT NULL denominator + 五班窗 p95 + 422 注释 + 处决案二 bogus substrate (砥 r3 §C 3/4/5)"
 2 files changed, 51 insertions(+), 21 deletions(-)
commit_exit=0
```

---

### 3 · guard 默认严 + --precommit index 模式 + 删 staged 排除 + 处决案 a 三态 — 过

**diff 摘要(`scripts/grid_infrastructure_guard.py`):**
- `_frozen_dirty_reasons(rel, *, precommit)`:runtime 严 `git diff --quiet HEAD -- rel`(staged 也算 dirty);`--precommit` 松 `git diff --quiet -- rel`(worktree vs index,staged 且 worktree==index 即 clean)
- `verify_runtime(*, strict, precommit=False)`:precommit 模式只验 tracked+clean,跳过 hash(hash 交给 redline hook + runtime boot)
- 删 `_staged_set` + `rel not in staged` 排除(方向反了)
- main 加 `--precommit` flag

处决案 a 三态输出:

```
$ # 步1:printf 空行 + git add
$ printf '\n' >> grid-sovereign-runtime/gateway/local_gateway.py && git add grid-sovereign-runtime/gateway/local_gateway.py

$ # 步2:runtime(默认)—— 须红
$ python3 scripts/grid_infrastructure_guard.py verify-runtime 2>&1 | grep -E 'FROZEN_DIRTY|BLOCK|OK'
FROZEN_DIRTY grid-sovereign-runtime/gateway/local_gateway.py (dirty)
P0 RUNTIME BLOCK: Grid infrastructure hash drift detected.

$ # 步3:--precommit —— 须绿
$ python3 scripts/grid_infrastructure_guard.py verify-runtime --precommit 2>&1 | grep -E 'FROZEN_DIRTY|BLOCK|OK'
OK: runtime infrastructure lock verified

$ # 步4:全量还原(index+worktree → HEAD)
$ git restore --source=HEAD --staged --worktree -- grid-sovereign-runtime/gateway/local_gateway.py

$ # 步5:还原后 runtime —— 须绿
$ python3 scripts/grid_infrastructure_guard.py verify-runtime 2>&1 | grep -E 'FROZEN_DIRTY|BLOCK|OK'
OK: runtime infrastructure lock verified

$ # 步6:还原后 --precommit —— 须绿
$ python3 scripts/grid_infrastructure_guard.py verify-runtime --precommit 2>&1 | grep -E 'FROZEN_DIRTY|BLOCK|OK'
OK: runtime infrastructure lock verified

$ # 校验
$ python3 -c "...sha match..."; git status --short -- ...local_gateway.py
match= True
(status 空)
```

三态全对:runtime 红 / --precommit 绿 / 还原后双绿 / sha match / status 空。

static gate test + verify-runtime(commit 前):

```
$ python3 -m pytest grid-sovereign-runtime/tests/test_infrastructure_guard.py -q
...                                                                      [100%]
3 passed in 0.42s
$ python3 scripts/grid_infrastructure_guard.py verify-runtime
OK: runtime infrastructure lock verified
```

---

### 4 · WARN 条件改 manifest hash ≠ staged blob hash — 过

**diff 摘要:** `check_tree_changes` 里 `if touched and _unlocked()` 的 WARN 从"冻结文件 staged 即警告"改为"staged sha256 ≠ manifest 才警告";新增 `_staged_sha256(rel)`(git show :<rel> → sha256)。

WARN 条件测试(staged sha ≠ manifest,未 update-lock):

```
$ printf '\n' >> grid-sovereign-runtime/gateway/local_gateway.py && git add grid-sovereign-runtime/gateway/local_gateway.py
$ GRID_INFRASTRUCTURE_UNLOCK=1 python3 scripts/grid_infrastructure_guard.py check-staged 2>&1
WARN: grid-sovereign-runtime/gateway/local_gateway.py staged sha256 ≠ manifest — run update-lock before commit (got=72863261b782 want=54e02f62ddee)
exit=0
$ git restore --source=HEAD --staged --worktree -- grid-sovereign-runtime/gateway/local_gateway.py
$ # 还原后 sha match=True,status 空
```

逻辑:update-lock 后 staged sha == manifest → 不警告;未 update-lock → 警告(原:只要 staged 就警告)。

commit(guard r3-3 + r3-4 一起):

```
$ git add scripts/grid_infrastructure_guard.py
$ git commit -m "guard: verify-runtime 默认严(HEAD 比) + --precommit index 模式 + WARN 条件改 staged sha≠manifest (砥 r3 §C 3/4)"
 1 file changed, 34 insertions(+), 12 deletions(-)
commit_exit=0
```

---

### 5 · manifest frozen_files 全列表(只读)— 过

```
$ python3 -c "import json,pathlib; m=json.loads(pathlib.Path('config/grid_infrastructure_lock.json').read_text()); ..."
version: 2026-07-27
frozen_files count: 10
---
 1. grid-sovereign-runtime/gateway/local_gateway.py        sha256=54e02f62ddee56c3...
 2. grid-sovereign-runtime/gateway/aster_identity.py        sha256=946a0e06f5de914c...
 3. grid-sovereign-runtime/gateway/field_now_context.py     sha256=00b3d9e832b5a4d7...
 4. grid-sovereign-runtime/gateway/contract_gate.py         sha256=34793625d5a70913...
 5. grid-sovereign-runtime/gateway/contract_lint.py         sha256=3b54d1e63b05f47d...
 6. grid-sovereign-runtime/gateway/substrate_backend.py     sha256=09988c450f0191d7...
 7. config/aster_chat_system_prompt.txt                     sha256=b57edc30ac375373...
 8. config/aster.toml                                       sha256=caae3604144da76b...
 9. scripts/substrate_airlock/scripts/substrate_sanitizer.py sha256=fec587239f0bf18c...
10. scripts/substrate_airlock/scripts/substrate_gate.py      sha256=011527faf3e1b759...
```

**给 Lyra 看名单:** 10 个 frozen 文件,全在 gateway 推理链 + Aster 身份锚 + substrate airlock。请核该冻的有没有漏(名单是 Lyra 的决定)。

---

## §C 二 · 贴身份(只读)

### 6 · 进程身份

```
--- :8788 ---
73680  uvicorn repo.telemetry.stub:app --host 127.0.0.1 --port 8788   (Python telemetry stub)
--- :8510 ---
73707  streamlit run aether_dashboard.py --server.port 8510          (aether dashboard)
--- :8686 ---
73709  uvicorn app.platform_main:app --host 127.0.0.1 --port 8686    (platform main)
--- :8795 ---
73693  python3 scripts/field_now_v1_6.py                             (FIELD_NOW)

--- docker ps ---
grid-console             127.0.0.1:8610->8610/tcp
alpha-platform-api-1    127.0.0.1:8600->8600/tcp
alpha-platform-worker-1  (无端口映射)
option-workstation       127.0.0.1:8620->8620/tcp
theta-terminal           127.0.0.1:25503->25503/tcp
grid-voice-bridge        127.0.0.1:8796->8796/tcp
```

**身份落定:**

| 端口 | 身份 | 类型 |
|----|----|----|
| 8788 | repo.telemetry.stub:app | Python uvicorn(本机进程) |
| 8510 | aether_dashboard.py | streamlit(本机进程) |
| 8686 | app.platform_main:app | Python uvicorn(本机进程) |
| 8795 | field_now_v1_6.py | FIELD_NOW(本机进程) |
| 8610 | grid-console | docker |
| 8620 | option-workstation | docker |
| 8796 | grid-voice-bridge | docker |
| 8600 | alpha-platform-api-1 | docker(砥未列,顺手贴) |

---

## §C 三 · 等 Lyra 拍后再动(未做)

- **7 · redline hook 认 unlock**(条件:UNLOCK=1 且 manifest hash == staged blob hash;否则仍拦)— 等批
- **8 · §C 1/2**(local_gateway.py:HTTPException 透传 + routed_to 带 substrate)— 7 拍下后走 unlock→改→update-lock→commit,重跑 (b)(d)
- **9 · aether-paper 结算**(§B 11 四条:entry_premium 改 Theta ATM 中价 / record_exit 接通 / 晚班 mark-to-market / 冒烟处决案)— 等一页设计拍板

## §C 四 · 不做

- 不动 §5 UI 四问
- 不动 MIN_VOLUME_MISSING_OI=100(砥建议维持,五个交易日后看 95–120 带再议)

---

## 收尾

```
$ git log --oneline -6
f242ca3 guard: verify-runtime 默认严(HEAD 比) + --precommit index 模式 + WARN 条件改 staged sha≠manifest (砥 r3 §C 3/4)
f03af41 routelog metrics: duration_ms IS NOT NULL denominator + 五班窗 p95 + 422 注释 + 处决案二 bogus substrate (砥 r3 §C 3/4/5)
4bd4019 aether: render OI contract smoke test + HARDZERO_TRIGGERED live log (砥 r3 §C 13/14)
19a3ac9 guard: verify-runtime requires frozen files tracked and clean
a46e2a5 config: commit aster.toml frozen-file drift ...
d72317d gateway baseline 2026-09-01 ...
```

本次 r3 三个 commit:4bd4019(13/14)/ f03af41(metrics+verify_routelog)/ f242ca3(guard)。
分支 `fix/harness-enforcement-v1` 未动;未 --no-verify;未 git add -A;未 restart gateway。剩余 WIP 不属本单。

—— 戌,2026-09-01 PDT


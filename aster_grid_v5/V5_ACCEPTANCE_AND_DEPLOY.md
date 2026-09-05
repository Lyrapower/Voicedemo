# V5 Pack — Fable Acceptance Report + Deployment Checklist
Date: 2026-07-06 · Pack: aster_grid_v5_hardened_pack.zip (GPT-assembled)
Verdict: **ACCEPTED with one condition** (see C1). All five findings verifiably closed.

## Independent verification (run in clean sandbox, not trusting pack's own claims)

py_compile: all 9 files OK.
Selftests: cloud_boundary PASS · provenance_registry PASS · sentinel_ledger_v5
PASS · jarvis_backend_runtime_v5 PASS · frontend_multimodal_v5 PASS ·
telegram_bot_v5 PASS · aether_router_v5 PASS.

bridge_v5 selftest: **refused to run in my sandbox** — "aether_sentinel_v1
import failed; refusing fallback verifier". This is F5 WORKING: sandbox has no
sentinel module, bridge fails closed instead of rubber-stamping. With
ASTER_ALLOW_FALLBACK_VERIFIER=1 it runs and PASSES with degraded stamp. Exactly
the specified behavior, verified from both sides.

Yesterday's live failures, re-run as adversarial probes against V5:
- "私钥保管好" → BLOCKED (V3: passed as YELLOW — CJK \b bug fixed)
- "auth token budget" → ALLOWED (V3: false-positive RED — word/value split works)
- clean user_text + secret in qwen_draft → BLOCKED (V3's F1 hole closed;
  component-level scan confirmed)
- laundered DeepSeek text, markers stripped → CAUGHT, overlap 0.875 (V3's F2
  closed; shingle registry works)
- true paraphrase of registered text → passes (threshold not over-tight)
- review flow: `--reviewed` launch flag GONE; review list/show/approve/reject
  present (F4 closed structurally)
- Telegram: private-only + no path dump confirmed in source (F8)

## C1 — Single condition before production

`aether_sentinel_v1` was NOT in the pack. The bridge's authority layer imports
it; the pack ships every wall except the judge. Before launchd deployment,
Cursor must confirm the real sentinel module is present at import path and add
one acceptance line: fresh checkout + `python3 aster_fable_bridge_v5.py
selftest` must PASS **without** ASTER_ALLOW_FALLBACK_VERIFIER. If it only
passes degraded, deployment stops there.

## Cursor deployment checklist (昨日清单③, rebased onto V5)

### Step 1 — Referee selftest wiring
```bash
# single command that must exit 0 before anything starts
python3 cloud_boundary.py && \
python3 provenance_registry.py selftest && \
python3 sentinel_ledger_v5.py selftest && \
python3 aster_fable_bridge_v5.py selftest && \
python3 jarvis_backend_runtime_v5.py selftest
```
Wrap as `referee_selftest.sh`, exit non-zero on any failure. launchd jobs
depend on this gate (Step 3).

### Step 2 — Ledger + registry initialization
```bash
python3 sentinel_ledger_v5.py init
python3 provenance_registry.py backfill \
  aether_api_router_data/deepseek_screen_only/   # historical quarantine
# register the charter itself so it can never be laundered into training data:
python3 provenance_registry.py register --source daemon_charter \
  --file daemon_charter.md
```
Acceptance: sqlite files exist; `provenance_registry.py check` on a pasted
deepseek artifact text returns clean=false.

### Step 3 — launchd (daemons run ONLY behind the selftest gate)
Two plists, both with:
- `ProgramArguments`: `/bin/bash -c "cd <repo> && ./referee_selftest.sh && exec python3 <daemon>.py"`
- `KeepAlive: {SuccessfulExit: false}` — crash restarts, selftest-fail stays dead
- `StandardErrorPath` into logs/, log rotation via newsyslog or size check
- NO env vars granting ASTER_ALLOW_FALLBACK_VERIFIER or EXPORT_REVIEWED_ONLY=0
  in the plist. Grep the plist in acceptance to prove absence.

Daemons in scope (信任台阶 order, unchanged):
1. 盘后摘要 daemon — report-only. May start after Step 1-2 accepted.
2. crypto anomaly sentinel — report-only. Starts only after 盘后摘要 runs
   7 clean days (charter invariant 5 = zero stop-condition hits in ledger).
Action permissions remain OFF for both. Charter invariants 1-5 are loaded as
runtime config, not comments.

### Step 4 — Acceptance script for the whole install
`accept_v5_install.sh` asserts, in order:
1. referee_selftest.sh exits 0 (undegraded)
2. cloud boundary: the four probe strings above behave as listed
3. provenance: laundering probe caught at >0.15
4. review: export without approval → rejected reason manual_review_required
5. launchd: both plists loaded, both jobs alive, plists contain no
   fallback/override env vars
6. ledger: stop_condition table exists and is empty
Print one line per check, PASS/FAIL, exit non-zero on any FAIL.

## Deferred (explicitly not in this deployment)
- jarvis-console 二期 (昨日清单②) — awaiting current console source from Lyra
- Qwen action permissions — gated on 7 clean daemon-days, per charter
- F3-style pattern expansion — collect boundary-violation log samples first,
  same logging-first rule as Aether filters

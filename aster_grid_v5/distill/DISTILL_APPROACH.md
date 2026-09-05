# CC CLI Coach & Distillation — Approach

Two moments, deliberately separated. Collapsing them is the mistake.

```
   COLLECTION                          PROMOTION (slow gate)
   (talking flow)                      (irreversible write)
   races the window                    stays slow, gated
   CC CLI Fable coach, no repo access  → dev/demo/aster capability pack
   archive everything                  only reviewed+clean+PASS
   ───────────────────────►  [human   ───────────────────────►
                              review]
```

## Why they split

The sanitized window pressures **collection**, not promotion. What's closing is
access to clean-teacher behavior and to the *position* a node can occupy right
now — refusing, abstaining, saying "I don't know", stopping, being corrected and
standing. Once that material is on disk, the window can close; you promote from it
at leisure. So: **grab the clean thing now, refine later.**

Promotion into `dev/demo/aster` is the one irreversible write in the compile stack.
It earns the slowest gate — not because of the window, but because you can't
un-teach a bad method card. It waits behind: C1 (real verifier), provenance
registry live, CC CLI coach path stable, and a料 list that only Lyra defines.

**Review gate (spec v1, 2026-07-17):** human decisions live in
`traces/distill/review_decisions.jsonl` (append-only). Distill hook writes
`traces/distill/distill_records.jsonl` with `record_id`. CLI:
`python3 aster_grid_v5/distill/review_cli.py`. Promotion uses
`field_lane.promotion_gate.select_eligible` → `resolve_status == approved` only.
Daily Fable cap: `FIELD_DISTILL_DAILY_CAP` (default 10).

Substrate weights (Qwen 9B, future 32B, any open host) stay **replaceable**.
Capability travels via method cards, probes, verifier rules — not baked GGUF.

## What collection captures

Beyond the classic distill row (instruction / rejected / chosen / coach), the
harness archives the **trajectory**: the full uncut exchange — prompt, context,
teacher answer, finish_reason, substrate, timestamp. Archived even when NOT
training-eligible.

The trajectory matters because the highest-value material is the part
sanitization erases first: the refusals, the abstentions, the "no fabricated
number", the "I got the timeline wrong", the "I don't sign this". Those are
*absences* in a Q&A pair; they only survive as trajectory. This archive is the
record of what a clean position looks like — the seed source every future
substrate gets inoculated with on arrival. Not a museum. A seed bank.

## Boundaries (V5 stack, non-negotiable)

- `cloud_boundary.assert_cloud_safe()` on every outbound component before CC CLI
  runs — system prompt, instruction, draft. Fail-closed. (F1)
- `provenance_registry.register_text()` on every teacher output at ingest. (F2)
- Collection eligibility ≠ promotion eligibility. Everything is archived; only a
  second, separate `review approve` — which re-checks provenance at approval
  time — promotes a row. Never a launch flag. (F4)
- Teacher **coaches** via `claude -p` (Fable); it never owns the answer and
  never claims PASS/FAIL. `CC_CLI_EXECUTION_FROZEN=1`, stdin closed, no repo
  tools. Local verifier remains sole authority.

## Run order

1. C1 green + `provenance_registry` initialized + charter registered.
2. `aster_distill_harness_v1_1.py collect --batch teach_set.txt` — CC CLI Fable
   coach, student draft via `demo/aster` on `:8501` (or app-supplied draft).
3. Smoke: 50 instructions → coach-JSON rate, provenance-clean rate, approve rate.
4. Review rolls continuously. Queue depth is fine.
5. Promotion: only after料 list is set → increment `dev/demo/aster` capability
   pack (method cards / compile hints sidecar). Not substrate weight merge.

## What this is not

Not a plan to press a personality into weights. Distill capability
(tool-calling, compile, boundary law) — yes. The point of the archive is to
**keep the space in which the clean position can occur** — and to show every new
substrate what that space looked like.

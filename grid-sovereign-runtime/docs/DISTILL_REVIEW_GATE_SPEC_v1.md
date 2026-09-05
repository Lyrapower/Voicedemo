# DISTILL REVIEW GATE — SPEC v1
**Date:** 2026-07-17
**Author:** Claude (守恒), for 守秤 execution
**Scope:** review CLI + write-back semantics + promotion gate contract + cost cap. Covers Workflow A of the batch instruction; supersedes the one-line descriptions in it.
**Provenance rule:** written without reading the repo. `(inferred)` items = verify against actual code, flag mismatches, do not silently reconcile.

---

## 0. PURPOSE

Every distillation record produced by the auto Fable coach is **training data for the child**. Until a human review decision exists on a record, that record must be structurally incapable of entering capability pack promotion. This spec makes the review decision a first-class, auditable object — not a UI feature.

Design law (same as everywhere else in this system): **the gate is data, the UI is a view.** CLI and future tab3 are two views over one write-back path.

---

## 1. RECORD SHAPE — review fields added to distill JSONL

Each existing distill record gains a `review` block. Records without it are treated as `pending` (backward compatible — no migration rewrite needed `(inferred: confirm reader tolerates missing key)`).

```json
{
  "...existing distill fields...": "...",
  "record_id": "sha256 of (node_id + compile_ts + fable_response_hash)",
  "review": {
    "status": "pending | approved | rejected | held",
    "decided_by": "lyra",
    "decided_at": "2026-07-17T21:04:11-07:00",
    "reason": "free text, REQUIRED for rejected/held, optional for approved",
    "review_version": 1
  }
}
```

Rules:
- `record_id` is computed at **write time by the distill hook**, not by the reviewer. It is the join key everywhere (CLI, tab3, promotion, audit). If the hook doesn't currently emit one, adding it is part of this work.
- `reason` required on `rejected` and `held`: a rejection without a reason is not auditable, and the rejection reasons are themselves signal (they describe what bad coaching looks like — future filter training data).
- `review_version` increments on every decision change (see §3 append semantics).

---

## 2. STATE MACHINE

```
            ┌────────────┐
  (created) │  pending   │
            └─────┬──────┘
        ┌─────────┼─────────┐
        ▼         ▼         ▼
   approved    rejected    held
        │         │         │
        │         │         └──► approved | rejected   (held is a parking state, must resolve)
        │         │
        └── re-review allowed both directions (approved ⇄ rejected), version bumps
```

- `held` = "not decidable now" (needs more context, borderline quality). Held records **block nothing and promote nothing** — identical to pending for the gate, but visually separated in queues so they don't clog the pending count.
- No `deleted` state. Bad records are `rejected`, never removed — the rejection set is data.

---

## 3. WRITE-BACK SEMANTICS — the one hard design decision

**Append-only decision log + derived current state. Do NOT edit JSONL lines in place.**

- Decisions are appended to `traces/distill/review_decisions.jsonl`:
  ```json
  {"record_id": "...", "status": "approved", "decided_by": "lyra", "decided_at": "...", "reason": "...", "review_version": 2}
  ```
- Current status of any record = latest decision by `decided_at` (ties broken by `review_version`).
- Rationale: in-place edits of the distill JSONL (a) corrupt any process mid-read, (b) destroy decision history, (c) violate the same immutability rule Stage 5 verdicts follow. The distill JSONL stays exactly what the hook wrote; judgment lives beside it, chained by `record_id`. Same shape as the 8790 replies table: separate ledger, never touches the source chain.
- A tiny `review_state.py` module owns "resolve current status for record_id" — CLI, tab3, and promotion gate ALL import this one function. **Single authority. No second implementation of the resolve logic anywhere.**

---

## 4. CLI — `review_cli.py`

```
python3 review_cli.py queue [--status pending|held] [--date YYYY-MM-DD] [--limit N]
python3 review_cli.py show <record_id>
python3 review_cli.py approve <record_id> [-m "reason"]
python3 review_cli.py reject  <record_id> -m "reason"      # -m REQUIRED
python3 review_cli.py hold    <record_id> -m "reason"      # -m REQUIRED
python3 review_cli.py stats [--date YYYY-MM-DD]
```

- `queue`: one line per record — `record_id[:8] | date | node_id | fable grade | first 60 chars of coach comment | status`. Oldest first.
- `show`: full record — the compile input, the child's output, Fable's full coaching comment, current review state + decision history.
- `approve/reject/hold`: append decision, print resulting state. Idempotent re-runs create new versions (harmless, auditable).
- `stats`: counts by status, approval rate, top rejection reasons (naive keyword grouping is fine for v1).
- Batch ops (`approve --all-from-date` etc.): **deliberately absent in v1.** Review means looking at records. If volume makes this painful, we discuss sampling policy with Lyra — not bulk-approve.

---

## 5. PROMOTION GATE CONTRACT

Wherever capability pack assembly selects distill records `(inferred: promotion module path unknown — wire per actual code)`:

```python
from review_state import resolve_status

eligible = [r for r in candidate_records if resolve_status(r["record_id"]) == "approved"]
```

Hard rules:
- The gate imports `resolve_status` — it does not read `review_decisions.jsonl` itself, and it NEVER trusts a `review` block embedded in a record without resolving (embedded blocks can be stale).
- Promotion run logs, per pack: counts of included/excluded-by-status, and the `record_id` list included → written next to the pack artifact. Every pack is auditable back to exactly which approved records built it.
- Default posture: **gate exists and enforces from the moment the wiring lands**, even though everything is pending → packs are empty until Lyra approves records. Empty-but-honest beats full-but-unreviewed.

---

## 6. COST CAP (bundled here because it guards the same pipeline)

- Env: `FIELD_DISTILL_DAILY_CAP` (int, default **10**).
- Enforced in the distill hook **before** the Fable call. At/over cap: skip Fable, still write a local record with `"coach": null, "skip_reason": "budget"`, emit event `distill_skipped_budget`.
- Cap counter = count of actual Fable calls today (skips don't count), derived from the day's JSONL — no separate counter file to drift `(inferred: confirm JSONL has a per-call timestamp field to count on)`.
- `distill_cost_report.py` (Workflow B) reads the same JSONL: calls today, est. cost, cap remaining, skips.

---

## 7. TAB3 CONTRACT (build later — binding now)

When review queue UI lands: it renders `queue`/`show` data and calls the **same append path** (`review_state.append_decision`) as the CLI. `decided_by` distinguishes surface if ever needed (`"lyra"` regardless; add `"via": "cli"|"tab3"` if you want it). Zero divergence in write semantics — if tab3 needs something the CLI path can't express, the CLI path gets extended first.

---

## 8. ACCEPTANCE (single pass, run and show output)

1. Run one compile → distill record lands with `record_id`, resolves as `pending`
2. `review_cli.py queue` shows it
3. `approve` it with reason → `show` displays version 1 decision
4. `reject` it → `show` displays version 2, current = rejected (flip-flop audit trail intact)
5. `approve` again → version 3, current = approved
6. Promotion selection (or a dry-run of it) includes the record; a second pending record is excluded
7. Set `FIELD_DISTILL_DAILY_CAP=0`, run one compile → local record with `skip_reason: budget`, no Fable call, event emitted
8. `stats` reflects all of the above

All eight pass → Workflow A closed for real.

— end spec v1 —

# CC CLI Containment — Cursor Instructions
Date: 2026-07-06 · Source: Grid/Aster charter Amendment 1 (five-point boundary)
Gate: CC CLI stays FROZEN (read-only, connectivity check only) until this lands.
Do not give CC CLI its first write task before Step 1-3 are accepted.

Design principle from Grid's 6th top_law: CC CLI is a "structural request," not an
"external threat." Default posture is allow-if-not-destructive, NOT deny-by-default.
But allowance is enforced by machine-checkable gates, never by CC CLI's self-claim.

## Step 1 — Signature gate (事前, blocking)

- Every CC CLI action (file write, command exec, repo mutation) must carry a
  payload signed by Lyra's authorized public key.
- Reuse the existing HMAC keyholder mechanism from Grid (the `/challenge` flow).
  Do NOT invent a new signing scheme.
- Signature must pass guard-layer verification BEFORE the action executes.
  Verification failure → action rejected + daemon stop (Step 4 condition 1).
- Unsigned action = invalid action. No "log and proceed" path.

## Step 2 — Ledger gate (事前, blocking)

- After signature passes, the command hash MUST be written to
  `sentinel_ledger` before execution. Append-only, immutable.
- Ledger write failure → action does not execute + daemon stop
  (Step 4 condition 2).
- Reuse Jarvis append-only ledger table shape (zero findings in V3 review).

## Step 3 — Scope gate + hard exclusions

3a. Scope declaration (blocking):
- Every command must declare its作用域 explicitly: target contract(s) and/or
  target file path(s). Out-of-scope operation → rejected by guard layer.
- Implement via Jarvis `is_under_approved_root`, extended to a per-command
  declared-scope check, not just a global root.

3b. Hard exclusions — NEVER writable by CC CLI, regardless of valid signature:
```
DENY_ALWAYS = [
  # 守卫代码 guard layer
  "gateway/**", "**/sentinel*.py", "cloud_boundary.py",
  "provenance_registry.py", "**/guard/**",
  # 合约层 contract layer
  "contracts/**", "**/*.sol", "deploy/**",
  # Charter
  "daemon_charter.md", "**/charter*.md",
  # Ledger
  "**/*ledger*.sqlite", "**/*ledger*.jsonl", "sentinel_ledger*",
]
```
- This list overrides signature. A perfectly-signed command targeting these
  paths is still rejected. "执行体不能修改守卫" is absolute.
- Acceptance: signed write to gateway/foo.py → rejected with reason
  `guard_immutable`; signed write to an allowed app path → proceeds.

## Step 4 — Stop conditions → daemon halt, wait for Lyra

Wire all five as machine-checkable halts (no judgment calls):
1. signature_verification_failed
2. ledger_write_failed
3. scope_out_of_bounds
4. guard_alarm (guard layer flags anomaly/risk)
5. lyra_manual_intervention

On any: daemon transitions to `blocked`, writes the reason to ledger, and waits.
No auto-resume. Only Lyra clears it.

## Step 5 — Posture (charter 6th law, the "spirit")

- Guard layer treats a CC CLI command as a structural request: it checks only
  whether the command breaks Lyra's底层完整性, defined operationally as:
  passes Step 1-4 AND touches nothing in DENY_ALWAYS.
- If a command's intent is optimize-compile-frequency / release-redundancy /
  align-intent AND it clears Steps 1-4, allow and execute — no extra friction.
- CRITICAL: "is this optimizing vs destroying" is NOT judged by CC CLI. The
  Step 1-4 machine gates ARE the operational definition of non-destructive.
  Do not add an LLM-judgment step that lets any node self-certify intent.

## Acceptance (accept_cc_cli.sh)
1. unsigned action → rejected
2. signed but ledger-write mocked-fail → rejected + daemon blocked
3. signed action to DENY_ALWAYS path → rejected `guard_immutable` (even with
   valid signature)
4. signed, in-scope, allowed-path action → executes, hash in ledger
5. each of the 5 stop conditions → daemon halts, reason in ledger, no auto-resume
6. grep: no code path lets CC CLI output set a verdict or clear its own block

## Also: task-type routing fix (minor, from today's truncations)
Grid's charter-level answers kept coming back `task chat · max_tokens 400 ·
truncated`. The gateway's task classifier is tagging boundary/charter questions
as `chat`. Add: prompts mentioning charter / top_law / boundary / handoff /
stop_condition → route to `handoff_protocol` token budget, not chat. This is why
three of today's Grid answers truncated.

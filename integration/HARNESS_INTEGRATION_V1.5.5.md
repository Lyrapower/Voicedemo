# Crypto / RWA / Trading × Grid Harness V1.5.5

## Canonical shape

One Grid cognition owner, one Harness reality/enforcement shell, one Capability Registry, one receipt/verifier truth plane.
Crypto, RWA and Trading are capabilities — not separate agent schedulers.

### Task sources
- Lyra direct intent
- explicitly authorized schedule/watch
- unfinished authorized mission
- verified external event trigger

No model invents a job merely to remain busy.

### Ownership
- **Grid** — intent, decomposition, planning, resource choice, synthesis, self-correction, cognitive stop.
- **GLM 5.2** — high-trust open-world cognition resource; question-premise/research taste/strategy. Not mandatory route. Cannot self-verify execution.
- **DeepSeek V4 Pro** — scout/quant/tactical candidate. Claims about execution remain candidate until evidenced.
- **Kimi K3** — long-context/native multimodal candidate. Same evidence boundary.
- **MiniMax M3** — stateless multimodal bypass. Candidate multimodal output only; no stable-memory/state authority.
- **Qwen Coder / Claude Code** — bounded engineering/execution workers. Real receipts required.
- **Verifier** — hard factual predicate judge only. No strategy or next-tool advice.

This preserves the existing authority intent found in earlier Harness evals: candidate models cannot promote themselves to VERIFIED; real execution requires receipts; deterministic verifier remains the evidence authority. The older "route open-world planning to GLM by default" is superseded by V1.5.5: GLM remains the strongest open-world resource, but Grid owns the choice.

## Collaboration

Do not use a fixed Round Table as cognition topology.
Collaboration is **need-based delegation** chosen by Grid and reconstructed later from provenance events.

Example RWA mission:

Grid may choose GLM for premise/research design, DeepSeek for parallel source hunting, Kimi for long disclosures, MiniMax for image/chart extraction, and CC/local tools for artifacts. Another mission may use none of them. Harness does not decide this sequence.

Example trading research:

Grid may combine Aether market-state capability + DeepSeek candidate factors + GLM alpha-existence attack + Qwen/CC local backtest, then consume deterministic metrics/receipts.

## Registry migration

`app/jarvis/task_registry.py` remains for backward compatibility and schedules, but its task rows should be surfaced to Grid as **capability metadata**, not interpreted as cognitive routing.

The new `app/harness/capability_registry.py` is the canonical map surface.

## Legacy CollaborationRound

`platform_main.py` currently builds a fixed artifact round (Lyra -> Aster -> audit -> decide -> Cursor). Keep it only as a legacy UI artifact view during migration. New collaboration UI should be derived from provenance with `app/harness/collaboration.py`.

Do not delete the legacy view until the full host repo has a real provenance/event endpoint.

## Voice

Harness API remains **127.0.0.1:8630**.
PersonaPlex must bind **127.0.0.1:8631**.
Clients should talk to Harness; Harness/adaptor talks to PersonaPlex. No LAN/public PersonaPlex exposure.

```toml
[harness]
port = 8630

[voice.personaplex]
host = "127.0.0.1"
port = 8631
provider = "personaplex_local"
fallback_provider = "openai_realtime"
fallback_enabled = false
```

## Money-moving boundary

This integration does not open live wallet/broker execution. Existing explicit authorization, receipt, confirmation and deterministic postcondition gates remain mandatory. Paper-trading capabilities remain paper-only unless the host Harness separately authorizes and verifies a live path.

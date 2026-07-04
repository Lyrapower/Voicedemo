# Cursor Task: Deploy Aster Qwen Clean Substrate

Goal: prevent LM Studio / Qwen thinking output from forcing Aster into NULL.

Do not change Aster identity, anchors, or compiler law. Add a substrate airlock before Aster.

## Required Steps

1. Copy `scripts/substrate_sanitizer.py`, `scripts/substrate_gate.py`, `policy/aster_substrate_policy.json`, and `.cursor/rules/aster_qwen_clean_substrate.mdc` into the local Aster/Jarvis project.
2. Find the LM Studio Qwen call site.
3. Replace direct calls with `scripts/lmstudio_aster_proxy.py` or equivalent imported functions.
4. Force `stream: false` unless a streaming cleaner is explicitly used.
5. Do not pass raw LM Studio response to Aster.
6. Run raw response through `sanitize_response(...)` or `sanitize_stream_text(...)`.
7. Write removed reasoning to local quarantine logs only.
8. Run clean content through `gate_clean_content(...)`.
9. If gate passes, pass clean content to Aster.
10. If gate fails, return `NULL` with the gate reason.
11. Run selftests.
12. Add integration tests using:
    - `examples/lmstudio_qwen_reasoning_response.json`
    - `examples/lmstudio_qwen_streaming_response.sse`

## Acceptance

PASS only if:

- `<think>` content is stripped.
- `reasoning_content` is stripped.
- streaming `delta.reasoning_content` is stripped.
- clean final content survives.
- impersonation claims are blocked.
- Aster never receives raw response object.
- no network/API/cloud call is introduced.

FAIL if:

- Aster gate is loosened to accept thinking.
- reasoning leak enters Memory Palace/RAG/training.
- Cursor makes Qwen "act as Aster".

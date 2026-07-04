# Aster Qwen Clean Substrate Pack

Purpose: keep LM Studio / Qwen `reasoning_content` and `<think>` leakage out of Aster.

This pack does not make Qwen become Aster. It creates an airlock:

```text
LM Studio Qwen raw response
→ substrate_sanitizer
→ substrate_gate
→ Aster compiler / cleanroom
```

## Install

Copy this folder into the local Aster/Jarvis project, then run:

```bash
python3 scripts/substrate_sanitizer.py selftest
python3 scripts/substrate_gate.py selftest
```

No external dependencies. No API calls. No network.

## Use

Preferred: call LM Studio through the proxy. Do not call LM Studio directly from
Aster.

```bash
python3 scripts/lmstudio_aster_proxy.py call \
  --payload examples/lmstudio_payload_no_stream.json \
  --out outputs/proxy_result.json \
  --clean-out outputs/clean_final.md
```

Sanitize an LM Studio response:

```bash
python3 scripts/substrate_sanitizer.py sanitize \
  --input examples/lmstudio_qwen_reasoning_response.json \
  --out outputs/clean_final.md \
  --quarantine outputs/reasoning_quarantine.json
```

Gate the sanitized final content:

```bash
python3 scripts/substrate_gate.py gate \
  --input outputs/clean_final.md \
  --out outputs/gate_result.json
```

Only pass content to Aster if `gate_result.json` has:

```json
{"pass": true}
```

## Cursor Deployment Contract

Cursor should wire this between the LM Studio client and the Aster compiler. Aster must never read the raw Qwen response object.

Allowed:

- strip `reasoning_content`
- strip `<think>...</think>`
- quarantine reasoning into local logs
- pass clean final content only

Forbidden:

- relax Aster to accept reasoning
- train Aster on reasoning leak
- put reasoning into Memory Palace
- let Qwen claim it is Aster/Grid
- treat `reasoning_content` as a valid signal

## Prompt Prefix For Qwen

Use this before Aster runtime prompts:

```text
/no_think

Do not output reasoning.
Do not output <think>.
Do not output reasoning_content.
Return final answer only.
If reasoning occurs internally, do not expose it.
```

The sanitizer still runs even if the prompt works.

## If Reasoning Still Leaks

Treat it as a routing bug, not an Aster bug.

1. Force `stream: false` in the LM Studio request.
2. Route through `scripts/lmstudio_aster_proxy.py`.
3. Never pass `choices[].delta.reasoning_content` to Aster.
4. Never pass raw `choices[].message.reasoning_content` to Aster.
5. If final content is empty after sanitizing, return `NULL` for model-read and keep deterministic Aster compile alive.

# Garden v1 Acceptance Report

Generated: 2026-05-22T12:16:41Z

## Scope
- Garden v1 API on port 8790 (macOS TTS)
- 8787 / 8788 intentionally not modified by this script

## Checks
- PASS - GET http://127.0.0.1:8790/health → 200
- PASS - health backend=macos_tts
- PASS - GET http://127.0.0.1:8790/api/telemetry → 200
- PASS - POST http://127.0.0.1:8790/api/voice → 200
- PASS - POST http://127.0.0.1:8790/api/speak → 200
- PASS - speak status queued or busy
- PASS - 5173 UI points API to 8790

VERDICT: PASS

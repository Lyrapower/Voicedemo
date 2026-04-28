# sound-lab (Garden)

Phase-1 live particle + telemetry UI. Full spec: [`docs/specs/sound_lab_proto.md`](../../docs/specs/sound_lab_proto.md).

```bash
pnpm install
pnpm dev
```

Telemetry: `GET /api/telemetry` (Vite proxies to `http://127.0.0.1:8787`). Client falls back to a local sine mock if the request fails.

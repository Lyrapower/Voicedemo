# Demo docs

## Garden (sound-lab) — dev in three shells

```bash
# shell 0 (optional) — stop stale uvicorn / vite
bash scripts/kill_sound_lab_dev.sh

# shell 1 — telemetry stub (8788)
bash scripts/start_telemetry.sh

# shell 2 — Vite particle UI (5173)
bash scripts/start_sound_lab.sh

# shell 3 — Aster Router (8787) reverse-proxies `/` → Vite
cd repo && ./scripts/run.sh
# or:  cd repo && python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

### Open

**http://127.0.0.1:8787/** — loads the live particle UI (proxied from `http://127.0.0.1:5173/`).

Direct Vite (no Aster): **http://127.0.0.1:5173/**

Aster health: **http://127.0.0.1:8787/health**

Telemetry health: **http://127.0.0.1:8788/health**

Spec: [`specs/sound_lab_proto.md`](specs/sound_lab_proto.md)

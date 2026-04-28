# sound-lab (Garden)

Spec: [`docs/specs/sound_lab_proto.md`](../../docs/specs/sound_lab_proto.md) · Quick dev: [`../../docs/README.md`](../../docs/README.md)

## One URL in the browser

With **Aster** on **8787** proxying to Vite on **5173**:

**http://127.0.0.1:8787/**

## Three processes

1. **Telemetry (8788):** `bash scripts/start_telemetry.sh`  
2. **Vite (5173):** `bash scripts/start_sound_lab.sh`  
3. **Aster (8787):** `cd repo && ./scripts/run.sh` (or `python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8787`)

Optional cleanup: `bash scripts/kill_sound_lab_dev.sh`

Direct Vite (no proxy): **http://127.0.0.1:5173/**

`TELEMETRY_PORT` defaults to **8788**; set in shell or `ui/sound-lab/.env` (see `.env.example`).

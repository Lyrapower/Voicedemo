# GRID Workbench UI (:8515) + Gateway APIs (:8501)

**Grid app (`grid.html`) is not modified.** Workbench is a separate Tailscale-facing UI.

| Layer | Port | What |
|-------|------|------|
| Grid app | **8501** | `grid.html`, voice, `/v1/chat/completions`, **`/task/candidate`**, **`/task/expanded`**, compile, store |
| Workbench UI | **8515** | Static only: `grid_workbench_b11.html`, `grid_multimodal.html` |

Workbench pages call **8501** for all APIs (chat, Kimi, expanded orchestration).

## Start

Grid gateway:

```bash
/Users/ciciwang/Projects/demo/scripts/start_grid_gateway.sh
```

Workbench UI (separate terminal):

```bash
/Users/ciciwang/Projects/demo/scripts/start_workbench_8515.sh
```

## Tailscale (verified 2026-07-22)

Serve paths (both must be up):

```bash
tailscale serve --bg "http://127.0.0.1:8501"
tailscale serve --bg --set-path=/workbench "http://127.0.0.1:8515"
```

**Phone b11 (bookmark this):**

https://cicimacbook-air.tail76db5b.ts.net/workbench/grid_workbench_b11.html

Short entry (302 → b11): https://cicimacbook-air.tail76db5b.ts.net/workbench/

On `.ts.net`, b11 auto-sets **8501 网关** = `https://<host>.ts.net` (HTTPS :443, **not** `:8501`). APIs: `/v1/chat/completions`, `/task/expanded`, `/task/candidate`.

Acceptance: `bash scripts/verify_b11_tailscale.sh`

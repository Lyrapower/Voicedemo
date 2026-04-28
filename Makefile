# Optional one-shot dev: UI (5173) + telemetry stub (TELEMETRY_PORT, default 8788).
# Requires: pnpm in ui/sound-lab, uvicorn on PATH or repo .venv, Node npx.
#
#   export TELEMETRY_PORT=8788   # optional; default 8788
#   make sound-lab-dev
#
.PHONY: sound-lab-dev sound-lab-ui sound-lab-telemetry

export TELEMETRY_PORT ?= 8788

sound-lab-ui:
	cd ui/sound-lab && TELEMETRY_PORT=$(TELEMETRY_PORT) pnpm dev

sound-lab-telemetry:
	TELEMETRY_PORT=$(TELEMETRY_PORT) bash scripts/start_telemetry.sh

sound-lab-dev:
	npx --yes concurrently -k -n ui,telemetry -c blue,green \
		"$(MAKE) sound-lab-ui" \
		"$(MAKE) sound-lab-telemetry"

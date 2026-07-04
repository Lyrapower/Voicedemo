# Optional one-shot dev: Garden UI (5173) + telemetry stub (TELEMETRY_PORT, default 8788).
#
#   export TELEMETRY_PORT=8788   # optional; default 8788
#   make sound-lab-dev
#
.PHONY: sound-lab-dev sound-lab-ui sound-lab-telemetry

export TELEMETRY_PORT ?= 8788

sound-lab-ui:
	python3 -m uvicorn scripts.sound_lab_fallback:app --host 127.0.0.1 --port 5173

sound-lab-telemetry:
	TELEMETRY_PORT=$(TELEMETRY_PORT) bash scripts/start_telemetry.sh

sound-lab-dev:
	npx --yes concurrently -k -n ui,telemetry -c blue,green \
		"$(MAKE) sound-lab-ui" \
		"$(MAKE) sound-lab-telemetry"

#!/usr/bin/env bash
# Stop common dev listeners (sound-lab / Aster / telemetry). Repo root: bash scripts/kill_sound_lab_dev.sh
set -u
pkill -f "uvicorn .*8787" 2>/dev/null || true
pkill -f "uvicorn .*8788" 2>/dev/null || true
pkill -f "telemetry.main:app" 2>/dev/null || true
pkill -f "vite.*5173" 2>/dev/null || true
pkill -f "node.*vite" 2>/dev/null || true
echo "kill_sound_lab_dev: sent signals (ignore if nothing was running)."

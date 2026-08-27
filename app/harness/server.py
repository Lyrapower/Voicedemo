"""Harness HTTP surface — 127.0.0.1:8630.

Read-only capability export. No cognition, no resource substitution.
"""
from __future__ import annotations

from fastapi import FastAPI

from app.harness.resource_gate import export_capability_surface

app = FastAPI(title="Grid Harness", version="1.5.5-enforcement")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "harness", "port": 8630}


@app.get("/api/capabilities")
def capabilities() -> dict:
    return export_capability_surface()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8630, log_level="warning")

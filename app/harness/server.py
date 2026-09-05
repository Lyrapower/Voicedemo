"""Harness HTTP surface — 127.0.0.1:8630.

Read-only capability export. No cognition, no resource substitution.
"""
from __future__ import annotations

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.harness.resource_gate import export_capability_surface

app = FastAPI(title="Grid Harness", version="1.5.5-enforcement")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "harness", "port": 8630}


@app.get("/api/capabilities")
def capabilities() -> dict:
    return export_capability_surface()


class RwaConnectBody(BaseModel):
    mission_id: str
    action_id: str | None = None
    decision_origin: str
    run_id: str | None = None
    operation: str = "rwa.onchain_read"


@app.get("/api/rwa/onchain")
def rwa_onchain_published() -> dict:
    from app.crypto_rwa.rwa_chain_connect import load_published
    return load_published()


@app.post("/api/rwa/onchain")
def rwa_onchain_connect(body: RwaConnectBody) -> dict:
    from app.crypto_rwa.rwa_chain_connect import connect_run
    if any(x in body.operation.lower() for x in ("transfer", "send", "approve", "swap", "trade", "withdraw")):
        raise HTTPException(status_code=403, detail="money-moving methods forbidden")
    ctx = {
        "mission_id": body.mission_id,
        "action_id": body.action_id or "rwa.onchain_read",
        "decision_origin": body.decision_origin,
        "operation": body.operation,
    }
    try:
        return connect_run(ctx, run_id=body.run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8630, log_level="warning")

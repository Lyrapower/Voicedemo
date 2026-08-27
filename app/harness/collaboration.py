"""Event-derived collaboration view.

Collaboration is reconstructed from provenance. It is not a fixed Round Table pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable


@dataclass(frozen=True)
class CollaborationEvent:
    mission_id: str
    event_id: str
    actor: str
    action: str
    target: str = ""
    status: str = ""
    evidence_pointer: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_collaboration_view(events: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    if events is None:
        from app.harness.provenance import read_events
        events = read_events()
    rows = []
    actors = []
    for event in events:
        actor = str(event.get("actor") or event.get("decision_origin") or "UNKNOWN")
        if actor not in actors:
            actors.append(actor)
        rows.append({
            "actor": actor,
            "action": event.get("action") or event.get("operation") or "",
            "target": event.get("target") or event.get("selected_resource") or "",
            "status": event.get("status") or "",
            "evidence_pointer": event.get("evidence_pointer") or "",
            "timestamp": event.get("timestamp") or "",
        })
    return {
        "mode": "EVENT_DERIVED",
        "actors_observed": actors,
        "events": rows,
        "note": "No fixed Lyra->Aster->Reviewer->Cursor cognition pipeline is implied.",
    }

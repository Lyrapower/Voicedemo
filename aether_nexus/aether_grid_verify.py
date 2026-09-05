"""Aether trading daemons → shared grid_verification_client (delegated grid-scheduler-v1)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_GW_PKG = Path(__file__).resolve().parents[1] / "grid-sovereign-runtime" / "gateway"
if str(_GW_PKG) not in sys.path:
    sys.path.insert(0, str(_GW_PKG))

from grid_verification_client import attach_grid_verification  # noqa: E402

AETHER_SIGNER_ID = "grid-scheduler-v1"


def gateway_base_from_url(gateway_url: str) -> str:
    return gateway_url.rstrip("/").rsplit("/v1/", 1)[0].rstrip("/")


def attach_aster_chat_verification(chat_body: dict[str, Any], *, gateway_url: str) -> dict[str, Any]:
    return attach_grid_verification(
        chat_body,
        gateway_base=gateway_base_from_url(gateway_url),
        signer_id=AETHER_SIGNER_ID,
    )

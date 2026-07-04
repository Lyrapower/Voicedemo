from fastapi import APIRouter
from app.config import settings
from app.schemas import ProviderStatusOut

router = APIRouter()


def _message(mode: str) -> str | None:
    if mode == "NOT_CONNECTED":
        return "Provider not connected. No live quotes shown."
    if mode == "DEBUG_DEMO":
        return "Demo data — provider not connected."
    return None


@router.get("/provider-status", response_model=ProviderStatusOut)
def provider_status():
    mode = settings.provider_mode_public()
    return ProviderStatusOut(
        provider_mode=mode,
        backend_mode=settings.resolved_backend_mode(),
        message=_message(mode),
    )

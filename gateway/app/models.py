"""Pydantic v2 request/response models and enums."""
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ProviderEnum(str, Enum):
    claude = "claude"
    openai = "openai"
    gemini = "gemini"
    mock = "mock"


class ModeEnum(str, Enum):
    companion = "companion"
    help = "help"
    compile = "compile"
    debug = "debug"


class TaskTypeEnum(str, Enum):
    chat = "chat"
    spec = "spec"
    contract = "contract"
    code = "code"
    summary = "summary"


# --- Chat ---
class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    context: Optional[dict[str, Any]] = None
    provider: Optional[ProviderEnum] = None
    mode: Optional[ModeEnum] = None
    task_type: Optional[TaskTypeEnum] = None


class ChatResponse(BaseModel):
    reply: str
    provider: str = "mock"
    selected_provider: Optional[str] = None
    provider_fallback: Optional[bool] = None


# --- TTS ---
class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1)
    lang: str = "zh"
    voice: str = "default"
    provider: Optional[ProviderEnum] = None


class TTSResponse(BaseModel):
    status: str = "ok"
    note: Optional[str] = None
    selected_provider: Optional[str] = None
    provider_fallback: Optional[bool] = None


# --- Vision ---
class VisionRequest(BaseModel):
    image_base64: str = Field(..., min_length=1)
    task: str = "med_label_read"
    provider: Optional[ProviderEnum] = None


class VisionResponse(BaseModel):
    summary: str
    parsed: dict[str, Any] = Field(default_factory=dict)
    risk_flags: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    selected_provider: Optional[str] = None
    provider_fallback: Optional[bool] = None

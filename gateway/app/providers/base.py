"""Abstract provider interface: chat, tts, vision."""
from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseChatProvider(ABC):
    @abstractmethod
    def chat(self, prompt: str, context: Optional[dict[str, Any]] = None) -> str:
        pass


class BaseTTSProvider(ABC):
    @abstractmethod
    def tts(self, text: str, lang: str = "zh", voice: str = "default") -> bytes | str:
        """Returns audio bytes or path. May return placeholder."""
        pass


class BaseVisionProvider(ABC):
    @abstractmethod
    def vision(self, image_base64: str, task: str = "med_label_read") -> dict[str, Any]:
        """Returns {summary, parsed, risk_flags, next_steps}."""
        pass

"""Mock providers for chat, tts, vision (no external API)."""
from typing import Any, Optional

from app.providers.base import BaseChatProvider, BaseTTSProvider, BaseVisionProvider


class MockChatProvider(BaseChatProvider):
    def chat(self, prompt: str, context: Optional[dict[str, Any]] = None) -> str:
        prompt_lower = (prompt or "").lower()
        if "hello" in prompt_lower or "你好" in prompt_lower:
            return "你好，这是 mock 回复。如需真实能力请配置对应 API key。"
        if "compile" in prompt_lower or "代码" in prompt_lower:
            return "Mock: 编译/代码类请求建议使用 OpenAI provider。"
        return "Mock 回复：已收到你的输入。请配置 Claude/OpenAI 等以获取真实回复。"


class MockTTSProvider(BaseTTSProvider):
    def tts(self, text: str, lang: str = "zh", voice: str = "default") -> bytes | str:
        return b""


class MockVisionProvider(BaseVisionProvider):
    def vision(self, image_base64: str, task: str = "med_label_read") -> dict[str, Any]:
        return {
            "summary": "Mock 解读：此为示例结果，未做真实图像识别。",
            "parsed": {
                "product_name": "示例产品名",
                "date": "2025-01-01",
                "risk_hint": "仅供演示，非医疗诊断",
            },
            "risk_flags": ["mock_data"],
            "next_steps": ["配置 Gemini 等 vision provider 以获取真实解读", "请勿依赖此结果做医疗决策"],
        }

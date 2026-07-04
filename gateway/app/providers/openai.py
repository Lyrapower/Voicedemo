"""OpenAI provider (chat). Key from OPENAI_API_KEY; missing key triggers failover."""
import os
from typing import Any, Optional

from app.config import PROVIDER_TIMEOUT
from app.providers.base import BaseChatProvider
from app.providers.claude import ProviderError


class OpenAIProvider(BaseChatProvider):
    def chat(self, prompt: str, context: Optional[dict[str, Any]] = None) -> str:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise ProviderError("OPENAI_API_KEY not set")
        try:
            import urllib.request
            import json
            body = {
                "model": "gpt-4o-mini",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            }
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=PROVIDER_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            choice = (data.get("choices") or [None])[0]
            if not choice:
                return ""
            msg = choice.get("message") or {}
            return msg.get("content", "")
        except Exception as e:
            if "401" in str(e) or "missing" in str(e).lower():
                raise ProviderError(str(e))
            raise

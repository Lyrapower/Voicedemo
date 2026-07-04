"""Claude provider (chat). Key from ANTHROPIC_API_KEY; missing key triggers failover."""
import os
from typing import Any, Optional

from app.config import PROVIDER_TIMEOUT
from app.providers.base import BaseChatProvider


class ProviderError(Exception):
    """Non-retryable or missing-key error; triggers failover."""
    pass


class ClaudeProvider(BaseChatProvider):
    def chat(self, prompt: str, context: Optional[dict[str, Any]] = None) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY not set")
        try:
            import urllib.request
            import json
            body = {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            }
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=PROVIDER_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            for block in data.get("content", []):
                if block.get("type") == "text":
                    return block.get("text", "")
            return ""
        except Exception as e:
            if "401" in str(e) or "missing" in str(e).lower():
                raise ProviderError(str(e))
            raise

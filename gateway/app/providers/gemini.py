"""Gemini provider (vision). Key from GEMINI_API_KEY; missing key triggers failover."""
import os
from typing import Any

from app.config import PROVIDER_TIMEOUT
from app.providers.base import BaseVisionProvider
from app.providers.claude import ProviderError


class GeminiProvider(BaseVisionProvider):
    def vision(self, image_base64: str, task: str = "med_label_read") -> dict[str, Any]:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise ProviderError("GEMINI_API_KEY not set")
        try:
            import urllib.request
            import json
            import base64
            # Strip data URL prefix if present
            raw = image_base64.split(",", 1)[-1] if "," in image_base64 else image_base64
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
            body = {
                "contents": [{
                    "parts": [
                        {"inline_data": {"mime_type": "image/jpeg", "data": raw}},
                        {"text": f"Describe this image for task: {task}. Return a short summary and any text visible."},
                    ]
                }],
                "generationConfig": {"maxOutputTokens": 512},
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=PROVIDER_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            text = ""
            for c in data.get("candidates", []):
                for p in c.get("content", {}).get("parts", []):
                    text += p.get("text", "")
            return {
                "summary": text or "No description",
                "parsed": {},
                "risk_flags": [],
                "next_steps": ["Review Gemini output; do not use for medical decisions."],
            }
        except Exception as e:
            if "401" in str(e) or "missing" in str(e).lower() or "API key" in str(e):
                raise ProviderError(str(e))
            raise

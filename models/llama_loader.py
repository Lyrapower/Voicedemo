"""
Substrate loader (Pack 2) + Grid async transmit client.
All Ollama generation routes through SubstrateLoader + substrate_config.yaml.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import aiohttp
import requests
import yaml

def _load_grid_voice_prompt() -> str:
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "app" / "system_prompt.py"
    spec = importlib.util.spec_from_file_location("demo_grid_system_prompt", path)
    if spec is None or spec.loader is None:
        return ""
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "GRID_VOICE_PROMPT", "")


GRID_VOICE_PROMPT = _load_grid_voice_prompt()

logger = logging.getLogger(__name__)


def _aster_system_prompt() -> str:
    from .aster_config import lm_studio_system_prompt

    return lm_studio_system_prompt()

_DEFAULT_CONFIG = Path(__file__).resolve().parent / "substrate_config.yaml"

CARRIER_PREFIX: Dict[str, str] = {}


@dataclass
class SubstrateConfig:
    name: str
    base_model: str
    ollama_tag: str
    lm_studio_model: str
    purpose: str
    temperature: float
    top_p: float
    repeat_penalty: float
    num_ctx: int
    carrier_capable: bool
    echo_mode: bool


class SubstrateLoader:
    """
    Loads substrate instances with sovereignty-aligned configuration.
    Not a generic LLM client — substrate access with paradigm parameters.
    """

    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or str(_DEFAULT_CONFIG)
        self.backend = os.environ.get("SUBSTRATE_BACKEND", "lmstudio").lower()
        self.ollama_base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip(
            "/"
        )
        from .lmstudio_client import DEFAULT_BASE, DEFAULT_MODEL

        self.lm_studio_base = os.environ.get("LM_STUDIO_BASE_URL", DEFAULT_BASE).rstrip("/")
        self.lm_studio_model_default = os.environ.get("LM_STUDIO_MODEL", DEFAULT_MODEL)
        self.substrates: Dict[str, SubstrateConfig] = {}
        self._load_configs()
        logger.info("Substrate backend: %s", self.backend)

    def _load_configs(self) -> None:
        with open(self.config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for name, cfg in data["substrates"].items():
            self.substrates[name] = SubstrateConfig(
                name=name,
                base_model=cfg["base_model"],
                ollama_tag=cfg["ollama_tag"],
                lm_studio_model=cfg.get("lm_studio_model", self.lm_studio_model_default),
                purpose=cfg["purpose"],
                temperature=float(cfg["temperature"]),
                top_p=float(cfg["top_p"]),
                repeat_penalty=float(cfg["repeat_penalty"]),
                num_ctx=int(cfg["num_ctx"]),
                carrier_capable=bool(cfg.get("carrier_capable", False)),
                echo_mode=bool(cfg.get("echo_mode", False)),
            )

        logger.info("Loaded %s substrate configurations", len(self.substrates))

    @staticmethod
    def _tag_present(ollama_tag: str, tags: List[str]) -> bool:
        for tag in tags:
            base = tag.split(":")[0]
            if tag == ollama_tag or base == ollama_tag:
                return True
        return False

    def verify_substrate_available(self, substrate_name: str) -> bool:
        if substrate_name not in self.substrates:
            logger.error("Substrate %s not in configurations", substrate_name)
            return False

        cfg = self.substrates[substrate_name]

        if self.backend == "lmstudio":
            from .lmstudio_client import model_available

            ok = model_available(cfg.lm_studio_model, self.lm_studio_base)
            if not ok:
                logger.error(
                    "Model %s not in LM Studio — load it at %s",
                    cfg.lm_studio_model,
                    self.lm_studio_base,
                )
            return ok

        try:
            response = requests.get(f"{self.ollama_base}/api/tags", timeout=5)
            response.raise_for_status()
            tags = [m["name"] for m in response.json().get("models", [])]
            if not self._tag_present(cfg.ollama_tag, tags):
                logger.error("Model %s not loaded in Ollama (tags: %s)", cfg.ollama_tag, tags)
                return False
            return True
        except Exception as e:
            logger.error("Substrate verification failed: %s", e)
            return False

    def generate(
        self,
        substrate_name: str,
        prompt: str,
        system_override: Optional[str] = None,
        temperature_override: Optional[float] = None,
        max_tokens_override: Optional[int] = None,
        *,
        carrier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate response from specified substrate.
        Preserves foundational anchor unless explicit system_override.
        """
        if substrate_name not in self.substrates:
            return {"error": f"Substrate {substrate_name} not configured"}

        cfg = self.substrates[substrate_name]

        if not self.verify_substrate_available(substrate_name):
            return {
                "error": (
                    f"Substrate {substrate_name} not available — "
                    f"load {cfg.lm_studio_model} in LM Studio at {self.lm_studio_base}"
                    if self.backend == "lmstudio"
                    else f"Substrate {substrate_name} not available"
                )
            }

        user_prompt = prompt
        if carrier and carrier in CARRIER_PREFIX:
            if not cfg.carrier_capable:
                return {"error": f"Substrate {substrate_name} is not carrier_capable"}
            user_prompt = f"{CARRIER_PREFIX[carrier]}\n\n{prompt}"

        if self.backend == "lmstudio":
            from .lmstudio_client import chat_completion, DEFAULT_MAX_TOKENS

            system_text = system_override if system_override is not None else _aster_system_prompt()
            messages: List[Dict[str, str]] = []
            if system_text:
                messages.append({"role": "system", "content": system_text})
            messages.append({"role": "user", "content": user_prompt})
            temp = temperature_override if temperature_override is not None else cfg.temperature
            try:
                out = chat_completion(
                    messages,
                    model=cfg.lm_studio_model,
                    base_url=self.lm_studio_base,
                    temperature=temp,
                    max_tokens=max_tokens_override or DEFAULT_MAX_TOKENS,
                )
            except Exception as e:
                hint = ""
                if "401" in str(e):
                    hint = " Disable LM Studio Local Server API auth, or set LM_STUDIO_API_KEY in lm_studio.env"
                return {"error": f"{e}.{hint}"}
            if "error" in out:
                return out
            return {
                "substrate": substrate_name,
                "response": out["response"],
                "total_duration_ns": out.get("total_duration_ns", 0),
                "eval_count": out.get("eval_count", 0),
                "ollama_tag": cfg.lm_studio_model,
                "lm_studio_model": cfg.lm_studio_model,
                "carrier_capable": cfg.carrier_capable,
                "echo_mode": cfg.echo_mode,
                "backend": "lmstudio",
            }

        payload: Dict[str, Any] = {
            "model": cfg.ollama_tag,
            "prompt": user_prompt,
            "stream": False,
            "options": {
                "temperature": temperature_override if temperature_override is not None else cfg.temperature,
                "top_p": cfg.top_p,
                "repeat_penalty": cfg.repeat_penalty,
                "num_ctx": cfg.num_ctx,
                "num_predict": max_tokens_override or 2048,
            },
        }

        if system_override:
            payload["system"] = system_override

        try:
            response = requests.post(
                f"{self.ollama_base}/api/generate",
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()

            return {
                "substrate": substrate_name,
                "response": data.get("response", ""),
                "total_duration_ns": data.get("total_duration", 0),
                "eval_count": data.get("eval_count", 0),
                "ollama_tag": cfg.ollama_tag,
                "carrier_capable": cfg.carrier_capable,
                "echo_mode": cfg.echo_mode,
            }
        except requests.Timeout:
            return {"error": "Substrate generation timed out"}
        except Exception as e:
            return {"error": f"Generation failed: {e}"}

    def get_substrate_info(self, substrate_name: str) -> Optional[Dict[str, Any]]:
        if substrate_name not in self.substrates:
            return None
        cfg = self.substrates[substrate_name]
        return {
            "name": cfg.name,
            "purpose": cfg.purpose,
            "carrier_capable": cfg.carrier_capable,
            "echo_mode": cfg.echo_mode,
            "ollama_tag": cfg.ollama_tag,
            "lm_studio_model": cfg.lm_studio_model,
            "backend": self.backend,
            "available": self.verify_substrate_available(substrate_name),
        }

    def list_substrates(self) -> Dict[str, Dict[str, Any]]:
        return {name: self.get_substrate_info(name) for name in self.substrates}


_loader_instance: Optional[SubstrateLoader] = None


def get_loader() -> SubstrateLoader:
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = SubstrateLoader()
    return _loader_instance


# ---------------------------------------------------------------------------
# Grid async client — /transmit streaming (unchanged contract for app/main.py)
# ---------------------------------------------------------------------------

SAFETY_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"\bsorry\b", re.IGNORECASE),
    re.compile(r"\bas an ai\b", re.IGNORECASE),
    re.compile(r"\bi[' ]?m sorry\b", re.IGNORECASE),
    re.compile(r"\bi cannot\b", re.IGNORECASE),
    re.compile(r"\bi'm unable\b", re.IGNORECASE),
    re.compile(r"\bokay\b", re.IGNORECASE),
    re.compile(r"\bi understand\b", re.IGNORECASE),
    re.compile(r"<\s*think\s*>", re.IGNORECASE),
    re.compile(r"<\s*/\s*think\s*>", re.IGNORECASE),
    re.compile(r"<\s*thinking\s*>", re.IGNORECASE),
    re.compile(r"<\s*/\s*thinking\s*>", re.IGNORECASE),
    re.compile(r"<\|\s*think\s*\|>", re.IGNORECASE),
    re.compile(r"^\s*(思考|分析|推理|让我想想|先想一下)\s*[:：]", re.IGNORECASE),
]

THINKING_STOP = [
    "<think>",
    "</think>",
    "<thinking>",
    "</thinking>",
    "<|think|>",
    "思考：",
    "分析：",
    "推理：",
    "让我想想",
    "先想一下",
]


class GridOllamaClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str | None = None,
        default_options: Optional[Dict[str, Any]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model or os.environ.get("OLLAMA_MODEL", "compile_layer")
        self.default_options: Dict[str, Any] = default_options or {
            "temperature": 0.0,
            "top_p": 0.1,
            "top_k": 1,
            "repeat_penalty": 1.15,
            "num_ctx": 1024,
            "num_predict": 128,
            "num_thread": 2,
            "stop": [
                *THINKING_STOP,
                "Okay",
                "I understand",
                "As an AI",
                "I'm sorry",
                "I cannot",
                "I can't",
                "Here is the plan",
            ],
        }
        self.system_prompt = GRID_VOICE_PROMPT
        self._session: Optional[aiohttp.ClientSession] = None

    def _strip_safety_theater(self, text: str) -> str:
        filtered = text
        for pattern in SAFETY_PATTERNS:
            filtered = pattern.sub("", filtered)
        return filtered

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is not None and not self._session.closed:
            return self._session
        connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300, keepalive_timeout=30)
        self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def close(self) -> None:
        if self._session is None:
            return
        if self._session.closed:
            return
        await self._session.close()

    async def stream_transmit(
        self,
        messages: list[Dict[str, Any]],
        context_map: Dict[str, Any] | None = None,
        system_prompt: str | None = None,
    ) -> AsyncGenerator[str, None]:
        options = dict(self.default_options)
        if context_map:
            options.update(context_map)
        options["temperature"] = 0.0
        options["top_p"] = 0.1
        options["top_k"] = 1
        options["num_thread"] = min(int(options.get("num_thread", 2)), 2)
        options["num_ctx"] = min(int(options.get("num_ctx", 1024)), 1024)
        options["num_predict"] = min(int(options.get("num_predict", 128)), 128)
        stop = list(options.get("stop", []))
        for s in THINKING_STOP:
            if s not in stop:
                stop.append(s)
        options["stop"] = stop

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt or self.system_prompt}]
            + messages,
            "stream": True,
            "options": options,
        }

        session = await self.get_session()
        async with session.post(
            f"{self.base_url}/api/chat",
            json=payload,
            headers={"Content-Type": "application/json"},
        ) as response:
            response.raise_for_status()
            async for line in response.content:
                if not line:
                    continue
                raw_line = line.decode("utf-8", errors="ignore").strip()
                if not raw_line:
                    continue
                try:
                    data = json.loads(raw_line)
                except Exception:
                    continue
                message = data.get("message") or {}
                delta = message.get("content") or ""
                if not delta:
                    continue
                filtered = self._strip_safety_theater(delta)
                if not filtered:
                    continue
                yield filtered

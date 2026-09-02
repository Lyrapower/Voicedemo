from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import hashlib
import json
import os

import httpx

from .config import Config, MemoryDomainConfig


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    content: str
    created_at: float | None = None
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MemoryLayerResult:
    content: str
    records: list[MemoryRecord]
    source_ok: bool
    error: str | None = None


class MemoryDomain:
    """
    Read adapter for one already-existing memory domain.

    V1.2 deliberately does not merge local + cloud memory. The worker's
    configured context profile selects exactly one domain.

    Expected HTTP contract (normalization is tolerant):

      GET stable_core_path?subject_id=aster
        -> {"content":"..."} OR {"text":"..."} OR a record object

      GET active_state_path?subject_id=aster
        -> {"content":"..."} OR {"state":{...}} OR a record object

      POST recall_path
        {"subject_id":"aster","query":"...","top_k":12}
        -> {"items":[...]} OR {"records":[...]} OR [...]

    A record may use:
      memory_id | id
      content | text
      created_at
      source
      metadata

    If your existing endpoints differ, change this adapter once. Do not create
    per-agent memory clients.
    """

    def __init__(self, name: str, cfg: MemoryDomainConfig, subject_id: str):
        self.name = name
        self.cfg = cfg
        self.subject_id = subject_id
        headers: dict[str, str] = {}
        token = os.getenv(cfg.auth_env, "").strip() if cfg.auth_env else ""
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.AsyncClient(
            base_url=cfg.base_url.rstrip("/"),
            timeout=cfg.timeout_seconds,
            headers=headers,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def stable_core(self) -> MemoryLayerResult:
        if not self.cfg.stable_core_path:
            return MemoryLayerResult("", [], True)
        try:
            r = await self.client.get(
                self.cfg.stable_core_path,
                params={"subject_id": self.subject_id},
            )
            r.raise_for_status()
            record = self._single_record(r.json(), fallback_id=f"{self.name}:stable_core")
            return MemoryLayerResult(record.content, [record], True)
        except Exception as e:
            return self._failure("stable_core", e)

    async def active_state(self) -> MemoryLayerResult:
        if not self.cfg.active_state_path:
            return MemoryLayerResult("", [], True)
        try:
            r = await self.client.get(
                self.cfg.active_state_path,
                params={"subject_id": self.subject_id},
            )
            r.raise_for_status()
            payload = r.json()
            if isinstance(payload, dict) and "state" in payload and not any(
                k in payload for k in ("content", "text")
            ):
                content = json.dumps(payload["state"], ensure_ascii=False, sort_keys=True)
                record = MemoryRecord(
                    memory_id=str(payload.get("memory_id") or payload.get("id") or f"{self.name}:active_state"),
                    content=content,
                    created_at=self._float_or_none(payload.get("created_at")),
                    source=str(payload.get("source") or self.name),
                    metadata=dict(payload.get("metadata") or {}),
                )
            else:
                record = self._single_record(payload, fallback_id=f"{self.name}:active_state")
            return MemoryLayerResult(record.content, [record], True)
        except Exception as e:
            return self._failure("active_state", e)

    async def recall(self, query: str, top_k: int) -> MemoryLayerResult:
        if not self.cfg.recall_path or not query.strip() or top_k <= 0:
            return MemoryLayerResult("", [], True)
        try:
            r = await self.client.post(
                self.cfg.recall_path,
                json={
                    "subject_id": self.subject_id,
                    "query": query,
                    "top_k": top_k,
                },
            )
            r.raise_for_status()
            records = self._records(r.json())
            content = "\n\n".join(
                f"[memory_id={x.memory_id} source={x.source or self.name}]\n{x.content}"
                for x in records
                if x.content
            )
            return MemoryLayerResult(content, records, True)
        except Exception as e:
            return self._failure("recall", e)

    async def write_turn(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        source_surface: str,
        worker: str,
    ) -> dict[str, Any]:
        """
        Optional external write-through.

        gateway_owned: 8501 / your existing path already persists memory.
        external: POST write_path exactly once from the harness.
        none: operational thread remains durable locally, no external write.
        """
        if self.cfg.write_mode != "external":
            return {
                "attempted": False,
                "mode": self.cfg.write_mode,
                "domain": self.name,
            }
        payload = {
            "subject_id": self.subject_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "source_surface": source_surface,
            "worker": worker,
        }
        try:
            r = await self.client.post(self.cfg.write_path, json=payload)
            r.raise_for_status()
            data = r.json() if r.content else {}
            return {
                "attempted": True,
                "ok": True,
                "mode": "external",
                "domain": self.name,
                "receipt": data,
            }
        except Exception as e:
            if self.cfg.required:
                raise
            return {
                "attempted": True,
                "ok": False,
                "mode": "external",
                "domain": self.name,
                "error": repr(e),
            }

    def _failure(self, layer: str, exc: Exception) -> MemoryLayerResult:
        if self.cfg.required:
            raise RuntimeError(f"{self.name} memory {layer} failed") from exc
        return MemoryLayerResult(
            content="",
            records=[],
            source_ok=False,
            error=repr(exc),
        )

    def _single_record(self, payload: Any, fallback_id: str) -> MemoryRecord:
        if isinstance(payload, str):
            return MemoryRecord(fallback_id, payload, source=self.name)
        if not isinstance(payload, dict):
            return MemoryRecord(
                fallback_id,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                source=self.name,
            )
        content = payload.get("content")
        if content is None:
            content = payload.get("text")
        if content is None:
            content = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return MemoryRecord(
            memory_id=str(payload.get("memory_id") or payload.get("id") or fallback_id),
            content=str(content),
            created_at=self._float_or_none(payload.get("created_at")),
            source=str(payload.get("source") or self.name),
            metadata=dict(payload.get("metadata") or {}),
        )

    def _records(self, payload: Any) -> list[MemoryRecord]:
        if isinstance(payload, dict):
            items = payload.get("items")
            if items is None:
                items = payload.get("records")
            if items is None:
                items = payload.get("memories")
            if items is None:
                items = [payload]
        elif isinstance(payload, list):
            items = payload
        else:
            items = [payload]

        out: list[MemoryRecord] = []
        for i, item in enumerate(items):
            if isinstance(item, str):
                out.append(MemoryRecord(f"{self.name}:recall:{i}", item, source=self.name))
                continue
            if not isinstance(item, dict):
                out.append(
                    MemoryRecord(
                        f"{self.name}:recall:{i}",
                        json.dumps(item, ensure_ascii=False, sort_keys=True),
                        source=self.name,
                    )
                )
                continue
            content = item.get("content")
            if content is None:
                content = item.get("text")
            if content is None:
                continue
            out.append(
                MemoryRecord(
                    memory_id=str(item.get("memory_id") or item.get("id") or f"{self.name}:recall:{i}"),
                    content=str(content),
                    created_at=self._float_or_none(item.get("created_at")),
                    source=str(item.get("source") or self.name),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return out

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None


class MemoryRouter:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.domains = {
            "local": MemoryDomain("local", cfg.memory.local, cfg.memory.subject_id),
            "cloud": MemoryDomain("cloud", cfg.memory.cloud, cfg.memory.subject_id),
        }

    def for_worker(self, worker: str) -> MemoryDomain:
        profile = self.cfg.context.profile(worker)
        domain = profile.memory_domain
        if domain not in self.domains:
            raise ValueError(f"unknown memory domain {domain!r} for worker {worker}")
        return self.domains[domain]

    async def close(self) -> None:
        for domain in self.domains.values():
            await domain.close()

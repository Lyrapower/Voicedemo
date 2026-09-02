from __future__ import annotations

from dataclasses import dataclass
import asyncio
from typing import Any
import hashlib
import json

from .config import Config, ContextProfileConfig
from .db import Store
from .memory_adapter import MemoryRouter, MemoryLayerResult, MemoryRecord


class ContextBudgetError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextLayer:
    name: str
    content: str
    estimated_tokens: int
    memory_ids: list[str]
    source_ok: bool = True
    error: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class ContextPack:
    worker: str
    memory_domain: str
    session_domain: str | None
    cross_domain_handoff: bool
    owner_mode: str
    stable_core: ContextLayer
    active_state: ContextLayer
    recent_turns: list[dict[str, str]]
    recent_turns_tokens: int
    recall: ContextLayer
    current_turn: str
    estimated_input_tokens: int
    max_context_tokens: int
    reserve_output_tokens: int
    framing_reserve_tokens: int
    context_hash: str

    def receipt(self) -> dict[str, Any]:
        return {
            "worker": self.worker,
            "memory_domain": self.memory_domain,
            "session_domain": self.session_domain,
            "cross_domain_handoff": self.cross_domain_handoff,
            "context_owner": self.owner_mode,
            "context_hash": self.context_hash,
            "estimated_input_tokens": self.estimated_input_tokens,
            "max_context_tokens": self.max_context_tokens,
            "reserve_output_tokens": self.reserve_output_tokens,
            "framing_reserve_tokens": self.framing_reserve_tokens,
            "layers": {
                "stable_core": {
                    "tokens": self.stable_core.estimated_tokens,
                    "memory_ids": self.stable_core.memory_ids,
                    "source_ok": self.stable_core.source_ok,
                    "error": self.stable_core.error,
                    "truncated": self.stable_core.truncated,
                },
                "active_state": {
                    "tokens": self.active_state.estimated_tokens,
                    "memory_ids": self.active_state.memory_ids,
                    "source_ok": self.active_state.source_ok,
                    "error": self.active_state.error,
                    "truncated": self.active_state.truncated,
                },
                "recent_turns": {
                    "tokens": self.recent_turns_tokens,
                    "turns": len(self.recent_turns),
                },
                "recall": {
                    "tokens": self.recall.estimated_tokens,
                    "memory_ids": self.recall.memory_ids,
                    "source_ok": self.recall.source_ok,
                    "error": self.recall.error,
                    "truncated": self.recall.truncated,
                },
                "current_turn": {
                    "tokens": estimate_tokens(self.current_turn),
                },
            },
            "external_memory_injected": self.owner_mode == "harness",
            "shadow_only": self.owner_mode == "shadow",
        }

    def to_messages(self, system_prompt: str) -> list[dict[str, str]]:
        """
        Build one canonical model context.

        gateway:
          System + current turn only. Gateway remains context owner.

        shadow:
          Preserve V1.1 recent-thread continuity, build four layers for receipts,
          but do not inject stable/active/recall yet.

        harness:
          Inject all four layers, then current turn.
        """
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

        if self.owner_mode == "gateway":
            messages.append({"role": "user", "content": self.current_turn})
            return messages

        if self.owner_mode == "harness":
            if self.stable_core.content:
                messages.append({
                    "role": "system",
                    "content": f"[STABLE_CORE domain={self.memory_domain}]\n{self.stable_core.content}",
                })
            if self.active_state.content:
                messages.append({
                    "role": "system",
                    "content": f"[ACTIVE_STATE domain={self.memory_domain}]\n{self.active_state.content}",
                })

        messages.extend(self.recent_turns)

        if self.owner_mode == "harness" and self.recall.content:
            messages.append({
                "role": "system",
                "content": f"[RELEVANT_RECALL domain={self.memory_domain}]\n{self.recall.content}",
            })

        messages.append({"role": "user", "content": self.current_turn})
        return messages

    def to_cc_markdown(self) -> str:
        """
        Context file for Claude Code. Same owner semantics as model messages.
        """
        parts = [
            "# Grid Context Pack",
            "",
            f"- worker: {self.worker}",
            f"- memory_domain: {self.memory_domain}",
            f"- context_owner: {self.owner_mode}",
            f"- context_hash: {self.context_hash}",
            "",
        ]
        if self.owner_mode == "harness":
            parts += ["## STABLE_CORE", "", self.stable_core.content or "(empty)", ""]
            parts += ["## ACTIVE_STATE", "", self.active_state.content or "(empty)", ""]
        if self.owner_mode != "gateway":
            parts += ["## RECENT_TURNS", ""]
            for m in self.recent_turns:
                parts += [f"### {m['role']}", "", m["content"], ""]
        if self.owner_mode == "harness":
            parts += ["## RELEVANT_RECALL", "", self.recall.content or "(empty)", ""]
        parts += ["## CURRENT_TURN", "", self.current_turn, ""]
        return "\n".join(parts)


def estimate_tokens(text: str) -> int:
    """
    Conservative tokenizer-independent upper bound.

    UTF-8 byte count is used as a deliberately conservative upper bound for
    byte/subword tokenizers. It overestimates normal English and CJK text, but
    avoids pretending a tokenizer-independent exact count exists.

    Route-specific tokenizers can replace this later without changing context
    ownership or layer semantics.
    """
    return len((text or "").encode("utf-8"))


def _truncate_utf8_bytes(text: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    raw=text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    clipped=raw[:max_bytes]
    while clipped:
        try:
            return clipped.decode("utf-8")
        except UnicodeDecodeError as e:
            clipped=clipped[:e.start]
    return ""


def _hash_obj(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _required_layer(
    name: str,
    result: MemoryLayerResult,
    budget: int,
) -> ContextLayer:
    tokens = estimate_tokens(result.content)
    if tokens > budget:
        raise ContextBudgetError(
            f"{name} requires {tokens} estimated tokens but budget is {budget}; "
            "hard layers are never silently truncated"
        )
    return ContextLayer(
        name=name,
        content=result.content,
        estimated_tokens=tokens,
        memory_ids=[r.memory_id for r in result.records],
        source_ok=result.source_ok,
        error=result.error,
        truncated=False,
    )


def _fit_recall(
    result: MemoryLayerResult,
    budget: int,
) -> ContextLayer:
    if budget <= 0 or not result.records:
        return ContextLayer(
            name="recall",
            content="",
            estimated_tokens=0,
            memory_ids=[],
            source_ok=result.source_ok,
            error=result.error,
        )

    chunks: list[str] = []
    ids: list[str] = []
    truncated = False

    for record in result.records:
        prefix = f"[memory_id={record.memory_id} source={record.source}]\n"
        separator = "\n\n" if chunks else ""
        existing = separator.join(chunks)
        used = estimate_tokens(existing)
        sep_cost = estimate_tokens(separator)
        remaining = budget - used - sep_cost
        if remaining <= estimate_tokens(prefix):
            truncated = True
            break

        full = prefix + record.content
        need = estimate_tokens(full)
        if need <= remaining:
            chunks.append(full)
            ids.append(record.memory_id)
            continue

        trunc_marker = "\n[TRUNCATED]"
        room = max(
            0,
            remaining
            - estimate_tokens(prefix)
            - estimate_tokens(trunc_marker),
        )
        if room > 0:
            clipped = _truncate_utf8_bytes(record.content, room)
            chunks.append(prefix + clipped + trunc_marker)
            ids.append(record.memory_id)
        truncated = True
        break

    content = "\n\n".join(chunks)
    if estimate_tokens(content) > budget:
        raise AssertionError("recall fitter exceeded configured byte/token upper-bound budget")
    return ContextLayer(
        name="recall",
        content=content,
        estimated_tokens=estimate_tokens(content),
        memory_ids=ids,
        source_ok=result.source_ok,
        error=result.error,
        truncated=truncated,
    )

def _fit_recent(
    messages: list[dict[str, Any]],
    current_turn: str,
    budget: int,
    cap: int,
) -> tuple[list[dict[str, str]], int]:
    """
    Keep the newest contiguous turns. The current turn is excluded here and
    appended once at the end of the context.
    """
    cleaned: list[dict[str, str]] = []
    for m in messages[-cap:]:
        role = str(m.get("role", ""))
        content = str(m.get("content", ""))
        if role not in {"user", "assistant"} or not content:
            continue
        cleaned.append({"role": role, "content": content})

    # The job goal/current turn is already persisted as the newest user message.
    if cleaned and cleaned[-1]["role"] == "user" and cleaned[-1]["content"] == current_turn:
        cleaned = cleaned[:-1]

    selected_rev: list[dict[str, str]] = []
    used = 0
    for m in reversed(cleaned):
        cost = estimate_tokens(m["content"]) + 8  # conservative role framing
        if used + cost > budget:
            break
        selected_rev.append(m)
        used += cost
    selected = list(reversed(selected_rev))
    return selected, used


class ContextAssembler:
    def __init__(self, cfg: Config, store: Store, memories: MemoryRouter):
        self.cfg = cfg
        self.store = store
        self.memories = memories

    async def build(
        self,
        *,
        worker: str,
        session_id: str | None,
        current_turn: str,
        job: dict[str, Any] | None = None,
    ) -> ContextPack:
        profile = self.cfg.context.profile(worker)
        memory = self.memories.for_worker(worker)

        stable_result, external_active_result, recall_result = await self._load_external(
            memory=memory,
            query=current_turn,
            top_k=profile.recall_top_k,
        )
        recall_result = self._drop_current_turn_from_recall(recall_result, current_turn)

        operational = self._operational_active_state(
            session_id=session_id,
            job=job,
            target_domain=profile.memory_domain,
        )
        active_result = self._merge_active_state(
            domain=profile.memory_domain,
            external=external_active_result,
            operational=operational,
        )

        stable = _required_layer("stable_core", stable_result, profile.stable_core_tokens)
        active = _required_layer("active_state", active_result, profile.active_state_tokens)

        session_domain = self._session_domain(session_id)
        cross_domain_handoff = bool(
            session_domain
            and session_domain != profile.memory_domain
        )

        history = self.store.list_messages(
            session_id,
            limit=self.cfg.context.recent_turns_cap,
        ) if session_id else []

        if cross_domain_handoff and self.cfg.memory.strict_domain_isolation:
            # A local thread escalating to cloud must not silently export its
            # whole recent conversation. CURRENT_TURN is the explicit handoff.
            recent, recent_tokens = [], 0
        else:
            recent, recent_tokens = _fit_recent(
                history,
                current_turn=current_turn,
                budget=profile.recent_turns_tokens,
                cap=self.cfg.context.recent_turns_cap,
            )
        recall = _fit_recall(recall_result, profile.recall_tokens)

        current_tokens = estimate_tokens(current_turn)
        base_tokens = (
            stable.estimated_tokens
            + active.estimated_tokens
            + recent_tokens
            + recall.estimated_tokens
            + current_tokens
        )

        available = (
            profile.max_context_tokens
            - profile.reserve_output_tokens
            - self.cfg.context.framing_reserve_tokens
        )
        if base_tokens > available:
            # Only supplemental layers are reduced automatically.
            overflow = base_tokens - available

            if recall.estimated_tokens:
                new_budget = max(0, recall.estimated_tokens - overflow)
                recall = _fit_recall(recall_result, new_budget)

            base_tokens = (
                stable.estimated_tokens
                + active.estimated_tokens
                + recent_tokens
                + recall.estimated_tokens
                + current_tokens
            )

            if base_tokens > available and recent:
                allowed_recent = max(
                    0,
                    available
                    - stable.estimated_tokens
                    - active.estimated_tokens
                    - recall.estimated_tokens
                    - current_tokens,
                )
                if cross_domain_handoff and self.cfg.memory.strict_domain_isolation:
                    recent, recent_tokens = [], 0
                else:
                    recent, recent_tokens = _fit_recent(
                        history,
                        current_turn=current_turn,
                        budget=allowed_recent,
                        cap=self.cfg.context.recent_turns_cap,
                    )

            base_tokens = (
                stable.estimated_tokens
                + active.estimated_tokens
                + recent_tokens
                + recall.estimated_tokens
                + current_tokens
            )

        if base_tokens > available:
            raise ContextBudgetError(
                f"context cannot fit worker={worker}: estimated={base_tokens}, available={available}; "
                "STABLE_CORE/ACTIVE_STATE are protected from silent truncation"
            )

        context_hash = _hash_obj({
            "worker": worker,
            "domain": profile.memory_domain,
            "session_domain": session_domain,
            "cross_domain_handoff": cross_domain_handoff,
            "owner": self.cfg.memory.context_owner,
            "stable": stable.content,
            "active": active.content,
            "recent": recent,
            "recall": recall.content,
            "current": current_turn,
        })

        return ContextPack(
            worker=worker,
            memory_domain=profile.memory_domain,
            session_domain=session_domain,
            cross_domain_handoff=cross_domain_handoff,
            owner_mode=self.cfg.memory.context_owner,
            stable_core=stable,
            active_state=active,
            recent_turns=recent,
            recent_turns_tokens=recent_tokens,
            recall=recall,
            current_turn=current_turn,
            estimated_input_tokens=base_tokens,
            max_context_tokens=profile.max_context_tokens,
            reserve_output_tokens=profile.reserve_output_tokens,
            framing_reserve_tokens=self.cfg.context.framing_reserve_tokens,
            context_hash=context_hash,
        )

    async def _load_external(self, *, memory, query: str, top_k: int):
        if not self.cfg.memory.enabled:
            empty = MemoryLayerResult("", [], True)
            return empty, empty, empty

        stable, active, recall = await asyncio.gather(
            memory.stable_core(),
            memory.active_state(),
            memory.recall(query, top_k),
        )
        return stable, active, recall

    def _session_domain(self, session_id: str | None) -> str | None:
        if not session_id:
            return None
        try:
            session=self.store.get_session(session_id)
        except KeyError:
            return None
        agent_id=str(session.get("agent_id") or "")
        if agent_id.startswith(("qwen","cc")):
            return "local"
        if agent_id.startswith(("glm","kimi")):
            return "cloud"
        return None

    def _drop_current_turn_from_recall(
        self,
        result: MemoryLayerResult,
        current_turn: str,
    ) -> MemoryLayerResult:
        if not current_turn:
            return result
        records=[r for r in result.records if r.content.strip()!=current_turn.strip()]
        content="\n\n".join(
            f"[memory_id={r.memory_id} source={r.source}]\n{r.content}"
            for r in records
            if r.content
        )
        return MemoryLayerResult(
            content=content,
            records=records,
            source_ok=result.source_ok,
            error=result.error,
        )

    def _operational_active_state(
        self,
        *,
        session_id: str | None,
        job: dict[str, Any] | None,
        target_domain: str,
    ) -> dict[str, Any]:
        state: dict[str, Any] = {
            "current_goal": job.get("goal") if job else None,
            "job_id": job.get("job_id") if job else None,
            "job_status": job.get("status") if job else None,
            "worker": job.get("worker") if job else None,
            "approval_mode": job.get("approval_mode") if job else None,
            "cloud_allowed": job.get("cloud_allowed") if job else None,
            "open_blocker": None,
            "pending_action": None,
            "last_verified_state": job.get("last_step") if job else None,
        }
        if target_domain == "local":
            state["allowed_tools"] = job.get("allowed_tools") if job else []
            state["allowed_paths"] = job.get("allowed_paths") if job else []
        else:
            # Cloud receives the task contract, not local filesystem topology.
            state["local_capabilities_redacted"] = True
        if session_id:
            try:
                session = self.store.get_session(session_id)
                state.update({
                    "session_id": session_id,
                    "session_state": session.get("state"),
                    "waiting_for": session.get("waiting_for"),
                    "active_job_id": session.get("active_job_id"),
                })
            except KeyError:
                state["session_id"] = session_id
                state["session_state"] = "unknown"
        return state

    def _merge_active_state(
        self,
        *,
        domain: str,
        external: MemoryLayerResult,
        operational: dict[str, Any],
    ) -> MemoryLayerResult:
        payload: dict[str, Any] = {
            "memory_domain": domain,
            "operational_state": operational,
        }
        if external.content:
            payload["existing_memory_active_state"] = external.content

        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        records = list(external.records)
        return MemoryLayerResult(
            content=content,
            records=records,
            source_ok=external.source_ok,
            error=external.error,
        )

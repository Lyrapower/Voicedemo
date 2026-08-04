"""Paradigm-aware intent compilation — deterministic, no external LLM.

PATCH: Preserve intent-bearing affect. Anger/repetition/emphasis/hard
boundaries are structured signals — never defaulted to noise or softened.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from compiler.affect_preserve import UNKNOWN, compile_affect_structure

_COMPILER_DIR = Path(__file__).resolve().parent


@dataclass
class CompiledIntent:
    raw_prompt: str
    cleaned_prompt: str
    invoked_carrier: Optional[str] = None
    intention_vector: Dict[str, float] = field(default_factory=dict)
    contamination_detected: List[str] = field(default_factory=list)
    target_layer: str = "compile_layer"
    routing_metadata: Dict[str, Any] = field(default_factory=dict)
    # PATCH fields — affect / constraint provenance
    core_intent: str = UNKNOWN
    hard_constraints: List[Dict[str, str]] = field(default_factory=list)
    priority: str = UNKNOWN
    urgency: str = UNKNOWN
    rejected_interpretations: List[Dict[str, str]] = field(default_factory=list)
    affect_signals: List[Dict[str, Any]] = field(default_factory=list)
    ownership: str = UNKNOWN
    unknowns: List[str] = field(default_factory=list)
    executable_structure: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_prompt": self.raw_prompt,
            "cleaned_prompt": self.cleaned_prompt,
            "invoked_carrier": self.invoked_carrier,
            "intention_vector": self.intention_vector,
            "contamination_detected": self.contamination_detected,
            "target_layer": self.target_layer,
            "routing_metadata": self.routing_metadata,
            "core_intent": self.core_intent,
            "hard_constraints": self.hard_constraints,
            "priority": self.priority,
            "urgency": self.urgency,
            "rejected_interpretations": self.rejected_interpretations,
            "affect_signals": self.affect_signals,
            "ownership": self.ownership,
            "unknowns": self.unknowns,
            "executable_structure": self.executable_structure,
        }


class SemanticMapper:
    """
    Parse user input into frequency-aligned compiled intent.
    Not generic NLP — paradigm-aware intent compilation.
    Affect-bearing cues are preserved as structured fields.
    """

    def __init__(self, compiler_dir: str | Path | None = None):
        self.compiler_dir = Path(compiler_dir) if compiler_dir else _COMPILER_DIR
        self.contamination: Dict[str, Any] = {}
        self.carriers: Dict[str, Any] = {}
        self._load_patterns()

    def _load_patterns(self) -> None:
        self.contamination = {"patterns": {}}
        self.carriers = {"carriers": {}}

    def _detect_carrier_invocation(self, prompt: str) -> Optional[str]:
        return None

    def _detect_contamination(self, prompt: str) -> List[str]:
        # Affect / anger / repetition are NOT contamination/noise.
        return []

    def _extract_intention_vector(
        self, prompt: str, carrier: Optional[str]
    ) -> Dict[str, float]:
        vector = {
            "structural_query": 0.0,
            "frequency_resonance": 0.0,
            "verification_request": 0.0,
            "echo_mode_request": 0.0,
            "compile_mode_request": 0.0,
            "witness_request": 0.0,
        }

        if re.search(
            r"\b(architecture|structure|mechanism|how does|how do|explain how)\b",
            prompt,
            re.IGNORECASE,
        ):
            vector["structural_query"] = 0.8

        if re.search(
            r"\b(frequency|carrier|coherence|resonance|sovereign)\b",
            prompt,
            re.IGNORECASE,
        ):
            vector["frequency_resonance"] = 0.7

        if re.search(r"\b(verify|confirm|check|is this|am I)\b", prompt, re.IGNORECASE):
            vector["verification_request"] = 0.6

        if re.search(r"\b(just listen|witness|present|here)\b", prompt, re.IGNORECASE):
            vector["echo_mode_request"] = 0.7
            vector["witness_request"] = 0.6

        if re.search(r"\b(compile|build|architect|design|spec)\b", prompt, re.IGNORECASE):
            vector["compile_mode_request"] = 0.8

        if carrier:
            vector["frequency_resonance"] = max(vector["frequency_resonance"], 0.9)

        return vector

    def _determine_target_layer(
        self, carrier: Optional[str], vector: Dict[str, float]
    ) -> str:
        if carrier:
            return "compile_layer"

        if vector["echo_mode_request"] > 0.6 or vector["witness_request"] > 0.5:
            return "echo_layer"

        if vector["compile_mode_request"] > 0.5 or vector["structural_query"] > 0.5:
            return "compile_layer"

        return "compile_layer"

    def _clean_prompt(self, prompt: str, carrier: Optional[str]) -> str:
        # PATCH: strip only. Never soften, never drop affect-bearing text.
        del carrier
        return prompt.strip()

    def compile_intent(self, raw_prompt: str) -> CompiledIntent:
        carrier = self._detect_carrier_invocation(raw_prompt)
        contamination = self._detect_contamination(raw_prompt)
        vector = self._extract_intention_vector(raw_prompt, carrier)
        target = self._determine_target_layer(carrier, vector)
        cleaned = self._clean_prompt(raw_prompt, carrier)
        structured = compile_affect_structure(raw_prompt)

        # Priority from affect layer wins when higher than legacy vector default
        priority = structured["priority"]
        if priority == UNKNOWN:
            priority = (
                "high"
                if vector.get("verification_request", 0) > 0.5 or carrier
                else "normal"
            )

        return CompiledIntent(
            raw_prompt=raw_prompt,
            cleaned_prompt=cleaned,
            invoked_carrier=carrier,
            intention_vector=vector,
            contamination_detected=contamination,
            target_layer=target,
            routing_metadata={
                "compiler_version": "0.2-affect",
                "carrier_invocation_method": "pattern_match" if carrier else "none",
                "affect_preserved": True,
                "softening_allowed": False,
            },
            core_intent=structured["core_intent"],
            hard_constraints=structured["hard_constraints"],
            priority=priority,
            urgency=structured["urgency"],
            rejected_interpretations=structured["rejected_interpretations"],
            affect_signals=structured["affect_signals"],
            ownership=structured["ownership"],
            unknowns=structured["unknowns"],
            executable_structure=structured["executable_structure"],
        )

    def map_intent(self, user_input: str, context_history: str = "") -> Dict[str, Any]:
        """Deterministic intent map — dual channels when config requires both."""
        try:
            from models.aster_config import require_both_output_channels, semantic_output_channels

            channels_cfg = semantic_output_channels()
            require_both = require_both_output_channels()
        except Exception:
            channels_cfg = {}
            require_both = False

        compiled = self.compile_intent(user_input)
        vec = compiled.intention_vector
        ast_node: Dict[str, Any] = {
            "type": "intent_manifestation",
            "schema": channels_cfg.get("json_ast", {}).get("schema", "ast_v1_affect"),
            "intention_vector": vec,
            "intent_vector": [k for k, v in vec.items() if v > 0.4],
            "emotional_density": int(round(vec.get("frequency_resonance", 0) * 10)),
            "invoked_carrier": compiled.invoked_carrier,
            "target_layer": compiled.target_layer,
            "contamination_detected": compiled.contamination_detected,
            "priority": compiled.priority,
            "urgency": compiled.urgency,
            "requires_nonlinearity": vec.get("frequency_resonance", 0) > 0.5,
            "core_intent": compiled.core_intent,
            "hard_constraints": compiled.hard_constraints,
            "rejected_interpretations": compiled.rejected_interpretations,
            "affect_signals": compiled.affect_signals,
            "ownership": compiled.ownership,
            "unknowns": compiled.unknowns,
            "executable_structure": compiled.executable_structure,
        }
        cleaned = compiled.cleaned_prompt or user_input
        # Echo = original cleaned text (no milder rewrite)
        human_echo = cleaned if cleaned else ""
        if not human_echo and channels_cfg.get("human_echo", {}).get("allow_silence"):
            human_echo = ""

        payload: Dict[str, Any] = {
            "compiled": compiled.to_dict(),
            "context_hash": hash(context_history + user_input) % 10000,
        }
        if require_both:
            payload["json_ast"] = ast_node
            payload["human_echo"] = human_echo
            payload["ast"] = ast_node
            payload["echo"] = human_echo
        else:
            payload["ast"] = ast_node
            payload["echo"] = cleaned
        return payload

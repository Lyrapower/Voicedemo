"""Intent AST bridge — Pack 3 SemanticMapper (deterministic)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from compiler.semantic_mapper import SemanticMapper  # noqa: E402

_mapper = SemanticMapper()


def map_intent_ast(message: str, context_history: str = "") -> Dict[str, Any]:
    compiled = _mapper.compile_intent(message)
    mapped = _mapper.map_intent(message, context_history)
    ast = mapped.get("ast") or {}
    return {
        "intent_ast": {
            "type": "compiled_intent",
            **compiled.to_dict(),
            "legacy_ast": ast,
        },
        "context_hash": mapped.get("context_hash"),
        "ast_hash": hash(str(compiled.to_dict())) % 10_000_000,
        "target_layer": compiled.target_layer,
        "invoked_carrier": compiled.invoked_carrier,
    }

"""Canonical offpool_coach payload schema — single authority for trial pipeline."""
from __future__ import annotations

from typing import Any, Literal, TypedDict

SCHEMA_VERSION = "1.1"

Window = Literal["PREMARKET", "EXECUTION"]

# --- Semantics (frozen; do not leave ambiguous) ---
#
# chain_summary[].kill_rules — INFORMATIONAL ONLY.
#   Tags from scan rejection log: why THAT leg failed BFS filters at scan time.
#   Legs remain visible so Fable sees wounds; presence in chain_summary is NOT re-gating.
#   Coach stage1 gates (momentum/liquidity/staleness) apply separately at ticker level.
#
#   Correct usage (reference: 2026-07-16 PREMARKET run):
#     • ONTO — cite gamma/delta kill tags as scan wounds on specific legs; explain
#       wounded geometry; do NOT treat kill_rules absence on another leg as "clean pass"
#       for liquidity or IV.
#     • GEV — best leg primary_kill=delta (e.g. 0.5046 vs threshold 0.5) is an edge wipe
#       / wounded-leg label from scan; NOT a coach veto. Score direction and premium
#       separately; mention delta tag in thesis or node_inferred only as informational.
#
#   Wrong usage:
#     • "kill_rules empty ⇒ leg cleared coach gates"
#     • Using kill_rules to override iv_scan_veto or oi_unverified / structure caps
#
# iv_context.iv_scan_veto — SCORING VETO (not a stage1 hard drop).
#   When True, Fable iv_environment must be 0, grade max C, thesis states premium too rich.
#   Stage4 enforces: S/A forbidden if iv_scan_veto.
#
# liquidity_context.oi_unverified — BLIND ZONE DECLARATION.
#   When True, OI was unavailable (null ≠ pass). Liquidity gate used spread_pct only.
#   Fable scores.liquidity MUST be ≤4 (hard cap); node_inferred MUST include
#   "oi_unverified blind zone". Stage4 rejects liquidity > 4.
#
# structure_context.structure_anchor_missing — STRUCTURE BLIND ZONE (PREMARKET v0).
#   When True, levels and atr14 are not wired. scores.structure MUST be null OR ≤3.
#   node_inferred MUST include "structure_anchor_missing". Subjective structure
#   impressions above 3 without anchors are treated as fabrication-adjacent.


class QuoteFreshness(TypedDict, total=False):
    scan_time: str
    scan_id: str
    quote_source: str
    oi_source: str
    staleness_policy: str
    age_minutes: float | None


class ChainLeg(TypedDict, total=False):
    strike: float
    type: str
    exp: str
    bid: float
    ask: float
    mid: float
    delta: float
    iv: float
    spread_pct: float
    volume: int
    open_interest: int | None
    oi_available: bool
    quote_stale: bool
    # INFORMATIONAL: scan kill tags on this leg; not re-applied as coach gate.
    kill_rules: list[str]
    asof: str


class LiquidityContext(TypedDict, total=False):
    spread_pct: float
    oi_available: bool
    oi_unverified: bool
    open_interest: int | None
    oi_source: str
    gate_mode: str
    score_cap: int
    note: str


class StructureContext(TypedDict, total=False):
    levels_available: bool
    atr14_available: bool
    structure_anchor_missing: bool
    score_cap: int | None
    note: str


class IvContext(TypedDict, total=False):
    iv: float
    iv_pct: float
    iv_unit: str
    iv_source: str
    scan_max_iv: float
    scan_max_iv_pct: float
    iv_scan_veto: bool
    scan_kill_rule: str | None
    path_verified: str
    note: str


class Levels(TypedDict, total=False):
    or_high: float | None
    or_low: float | None
    pdh: float | None
    pdl: float | None
    vwap: float | None
    note: str


class Candidate(TypedDict, total=False):
    ticker: str
    why_surfaced: str
    best_score: float
    quote: dict[str, Any]
    quote_freshness: QuoteFreshness
    levels: Levels | None
    atr14: float | None
    structure_context: StructureContext
    iv_context: IvContext
    liquidity_context: LiquidityContext
    chain_summary: list[ChainLeg]
    event_lane: bool
    gate_pass: list[str]
    gate_reject: list[str]


class Payload(TypedDict, total=False):
    schema_version: str
    window: Window
    generated_at: str
    trade_date: str
    scan_provenance: dict[str, Any]
    market_context: dict[str, Any]
    candidates: list[Candidate]
    risk_budget: dict[str, Any]
    builder_notes: list[str]
    schema_semantics: dict[str, str]

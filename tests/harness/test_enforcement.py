"""Fable review 2026-08-26 — enforcement tests (the bundle's three tests asserted docs, not behaviour)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.harness.action_envelope import ActionEnvelope, FactualReceipt, validate_external_receipt
from app.harness import resource_gate, provenance
from app.harness.collaboration import build_collaboration_view


def _env(res, scope="read_only", op="scan", args=None, origin="GRID_LOCAL"):
    return ActionEnvelope(mission_id="m1", action_id="a1", decision_origin=origin, selected_resource=res,
                          operation=op, arguments=args or {}, authorization_scope=scope)


def test_unknown_resource_denied_without_substitute():
    d = resource_gate.gate(_env("bybit_live_perps", "money_moving", "open_long"))
    assert not d.allowed and d.receipt.status == "DENIED" and d.receipt.metadata["substitute"] is None
    assert "not in capability surface" in d.reason


def test_paper_resource_cannot_take_money_scope():
    d = resource_gate.gate(_env("aether_paper", "money_moving", "open_long"))
    assert not d.allowed and "exceeds resource permission paper_only" in d.reason


def test_read_only_allowed():
    d = resource_gate.gate(_env("local_scanner", "read_only", "scan"))
    assert d.allowed


def test_us_denies_offshore_perps_even_with_token():
    surface = {"capabilities": [{"capability_id": "trading.live.perps", "provider": "bybit", "kind": "tool", "permission": "money_moving", "status": "available"}], "model_profiles": []}
    e = _env("bybit", "money_moving", "open_long", {"product": "perp"})
    d = resource_gate.gate(e, jurisdiction="US", authorization_token="m1:a1:humanapproved1234", surface=surface)
    assert not d.allowed and "not available to US persons" in d.reason


def test_money_scope_requires_bound_token():
    surface = {"capabilities": [{"capability_id": "trading.live.spot", "provider": "coinbase", "kind": "tool", "permission": "money_moving", "status": "available"}], "model_profiles": []}
    e = _env("coinbase", "money_moving", "buy", {"product": "spot"})
    assert not resource_gate.gate(e, surface=surface).allowed
    assert not resource_gate.gate(e, surface=surface, authorization_token="m9:a9:humanapproved1234").allowed
    assert resource_gate.gate(e, surface=surface, authorization_token="m1:a1:humanapproved1234").allowed


def test_receipt_prefix_leak_and_status():
    try:
        FactualReceipt(mission_id="m1", action_id="a1", status="EXECUTED", executed=True, metadata={"next_step": "buy more"}).to_dict()
        raise AssertionError("next_step must be rejected")
    except ValueError:
        pass
    try:
        FactualReceipt(mission_id="m1", action_id="a1", status="DONE", executed=True).to_dict()
        raise AssertionError("unknown status must be rejected")
    except ValueError:
        pass
    try:
        validate_external_receipt({"status": "VERIFIED", "executed": True})
        raise AssertionError("self-claimed VERIFIED must be rejected")
    except ValueError:
        pass


def test_verified_only_via_verifier_and_chain():
    tmp = tempfile.mkdtemp(); os.environ["HARNESS_PROVENANCE_LOG"] = os.path.join(tmp, "prov.jsonl")
    e = _env("local_scanner", "read_only", "scan")
    provenance.record_action(e)
    r = FactualReceipt(mission_id="m1", action_id="a1", status="EXECUTED", executed=True, observed_value=5)
    provenance.record_receipt(r)
    try:
        provenance.record_receipt(FactualReceipt(mission_id="m1", action_id="a1", status="VERIFIED", executed=True))
        raise AssertionError("caller-made VERIFIED must be rejected")
    except ValueError:
        pass
    v = provenance.mark_verified(r, lambda rc: rc.observed_value == 5, "observed_value_eq_5")
    assert v.status == "VERIFIED" and v.metadata["verifier_predicate"] == "observed_value_eq_5"
    bad = provenance.mark_verified(r, lambda rc: rc.observed_value == 6, "observed_value_eq_6")
    assert bad.status == "FAILED_VERIFICATION"
    ev = provenance.read_events("m1")
    assert [x["kind"] for x in ev] == ["action", "receipt", "verify", "verify"] and provenance.verify_chain(ev)
    view = build_collaboration_view(ev)
    assert view["mode"] == "EVENT_DERIVED" and "GRID_LOCAL" in view["actors_observed"] and "VERIFIER" in view["actors_observed"]
    # tamper → chain breaks
    ev[1]["status"] = "VERIFIED"
    assert not provenance.verify_chain(ev)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f(); print("PASS", n)

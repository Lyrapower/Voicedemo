from app.harness.action_envelope import ActionEnvelope, validate_external_receipt
from app.harness.capability_registry import capability_surface


def test_registry_is_map_not_driver():
    surface = capability_surface()
    assert surface["routing_policy"] == "GRID_CHOOSES"
    assert surface["registry_role"] == "MAP_NOT_DRIVER"
    dumped = repr(surface)
    assert "research -> GLM" not in dumped
    assert "code ->" not in dumped


def test_action_origin_cannot_be_harness():
    action = ActionEnvelope(
        mission_id="m1", action_id="a1", decision_origin="HARNESS",
        selected_resource="local_scanner", operation="scan"
    )
    try:
        action.validate()
    except ValueError:
        return
    raise AssertionError("Harness must not originate cognitive next action")


def test_receipt_rejects_strategy_leakage():
    try:
        validate_external_receipt({"status": "FAIL", "next_tool": "glm_5_2"})
    except ValueError:
        return
    raise AssertionError("receipt must reject next-tool advice")

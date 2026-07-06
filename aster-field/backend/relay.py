"""chat 转发的状态派生。derive_event / coherence_proxy 为纯函数,tests/ 直接测。"""

def derive_event(chunk: dict, state: str) -> dict:
    out = {"state": state, "token": None, "reasoning": False,
           "finish": None, "served_by": chunk.get("served_by")}
    ch = (chunk.get("choices") or [{}])[0]
    delta = ch.get("delta") or {}
    out["finish"] = ch.get("finish_reason")
    out["contract_flag"] = chunk.get("contract_flag")
    if delta.get("tool_calls") and state != "working":
        out["state"] = "working"
    if delta.get("reasoning_content") and out["state"] == "thinking":
        out["reasoning"] = True
    c = delta.get("content")
    if c:
        out["state"] = "output"
        out["token"] = c
    return out

def coherence_proxy(finish, has_text: bool, elapsed_s: float, garden_coh=None) -> float:
    """finish_reason=length is transport truncation, not semantic model failure."""
    if garden_coh is not None:
        return round(max(min(garden_coh, 1.0), 0.05), 2)
    coh = 0.85
    if not has_text:
        coh -= 0.35
    elif finish == "length":
        coh -= 0.05
    if elapsed_s > 60:
        coh -= 0.10
    return round(max(coh, 0.05), 2)

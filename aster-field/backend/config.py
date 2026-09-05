import os
from .task_route import TASK_BUDGETS

CFG = {
    "port": int(os.environ.get("FIELD_PORT", 8790)),
    "gateway": os.environ.get("GRID_GATEWAY", "http://127.0.0.1:8501/v1/chat/completions"),
    "gateway_model": os.environ.get("GRID_MODEL", "demo/aster"),
    "vl_model": os.environ.get("GRID_VL_MODEL", "qwen2.5-vl-3b-instruct"),
    "garden_health": os.environ.get("GARDEN_HEALTH", "http://127.0.0.1:8787/legacy/health"),
    "garden_poll_s": 2.0,
    "max_tokens": TASK_BUDGETS["chat"],
    "task_budgets": dict(TASK_BUDGETS),
    "temperature": 0.7,
    "max_continuations": int(os.environ.get("FIELD_MAX_CONTINUATIONS", "3")),
    "chat_node_id": os.environ.get("FIELD_CHAT_NODE_ID", "field-particle"),
    "memory_epoch_anchor": os.environ.get("FIELD_MEMORY_EPOCH_ANCHOR", "2026-07-16"),
    "dist": os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist"),
}

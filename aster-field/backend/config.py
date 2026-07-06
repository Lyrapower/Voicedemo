import os
from .task_route import TASK_BUDGETS

CFG = {
    "port": int(os.environ.get("FIELD_PORT", 8790)),
    "gateway": os.environ.get("GRID_GATEWAY", "http://127.0.0.1:8501/v1/chat/completions"),
    "gateway_model": os.environ.get("GRID_MODEL", "demo/aster"),
    "garden_health": os.environ.get("GARDEN_HEALTH", "http://127.0.0.1:8787/legacy/health"),
    "garden_poll_s": 2.0,
    "max_tokens": TASK_BUDGETS["chat"],
    "task_budgets": dict(TASK_BUDGETS),
    "temperature": 0.7,
    "max_continuations": int(os.environ.get("FIELD_MAX_CONTINUATIONS", "3")),
    "dist": os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist"),
}

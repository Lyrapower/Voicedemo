"""POST /factory/task — Alpha Factory L1 entry (Grid Router, additive route).

Workshop clients send kind + payload only; prompts and substrate selection stay here.
Does not modify /chat, /compile, or /task/expanded handler bodies.
"""
from __future__ import annotations

import re
from typing import Any

FACTORY_MEMORY_NODE = "alpha-factory"

_CODE_BLOCK = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S | re.I)
_HYPOTHESIS = re.compile(r"(?:假设说明|hypothesis)\s*[：:]\s*(.+?)(?:\n\n|\Z)", re.S | re.I)


def _bars_schema_hint() -> str:
    return (
        "输入 DataFrame 列: ts(int unix), symbol(str), o,h,l,c,v(float)。"
        "index 任意;按 symbol+ts 排序后使用。"
    )


def build_factory_task(kind: str, payload: dict[str, Any], budget_hint: str = "std") -> str:
    kind = (kind or "").strip().lower()
    payload = payload if isinstance(payload, dict) else {}
    depth = {"low": "简洁", "std": "标准", "deep": "详尽"}.get((budget_hint or "std").lower(), "标准")

    if kind == "propose":
        idea = str(payload.get("idea") or "").strip()
        if not idea:
            raise ValueError("payload.idea required for propose")
        return (
            f"【Alpha Factory · 因子提案 · {depth}】\n"
            f"用户想法:{idea}\n\n"
            f"产出要求:\n"
            f"1) 一段「假设说明:」开头的自然语言假设(你的解读职权,不含数值结论)。\n"
            f"2) 一个 ```python 代码块,含标准接口:\n"
            f"   # meta: {{name, hypothesis, universe, cadence, author: grid-extended}}\n"
            f"   def factor(df: pd.DataFrame) -> pd.Series: ...\n"
            f"3) 仅 pandas/numpy;禁止 import requests/urllib/socket/subprocess/os.system。\n"
            f"4) {_bars_schema_hint()}\n"
            f"5) 不要输出 IC/IR/收益等数字——数字由 worker 计算。"
        )

    if kind == "review_explain":
        metrics = payload.get("metrics") or {}
        name = str(payload.get("name") or "factor")
        lines = [f"【Alpha Factory · Grid 解读 · {name}】", "以下指标全部由确定性 worker 计算,请只做文字解读,不要改数字、不要新造数字:"]
        for k, v in metrics.items():
            lines.append(f"- {k}: {v}")
        lines.append("输出以「Grid 解读:」开头,说明因子逻辑与指标含义,禁止给出交易建议。")
        return "\n".join(lines)

    if kind == "fix_error":
        code = str(payload.get("code") or "").strip()
        if not code:
            raise ValueError("payload.code required for fix_error")
        exc_type = str(payload.get("exc_type") or "Error")
        exc_message = str(payload.get("exc_message") or payload.get("error") or "").strip()
        frames = payload.get("traceback_frames") or []
        df_head = str(payload.get("df_head") or "").strip()
        if not exc_message:
            raise ValueError("payload.exc_message required for fix_error")
        tb = "\n".join(str(f) for f in frames[:3])
        head = df_head[:1200] if df_head else "(empty)"
        return (
            f"【Alpha Factory · 修错一轮 · factor() 异常】\n"
            f"异常: {exc_type}: {exc_message}\n\n"
            f"traceback (factor 相关, ≤3帧):\n{tb or '(none)'}\n\n"
            f"df.head() 输入形状参考:\n{head}\n\n"
            f"原代码:\n```python\n{code[:12000]}\n```\n\n"
            f"请输出修正后的完整 ```python 代码块(同样 factor 接口),并简短说明改了什么。"
            f"仍禁止 requests 等越权 import。{_bars_schema_hint()}"
        )

    raise ValueError(f"unknown factory kind: {kind}")


def parse_factory_result(kind: str, final_text: str) -> dict[str, Any]:
    text = (final_text or "").strip()
    out: dict[str, Any] = {"content": text}
    blocks = _CODE_BLOCK.findall(text)
    if blocks:
        out["code"] = blocks[-1].strip()
    m = _HYPOTHESIS.search(text)
    if m:
        out["hypothesis"] = m.group(1).strip()
    elif kind == "review_explain":
        out["grid_explain"] = text
    return out


def map_factory_route(substrate: str) -> str:
    s = (substrate or "").strip().lower()
    if s in ("local", "") or s.startswith("local"):
        return "local"
    return "extended"

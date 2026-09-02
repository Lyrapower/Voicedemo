"""Alpha Factory prompts — shared task text + parse (no Grid orchestration)."""
from __future__ import annotations

import json
import re
from typing import Any

from factory_schema import schema_hint_text, template_comment_block

_CODE_BLOCK = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S | re.I)
_HYPOTHESIS = re.compile(r"(?:假设说明|hypothesis)\s*[：:]\s*(.+?)(?:\n\n|\Z)", re.S | re.I)


def build_factory_task(kind: str, payload: dict[str, Any], budget_hint: str = "std") -> str:
    kind = (kind or "").strip().lower()
    payload = payload if isinstance(payload, dict) else {}
    depth = {"low": "简洁", "std": "标准", "deep": "详尽"}.get((budget_hint or "std").lower(), "标准")
    schema = schema_hint_text()
    template = template_comment_block()

    if kind == "propose":
        idea = str(payload.get("idea") or "").strip()
        if not idea:
            raise ValueError("payload.idea required for propose")
        recent = payload.get("recent_factors") or []
        neg = ""
        if isinstance(recent, list) and recent:
            lines = []
            for item in recent[:40]:
                if not isinstance(item, dict):
                    continue
                n = str(item.get("name") or "").strip()
                s = str(item.get("summary") or "").strip()
                if n:
                    lines.append(f"- {n}: {s}" if s else f"- {n}")
            if lines:
                neg = (
                    "\n\n【近7日已产因子·负面约束·勿复刻同名/同逻辑】\n"
                    + "\n".join(lines)
                    + "\n"
                )
        return (
            f"【Alpha Factory · 因子提案 · {depth}】\n"
            f"用户想法:{idea}\n"
            f"{neg}\n"
            f"产出要求:\n"
            f"1) 一段「假设说明:」开头的自然语言假设(你的解读职权,不含数值结论)。\n"
            f"2) 一个 ```python 代码块,含标准接口:\n"
            f"   {template.replace(chr(10), chr(10) + '   ')}\n"
            f"   def factor(df: pd.DataFrame) -> pd.Series: ...\n"
            f"3) 仅 pandas/numpy;禁止 import requests/urllib/socket/subprocess/os.system。\n"
            f"4) {schema}\n"
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
            f"仍禁止 requests 等越权 import。{schema}"
        )

    if kind == "mutate":
        # QuantaAlpha mutation:定位失败步,只重写失败段,前缀(hypothesis)冻结。
        parent_hyp = str(payload.get("parent_hypothesis") or "").strip()
        parent_code = str(payload.get("parent_code") or "").strip()
        err = str(payload.get("rejection_error") or "").strip()
        detail = payload.get("rejection_detail") or {}
        if not parent_code:
            raise ValueError("payload.parent_code required for mutate")
        detail_txt = json.dumps(detail, ensure_ascii=False)[:1200] if detail else "(none)"
        return (
            f"【Alpha Factory · 进化 · mutation · {depth}】\n"
            f"父 trajectory 的假设(冻结,不得改):\n{parent_hyp or '(无)'}\n\n"
            f"父 trajectory 的因子代码(在沙箱被拒):\n```python\n{parent_code[:12000]}\n```\n\n"
            f"沙箱拒绝原因:\n{err or '(未记录)'}\n"
            f"拒绝细节(AST/runtime 分类):\n{detail_txt}\n\n"
            f"mutation 规则:\n"
            f"1) 保持父假设不变(前缀冻结),只重写导致失败的那段 factor() 代码。\n"
            f"2) 定位失败步(列名错/类型错/越权 import/返回不对齐),针对性修,不要整体推翻重写。\n"
            f"3) 输出「假设说明:」开头的自然语言(可复述父假设,可补一句改了什么),再输出 ```python 代码块。\n"
            f"4) 仅 pandas/numpy;禁止 requests/urllib/socket/subprocess/os.system。\n"
            f"5) {schema}\n"
            f"6) 不要输出 IC/IR/收益等数字——数字由 worker 计算。"
        )

    if kind == "crossover":
        # QuantaAlpha crossover:重组两个高 reward 父的互补段。
        a_hyp = str(payload.get("parent_hypothesis") or "").strip()
        a_code = str(payload.get("parent_code") or "").strip()
        b_hyp = str(payload.get("parent_b_hypothesis") or "").strip()
        b_code = str(payload.get("parent_b_code") or "").strip()
        if not (a_code and b_code):
            raise ValueError("payload.parent_code + parent_b_code required for crossover")
        return (
            f"【Alpha Factory · 进化 · crossover · {depth}】\n"
            f"父 A(高 reward,贡献假设结构):\n假设:{a_hyp or '(无)'}\n```python\n{a_code[:6000]}\n```\n\n"
            f"父 B(高 reward,贡献构造 pattern):\n假设:{b_hyp or '(无)'}\n```python\n{b_code[:6000]}\n```\n\n"
            f"crossover 规则:\n"
            f"1) 合成一个新因子:继承父 A 的假设结构 + 父 B 的构造 pattern(如时间尺度/窗/归一化方式)。\n"
            f"2) 不是简单拼接代码,而是提炼两父的核心机制重组为新假设 + 新 factor()。\n"
            f"3) 输出「假设说明:」开头的自然语言(说明继承自 A 的什么 + B 的什么),再输出 ```python 代码块。\n"
            f"4) 仅 pandas/numpy;禁止 requests/urllib/socket/subprocess/os.system。\n"
            f"5) {schema}\n"
            f"6) 不要输出 IC/IR/收益等数字——数字由 worker 计算。"
        )

    if kind == "direction":
        # bandit 选向后的 fresh propose:给定方向,产新假设+因子。
        direction = str(payload.get("direction") or "").strip()
        examples = payload.get("knowledge_examples") or []
        fewshot = ""
        if isinstance(examples, list) and examples:
            lines = []
            for ex in examples[:3]:
                if not isinstance(ex, dict):
                    continue
                h = str(ex.get("hypothesis") or "").strip()[:120]
                if h:
                    lines.append(f"- {h}")
            if lines:
                fewshot = "\n\n【同方向已验证因子·参考·勿复刻】\n" + "\n".join(lines) + "\n"
        return (
            f"【Alpha Factory · 因子提案 · bandit 方向={direction} · {depth}】\n"
            f"本轮方向:{direction}\n"
            f"请围绕此方向产一个新因子假设 + factor() 代码。{fewshot}\n"
            f"产出要求:\n"
            f"1) 一段「假设说明:」开头的自然语言假设(你的解读职权,不含数值结论)。\n"
            f"2) 一个 ```python 代码块,含标准接口:\n"
            f"   {template.replace(chr(10), chr(10) + '   ')}\n"
            f"   def factor(df: pd.DataFrame) -> pd.Series: ...\n"
            f"3) 仅 pandas/numpy;禁止 import requests/urllib/socket/subprocess/os.system。\n"
            f"4) {schema}\n"
            f"5) 不要输出 IC/IR/收益等数字——数字由 worker 计算。"
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

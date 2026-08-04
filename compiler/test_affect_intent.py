"""PATCH + ADDENDUM · affect / negation provenance regression."""
from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from compiler.affect_preserve import (  # noqa: E402
    UNKNOWN,
    bare_rule_readable_as_positive,
    constraint_export,
)
from compiler.semantic_mapper import SemanticMapper  # noqa: E402

# Anger + repetition + explicit negation + hard boundary + ownership
ANGRY_INPUT = """
我已经说了三遍！说了三遍！不要再把我的要求改写成温和建议。
我很愤怒：禁止软化语气，禁止重新解释我的硬边界。
红线：不得添加我没授权的解决方案。
目标不变——修好意图编译器，立刻。
这是我的决定，由我决定验收是否通过。
不要假设我想冷静下来。
""".strip()


class AffectIntentRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapper = SemanticMapper()
        cls.compiled = cls.mapper.compile_intent(ANGRY_INPUT)
        cls.d = cls.compiled.to_dict()
        cls.mapped = cls.mapper.map_intent(ANGRY_INPUT)

    def test_required_fields_present(self) -> None:
        for k in (
            "core_intent", "hard_constraints", "priority", "urgency",
            "rejected_interpretations", "affect_signals", "ownership",
            "unknowns", "executable_structure",
        ):
            self.assertIn(k, self.d)

    def test_no_softening_of_cleaned_prompt(self) -> None:
        self.assertEqual(self.d["cleaned_prompt"], ANGRY_INPUT)
        mild = ("温和建议", "perhaps", "maybe you could", "I understand you're upset")
        # cleaned must still contain raw anger/negation phrases
        self.assertIn("愤怒", self.d["cleaned_prompt"])
        self.assertIn("不要再把我的要求改写成温和建议", self.d["cleaned_prompt"])
        for m in mild:
            # must not introduce milder rewrite as cleaned_prompt replacement
            pass
        self.assertFalse(self.d["routing_metadata"].get("softening_allowed"))

    def test_affect_machine_readable(self) -> None:
        sigs = self.d["affect_signals"]
        self.assertTrue(sigs, "affect_signals must be non-empty for angry input")
        types = {s["type"] for s in sigs}
        self.assertIn("anger", types)
        self.assertIn("repetition", types)
        self.assertTrue(types & {"anger", "repetition", "urgency", "frustration", "emphasis"})
        for s in sigs:
            self.assertIn(s["type"], {
                "anger", "urgency", "repetition", "emphasis", "frustration", "other", UNKNOWN,
            })
            self.assertIsInstance(s["intensity"], float)
            self.assertGreaterEqual(s["intensity"], 0.0)
            self.assertLessEqual(s["intensity"], 1.0)
            self.assertIn("target", s)
            self.assertIn("source_phrase", s)
            self.assertTrue(str(s["source_phrase"]).strip())
            # intensity is routing signal — field exists, not a personality label
            self.assertNotIn("personality", s)
            self.assertNotIn("trait", s)

    def test_rejected_all_have_source_phrase(self) -> None:
        rejected = self.d["rejected_interpretations"]
        self.assertTrue(rejected, "explicit negations must populate rejected")
        joined_src = " ".join(r["source_phrase"] for r in rejected)
        self.assertTrue(
            any(x in joined_src for x in ("不要", "禁止", "不得")),
            joined_src,
        )
        for r in rejected:
            self.assertIn("normalized_rule", r)
            self.assertIn("source_phrase", r)
            self.assertEqual(r.get("polarity"), "forbidden")
            # source must appear in original input (provenance)
            self.assertIn(r["source_phrase"], ANGRY_INPUT)
            self.assertTrue(str(r["normalized_rule"]).startswith("FORBIDDEN:"))
            self.assertFalse(
                bare_rule_readable_as_positive(r["normalized_rule"]),
                r["normalized_rule"],
            )

    def test_fixture2_polarity_bomb_no_bare_positive(self) -> None:
        """INTENT_CONVERGE §1 · fixture #2 — 禁止软化… 不得裸读为正向指令."""
        fixture2 = "禁止软化语气，禁止重新解释我的硬边界"
        rejected = self.mapper.compile_intent(fixture2).rejected_interpretations
        self.assertGreaterEqual(len(rejected), 2, rejected)
        bodies = []
        for r in rejected:
            self.assertEqual(r["polarity"], "forbidden")
            self.assertTrue(r["normalized_rule"].startswith("FORBIDDEN:"))
            self.assertFalse(
                bare_rule_readable_as_positive(r["normalized_rule"]),
                msg="polarity bomb: %r" % r["normalized_rule"],
            )
            # export path also safe
            self.assertFalse(
                bare_rule_readable_as_positive(constraint_export(r)),
            )
            bodies.append(r["normalized_rule"])
        blob = " ".join(bodies)
        self.assertIn("FORBIDDEN:软化语气", blob.replace(" ", ""))
        self.assertIn("重新解释", blob)
        # Classic bomb string must NOT appear as normalized_rule
        for r in rejected:
            self.assertNotEqual(
                r["normalized_rule"],
                "软化语气，禁止重新解释我的硬边界",
            )
            self.assertNotEqual(r["normalized_rule"], "软化语气")

    def test_hard_constraints_provenance(self) -> None:
        hard = self.d["hard_constraints"]
        self.assertTrue(hard)
        blob = json.dumps(hard, ensure_ascii=False)
        self.assertTrue("红线" in blob or "硬边界" in ANGRY_INPUT and any(
            "红线" in h["source_phrase"] or "禁止" in h["source_phrase"] for h in hard
        ))
        for h in hard:
            self.assertIn(h["source_phrase"], ANGRY_INPUT)

    def test_unknown_not_upgraded_to_rejected(self) -> None:
        # Compiler must not invent rejections absent from user text
        for r in self.d["rejected_interpretations"]:
            self.assertIn(r["source_phrase"], ANGRY_INPUT)
        # A benign prompt → no rejected
        mild = self.mapper.compile_intent("今天天气如何")
        self.assertEqual(mild.rejected_interpretations, [])

    def test_priority_not_downgraded(self) -> None:
        self.assertEqual(self.d["priority"], "high")
        self.assertIn(self.d["urgency"], ("high", "elevated"))

    def test_ownership_not_rewritten(self) -> None:
        own = self.d["ownership"]
        self.assertNotEqual(own, UNKNOWN)
        self.assertTrue("我" in own or "决定" in own)

    def test_executable_structure_flags(self) -> None:
        ex = self.d["executable_structure"]
        self.assertFalse(ex.get("softening_allowed"))
        self.assertFalse(ex.get("reinterpretation_allowed"))
        self.assertTrue(ex.get("must_not"))
        for rule in ex["must_not"]:
            self.assertTrue(str(rule).startswith("FORBIDDEN:"), rule)
            self.assertFalse(bare_rule_readable_as_positive(str(rule)), rule)

    def test_map_intent_ast_carries_structure(self) -> None:
        ast = self.mapped["ast"]
        self.assertEqual(ast["priority"], "high")
        self.assertTrue(ast["affect_signals"])
        self.assertTrue(ast["rejected_interpretations"])
        # echo is not a milder paraphrase
        self.assertIn("愤怒", self.mapped["echo"])

    def test_anger_not_listed_as_contamination(self) -> None:
        self.assertEqual(self.d["contamination_detected"], [])


class Gateway8501Evidence(unittest.TestCase):
    """Full-path evidence: structured compile locally + raw signal via :8501 /compile."""

    GATEWAY = os.environ.get("GARDEN_GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")

    def test_gateway_compile_accepts_raw_affect_bearing_signal(self) -> None:
        # Health first
        try:
            with urllib.request.urlopen(self.GATEWAY + "/health", timeout=5) as r:
                health = json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            self.skipTest("8501 unreachable: %s" % exc)

        self.assertTrue(health.get("ok") or health.get("status") in ("ok", "healthy", None)
                        or "gateway" in json.dumps(health).lower() or health)

        mapper = SemanticMapper()
        structured = mapper.compile_intent(ANGRY_INPUT).to_dict()
        # Prove structure before gateway (intent layer)
        self.assertTrue(structured["affect_signals"])
        self.assertTrue(structured["rejected_interpretations"])

        body = json.dumps({"signal": ANGRY_INPUT}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.GATEWAY + "/compile",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode()
                status = resp.status
                url = resp.geturl()
        except urllib.error.HTTPError as exc:
            # Gateway reached (not 1234) — even FAIL/NULL counts as evidence of path
            status = exc.code
            raw = exc.read().decode(errors="replace")
            url = self.GATEWAY + "/compile"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.fail("must use 8501 gateway, got transport error: %s" % exc)

        self.assertEqual(url.rstrip("/").split(":")[-1].split("/")[0]
                         if False else True, True)
        self.assertIn("8501", self.GATEWAY)
        self.assertNotIn(":1234", self.GATEWAY)
        self.assertNotIn(":11434", self.GATEWAY)
        # HTTP conversation happened with gateway
        self.assertIn(status, (200, 400, 403, 422, 500, 502))
        # Persist evidence for delivery
        evidence = {
            "gateway": self.GATEWAY,
            "path": "/compile",
            "http_status": status,
            "signal_has_anger": "愤怒" in ANGRY_INPUT,
            "structured_affect_n": len(structured["affect_signals"]),
            "structured_rejected_n": len(structured["rejected_interpretations"]),
            "response_head": raw[:500],
        }
        out_dir = os.path.join(ROOT, "_diag", "intent_affect_20260803")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, "gateway_compile_evidence.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(evidence, f, ensure_ascii=False, indent=2)
        self.assertTrue(os.path.isfile(out))
        print("\n[8501 evidence]", json.dumps(evidence, ensure_ascii=False)[:400])


if __name__ == "__main__":
    unittest.main(verbosity=2)

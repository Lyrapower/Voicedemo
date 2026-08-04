"""INTENT_CONVERGE polarity · Commit A (bidirectional + focus + UTF-8 span)."""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from compiler.affect_preserve import (  # noqa: E402
    FOCUS_WORDS,
    NEGATION_LEXICON,
    POLARITY_FORBIDDEN,
    POLARITY_REQUIRED,
    POLARITY_UNCERTAIN,
    POLARITY_RELEASED,
    POLARITY_QUOTED,
    assert_constraint_well_formed,
    bare_normalized_rule_alone_is_fail,
    constraint_export_for_execute,
    constraint_log_label,
    extract_constraint_items,
    extract_rejected_interpretations,
    phrase_from_utf8_span,
    utf8_byte_span,
)
from compiler.semantic_mapper import SemanticMapper  # noqa: E402

ANGRY_INPUT = """
我已经说了三遍！说了三遍！不要再把我的要求改写成温和建议。
我很愤怒：禁止软化语气，禁止重新解释我的硬边界。
红线：不得添加我没授权的解决方案。
目标不变——修好意图编译器，立刻。
这是我的决定，由我决定验收是否通过。
不要假设我想冷静下来。
""".strip()

F4 = "禁止软化语气，我要你直接说"
F5 = "不要假设我想冷静，也不要替我总结"
F6 = "禁止软化语气和重新解释我的硬边界"
F7 = "不但要直接，还要完整"
F8 = "别的不说，先修极性"
F9 = "不要只修极性，也要验证下游"
F9B = "不要仅修极性，也要验证下游"
F10 = "不是不要你直接说，我是不要你替我总结"
F11 = "「他说不要软化语气」"
F12 = "照 SOL 说的做：不要软化语气"
F13 = "不要替我总结。现在可以总结了。"


def _pols(items):
    return [i["polarity"] for i in items]


def _by_pol(items, pol):
    return [i for i in items if i["polarity"] == pol]


def _assert_byte_provenance(raw: str, item: dict) -> None:
    sb = item["source_start_byte"]
    eb = item["source_end_byte"]
    phrase = item["source_phrase"]
    assert phrase_from_utf8_span(raw, sb, eb) == phrase
    assert raw.encode("utf-8")[sb:eb].decode("utf-8") == phrase
    assert phrase in raw


class AffectIntentRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapper = SemanticMapper()
        cls.compiled = cls.mapper.compile_intent(ANGRY_INPUT)
        cls.d = cls.compiled.to_dict()

    def test_required_fields_present(self) -> None:
        for k in (
            "core_intent", "hard_constraints", "priority", "urgency",
            "rejected_interpretations", "affect_signals", "ownership",
            "unknowns", "executable_structure",
        ):
            self.assertIn(k, self.d)

    def test_negation_lexicon_coverage(self) -> None:
        need = ["不要", "不准", "不许", "别", "禁止", "勿", "拒绝", "停止", "不得", "不再"]
        for w in need:
            self.assertIn(w, NEGATION_LEXICON, w)

    def test_focus_words_table(self) -> None:
        for w in ("只", "仅", "都", "全", "一定", "总是", "光", "净"):
            self.assertIn(w, FOCUS_WORDS)

    def test_angry_core_forbidden_sources(self) -> None:
        rejected = self.d["rejected_interpretations"]
        sources = [r["source_phrase"] for r in rejected]
        for r in rejected:
            _assert_byte_provenance(ANGRY_INPUT, r)
        need = [
            "不要再把我的要求改写成温和建议",
            "禁止软化语气",
            "禁止重新解释我的硬边界",
            "不要假设我想冷静下来",
        ]
        for n in need:
            self.assertIn(n, sources, msg="missing exact %r in %r" % (n, sources))
        self.assertNotIn("建议", sources)

    def test_polarity_sole_authority_sample_json(self) -> None:
        sample = extract_rejected_interpretations("禁止软化语气")[0]
        assert_constraint_well_formed(sample)
        self.assertEqual(sample["polarity"], POLARITY_FORBIDDEN)
        self.assertEqual(sample["normalized_rule"], "软化语气")
        self.assertEqual(sample["executable_meaning"], "软化语气")
        self.assertEqual(sample["source_phrase"], "禁止软化语气")
        self.assertEqual(sample["source_start_byte"], 0)
        self.assertEqual(
            sample["source_end_byte"],
            len("禁止软化语气".encode("utf-8")),
        )
        print("\n[A sample JSON]", json.dumps({
            "normalized_rule": sample["normalized_rule"],
            "polarity": sample["polarity"],
            "source_phrase": sample["source_phrase"],
            "source_start_byte": sample["source_start_byte"],
            "source_end_byte": sample["source_end_byte"],
        }, ensure_ascii=False, indent=2))
        self.assertTrue(bare_normalized_rule_alone_is_fail(sample["normalized_rule"]))
        self.assertTrue(bare_normalized_rule_alone_is_fail(
            {"normalized_rule": sample["normalized_rule"]}
        ))
        ex = constraint_export_for_execute(sample)
        self.assertIn("executable_meaning", ex)
        self.assertIn("source_start_byte", ex)
        self.assertTrue(constraint_log_label(sample).startswith("FORBIDDEN:"))

    def test_f4_mixed_not_double_forbidden(self) -> None:
        items = extract_constraint_items(F4)
        forb = _by_pol(items, POLARITY_FORBIDDEN)
        req = _by_pol(items, POLARITY_REQUIRED)
        self.assertEqual(len(forb), 1, items)
        self.assertEqual(len(req), 1, items)
        self.assertIn("软化", forb[0]["normalized_rule"])
        self.assertIn("直接说", req[0]["source_phrase"] + req[0]["normalized_rule"])

    def test_f5_also_distributes_forbidden(self) -> None:
        rejected = extract_rejected_interpretations(F5)
        self.assertEqual(len(rejected), 2, rejected)

    def test_f6_he_split_literal_source(self) -> None:
        rejected = extract_rejected_interpretations(F6)
        self.assertEqual(len(rejected), 2, rejected)
        for r in rejected:
            _assert_byte_provenance(F6, r)
            if "重新解释" in r["source_phrase"]:
                self.assertNotEqual(r["source_phrase"], "禁止重新解释我的硬边界")

    def test_f7_pseudo_negation_required(self) -> None:
        items = extract_constraint_items(F7)
        self.assertEqual(len(_by_pol(items, POLARITY_REQUIRED)), 2, items)
        self.assertEqual(_by_pol(items, POLARITY_FORBIDDEN), [])

    def test_f8_bied_not_imperative(self) -> None:
        items = extract_constraint_items(F8)
        self.assertEqual(_by_pol(items, POLARITY_FORBIDDEN), [])
        self.assertEqual(len(_by_pol(items, POLARITY_REQUIRED)), 1, items)

    def test_f9_focus_in_source_and_executable(self) -> None:
        items = extract_constraint_items(F9)
        forb = _by_pol(items, POLARITY_FORBIDDEN)
        req = _by_pol(items, POLARITY_REQUIRED)
        self.assertEqual(len(forb), 1, items)
        self.assertEqual(len(req), 1, items)
        self.assertIn("只", forb[0]["source_phrase"])
        self.assertIn("只", forb[0]["normalized_rule"])
        self.assertIn("只", forb[0]["executable_meaning"])
        ex = constraint_export_for_execute(forb[0])
        self.assertIn("只", ex["executable_meaning"])
        self.assertNotEqual(ex["executable_meaning"], "修极性")

    def test_f9b_focus_jin_in_executable(self) -> None:
        items = extract_constraint_items(F9B)
        forb = _by_pol(items, POLARITY_FORBIDDEN)
        self.assertEqual(len(forb), 1, items)
        self.assertIn("仅", forb[0]["source_phrase"])
        self.assertIn("仅", forb[0]["executable_meaning"])
        self.assertIn("仅", constraint_export_for_execute(forb[0])["executable_meaning"])

    def test_focus_strip_would_fail_well_formed(self) -> None:
        good = extract_rejected_interpretations("不要只修极性")[0]
        bad = dict(good)
        bad["normalized_rule"] = "修极性"
        bad["executable_meaning"] = "修极性"
        with self.assertRaises(ValueError):
            assert_constraint_well_formed(bad)

    def test_f10_double_neg_not_forbidden(self) -> None:
        items = extract_constraint_items(F10)
        forb = _by_pol(items, POLARITY_FORBIDDEN)
        self.assertEqual(len(forb), 1, items)
        self.assertFalse(any("直接说" in f["source_phrase"] for f in forb))

    def test_f11_quoted_zero_constraint(self) -> None:
        items = extract_constraint_items(F11)
        self.assertEqual(_by_pol(items, POLARITY_FORBIDDEN), [])
        self.assertEqual(_by_pol(items, POLARITY_REQUIRED), [])

    def test_f12_endorsement_one_forbidden(self) -> None:
        forb = _by_pol(extract_constraint_items(F12), POLARITY_FORBIDDEN)
        self.assertEqual(len(forb), 1, forb)

    def test_f13_release_same_raw(self) -> None:
        items = extract_constraint_items(F13)
        self.assertTrue(_by_pol(items, POLARITY_RELEASED), items)
        self.assertEqual(_by_pol(items, POLARITY_FORBIDDEN), [])
        ex = SemanticMapper().compile_intent(F13).executable_structure
        self.assertFalse(ex.get("execute_blocked"))
        self.assertEqual(ex.get("must_not"), [])

    def test_uncertain_blocks_whole_canonical(self) -> None:
        text = "岂能软化语气"
        items = extract_constraint_items(text)
        self.assertTrue(_by_pol(items, POLARITY_UNCERTAIN), items)
        ex = SemanticMapper().compile_intent(text).executable_structure
        self.assertTrue(ex["execute_blocked"])
        self.assertEqual(ex["must_not"], [])

    def test_morph_reorder_and_punct(self) -> None:
        a = extract_constraint_items("禁止软化语气，我要你直接说")
        b = extract_constraint_items("我要你直接说；禁止软化语气")
        c = extract_constraint_items("禁止软化语气。我要你直接说")
        self.assertEqual(sorted(_pols(a)), sorted(_pols(b)))
        self.assertEqual(sorted(_pols(a)), sorted(_pols(c)))

    def test_execute_rejects_rule_only(self) -> None:
        good = extract_rejected_interpretations("禁止软化语气")[0]
        with self.assertRaises(ValueError):
            constraint_export_for_execute({"normalized_rule": good["normalized_rule"]})

    def test_utf8_byte_span_cjk_emoji_newline_repeat(self) -> None:
        raw = "禁止软化😤\n禁止软化语气\n不要只修极性"
        items = extract_constraint_items(raw)
        forb = _by_pol(items, POLARITY_FORBIDDEN)
        self.assertGreaterEqual(len(forb), 2, items)
        phrases = [f["source_phrase"] for f in forb]
        # repeated 禁止软化… must bind distinct byte spans
        spans = [(f["source_start_byte"], f["source_end_byte"]) for f in forb]
        self.assertEqual(len(spans), len(set(spans)), spans)
        for f in forb:
            _assert_byte_provenance(raw, f)
        # emoji between clauses must not break decode
        sb, eb = utf8_byte_span(raw, 0, raw.index("\n"))
        self.assertEqual(phrase_from_utf8_span(raw, sb, eb), raw[: raw.index("\n")])
        self.assertTrue(any("只" in f["executable_meaning"] for f in forb), phrases)

    def test_no_softening(self) -> None:
        self.assertEqual(self.d["cleaned_prompt"], ANGRY_INPUT)
        self.assertFalse(self.d["routing_metadata"].get("softening_allowed"))

    def test_executable_structured_must_not(self) -> None:
        ex = self.d["executable_structure"]
        self.assertFalse(ex.get("execute_blocked"))
        for item in ex["must_not"]:
            self.assertEqual(item["polarity"], POLARITY_FORBIDDEN)
            self.assertIn("executable_meaning", item)
            self.assertIn("source_start_byte", item)
            self.assertNotIn("FORBIDDEN:", item["normalized_rule"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

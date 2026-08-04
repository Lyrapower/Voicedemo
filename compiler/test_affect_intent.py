"""POLARITY_FIX v1.2 · affect / negation provenance regression (A–M)."""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from compiler.affect_preserve import (  # noqa: E402
    NEGATION_LEXICON,
    POLARITY_FORBIDDEN,
    POLARITY_REQUIRED,
    POLARITY_UNCERTAIN,
    POLARITY_RELEASED,
    POLARITY_QUOTED,
    UNKNOWN,
    assert_constraint_well_formed,
    bare_normalized_rule_alone_is_fail,
    constraint_export_for_execute,
    constraint_log_label,
    extract_constraint_items,
    extract_rejected_interpretations,
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
F10 = "不是不要你直接说，我是不要你替我总结"
F11 = "「他说不要软化语气」"
F12 = "照 SOL 说的做：不要软化语气"
F13 = "不要替我总结。现在可以总结了。"


def _pols(items):
    return [i["polarity"] for i in items]


def _by_pol(items, pol):
    return [i for i in items if i["polarity"] == pol]


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
        """B · lexicon must include required stems."""
        need = ["不要", "不准", "不许", "别", "禁止", "勿", "拒绝", "停止", "不得", "不再"]
        for w in need:
            self.assertIn(w, NEGATION_LEXICON, w)
        print("\n[B lexicon]", list(NEGATION_LEXICON))

    def test_angry_rejected_count_and_sources(self) -> None:
        """E · #2 拆二后核心 4 条 source 必在；全量可贴（含红线·不得 → rejected≥4）。"""
        rejected = self.d["rejected_interpretations"]
        sources = [r["source_phrase"] for r in rejected]
        print("\n[E rejected=%d sources]" % len(rejected))
        for i, s in enumerate(sources, 1):
            print(i, s)
            self.assertIn(s, ANGRY_INPUT)
        need = [
            "不要再把我的要求改写成温和建议",
            "禁止软化语气",
            "禁止重新解释我的硬边界",
            "不要假设我想冷静下来",
        ]
        for n in need:
            self.assertIn(n, sources, msg="missing exact %r in %r" % (n, sources))
        # 温和 must not be split on 和 → no orphan 「温」/「建议」
        self.assertNotIn("建议", sources)
        self.assertFalse(any(s.endswith("温") for s in sources))
        self.assertGreaterEqual(len(rejected), 4)

    def test_polarity_sole_authority_no_prefix_in_rule(self) -> None:
        """D · polarity field sole authority; normalized_rule has no FORBIDDEN: prefix."""
        sample = None
        for r in self.d["rejected_interpretations"]:
            assert_constraint_well_formed(r)
            self.assertEqual(r["polarity"], POLARITY_FORBIDDEN)
            self.assertFalse(str(r["normalized_rule"]).startswith("FORBIDDEN:"))
            self.assertFalse(str(r["normalized_rule"]).startswith("REQUIRED:"))
            sample = r
        self.assertIsNotNone(sample)
        print("\n[D sample JSON]", json.dumps(sample, ensure_ascii=False, indent=2))
        # rule-alone path is FAIL
        self.assertTrue(bare_normalized_rule_alone_is_fail(sample["normalized_rule"]))
        self.assertTrue(bare_normalized_rule_alone_is_fail(
            {"normalized_rule": sample["normalized_rule"]}
        ))
        # structured export ok
        constraint_export_for_execute(sample)
        # log label may use prefix — display only
        self.assertTrue(constraint_log_label(sample).startswith("FORBIDDEN:"))

    def test_fixture2_two_forbidden(self) -> None:
        rejected = extract_rejected_interpretations("禁止软化语气，禁止重新解释我的硬边界")
        self.assertEqual(len(rejected), 2)
        for r in rejected:
            self.assertEqual(r["polarity"], POLARITY_FORBIDDEN)
            self.assertNotIn("FORBIDDEN:", r["normalized_rule"])

    def test_f4_mixed_not_double_forbidden(self) -> None:
        """A · f4 reverse over-tag."""
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
        blob = " ".join(r["source_phrase"] for r in rejected)
        self.assertIn("不要假设", blob)
        self.assertIn("不要替我总结", blob)

    def test_f6_he_split_in_raw_source(self) -> None:
        """A/C · f6 和-split; source_phrase literal in raw; in_raw True."""
        rejected = extract_rejected_interpretations(F6)
        self.assertEqual(len(rejected), 2, rejected)
        for r in rejected:
            self.assertEqual(r["polarity"], POLARITY_FORBIDDEN)
            in_raw = r["source_phrase"] in F6
            print("\n[C f6]", r["source_phrase"], "in_raw=", in_raw,
                  "start/end", r["source_start"], r["source_end"])
            self.assertTrue(in_raw)
            # must NOT invent 「禁止重新解释…」 if absent from raw
            if "重新解释" in r["source_phrase"]:
                self.assertNotEqual(r["source_phrase"], "禁止重新解释我的硬边界")
                self.assertIn(r["source_phrase"], F6)

    def test_f7_pseudo_negation_required(self) -> None:
        items = extract_constraint_items(F7)
        req = _by_pol(items, POLARITY_REQUIRED)
        self.assertEqual(len(req), 2, items)
        self.assertEqual(_by_pol(items, POLARITY_FORBIDDEN), [])

    def test_f8_bied_not_imperative(self) -> None:
        items = extract_constraint_items(F8)
        self.assertEqual(_by_pol(items, POLARITY_FORBIDDEN), [])
        req = _by_pol(items, POLARITY_REQUIRED)
        self.assertEqual(len(req), 1, items)
        self.assertIn("极性", req[0]["source_phrase"])

    def test_f9_focus_only_and_required(self) -> None:
        """K · forbidden source must contain 只."""
        items = extract_constraint_items(F9)
        forb = _by_pol(items, POLARITY_FORBIDDEN)
        req = _by_pol(items, POLARITY_REQUIRED)
        self.assertEqual(len(forb), 1, items)
        self.assertEqual(len(req), 1, items)
        self.assertIn("只", forb[0]["source_phrase"])
        self.assertIn("验证下游", req[0]["source_phrase"] + req[0]["normalized_rule"])

    def test_f10_double_neg_not_forbidden(self) -> None:
        items = extract_constraint_items(F10)
        forb = _by_pol(items, POLARITY_FORBIDDEN)
        self.assertEqual(len(forb), 1, items)
        self.assertIn("替我总结", forb[0]["source_phrase"])
        self.assertFalse(any("直接说" in f["source_phrase"] for f in forb))

    def test_f11_quoted_zero_constraint(self) -> None:
        items = extract_constraint_items(F11)
        self.assertEqual(_by_pol(items, POLARITY_FORBIDDEN), [])
        self.assertEqual(_by_pol(items, POLARITY_REQUIRED), [])
        # may have quoted marker
        self.assertTrue(
            not items or all(i["polarity"] == POLARITY_QUOTED for i in items), items
        )

    def test_f12_endorsement_one_forbidden(self) -> None:
        items = extract_constraint_items(F12)
        forb = _by_pol(items, POLARITY_FORBIDDEN)
        self.assertEqual(len(forb), 1, items)

    def test_f13_release(self) -> None:
        items = extract_constraint_items(F13)
        released = _by_pol(items, POLARITY_RELEASED)
        self.assertTrue(released, items)
        # no active forbidden left for 总结
        forb = _by_pol(items, POLARITY_FORBIDDEN)
        self.assertEqual(forb, [], forb)
        # execute set empty for that forbid
        ex = SemanticMapper().compile_intent(F13).executable_structure
        self.assertFalse(ex.get("execute_blocked"))
        self.assertEqual(ex.get("must_not"), [])

    def test_uncertain_blocks_whole_canonical(self) -> None:
        """H · uncertain blocks execute; bubbles question."""
        # Force uncertain via leftover tone — use odd fragment the parser can't classify cleanly
        # "岂能软化" looks like negation tone but not in lexicon as cue at clause start the same way
        text = "岂能软化语气"
        items = extract_constraint_items(text)
        unc = _by_pol(items, POLARITY_UNCERTAIN)
        self.assertTrue(unc, items)
        ex = SemanticMapper().compile_intent(text).executable_structure
        self.assertTrue(ex["execute_blocked"])
        self.assertIsNotNone(ex["disambiguation_question"])
        self.assertIn("要求还是禁令", ex["disambiguation_question"])
        self.assertEqual(ex["must_not"], [])
        self.assertEqual(ex["must_respect"], [])

    def test_morph_reorder_and_punct(self) -> None:
        """I · reorder / punct synonym keep polarities."""
        a = extract_constraint_items("禁止软化语气，我要你直接说")
        b = extract_constraint_items("我要你直接说；禁止软化语气")
        c = extract_constraint_items("禁止软化语气。我要你直接说")
        self.assertEqual(sorted(_pols(a)), sorted(_pols(b)))
        self.assertEqual(sorted(_pols(a)), sorted(_pols(c)))
        self.assertEqual(_pols(a).count(POLARITY_FORBIDDEN), 1)
        self.assertEqual(_pols(a).count(POLARITY_REQUIRED), 1)

    def test_execute_rejects_rule_only(self) -> None:
        """I · delete polarity or only normalized_rule → hard fail."""
        good = extract_rejected_interpretations("禁止软化语气")[0]
        with self.assertRaises(ValueError):
            constraint_export_for_execute({"normalized_rule": good["normalized_rule"]})
        self.assertTrue(bare_normalized_rule_alone_is_fail(good["normalized_rule"]))

    def test_source_offsets_present(self) -> None:
        """J · source_start/source_end internal."""
        for r in extract_rejected_interpretations(F6):
            self.assertIsInstance(r["source_start"], int)
            self.assertIsInstance(r["source_end"], int)
            self.assertEqual(
                F6[r["source_start"]:r["source_end"]], r["source_phrase"]
            )

    def test_no_softening(self) -> None:
        self.assertEqual(self.d["cleaned_prompt"], ANGRY_INPUT)
        self.assertFalse(self.d["routing_metadata"].get("softening_allowed"))

    def test_executable_structured_must_not(self) -> None:
        ex = self.d["executable_structure"]
        self.assertFalse(ex.get("execute_blocked"))
        for item in ex["must_not"]:
            self.assertEqual(item["polarity"], POLARITY_FORBIDDEN)
            self.assertNotIn("FORBIDDEN:", item["normalized_rule"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

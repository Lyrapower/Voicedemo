"""§八 只降不升断言(Phase 3,补 G3):证据等级只能往 unverified 方向降,不能升。
处决案②一般 receipt 升级 → 拒;处决案③对账层 receipt ≥ 原级 → 拒(只能严格降)。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.harness.action_envelope import FactualReceipt
from app.harness import provenance


def _receipt(mission, action, grade, status="EXECUTED", reconcile=False):
    meta = {"evidence_grade": grade}
    if reconcile:
        meta["reconcile"] = True
    return FactualReceipt(
        mission_id=mission, action_id=action, status=status, executed=True,
        result=None, metadata=meta,
    )


class GradeMonotoneDescentTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w")
        self._tmp.close()
        os.environ["HARNESS_PROVENANCE_LOG"] = self._tmp.name

    def tearDown(self):
        os.environ.pop("HARNESS_PROVENANCE_LOG", None)
        os.unlink(self._tmp.name)

    def test_first_receipt_any_grade_accepted(self):
        provenance.record_receipt(_receipt("m1", "a1", "attested"))
        ev = provenance.read_events("m1")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["evidence_grade"], "attested")
        self.assertTrue(provenance.verify_chain(ev))

    def test_descending_allowed(self):
        provenance.record_receipt(_receipt("m2", "a2", "witnesses_agree"))
        provenance.record_receipt(_receipt("m2", "a2", "witness_only"))   # 降
        provenance.record_receipt(_receipt("m2", "a2", "unverified"))     # 再降
        ev = provenance.read_events("m2")
        self.assertEqual(len(ev), 3)
        self.assertTrue(provenance.verify_chain(ev))

    def test_same_grade_allowed_general(self):
        provenance.record_receipt(_receipt("m3", "a3", "witness_only"))
        provenance.record_receipt(_receipt("m3", "a3", "witness_only"))   # 相同,一般 receipt 允许
        ev = provenance.read_events("m3")
        self.assertEqual(len(ev), 2)

    def test_ascending_rejected(self):
        provenance.record_receipt(_receipt("m4", "a4", "secondhand"))
        with self.assertRaises(ValueError) as cm:
            provenance.record_receipt(_receipt("m4", "a4", "attested"))    # 升 → 拒(处决案②)
        self.assertIn("只降不升", str(cm.exception))
        ev = provenance.read_events("m4")
        self.assertEqual(len(ev), 1)  # 第二条没写进去

    def test_reconcile_same_grade_rejected(self):
        provenance.record_receipt(_receipt("m5", "a5", "witness_only"))
        with self.assertRaises(ValueError) as cm:
            provenance.record_receipt(_receipt("m5", "a5", "witness_only", reconcile=True))  # 对账层 ≥ 原级 → 拒(处决案③)
        self.assertIn("对账层", str(cm.exception))

    def test_reconcile_ascending_rejected(self):
        provenance.record_receipt(_receipt("m6", "a6", "witness_only"))
        with self.assertRaises(ValueError) as cm:
            provenance.record_receipt(_receipt("m6", "a6", "attested", reconcile=True))
        self.assertIn("对账层", str(cm.exception))

    def test_reconcile_strict_descent_allowed(self):
        provenance.record_receipt(_receipt("m7", "a7", "witness_only"))
        provenance.record_receipt(_receipt("m7", "a7", "unverified", reconcile=True))  # 对账层严格降 → 允许
        ev = provenance.read_events("m7")
        self.assertEqual(len(ev), 2)

    def test_no_grade_skips_enforcement(self):
        # 无 evidence_grade 的 receipt 不触发断言,兼容旧 receipt
        r = FactualReceipt(mission_id="m8", action_id="a8", status="EXECUTED", executed=True, metadata={})
        provenance.record_receipt(r)
        provenance.record_receipt(r)  # 无 grade,重复写不拒
        ev = provenance.read_events("m8")
        self.assertEqual(len(ev), 2)

    def test_unknown_grade_skips_enforcement(self):
        provenance.record_receipt(_receipt("m9", "a9", "bogus_grade"))
        ev = provenance.read_events("m9")
        self.assertEqual(len(ev), 1)
        self.assertNotIn("evidence_grade", ev[0])  # 未知 grade 不落字段


if __name__ == "__main__":
    unittest.main()

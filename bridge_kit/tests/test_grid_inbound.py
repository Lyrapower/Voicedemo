import os
import tempfile
import unittest

from bridge_kit import grid_inbound as gi


def _paths():
    d = tempfile.mkdtemp()
    return os.path.join(d, "stream.txt"), None


def _lines(p):
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [l.rstrip("\n") for l in f if l.strip()]


R1 = {"jid": "J-b5050da341d7", "tool": "web.fetch", "status": "ok", "grade": "unverified",
      "chars": 430, "ts": 1789155300, "note": "DDG challenge page"}
R2 = {"jid": "J-dcc3623e086d", "tool": "rwa.read", "status": "ok", "note": "cards=5 permission=read_only"}
R3 = {"jid": "J-0f9f1853fb58", "tool": "option.shadow", "status": "unsettled:http_472", "ts": 1789205000}


class T(unittest.TestCase):
    def test_execution_missing_jid_rejected_file_untouched(self):
        s, l = _paths()
        w = gi.InboundWriter(s)
        with self.assertRaises(gi.InboundError):
            w.write({"tool": "web.fetch", "status": "ok"})
        self.assertEqual(_lines(s), [])

    def test_execution_duplicate_does_not_grow_stream(self):
        s, l = _paths()
        w = gi.InboundWriter(s)
        self.assertEqual(w.write(R1), "written")
        self.assertEqual(w.write(R1), "duplicate")
        self.assertEqual(len(_lines(s)), 1)
        # 新进程重开 writer 也记得
        w2 = gi.InboundWriter(s)
        self.assertEqual(w2.write(R1), "duplicate")
        self.assertEqual(len(_lines(s)), 1)

    def test_execution_persona_text_refused(self):
        s, l = _paths()
        w = gi.InboundWriter(s)
        bad = dict(R2, note="You are an autonomous agent with tools")
        with self.assertRaises(gi.InboundError):
            w.write(bad)
        self.assertEqual(_lines(s), [])

    def test_execution_newline_in_note_flattened(self):
        row = gi.format_receipt_row(dict(R2, note="a\nb\r\nc"))
        self.assertNotIn("\n", row)
        self.assertIn('note="a b c"', row)

    def test_time_is_los_angeles_not_utc(self):
        row = gi.format_receipt_row(R1)
        # 1789198500 = 2026-09-11T19:35:00Z = 2026-09-11T12:35:00-07:00
        self.assertIn("at=2026-09-11T12:35:00-07:00", row)

    def test_backfill_three_real_jids_and_one_bad(self):
        s, l = _paths()
        w = gi.InboundWriter(s)
        out = w.backfill([R1, R2, R3, {"_bad_line": "x"}])
        self.assertEqual(out, {"written": 3, "duplicate": 0, "rejected": 1})
        rows = _lines(s)
        self.assertEqual(len(rows), 3)
        for jid in ("J-b5050da341d7", "J-dcc3623e086d", "J-0f9f1853fb58"):
            self.assertTrue(any(("jid=%s " % jid) in r for r in rows), jid)
        self.assertTrue(any("status=unsettled:http_472" in r for r in rows))
        # 再回填一次 = 全 duplicate
        self.assertEqual(w.backfill([R1, R2, R3]), {"written": 0, "duplicate": 3, "rejected": 0})

    def test_execution_missing_ts_is_unknown_not_now(self):
        row = gi.format_receipt_row(R2)
        self.assertIn("at=unknown", row)
        self.assertIn("ingested=", row)
        row = gi.format_receipt_row(dict(R2, finished_at=1789155300))
        self.assertIn("at=2026-09-11T12:35:00-07:00", row)
        self.assertIn("ingested=", row)

    def test_execution_two_writers_same_file_no_interleave_no_dup(self):
        import threading
        s, _ = _paths()
        errs = []
        def worker(n):
            try:
                w = gi.InboundWriter(s)
                for i in range(30):
                    w.write({"jid": "J-%012d" % i, "tool": "t", "status": "ok"})
            except Exception as e:  # noqa
                errs.append(e)
        ts = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(errs, [])
        rows = _lines(s)
        self.assertEqual(len(rows), 30)
        self.assertTrue(all(r.startswith("[harness] key=j:J-") for r in rows))
        self.assertEqual(len(set(rows)), 30)

    def test_execution_truncated_tail_line_is_quarantined_not_merged(self):
        """崩溃留下没有换行的半行:重建不把它当已见键,下一次追加从新行开始,半行不与新行粘连。"""
        s, _ = _paths()
        full = gi.format_receipt_row({"jid": "J-aaaaaaaaaaaa", "tool": "t", "status": "ok"})
        half = gi.format_receipt_row({"jid": "J-cccccccccccc", "tool": "t", "status": "ok"})[:40]  # 真半行,含 key= 但无换行
        with open(s, "w") as f:
            f.write(full + "\n" + half)
        w = gi.InboundWriter(s)
        self.assertEqual(w.write({"jid": "J-aaaaaaaaaaaa", "tool": "t", "status": "ok"}), "duplicate")
        # 半行的键不算已见:同 jid 再写必须 written(半行不是收据)
        self.assertEqual(w.write({"jid": "J-cccccccccccc", "tool": "t", "status": "ok"}), "written")
        raw = open(s, encoding="utf-8").read()
        lines = raw.split("\n")
        self.assertTrue(lines[1].startswith("[harness] key=j:J-cccccccccccc"))  # 半行原样留着
        self.assertTrue(lines[2].startswith("[harness] key=j:J-cccccccccccc jid=J-cccccccccccc mid=- tool=t status=ok"))
        self.assertEqual(len(gi.parse_stream(s)), 2)  # 只有两条完整收据

    def test_row_has_no_explanatory_prose(self):
        row = gi.format_receipt_row(R3)
        self.assertTrue(row.startswith("[harness] key=j:J-0f9f1853fb58 jid=J-0f9f1853fb58 mid=- tool=option.shadow status=unsettled:http_472"))
        self.assertNotIn("Grid", row)


if __name__ == "__main__":
    unittest.main()

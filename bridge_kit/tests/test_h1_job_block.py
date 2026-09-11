import unittest

from bridge_kit import h1_job_block as h1
from bridge_kit import grid_inbound as gi

GOOD = """type: MISSION
action.goal: fetch https://api.github.com/zen and report status
bounds.gate: read_only
bounds.budget: 3 hops / 5 min / $0
bounds.stop: first ok receipt
resources.worker: deep
resources.tools: web.fetch
"""

TEXT = "前面是 Grid 的话。\n```job\n" + GOOD + "```\n后面还有话。"


class T(unittest.TestCase):
    def test_extract_one_block(self):
        blocks = h1.extract_job_blocks(TEXT)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].strip(), GOOD.strip())

    def test_good_block_compiles(self):
        p = h1.parse_job_block(GOOD)
        c = h1.compile_job(p, origin="synthetic_xu", block_text=GOOD)
        self.assertEqual(c["status"], "proposed")
        self.assertEqual(c["resources"]["tools"], ["web.fetch"])
        self.assertEqual(len(c["seed_hash"]), 64)
        self.assertEqual(c["seed_hash"], h1.seed_hash_of(GOOD))

    def test_execution_missing_bounds_stop_rejected(self):
        p = h1.parse_job_block(GOOD.replace("bounds.stop: first ok receipt\n", ""))
        with self.assertRaises(h1.CompileError) as cm:
            h1.compile_job(p, origin="grid")
        self.assertEqual(cm.exception.missing, ["bounds.stop"])

    def test_execution_missing_whole_resources_rejected(self):
        p = {"type": "MISSION", "action": {"goal": "x"},
             "bounds": {"gate": "read_only", "budget": "1", "stop": "1"}}
        with self.assertRaises(h1.CompileError) as cm:
            h1.compile_job(p, origin="grid")
        self.assertEqual(cm.exception.missing, ["resources"])

    def test_execution_not_mission_type_rejected(self):
        p = h1.parse_job_block(GOOD.replace("type: MISSION", "type: STATE_REPORT"))
        with self.assertRaises(h1.CompileError) as cm:
            h1.compile_job(p, origin="grid")
        self.assertIn("type=MISSION", cm.exception.missing)

    def test_execution_empty_tools_list_rejected(self):
        p = h1.parse_job_block(GOOD.replace("resources.tools: web.fetch", "resources.tools: "))
        with self.assertRaises(h1.CompileError):
            h1.compile_job(p, origin="grid")

    def test_roundtrip_receipt_row_links_back_to_seed(self):
        c = h1.compile_job(h1.parse_job_block(GOOD), origin="synthetic_xu", block_text=GOOD)
        receipt = {"jid": "J-000000000001", "tool": "web.fetch", "status": "ok", "chars": 60}
        r = h1.attach_lineage(receipt, c, mission_ref="M-000000000001")
        row = gi.format_receipt_row(r)
        self.assertTrue(h1.verify_roundtrip(c, row))
        self.assertIn("mid=M-000000000001", row)
        # 换一个块 → 对不上
        other = h1.compile_job(h1.parse_job_block(GOOD.replace("zen", "octocat")),
                               origin="synthetic_xu", block_text=GOOD.replace("zen", "octocat"))
        self.assertFalse(h1.verify_roundtrip(other, row))

    def test_execution_lineage_fields_inside_note_do_not_count(self):
        c = h1.compile_job(h1.parse_job_block(GOOD), origin="synthetic_xu", block_text=GOOD)
        fake = {"jid": "J-000000000002", "tool": "web.fetch", "status": "ok",
                "note": "seed_hash=%s origin=synthetic_xu" % c["seed_hash"]}
        row = gi.format_receipt_row(fake)   # 没经过 attach_lineage,只有 note 里冒充
        self.assertFalse(h1.verify_roundtrip(c, row))
        f = h1.parse_row_fields(row)
        self.assertNotIn("seed_hash", f)


if __name__ == "__main__":
    unittest.main()

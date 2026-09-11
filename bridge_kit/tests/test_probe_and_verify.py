import json, os, subprocess, sys, tempfile, unittest
from bridge_kit import grid_inbound as gi, h1_job_block as h1

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable


def run(mod, *args):
    p = subprocess.run([PY, os.path.join(ROOT, "bridge_kit", mod)] + list(args), capture_output=True, text=True, cwd=ROOT)
    return p.returncode, p.stdout, p.stderr


class TProbe(unittest.TestCase):
    def test_execution_probe_never_crashes_on_missing_everything(self):
        d = tempfile.mkdtemp()
        rc, out, err = run("site_probe.py", "--repo", d, "--egress", "nope.md", "--gateway", "nope.py",
                           "--stream", os.path.join(d, "no"), "--no-net")
        self.assertEqual(rc, 0, err)
        R = json.loads(out)
        self.assertEqual(R["egress_rows"]["status"], "NOT_FOUND")
        self.assertEqual(R["gateway_inbound"]["status"], "NOT_FOUND")
        self.assertEqual(R["stream_has_jids"]["status"], "NOT_FOUND")
        self.assertEqual(R["h1_mission_route"]["status"], "NOT_GIVEN")
        self.assertIn(R["env_keys"]["OLLAMA_API_KEY"], ("SET", "UNSET"))
        self.assertNotIn("ollama-", out)  # 不泄值

    def test_execution_probe_reports_real_hits_and_unreachable_net(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "EGRESS.md"), "w") as f:
            f.write("| ollama.com | POST | deep,research |\n| api.github.com | GET | deep |\n")
        st = os.path.join(d, "stream.txt")
        gi.InboundWriter(st).write({"jid": "J-b5050da341d7", "tool": "web.fetch", "status": "ok"})
        rc, out, err = run("site_probe.py", "--repo", d, "--egress", "EGRESS.md", "--stream", st)
        self.assertEqual(rc, 0, err)
        R = json.loads(out)
        self.assertEqual(R["egress_rows"]["n"], 2)
        self.assertEqual(R["stream_has_jids"]["n"], 1)
        # 沙箱没有 8630/11434/25503:必须是 NOT_REACHABLE,不是崩
        for k in ("8630_missions", "11434_web_search_proxy", "theta_mdds"):
            self.assertIn(R["net"][k]["status"], ("NOT_REACHABLE", 404, 200, 405, 400, 401, 403))


class TVerify(unittest.TestCase):
    def _fixture(self):
        d = tempfile.mkdtemp()
        rec = os.path.join(d, "receipts.jsonl"); st = os.path.join(d, "stream.txt")
        recs = [{"jid": j, "tool": "t", "status": "ok"} for j in gi.__dict__.get("JIDS", ["J-b5050da341d7", "J-dcc3623e086d", "J-0f9f1853fb58"])]
        with open(rec, "w") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")
        w = gi.InboundWriter(st)
        for r in recs:
            w.write(r)
        return d, rec, st

    def test_pass_when_wired_correctly(self):
        d, rec, st = self._fixture()
        rc, out, err = run("wire_verify.py", "--receipts", rec, "--stream", st)
        R = json.loads(out)
        self.assertEqual(R["overall"], "PASS", out)
        self.assertEqual(rc, 0)

    def test_execution_missing_receipt_row_fails_with_name(self):
        d, rec, st = self._fixture()
        with open(rec, "a") as f:
            f.write(json.dumps({"jid": "J-notwritten01", "tool": "t", "status": "ok"}) + "\n")
        rc, out, _ = run("wire_verify.py", "--receipts", rec, "--stream", st)
        R = json.loads(out)
        self.assertEqual(rc, 1)
        self.assertEqual(R["A1_every_receipt_in_stream"]["missing"], ["j:J-notwritten01"])

    def test_execution_half_line_and_fake_lineage_fail(self):
        d, rec, st = self._fixture()
        with open(st, "a") as f:
            f.write("[harness] key=j:J-zzzz jid=J-zzzz tool=t status=ok seed_hash=short origin=grid at=unknown ingested=x\n")
            f.write("[harness] key=j:J-half jid=J-ha")  # 半行
        rc, out, _ = run("wire_verify.py", "--receipts", rec, "--stream", st)
        R = json.loads(out)
        self.assertEqual(rc, 1)
        self.assertEqual(R["A3_no_half_line"]["result"], "FAIL")
        self.assertEqual(R["B1_lineage_rows_parse"]["result"], "FAIL")

    def test_execution_duplicate_key_written_by_foreign_writer_detected(self):
        d, rec, st = self._fixture()
        line = gi.parse_stream(st)[0]
        with open(st, "a") as f:
            f.write(line + "\n")  # 别的写入者绕过 InboundWriter 重复写
        rc, out, _ = run("wire_verify.py", "--receipts", rec, "--stream", st)
        R = json.loads(out)
        self.assertEqual(R["A2_no_duplicate_keys"]["result"], "FAIL")


if __name__ == "__main__":
    unittest.main()

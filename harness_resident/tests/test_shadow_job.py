import json
import tempfile
import unittest
from pathlib import Path
from harness.shadow_job import publish,run_briefs
from tests.test_option_shadow_ledger import fake,LEG,D

class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'ledger.json'
    def test_publish_idempotent(self):
        self.assertEqual(publish(self.path,{'a':1}),publish(self.path,{'a':1}))
    def test_preserve_existing(self):
        publish(self.path,{'a':1})
        with self.assertRaises(FileExistsError): publish(self.path,{'a':2})
        self.assertEqual(json.loads(self.path.read_text()),{'a':1})
    def test_no_partial_file_on_serialization_error(self):
        with self.assertRaises(ValueError): publish(self.path,{'x':float('nan')})
        self.assertFalse(self.path.exists())
    def test_symlink_refused(self):
        target=Path(self.tmp.name)/'target'; target.write_text('safe')
        self.path.symlink_to(target)
        with self.assertRaises(FileExistsError): publish(self.path,{'a':1})
        self.assertEqual(target.read_text(),'safe')
    def test_job_end_to_end_fixture(self):
        r=run_briefs(fake(),{'schema_version':1,'legs':[LEG]},D,self.path)
        self.assertEqual((r['settled'],r['total']),(1,1))
        self.assertEqual(r['receipt_delivery'],'PENDING_EXTERNAL_ACK')
        self.assertEqual(json.loads(self.path.read_text())['legs'][0]['net'],28.7)
    def test_rejected_leg_not_fake_success(self):
        r=run_briefs(fake(),{'schema_version':1,'legs':[dict(LEG,position='short')]},D,self.path)
        self.assertEqual(r['settled'],0)
    def test_empty_briefs(self):
        with self.assertRaises(ValueError): run_briefs(fake(),{'schema_version':1,'legs':[]},D,self.path)

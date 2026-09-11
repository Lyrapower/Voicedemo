import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

class SelfcheckTests(unittest.TestCase):
    def test_failure_stops_theta_and_has_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'harness').mkdir(); (root/'tests').mkdir()
            source=Path(__file__).resolve().parent.parent/'harness'
            for name in ('__init__.py','selfcheck.py','option_shadow_ledger.py'):
                shutil.copyfile(source/name,root/'harness'/name)
            (root/'tests/__init__.py').touch()
            (root/'tests/test_fail.py').write_text('import unittest\nclass Failure(unittest.TestCase):\n def test_fail(self): self.fail("intentional")\n')
            r=subprocess.run([sys.executable,'-S','-m','harness.selfcheck','--report',str(root/'report')],cwd=root,capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,1)
            report=json.loads((root/'report/report.json').read_text())
            self.assertEqual(report['unit']['failures'],1)
            self.assertEqual(report['theta']['status'],'not_run:unit_failed')
    def test_bad_port_is_config_failure_not_code_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'harness').mkdir(); (root/'tests').mkdir()
            source=Path(__file__).resolve().parent.parent/'harness'
            for name in ('__init__.py','selfcheck.py','option_shadow_ledger.py'):
                shutil.copyfile(source/name,root/'harness'/name)
            (root/'tests/__init__.py').touch()
            (root/'tests/test_ok.py').write_text('import unittest\nclass OK(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n')
            env=dict(os.environ,THETA_PORT="25503');__import__('pathlib').Path('pwned').touch();#")
            r=subprocess.run([sys.executable,'-S','-m','harness.selfcheck','--report',str(root/'report')],cwd=root,env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,1)
            report=json.loads((root/'report/report.json').read_text())
            self.assertEqual(report['theta']['status'],'invalid_THETA_PORT')
            self.assertFalse((root/'pwned').exists())

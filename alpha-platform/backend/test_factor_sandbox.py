"""Unit tests — factor sandbox V1.2/V1.3 guards."""
from __future__ import annotations

import unittest

from factor_sandbox import (
    FactorCodeError,
    ResourceLimit,
    SandboxRejection,
    WorkerPipelineError,
    _validate_ast,
    eligible_for_fix_error,
    run_factor_review,
)
from factory_schema import column_whitelist, load_contract


class FactorSandboxAstTest(unittest.TestCase):
    def test_reject_requests_import(self):
        code = "import requests\ndef factor(df):\n    return df['c']"
        with self.assertRaises(SandboxRejection):
            _validate_ast(code)

    def test_reject_dunder_import_call(self):
        code = "def factor(df):\n    __import__('os')\n    return df['c']"
        with self.assertRaises(SandboxRejection):
            _validate_ast(code)

    def test_reject_eval(self):
        code = 'def factor(df):\n    eval("1+1")\n    return df["c"]'
        with self.assertRaises(SandboxRejection):
            _validate_ast(code)

    def test_reject_getattr_builtins(self):
        code = "def factor(df):\n    getattr(pd, '__builtins__')\n    return df['c']"
        with self.assertRaises(SandboxRejection):
            _validate_ast(code)

    def test_allow_pandas(self):
        code = "import pandas as pd\nimport numpy as np\ndef factor(df):\n    return pd.Series([1]*len(df))"
        _validate_ast(code)


class FactorSandboxCategoryTest(unittest.TestCase):
    def test_sandbox_not_fix_eligible(self):
        self.assertFalse(eligible_for_fix_error(SandboxRejection("blocked")))

    def test_factor_code_fix_eligible(self):
        exc = FactorCodeError("x", exc_type="KeyError", exc_message="bad col", traceback_frames=[], df_head="")
        self.assertTrue(eligible_for_fix_error(exc))


class FactorSandboxIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import sqlite3
        import tempfile

        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.db_path = cls._tmp.name
        cls._tmp.close()
        con = sqlite3.connect(cls.db_path)
        con.execute(
            "CREATE TABLE bars(id INTEGER PRIMARY KEY, ts INTEGER, symbol TEXT, "
            "o REAL, h REAL, l REAL, c REAL, v REAL)"
        )
        rows = []
        for i in range(50):
            rows.append((1700000000 + i * 60, "AAPL", 1.0, 1.1, 0.9, 1.0 + i * 0.001, 1000.0))
        con.executemany("INSERT INTO bars(ts,symbol,o,h,l,c,v) VALUES(?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()

    @classmethod
    def tearDownClass(cls) -> None:
        import os

        try:
            os.unlink(cls.db_path)
        except OSError:
            pass

    def test_off_schema_column_code(self):
        code = "def factor(df):\n    return df['not_in_schema']\n"
        with self.assertRaises(FactorCodeError):
            run_factor_review(code, self.db_path, ["AAPL"])

    def test_pipeline_missing_db(self):
        code = "def factor(df):\n    return df['c']"
        with self.assertRaises(WorkerPipelineError):
            run_factor_review(code, "/nonexistent/platform.db", ["AAPL"])


class FactorySchemaTest(unittest.TestCase):
    def test_contract_loads(self):
        c = load_contract()
        self.assertEqual(c["schema_id"], "alpha-factory-bars-v0")
        self.assertIn("ts", column_whitelist())


if __name__ == "__main__":
    unittest.main()

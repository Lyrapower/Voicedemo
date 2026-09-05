"""Tests — L0 runner code_source + GLM lane hard gate."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

import db
import l0_runner
from l0_runner import (
    CODE_SOURCE_GLM,
    CODE_SOURCE_SUBSTITUTE,
    LANE_GLM,
    LANE_PIPELINE_SMOKE,
    assert_glm_lane_eligible,
    ensure_l0_schema,
    record_glm_lane_stat,
    resolve_code_source,
)


class L0RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._prev = os.environ.get("PLATFORM_DB")
        os.environ["PLATFORM_DB"] = os.path.join(self._tmpdir, "t.db")
        os.environ["PLATFORM_DB_DIRECT_WRITE"] = "1"

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("PLATFORM_DB", None)
        else:
            os.environ["PLATFORM_DB"] = self._prev

    def test_resolve_substitute_when_code_differs(self) -> None:
        meta = json.dumps({"glm_code_original": "def factor(df):\n    return df['c']"})
        src = resolve_code_source(code="def factor(df):\n    return df['o']", meta_raw=meta)
        self.assertEqual(src, CODE_SOURCE_SUBSTITUTE)

    def test_glm_lane_stat_blocks_substitute(self) -> None:
        c = db.conn_factory()
        ensure_l0_schema(c)
        c.execute(
            "INSERT INTO factor_reviews(draft_id, created, status, metrics, grid_explain, error, "
            "code_source, lane, quarantine) VALUES(1, ?, 'passed', '{}', '', '', ?, ?, 1)",
            (1, CODE_SOURCE_SUBSTITUTE, LANE_PIPELINE_SMOKE),
        )
        review_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.commit()
        with self.assertRaises(ValueError):
            record_glm_lane_stat(
                c,
                review_id=review_id,
                draft_id=1,
                outcome="passed",
                code_source=CODE_SOURCE_SUBSTITUTE,
                lane=LANE_PIPELINE_SMOKE,
            )
        c.close()

    def test_glm_lane_stat_allows_glm_generated(self) -> None:
        c = db.conn_factory()
        ensure_l0_schema(c)
        c.execute(
            "INSERT INTO factor_reviews(draft_id, created, status, metrics, grid_explain, error, "
            "code_source, lane, quarantine) VALUES(1, ?, 'passed', '{}', '', '', ?, ?, 0)",
            (1, CODE_SOURCE_GLM, LANE_GLM),
        )
        review_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        record_glm_lane_stat(
            c,
            review_id=review_id,
            draft_id=1,
            outcome="passed",
            code_source=CODE_SOURCE_GLM,
            lane=LANE_GLM,
        )
        n = c.execute("SELECT COUNT(*) FROM glm_lane_stats WHERE review_id=?", (review_id,)).fetchone()[0]
        c.commit()
        c.close()
        self.assertEqual(n, 1)

    def test_assert_glm_lane_eligible(self) -> None:
        assert_glm_lane_eligible(CODE_SOURCE_GLM)
        with self.assertRaises(ValueError):
            assert_glm_lane_eligible(CODE_SOURCE_SUBSTITUTE)


class FactorDraftsGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._prev = os.environ.get("PLATFORM_DB")
        os.environ["PLATFORM_DB"] = os.path.join(self._tmpdir, "guard.db")
        os.environ["PLATFORM_DB_DIRECT_WRITE"] = "1"

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("PLATFORM_DB", None)
        else:
            os.environ["PLATFORM_DB"] = self._prev

    def test_bar_shaped_insert_rejected(self) -> None:
        c = db.conn_factory()
        db.ensure_factor_drafts_guard(c)
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute(
                "INSERT INTO factor_drafts(created, slug, name, hypothesis, code, status) "
                "VALUES(?,?,?,?,?,?)",
                (1, "AMZN", 231.3, 231.07, 230.5, 230.0),
            )
        c.close()


if __name__ == "__main__":
    unittest.main()

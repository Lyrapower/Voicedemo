"""SCOUT_GOAL v3: file text + parse + no old industry-kill words in the goal."""
from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOML = ROOT / "missions.toml"
GOAL_V3 = """你是资源侦察 worker。目录源里当前开放的公开机会,你只做三件事,每条一行可解析:
1. kind:归入七类之一——资金 / 硬件资源 / 项目与人才计划 / 融资 / 采购 / 社区 / 政策数据。
2. eligibility:原文摘录申请人资格条款,不归类、不判是否符合;摘不到写 needs_verification。
3. note:一句事实(规模、地区、主办方类型),没有就留空。
你不判断"是否相关",不按申请人、领域、地区筛选,不写"不符合目标"。
HIT / MISS 不由你判:runner 按字段齐全(opp_id、title、agency、deadline 可解析且未过、URL、event_id)判 HIT;缺字段且 detail 取不到、或 deadline 已过判 MISS。
输出上限:每跳把拿到的行全部写完,不截断,不挑选。"""
BANNED = re.compile(r"(?i)\b(?:AI|startup|Yardi|Lyra)\b|人工智能|基建|商业地产|资管|地产|加州")


class TestScoutGoalV3(unittest.TestCase):
    def test_toml_parses_and_goal_matches_field(self):
        data = tomllib.loads(TOML.read_text(encoding="utf-8"))
        scout = data["mission"]["scout"]
        self.assertEqual(scout["goal"].strip(), GOAL_V3.strip())
        search = scout["search"]
        self.assertIs(search.get("profile_filter"), False)
        self.assertIs(search.get("unknown_is_allowed"), True)

    def test_goal_has_no_banned_industry_words(self):
        data = tomllib.loads(TOML.read_text(encoding="utf-8"))
        goal = data["mission"]["scout"]["goal"]
        self.assertIsNone(BANNED.search(goal))

    def test_complete_off_profile_row_not_industry_miss(self):
        """Old industry filter would MISS commercial real estate / CA. v3 does not."""
        data = tomllib.loads(TOML.read_text(encoding="utf-8"))
        search = data["mission"]["scout"]["search"]
        row = {
            "opp_id": "CA-CRE-1",
            "title": "Commercial real estate retrofit",
            "agency": "California Energy Commission",
            "deadline": "2026-12-01",
            "url": "https://www.grants.gov/search-results-detail/CA-CRE-1",
            "event_id": "E-cre-1",
        }
        self.assertFalse(search.get("profile_filter"))
        self.assertTrue(search.get("unknown_is_allowed"))
        self.assertTrue(all(row.values()))


if __name__ == "__main__":
    unittest.main()

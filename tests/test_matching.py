"""Behavior checks against the workshop's synthetic reference classes."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "functions"))

from matching import check_groups, match_people, validate_people  # noqa: E402

FIXTURES = ROOT.parent / "padua_workshop" / "examples" / "ex5c"


def fixture(name: str):
    return json.loads((FIXTURES / f"class_{name}.json").read_text())


class MatchingTests(unittest.TestCase):
    def test_feasible_base_prefers_fours_and_passes_rules(self):
        people = fixture("base")
        result = match_people(people, seconds=5)
        self.assertFalse(result["relaxed"])
        self.assertTrue(result["check"]["hardRulesPass"])
        self.assertEqual(sorted(len(group) for group in result["groups"]), [4] * 9)

    def test_infeasible_case_flags_violations(self):
        people = fixture("infeasible")
        result = match_people(people, seconds=5)
        self.assertEqual(result["hardStatus"], "INFEASIBLE")
        self.assertTrue(result["relaxed"])
        self.assertFalse(result["check"]["hardRulesPass"])
        self.assertFalse(result["check"]["partitionErrors"])
        self.assertTrue(result["check"]["violations"])

    def test_checker_catches_duplicate_and_veto(self):
        people = fixture("base")
        grouping = [[p["id"] for p in people]]
        checked = check_groups(people, grouping)
        self.assertFalse(checked["hardRulesPass"])
        self.assertTrue(any(v["rule"] == "veto" for v in checked["violations"]))
        checked = check_groups(people, grouping + [[people[0]["id"]]])
        self.assertTrue(checked["partitionErrors"])

    def test_bad_preferences_rejected(self):
        people = fixture("base")
        people[0]["vetoes"].append(people[0]["id"])
        with self.assertRaises(ValueError):
            validate_people(people)


if __name__ == "__main__":
    unittest.main()

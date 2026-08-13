import json
import os
import tempfile
import unittest

from upgrade_guard import FeatureFlags, UpgradeGuard


class UpgradeGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.flags_path = os.path.join(self.temp_dir.name, "flags.json")
        self.guard = UpgradeGuard(FeatureFlags(self.flags_path))

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def valid_match():
        return {
            "id": "mk-1", "status": "IN_PROGRESS", "score_orientation": "home-away",
            "home": {"name": "A"}, "away": {"name": "B"},
            "live_score": {"home": 2, "away": 1},
        }

    def test_valid_match_preserves_home_away_score(self):
        accepted, report = self.guard.audit_matches([self.valid_match()])
        self.assertEqual(accepted[0]["live_score"], {"home": 2, "away": 1})
        self.assertEqual(report["accepted"], 1)
        self.assertEqual(report["rejected"], 0)

    def test_invalid_score_orientation_is_rejected(self):
        match = self.valid_match()
        match["score_orientation"] = "away-home"
        accepted, report = self.guard.audit_matches([match])
        self.assertEqual(accepted, [])
        self.assertEqual(report["issues"]["score_orientation"], 1)

    def test_analysis_contract_rejects_broken_probability_sum(self):
        valid, issues = self.guard.validate_analysis({"probs": {"home_win": 50, "draw": 30, "away_win": 30}})
        self.assertFalse(valid)
        self.assertIn("probability_sum", issues)

    def test_candidate_is_off_but_shadow_is_on_by_default_and_file_overrides_work(self):
        self.assertFalse(self.guard.flags.enabled("candidate_predictor"))
        self.assertTrue(self.guard.flags.enabled("shadow_predictor"))
        with open(self.flags_path, "w", encoding="utf-8") as stream:
            json.dump({"shadow_predictor": False}, stream)
        flags = FeatureFlags(self.flags_path)
        self.assertFalse(flags.enabled("shadow_predictor"))
        self.assertFalse(flags.enabled("candidate_predictor"))

    def test_shadow_comparison_records_probability_delta(self):
        stable = {"probs": {"home_win": 45, "draw": 30, "away_win": 25}}
        candidate = {"probs": {"home_win": 48, "draw": 28, "away_win": 24}}
        result = self.guard.compare_shadow(stable, candidate)
        self.assertEqual(result["max_probability_delta"], 3.0)
        self.assertEqual(self.guard.snapshot()["shadow_compared"], 1)


if __name__ == "__main__":
    unittest.main()

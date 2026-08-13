import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from model_lab import HistoricalModelLab


class DeterministicPredictor:
    VERSION = "walk-forward-test"

    def analyze_match(self, match):
        home_games = match.get("home", {}).get("historical_games", 0)
        home_prob = 55.0 if home_games else 45.0
        return {"probs": {"home_win": home_prob, "draw": 25.0, "away_win": 75.0 - home_prob}}


class HistoricalModelLabTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.lab = HistoricalModelLab(os.path.join(self.temp_dir.name, "lab.sqlite3"))

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def record(index, league="Test Ligi"):
        kickoff = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
        return {
            "id": f"hist-{index}", "kickoff": kickoff.isoformat(),
            "feature_cutoff": (kickoff - timedelta(hours=1)).isoformat(),
            "result_observed_at": (kickoff + timedelta(hours=2)).isoformat(),
            "league": league, "home_name": "Ev", "away_name": "Dep",
            "home_score": 2 if index % 2 == 0 else 0,
            "away_score": 0 if index % 2 == 0 else 1,
            "home_odds": 2.1, "draw_odds": 3.2, "away_odds": 3.4,
        }

    def test_import_rejects_future_information_and_deduplicates(self):
        valid = self.record(0)
        leaked = self.record(1)
        leaked["feature_cutoff"] = "2025-01-03T00:00:00+00:00"
        result = self.lab.import_records([valid, valid, leaked], "test")
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["rejected"], 1)
        status = self.lab.status()
        self.assertEqual(status["historical_matches"], 1)
        self.assertTrue(status["leakage_guard"])

    def test_walk_forward_uses_only_prior_results_and_persists_report(self):
        result = self.lab.import_records([self.record(index) for index in range(12)], "test")
        self.assertEqual(result["inserted"], 12)
        report = self.lab.run_walk_forward(DeterministicPredictor, minimum_history=3)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["evaluated_matches"], 9)
        self.assertTrue(report["chronological"])
        self.assertTrue(report["leakage_guard"])
        self.assertIsNotNone(report["brier_score"])
        status = self.lab.status()
        self.assertEqual(status["latest_walk_forward"]["evaluated_matches"], 9)
        self.assertEqual(self.lab.evidence_for("Test Ligi")["samples"], 9)

    def test_small_dataset_does_not_claim_verified_accuracy(self):
        self.lab.import_records([self.record(0), self.record(1)], "test")
        report = self.lab.run_walk_forward(DeterministicPredictor, minimum_history=3)
        self.assertEqual(report["status"], "insufficient_data")
        self.assertEqual(self.lab.status()["readiness"], "collecting")


if __name__ == "__main__":
    unittest.main()

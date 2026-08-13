import unittest

from predictor_candidate import PredictorEngineVNext


class PredictorCandidateTests(unittest.TestCase):
    def test_candidate_is_calibrated_but_marked_shadow_only(self):
        match = {
            "id": "shadow-1", "status": "SCHEDULED",
            "home": {"name": "A", "form": ["W"] * 5},
            "away": {"name": "B", "form": ["L"] * 5},
            "home_odds": None, "draw_odds": None, "away_odds": None,
            "odds_available": False, "stats_quality": "mackolik_score_only",
        }
        result = PredictorEngineVNext().analyze_match(match)
        self.assertAlmostEqual(sum(result["probs"].values()), 100.0, places=1)
        self.assertTrue(result["model_meta"]["shadow_only"])
        self.assertEqual(result["model_meta"]["version"], "18000.0-SHADOW-CONSERVATIVE")

    def test_data_trust_exposes_missing_inputs(self):
        match = {
            "id": "trust-1", "status": "SCHEDULED", "data_source": "Maçkolik",
            "home": {"name": "A"}, "away": {"name": "B"},
            "home_odds": None, "draw_odds": None, "away_odds": None,
            "odds_available": False, "stats_quality": "mackolik_score_only",
        }
        result = PredictorEngineVNext().analyze_match(match)
        trust = result["model_meta"]["data_trust"]
        self.assertIn("kesin ilk 11", trust["missing"])
        self.assertIn(trust["grade"], {"A", "B", "C", "D"})


if __name__ == "__main__":
    unittest.main()

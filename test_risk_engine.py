import unittest

from risk_engine import CouponRiskEngine


class CouponRiskEngineTests(unittest.TestCase):
    def test_negative_edge_coupon_gets_zero_stake(self):
        result = CouponRiskEngine().analyze([
            {"matchId": "a", "odds": 1.80, "prob": 45},
            {"matchId": "b", "odds": 1.80, "prob": 45},
        ], bankroll=10000)
        self.assertEqual(result["recommended_stake"], 0.0)
        self.assertLess(result["expected_value_pct"], 0)

    def test_correlated_coupon_is_penalized_and_capped(self):
        matches = [
            {"id": "a", "league": "Süper Lig", "local_date": "2026-08-13"},
            {"id": "b", "league": "Süper Lig", "local_date": "2026-08-13"},
            {"id": "c", "league": "Süper Lig", "local_date": "2026-08-13"},
        ]
        picks = [{"matchId": key, "odds": 2.20, "prob": 58} for key in ("a", "b", "c")]
        result = CouponRiskEngine().analyze(picks, matches, 10000)
        self.assertEqual(result["correlated_pairs"], 3)
        self.assertGreater(result["dependency_haircut_pct"], 0)
        self.assertLessEqual(result["recommended_stake"], 200)
        self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()

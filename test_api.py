import unittest
import tempfile
import os

from app import Api, HTTP_GET_METHODS, HTTP_POST_METHODS


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.api = Api(
            os.path.join(self.temp_dir.name, "learning.sqlite3"),
            os.path.join(self.temp_dir.name, "flags.json"),
            os.path.join(self.temp_dir.name, "matches.json"),
        )
        self.matches = [{
            "id": "m1", "status": "SCHEDULED", "league": "Test League",
            "match_date": "Bugün", "match_time": "20:00", "data_source": "TEST",
            "home": {"name": "A", "form": ["W"] * 5},
            "away": {"name": "B", "form": ["L"] * 5},
            "home_odds": 2.0, "draw_odds": 3.2, "away_odds": 3.8,
        }]
        self.api.fetcher.fetch_live_fixtures = lambda: self.matches

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_analysis_response_contains_completion_metadata(self):
        result = self.api.get_matches_with_analysis()
        self.assertEqual(result["meta"]["total_matches"], 1)
        self.assertEqual(result["meta"]["analyzed_matches"], 1)
        self.assertTrue(result["meta"]["is_complete"])
        self.assertTrue(result["meta"]["shadow"]["enabled"])
        self.assertEqual(result["meta"]["shadow"]["sample_size"], 1)
        self.assertEqual(result["analyses"]["m1"]["monte_carlo"]["runs"], 0)
        self.assertEqual(result["analyses"]["m1"]["model_meta"]["probability_engine"], "exact_dixon_coles")
        self.assertIn("input_quality", result["analyses"]["m1"]["model_meta"])
        self.assertEqual(result["analyses"]["m1"]["model_meta"]["evidence"]["grade"], "UNVERIFIED")

    def test_priority_analysis_returns_visible_prediction_immediately(self):
        self.api.get_matches()
        result = self.api.get_priority_analyses(["m1"])
        self.assertEqual(result["completed"], 1)
        self.assertIn("probs", result["analyses"]["m1"])
        self.assertIn("best_bet", result["analyses"]["m1"])

    def test_priority_analysis_is_available_to_http_fallback(self):
        self.assertIn("get_priority_analyses", HTTP_GET_METHODS)
        self.assertIn("get_priority_analyses", HTTP_POST_METHODS)
        self.assertIn("get_model_performance", HTTP_GET_METHODS)

    def test_model_performance_exposes_truth_policy(self):
        report = self.api.get_model_performance()
        self.assertTrue(report["truth_policy"]["one_match_one_vote"])
        self.assertTrue(report["truth_policy"]["prematch_lock"])
        self.assertFalse(report["model_gate"]["automatic_promotion"])

    def test_finished_matches_are_settled_but_hidden_from_bulletin(self):
        finished = dict(self.matches[0])
        finished.update({"id": "done", "status": "POST", "live_score": {"home": 2, "away": 1}})
        self.api.fetcher.fetch_live_fixtures = lambda: [finished, self.matches[0]]
        visible = self.api.get_matches()
        self.assertEqual([match["id"] for match in visible], ["m1"])

    def test_health_endpoint_has_fetch_analysis_and_cache_sections(self):
        self.api.get_matches_with_analysis()
        health = self.api.get_system_health()
        self.assertIn("fetcher", health)
        self.assertIn("analysis", health)
        self.assertIn("model_learning", health)
        self.assertIn("model_lab", health)
        self.assertTrue(health["model_lab"]["leakage_guard"])
        self.assertIn("external_data", health)
        self.assertIn("safe_upgrade", health)
        self.assertTrue(health["safe_upgrade"]["safe_mode"])
        self.assertTrue(health["safe_upgrade"]["flags"]["match_contract_v2"])
        self.assertEqual(health["match_cache"]["count"], 1)

    def test_invalid_provider_row_is_blocked_before_prediction(self):
        self.api.fetcher.fetch_live_fixtures = lambda: [{"id": "bad", "home": {}, "away": {"name": "B"}}]
        self.assertEqual(self.api.get_matches(), [])
        health = self.api.get_system_health()
        self.assertEqual(health["match_contract"]["rejected"], 1)

    def test_score_only_analysis_does_not_invent_odds_ev_or_kelly(self):
        match = dict(self.matches[0])
        match.update({"home_odds": None, "draw_odds": None, "away_odds": None, "odds_available": False, "stats_quality": "mackolik_score_only", "data_source": "Maçkolik"})
        analysis = self.api.predictor.analyze_match(match)
        self.assertFalse(analysis["model_meta"]["market_odds_used"])
        self.assertIsNone(analysis["best_bet"]["odds"])
        self.assertIsNone(analysis["best_bet"]["ev"])
        self.assertEqual(analysis["best_bet"]["kelly"], 0.0)
        self.assertLessEqual(analysis["confidence"]["rank"], 3)
        self.assertGreaterEqual(analysis["model_meta"]["structural_uncertainty_pct"], 10)
        self.assertAlmostEqual(sum(analysis["probs"].values()), 100.0, places=1)

    def test_real_market_odds_activate_calibration_and_ev(self):
        match = dict(self.matches[0])
        match.update({"odds_available": True, "odds_are_estimated": False, "data_source": "Maçkolik"})
        analysis = self.api.predictor.analyze_match(match)
        self.assertTrue(analysis["model_meta"]["market_odds_used"])
        self.assertEqual(analysis["model_meta"]["calibration_profile"], "Mackolik market + ensemble")
        self.assertIsNotNone(analysis["all_ev"]["home"]["ev"])
        self.assertGreaterEqual(analysis["model_meta"]["input_quality"]["score"], 80)

    def test_late_live_lead_uses_current_score_and_remaining_time(self):
        match = dict(self.matches[0])
        match.update({
            "id": "live-85", "status": "IN_PROGRESS", "game_clock": "85'",
            "live_score": {"home": 2, "away": 0}, "data_source": "Maçkolik",
            "home_odds": None, "draw_odds": None, "away_odds": None,
            "odds_available": False, "stats_quality": "mackolik_score_only",
        })
        analysis = self.api.predictor.analyze_match(match)
        self.assertGreater(analysis["probs"]["home_win"], 85.0)
        self.assertEqual(analysis["model_meta"]["live_clock"], 85)
        self.assertLess(analysis["model_meta"]["remaining_xg"]["home"], 0.2)
        for score, _ in analysis["top_scores"]:
            self.assertGreaterEqual(int(score.split("-")[0].strip()), 2)

    def test_red_card_reduces_live_scoring_strength(self):
        base = dict(self.matches[0])
        base.update({"id": "live-base", "status": "IN_PROGRESS", "game_clock": "60'", "live_score": {"home": 0, "away": 0}, "odds_available": False, "home_odds": None, "draw_odds": None, "away_odds": None})
        red = dict(base)
        red.update({"id": "live-red", "red_cards_home": 1})
        normal_analysis = self.api.predictor.analyze_match(base)
        red_analysis = self.api.predictor.analyze_match(red)
        self.assertLess(red_analysis["model_meta"]["remaining_xg"]["home"], normal_analysis["model_meta"]["remaining_xg"]["home"])

    def test_exact_engine_is_deterministic_and_probabilities_balance(self):
        match = dict(self.matches[0], id="exact-repeat")
        first = self.api.predictor.analyze_match(match)
        self.api.predictor._cache.clear()
        second = self.api.predictor.analyze_match(match)
        self.assertEqual(first["probs"], second["probs"])
        self.assertEqual(first["outcomes"], second["outcomes"])
        self.assertAlmostEqual(sum(first["probs"].values()), 100.0, places=1)
        self.assertEqual(first["monte_carlo"]["method"], "exact_dixon_coles")

    def test_market_change_invalidates_prematch_prediction_cache(self):
        match = dict(self.matches[0], id="market-move")
        first = self.api.predictor.analyze_match(match)
        match["home_odds"], match["away_odds"] = 1.45, 7.0
        second = self.api.predictor.analyze_match(match)
        self.assertGreater(second["probs"]["home_win"], first["probs"]["home_win"])

    def test_verified_absence_data_changes_xg_and_is_auditable(self):
        base = dict(self.matches[0], id="squad-base")
        normal = self.api.predictor.analyze_match(base)
        affected = dict(base, id="squad-affected", verified_absences={
            "source": "API-Football",
            "home": [{"player": f"P{i}", "type": "Missing Fixture"} for i in range(3)],
            "away": [],
        })
        analysis = self.api.predictor.analyze_match(affected)
        self.assertLess(analysis["xg_home"], normal["xg_home"])
        self.assertEqual(analysis["model_meta"]["squad_data"]["source"], "API-Football")
        self.assertEqual(analysis["model_meta"]["squad_data"]["home_absence_weight"], 3.0)

    def test_consensus_market_is_used_only_when_mackolik_odds_are_missing(self):
        match = dict(self.matches[0], id="consensus-only")
        match.update({
            "home_odds": None, "draw_odds": None, "away_odds": None,
            "odds_available": False,
            "consensus_odds": {"home": 1.80, "draw": 3.60, "away": 4.50, "source": "The Odds API"},
        })
        analysis = self.api.predictor.analyze_match(match)
        self.assertTrue(analysis["model_meta"]["market_odds_used"])
        self.assertEqual(analysis["model_meta"]["market_source"], "The Odds API")
        self.assertIsNotNone(analysis["all_ev"]["home"]["ev"])

    def test_late_scoreless_match_does_not_get_artificial_over_floor(self):
        match = dict(self.matches[0])
        match.update({
            "id": "late-scoreless", "status": "IN_PROGRESS", "game_clock": "88'",
            "live_score": {"home": 0, "away": 0}, "odds_available": False,
            "home_odds": None, "draw_odds": None, "away_odds": None,
        })
        analysis = self.api.predictor.analyze_match(match)
        self.assertLess(analysis["outcomes"]["over_15"], 10.0)
        self.assertGreater(analysis["probs"]["draw"], 80.0)

    def test_empty_provider_result_is_short_lived_cached(self):
        calls = {"count": 0}
        def empty_fetch():
            calls["count"] += 1
            return []
        self.api.fetcher.fetch_live_fixtures = empty_fetch
        self.api.get_matches()
        self.api.get_matches_with_analysis()
        self.assertEqual(calls["count"], 1)

    def test_recent_disk_bulletin_is_returned_before_provider_refresh(self):
        import time
        from datetime import datetime
        warm = [dict(self.matches[0], id="warm-1")]
        self.api.fetcher._last_real_matches = warm
        self.api.fetcher._last_success_at = datetime.now().astimezone()
        provider_started = __import__("threading").Event()
        provider_release = __import__("threading").Event()

        def slow_provider():
            provider_started.set()
            provider_release.wait(2)
            return [dict(self.matches[0], id="fresh-1")]

        self.api.fetcher.fetch_live_fixtures = slow_provider
        started = time.perf_counter()
        result = self.api.get_matches()
        elapsed = time.perf_counter() - started
        self.assertEqual(result[0]["id"], "warm-1")
        self.assertLess(elapsed, 0.5)
        self.assertTrue(provider_started.wait(1))
        self.assertTrue(self.api.get_system_health()["fast_start"]["used"])
        provider_release.set()
        self.api._provider_refresh_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

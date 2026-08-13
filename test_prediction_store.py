import os
import tempfile
import unittest
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from prediction_store import PredictionStore


class PredictionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = PredictionStore(os.path.join(self.temp_dir.name, "history.sqlite3"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_predictions_settle_metrics_and_team_ratings(self):
        for index in range(30):
            match_id = f"m-{index}"
            kickoff = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            match = {
                "id": match_id, "status": "SCHEDULED", "iso_date": kickoff,
                "data_source": "Maçkolik", "league": "Test Ligi", "home": {"name": f"Home {index % 3}"},
                "away": {"name": f"Away {index % 3}"},
            }
            analysis = {
                "probs": {"home_win": 60.0, "draw": 25.0, "away_win": 15.0},
                "model_meta": {"version": "test-model", "components": {
                    "neural": [50.0, 30.0, 20.0],
                    "exact_score_matrix": [65.0, 22.0, 13.0],
                    "elo": [55.0, 25.0, 20.0],
                }},
            }
            self.store.record_prediction(match, analysis)
            match.update({"status": "POST", "live_score": {"home": 2, "away": 1}})
            self.assertTrue(self.store.settle_match(match))
            self.assertFalse(self.store.settle_match(match))

        metrics = self.store.metrics()
        self.assertEqual(metrics["settled_predictions"], 30)
        self.assertEqual(metrics["accuracy_pct"], 100.0)
        self.assertIsNotNone(metrics["brier_score"])
        self.assertEqual(metrics["calibration_status"], "Aktif kalibrasyon")
        self.assertIn("drift_status", metrics)
        self.assertGreater(metrics["learned_teams"], 0)
        self.assertEqual(set(metrics["component_brier"]), {"neural", "dixon_coles", "elo"})
        self.assertIsNotNone(metrics["adaptive_component_weights"])
        self.assertEqual(metrics["league_backtest"][0]["league"], "Test Ligi")
        self.assertEqual(metrics["locked_predictions"], 30)
        self.assertEqual(metrics["pending_settlements"], 0)
        self.assertIn("Test Ligi", metrics["calibration_by_league"])
        self.assertTrue(metrics["reliability_bins"])

        matches = [{"id": "next", "league": "Test Ligi", "home": {"name": "Home 0"}, "away": {"name": "Away 0"}}]
        self.store.enrich_matches(matches)
        self.assertGreater(matches[0]["home"]["historical_games"], 0)
        self.assertGreater(matches[0]["home"]["home_attack_rating"], 1.42)
        self.assertEqual(matches[0]["league_profile"]["games"], 30)

    def test_real_odds_snapshots_create_opening_movement(self):
        match = {
            "id": "odds-1", "league": "Test", "odds_available": True,
            "odds_are_estimated": False, "home_odds": 2.20, "draw_odds": 3.20,
            "away_odds": 3.40, "home": {"name": "A"}, "away": {"name": "B"},
        }
        self.assertEqual(self.store.record_odds_snapshots([match]), 1)
        match["home_odds"] = 1.98
        self.store.enrich_matches([match])
        self.assertEqual(match["opening_odds"]["home"], 2.20)
        self.assertEqual(match["odds_drop_pct"], -10.0)

    def test_existing_database_is_migrated_without_losing_history(self):
        legacy_path = os.path.join(self.temp_dir.name, "legacy.sqlite3")
        with closing(sqlite3.connect(legacy_path)) as db:
            db.executescript("""
                CREATE TABLE predictions(match_id TEXT, phase TEXT, model_version TEXT, created_at TEXT,
                    home_name TEXT, away_name TEXT, kickoff TEXT, source TEXT, home_prob REAL,
                    draw_prob REAL, away_prob REAL, actual TEXT, settled_at TEXT,
                    PRIMARY KEY(match_id, phase, model_version));
                CREATE TABLE settled_matches(match_id TEXT PRIMARY KEY, home_name TEXT, away_name TEXT,
                    home_score INTEGER, away_score INTEGER, settled_at TEXT);
                CREATE TABLE team_ratings(team_name TEXT PRIMARY KEY, elo REAL, games INTEGER,
                    goals_for_ema REAL, goals_against_ema REAL, updated_at TEXT);
            """)
            db.commit()
        PredictionStore(legacy_path)
        with closing(sqlite3.connect(legacy_path)) as db:
            prediction_columns = {row[1] for row in db.execute("PRAGMA table_info(predictions)")}
            team_columns = {row[1] for row in db.execute("PRAGMA table_info(team_ratings)")}
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"league", "components_json"}.issubset(prediction_columns))
        self.assertTrue({"home_games", "away_games", "home_goals_for_ema", "away_goals_for_ema"}.issubset(team_columns))
        self.assertTrue({"league_profiles", "odds_snapshots"}.issubset(tables))

    def test_one_match_has_one_canonical_prematch_vote(self):
        kickoff = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        match = {"id": "one-vote", "status": "SCHEDULED", "iso_date": kickoff,
                 "league": "Test", "home": {"name": "A"}, "away": {"name": "B"}}
        for version, home_prob in (("stable", 55.0), ("candidate", 65.0)):
            self.store.record_prediction(match, {"probs": {"home_win": home_prob, "draw": 25.0,
                                                             "away_win": 75.0-home_prob},
                                                 "model_meta": {"version": version}})
        live = dict(match, status="IN_PROGRESS", game_clock="55'", live_score={"home": 1, "away": 0})
        self.store.record_prediction(live, {"probs": {"home_win": 80.0, "draw": 15.0, "away_win": 5.0},
                                            "model_meta": {"version": "stable"}})
        finished = dict(match, status="POST", live_score={"home": 2, "away": 0})
        self.store.settle_match(finished)
        metrics = self.store.metrics()
        self.assertEqual(metrics["settled_predictions"], 1)
        self.assertEqual(metrics["locked_predictions"], 1)

    def test_prediction_after_kickoff_is_not_locked(self):
        kickoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        match = {"id": "late", "status": "SCHEDULED", "iso_date": kickoff,
                 "league": "Test", "home": {"name": "A"}, "away": {"name": "B"}}
        self.store.record_prediction(match, {"probs": {"home_win": 50.0, "draw": 30.0, "away_win": 20.0},
                                             "model_meta": {"version": "stable"}})
        self.assertEqual(self.store.metrics()["locked_predictions"], 0)


if __name__ == "__main__":
    unittest.main()

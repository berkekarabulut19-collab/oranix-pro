"""Persistent learning, calibration and audit store for Oranix predictions."""

import json
import math
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone


ISTANBUL_TZ = timezone(timedelta(hours=3), name="Europe/Istanbul")


class PredictionStore:
    def __init__(self, db_path=None):
        app_data = os.environ.get("LOCALAPPDATA") or os.path.dirname(__file__)
        self.db_path = db_path or os.path.join(app_data, "OranixPro", "prediction_history.sqlite3")
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=8)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=8000")
        return connection

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _ensure_schema(self):
        with self._lock, self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS predictions (
                    match_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    home_name TEXT NOT NULL,
                    away_name TEXT NOT NULL,
                    kickoff TEXT,
                    source TEXT,
                    home_prob REAL NOT NULL,
                    draw_prob REAL NOT NULL,
                    away_prob REAL NOT NULL,
                    actual TEXT,
                    settled_at TEXT,
                    PRIMARY KEY (match_id, phase, model_version)
                );
                CREATE TABLE IF NOT EXISTS settled_matches (
                    match_id TEXT PRIMARY KEY,
                    home_name TEXT NOT NULL,
                    away_name TEXT NOT NULL,
                    home_score INTEGER NOT NULL,
                    away_score INTEGER NOT NULL,
                    settled_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS team_ratings (
                    team_name TEXT PRIMARY KEY,
                    elo REAL NOT NULL DEFAULT 1500,
                    games INTEGER NOT NULL DEFAULT 0,
                    goals_for_ema REAL NOT NULL DEFAULT 1.35,
                    goals_against_ema REAL NOT NULL DEFAULT 1.35,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS league_profiles (
                    league TEXT PRIMARY KEY,
                    games INTEGER NOT NULL DEFAULT 0,
                    avg_home_goals REAL NOT NULL DEFAULT 1.42,
                    avg_away_goals REAL NOT NULL DEFAULT 1.18,
                    home_win_rate REAL NOT NULL DEFAULT 0.43,
                    draw_rate REAL NOT NULL DEFAULT 0.28,
                    low_score_rate REAL NOT NULL DEFAULT 0.35,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS odds_snapshots (
                    match_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    home_odds REAL NOT NULL,
                    draw_odds REAL NOT NULL,
                    away_odds REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'Mackolik',
                    PRIMARY KEY (match_id, captured_at)
                );
                CREATE INDEX IF NOT EXISTS idx_odds_match_time ON odds_snapshots(match_id, captured_at);
                CREATE TABLE IF NOT EXISTS prediction_locks (
                    match_id TEXT PRIMARY KEY,
                    model_version TEXT NOT NULL,
                    locked_at TEXT NOT NULL,
                    kickoff TEXT,
                    league TEXT,
                    source TEXT,
                    home_name TEXT NOT NULL,
                    away_name TEXT NOT NULL,
                    home_prob REAL NOT NULL,
                    draw_prob REAL NOT NULL,
                    away_prob REAL NOT NULL,
                    components_json TEXT,
                    actual TEXT,
                    settled_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_prediction_locks_settled
                    ON prediction_locks(actual, settled_at);
            """)
            self._ensure_column(db, "predictions", "league", "TEXT")
            self._ensure_column(db, "predictions", "components_json", "TEXT")
            self._ensure_column(db, "settled_matches", "league", "TEXT")
            self._ensure_column(db, "team_ratings", "home_games", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(db, "team_ratings", "away_games", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(db, "team_ratings", "home_goals_for_ema", "REAL NOT NULL DEFAULT 1.42")
            self._ensure_column(db, "team_ratings", "home_goals_against_ema", "REAL NOT NULL DEFAULT 1.18")
            self._ensure_column(db, "team_ratings", "away_goals_for_ema", "REAL NOT NULL DEFAULT 1.18")
            self._ensure_column(db, "team_ratings", "away_goals_against_ema", "REAL NOT NULL DEFAULT 1.42")
            self._ensure_column(db, "odds_snapshots", "source", "TEXT NOT NULL DEFAULT 'Mackolik'")
            # Preserve the earliest pre-match forecast from existing installs.
            # This table is the canonical, one-match-one-vote evaluation set.
            db.execute("""
                INSERT OR IGNORE INTO prediction_locks
                (match_id, model_version, locked_at, kickoff, league, source, home_name,
                 away_name, home_prob, draw_prob, away_prob, components_json, actual, settled_at)
                SELECT p.match_id, p.model_version, p.created_at, p.kickoff, p.league, p.source,
                       p.home_name, p.away_name, p.home_prob, p.draw_prob, p.away_prob,
                       p.components_json, p.actual, p.settled_at
                FROM predictions p
                WHERE p.phase='prematch' AND p.created_at=(
                    SELECT MIN(p2.created_at) FROM predictions p2
                    WHERE p2.match_id=p.match_id AND p2.phase='prematch'
                )
            """)

    @staticmethod
    def _ensure_column(db, table, column, definition):
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _phase(match):
        if match.get("status") == "IN_PROGRESS":
            digits = "".join(ch for ch in str(match.get("game_clock", "")) if ch.isdigit())
            minute = min(90, int(digits or 45))
            return f"live_{(minute // 5) * 5:02d}"
        return "prematch"

    @staticmethod
    def kickoff_for(match):
        raw = str(match.get("iso_date") or "").strip()
        scheduled = str(match.get("scheduled_time") or match.get("match_time") or "").strip()
        if len(raw) == 10 and len(scheduled) >= 5 and scheduled[2:3] == ":":
            raw = f"{raw}T{scheduled[:5]}:00+03:00"
        elif len(raw) == 10:
            # A date without a scheduled time cannot be used as a trustworthy
            # cut-off; keep the prediction but mark kickoff as unverified.
            return None
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ISTANBUL_TZ)
            return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            return None

    @classmethod
    def _lockable(cls, match, created_at):
        if cls._phase(match) != "prematch" or str(match.get("status") or "").upper() != "SCHEDULED":
            return False
        kickoff = cls.kickoff_for(match)
        if not kickoff:
            return True
        try:
            return datetime.fromisoformat(created_at) <= datetime.fromisoformat(kickoff)
        except ValueError:
            return False

    def record_prediction(self, match, analysis):
        self.record_predictions_batch([(match, analysis)])

    def record_predictions_batch(self, records):
        """Persist an analyzed bulletin using one SQLite transaction."""
        rows, lock_rows = [], []
        created_at = datetime.now(timezone.utc).isoformat()
        for match, analysis in records:
            probs = analysis.get("probs", {})
            if not all(isinstance(probs.get(key), (int, float)) for key in ("home_win", "draw", "away_win")):
                continue
            kickoff = self.kickoff_for(match) or match.get("iso_date")
            model_version = analysis.get("model_meta", {}).get("version", "unknown")
            components_json = json.dumps(analysis.get("model_meta", {}).get("components", {}), ensure_ascii=False)
            rows.append((
                str(match.get("id")), self._phase(match), model_version,
                created_at, match.get("home", {}).get("name", "Ev Sahibi"),
                match.get("away", {}).get("name", "Deplasman"), kickoff,
                match.get("data_source", ""), float(probs["home_win"]), float(probs["draw"]),
                float(probs["away_win"]), match.get("league", ""),
                components_json,
            ))
            if self._lockable(match, created_at):
                lock_rows.append((
                    str(match.get("id")), model_version, created_at, kickoff, match.get("league", ""),
                    match.get("data_source", ""), match.get("home", {}).get("name", "Ev Sahibi"),
                    match.get("away", {}).get("name", "Deplasman"), float(probs["home_win"]),
                    float(probs["draw"]), float(probs["away_win"]), components_json,
                ))
        if not rows:
            return 0
        with self._lock, self._db() as db:
            db.executemany("""
                INSERT OR IGNORE INTO predictions
                (match_id, phase, model_version, created_at, home_name, away_name, kickoff, source,
                 home_prob, draw_prob, away_prob, league, components_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            if lock_rows:
                db.executemany("""
                    INSERT OR IGNORE INTO prediction_locks
                    (match_id, model_version, locked_at, kickoff, league, source, home_name,
                     away_name, home_prob, draw_prob, away_prob, components_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, lock_rows)
        return len(rows)

    def settle_match(self, match):
        if match.get("status") != "POST" or not isinstance(match.get("live_score"), dict):
            return False
        match_id = str(match.get("id"))
        home_name = match.get("home", {}).get("name", "Ev Sahibi")
        away_name = match.get("away", {}).get("name", "Deplasman")
        league = str(match.get("league") or "Diğer Ligler")
        home_score = int(match["live_score"].get("home", 0))
        away_score = int(match["live_score"].get("away", 0))
        actual = "H" if home_score > away_score else ("A" if away_score > home_score else "D")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._db() as db:
            exists = db.execute("SELECT 1 FROM settled_matches WHERE match_id=?", (match_id,)).fetchone()
            db.execute("UPDATE predictions SET actual=?, settled_at=? WHERE match_id=? AND actual IS NULL", (actual, now, match_id))
            db.execute("UPDATE prediction_locks SET actual=?, settled_at=? WHERE match_id=? AND actual IS NULL", (actual, now, match_id))
            if exists:
                return False
            db.execute("""INSERT INTO settled_matches
                       (match_id, home_name, away_name, home_score, away_score, settled_at, league)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                       (match_id, home_name, away_name, home_score, away_score, now, league))
            self._update_team_ratings(db, home_name, away_name, home_score, away_score, now)
            self._update_league_profile(db, league, home_score, away_score, now)
        return True

    @staticmethod
    def _team_row(db, name):
        row = db.execute("SELECT * FROM team_ratings WHERE team_name=?", (name,)).fetchone()
        return dict(row) if row else {
            "elo": 1500.0, "games": 0, "goals_for_ema": 1.35, "goals_against_ema": 1.35,
            "home_games": 0, "away_games": 0, "home_goals_for_ema": 1.42,
            "home_goals_against_ema": 1.18, "away_goals_for_ema": 1.18,
            "away_goals_against_ema": 1.42, "updated_at": None,
        }

    def _update_team_ratings(self, db, home_name, away_name, home_score, away_score, now):
        home = self._decay_team_profile(self._team_row(db, home_name), now)
        away = self._decay_team_profile(self._team_row(db, away_name), now)
        expected_home = 1.0 / (1.0 + 10 ** (-((home["elo"] + 65.0) - away["elo"]) / 400.0))
        actual_home = 1.0 if home_score > away_score else (0.0 if home_score < away_score else 0.5)
        margin = max(1, abs(home_score - away_score))
        k = 24.0 * (1.0 + min(2.0, (margin - 1) * 0.25))
        delta = k * (actual_home - expected_home)
        alpha = 0.18

        def save(name, row, elo, goals_for, goals_against, venue):
            gf = row["goals_for_ema"] * (1 - alpha) + goals_for * alpha
            ga = row["goals_against_ema"] * (1 - alpha) + goals_against * alpha
            hg = int(row.get("home_games", 0)) + (1 if venue == "home" else 0)
            ag = int(row.get("away_games", 0)) + (1 if venue == "away" else 0)
            hgf = row.get("home_goals_for_ema", 1.42)
            hga = row.get("home_goals_against_ema", 1.18)
            agf = row.get("away_goals_for_ema", 1.18)
            aga = row.get("away_goals_against_ema", 1.42)
            if venue == "home":
                hgf, hga = hgf * (1 - alpha) + goals_for * alpha, hga * (1 - alpha) + goals_against * alpha
            else:
                agf, aga = agf * (1 - alpha) + goals_for * alpha, aga * (1 - alpha) + goals_against * alpha
            db.execute("""
                INSERT INTO team_ratings(team_name, elo, games, goals_for_ema, goals_against_ema, updated_at,
                    home_games, away_games, home_goals_for_ema, home_goals_against_ema,
                    away_goals_for_ema, away_goals_against_ema)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_name) DO UPDATE SET elo=excluded.elo, games=excluded.games,
                    goals_for_ema=excluded.goals_for_ema, goals_against_ema=excluded.goals_against_ema,
                    home_games=excluded.home_games, away_games=excluded.away_games,
                    home_goals_for_ema=excluded.home_goals_for_ema,
                    home_goals_against_ema=excluded.home_goals_against_ema,
                    away_goals_for_ema=excluded.away_goals_for_ema,
                    away_goals_against_ema=excluded.away_goals_against_ema,
                    updated_at=excluded.updated_at
            """, (name, round(elo, 2), row["games"] + 1, round(gf, 4), round(ga, 4), now,
                  hg, ag, round(hgf, 4), round(hga, 4), round(agf, 4), round(aga, 4)))

        save(home_name, home, home["elo"] + delta, home_score, away_score, "home")
        save(away_name, away, away["elo"] - delta, away_score, home_score, "away")

    @staticmethod
    def _decay_team_profile(row, now):
        """Regress stale ratings toward neutral with a one-year half-life."""
        updated = row.get("updated_at")
        if not updated:
            return row
        try:
            days = max(0.0, (datetime.fromisoformat(now) - datetime.fromisoformat(updated)).total_seconds() / 86400.0)
        except (TypeError, ValueError):
            return row
        keep = math.exp(-math.log(2.0) * days / 365.0)
        result = dict(row)
        result["elo"] = 1500.0 + (float(row["elo"]) - 1500.0) * keep
        for key, neutral in (("goals_for_ema", 1.35), ("goals_against_ema", 1.35),
                             ("home_goals_for_ema", 1.42), ("home_goals_against_ema", 1.18),
                             ("away_goals_for_ema", 1.18), ("away_goals_against_ema", 1.42)):
            result[key] = neutral + (float(row.get(key, neutral)) - neutral) * keep
        return result

    @staticmethod
    def _update_league_profile(db, league, home_score, away_score, now):
        row = db.execute("SELECT * FROM league_profiles WHERE league=?", (league,)).fetchone()
        current = dict(row) if row else {"games": 0, "avg_home_goals": 1.42, "avg_away_goals": 1.18,
                                         "home_win_rate": 0.43, "draw_rate": 0.28, "low_score_rate": 0.35}
        # Smaller alpha than team form: league scoring environments move slowly.
        alpha = 0.06
        values = (
            current["games"] + 1,
            current["avg_home_goals"] * (1 - alpha) + home_score * alpha,
            current["avg_away_goals"] * (1 - alpha) + away_score * alpha,
            current["home_win_rate"] * (1 - alpha) + (1.0 if home_score > away_score else 0.0) * alpha,
            current["draw_rate"] * (1 - alpha) + (1.0 if home_score == away_score else 0.0) * alpha,
            current["low_score_rate"] * (1 - alpha) + (1.0 if home_score + away_score <= 2 else 0.0) * alpha,
        )
        db.execute("""INSERT INTO league_profiles
                   (league, games, avg_home_goals, avg_away_goals, home_win_rate, draw_rate, low_score_rate, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(league) DO UPDATE SET games=excluded.games,
                   avg_home_goals=excluded.avg_home_goals, avg_away_goals=excluded.avg_away_goals,
                   home_win_rate=excluded.home_win_rate, draw_rate=excluded.draw_rate,
                   low_score_rate=excluded.low_score_rate, updated_at=excluded.updated_at""",
                   (league, *values, now))

    def enrich_matches(self, matches):
        names = {m.get(side, {}).get("name") for m in matches for side in ("home", "away")}
        names.discard(None)
        leagues = {str(m.get("league") or "Diğer Ligler") for m in matches}
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._db() as db:
            profiles = {name: self._decay_team_profile(self._team_row(db, name), now) for name in names}
            league_profiles = {}
            for league in leagues:
                row = db.execute("SELECT * FROM league_profiles WHERE league=?", (league,)).fetchone()
                if row:
                    league_profiles[league] = dict(row)
            opening_odds = {}
            for match in matches:
                row = db.execute("""SELECT home_odds, draw_odds, away_odds, captured_at
                                  FROM odds_snapshots WHERE match_id=? ORDER BY captured_at ASC LIMIT 1""",
                                 (str(match.get("id")),)).fetchone()
                if row:
                    opening_odds[str(match.get("id"))] = dict(row)
        for match in matches:
            league = str(match.get("league") or "Diğer Ligler")
            if league in league_profiles:
                match["league_profile"] = league_profiles[league]
            for side in ("home", "away"):
                team = match.setdefault(side, {})
                profile = profiles.get(team.get("name"), {})
                if profile.get("games", 0) > 0:
                    team["elo_rating"] = profile["elo"]
                    team["attack_rating"] = max(0.55, min(2.40, profile["goals_for_ema"]))
                    team["defense_rating"] = max(0.55, min(2.40, profile["goals_against_ema"]))
                    team["historical_games"] = profile["games"]
                    team["home_attack_rating"] = max(0.55, min(2.40, profile.get("home_goals_for_ema", 1.42)))
                    team["home_defense_rating"] = max(0.55, min(2.40, profile.get("home_goals_against_ema", 1.18)))
                    team["away_attack_rating"] = max(0.55, min(2.40, profile.get("away_goals_for_ema", 1.18)))
                    team["away_defense_rating"] = max(0.55, min(2.40, profile.get("away_goals_against_ema", 1.42)))
            opening = opening_odds.get(str(match.get("id")))
            if opening and all(isinstance(match.get(key), (int, float)) for key in ("home_odds", "draw_odds", "away_odds")):
                match["opening_odds"] = {"home": opening["home_odds"], "draw": opening["draw_odds"], "away": opening["away_odds"]}
                match["odds_open"] = opening["home_odds"]
                match["odds_drop_pct"] = round((float(match["home_odds"]) / opening["home_odds"] - 1.0) * 100.0, 1)
        return matches

    def record_odds_snapshots(self, matches):
        """Track real Maçkolik 1X2 movement; estimated/demo odds are ignored."""
        captured = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        rows = []
        for match in matches:
            raw = (match.get("home_odds"), match.get("draw_odds"), match.get("away_odds"))
            try:
                valid = bool(match.get("odds_available")) and not match.get("odds_are_estimated") and all(float(v) > 1.01 for v in raw)
            except (TypeError, ValueError):
                valid = False
            if valid:
                rows.append((str(match.get("id")), captured, *[float(v) for v in raw], "Mackolik"))
            consensus = match.get("consensus_odds") or {}
            consensus_raw = (consensus.get("home"), consensus.get("draw"), consensus.get("away"))
            try:
                if all(float(value) > 1.01 for value in consensus_raw):
                    consensus_time = datetime.now(timezone.utc).isoformat(timespec="microseconds")
                    rows.append((str(match.get("id")), consensus_time, *[float(v) for v in consensus_raw],
                                 str(consensus.get("source") or "Verified market")))
            except (TypeError, ValueError):
                pass
        if not rows:
            return 0
        with self._lock, self._db() as db:
            db.executemany("""INSERT OR IGNORE INTO odds_snapshots
                           (match_id, captured_at, home_odds, draw_odds, away_odds, source)
                           VALUES (?, ?, ?, ?, ?, ?)""", rows)
        return len(rows)

    def metrics(self):
        with self._lock, self._db() as db:
            rows = db.execute("""
                SELECT home_prob, draw_prob, away_prob, actual, components_json, league,
                       model_version, match_id, settled_at
                FROM prediction_locks WHERE actual IS NOT NULL
                ORDER BY settled_at DESC LIMIT 5000
            """).fetchall()
            team_count = db.execute("SELECT COUNT(*) FROM team_ratings").fetchone()[0]
            locked_count = db.execute("SELECT COUNT(*) FROM prediction_locks").fetchone()[0]
            pending_count = db.execute("SELECT COUNT(*) FROM prediction_locks WHERE actual IS NULL").fetchone()[0]
        if not rows:
            return {"settled_predictions": 0, "brier_score": None, "log_loss": None,
                    "accuracy_pct": None, "ece_pct": None, "temperature": 1.0,
                    "learned_teams": team_count, "calibration_status": "Öğrenme verisi bekleniyor",
                    "drift_status": "Veri bekleniyor", "recent_brier": None,
                    "component_brier": {}, "adaptive_component_weights": None, "league_backtest": [],
                    "locked_predictions": locked_count, "pending_settlements": pending_count,
                    "calibration_by_league": {}, "reliability_bins": []}

        samples = []
        component_losses = {"neural": [0.0, 0.0], "dixon_coles": [0.0, 0.0], "elo": [0.0, 0.0]}
        league_scores = {}
        league_samples = {}
        correct = 0
        bins = [[] for _ in range(10)]
        brier_total = log_total = 0.0
        for row in rows:
            probs = [row["home_prob"] / 100.0, row["draw_prob"] / 100.0, row["away_prob"] / 100.0]
            actual_idx = {"H": 0, "D": 1, "A": 2}[row["actual"]]
            target = [1.0 if idx == actual_idx else 0.0 for idx in range(3)]
            brier_total += sum((probs[idx] - target[idx]) ** 2 for idx in range(3)) / 3.0
            log_total += -math.log(max(1e-9, probs[actual_idx]))
            predicted_idx = max(range(3), key=lambda idx: probs[idx])
            correct += int(predicted_idx == actual_idx)
            confidence = probs[predicted_idx]
            bins[min(9, int(confidence * 10))].append((confidence, int(predicted_idx == actual_idx)))
            samples.append((probs, actual_idx))
            league = row["league"] or "Diğer Ligler"
            league_bucket = league_scores.setdefault(league, [0.0, 0])
            league_bucket[0] += sum((probs[idx] - target[idx]) ** 2 for idx in range(3)) / 3.0
            league_bucket[1] += 1
            league_samples.setdefault(league, []).append((probs, actual_idx))
            try:
                components = json.loads(row["components_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                components = {}
            for stored_key, metric_key in (("neural", "neural"), ("exact_score_matrix", "dixon_coles"), ("elo", "elo")):
                vector = components.get(stored_key)
                if isinstance(vector, list) and len(vector) == 3:
                    normalized = [float(value) / 100.0 for value in vector]
                    loss = sum((normalized[idx] - target[idx]) ** 2 for idx in range(3)) / 3.0
                    component_losses[metric_key][0] += loss
                    component_losses[metric_key][1] += 1

        ece = sum((len(bucket) / len(rows)) * abs(sum(x[0] for x in bucket) / len(bucket) - sum(x[1] for x in bucket) / len(bucket)) for bucket in bins if bucket)
        temperature = self._best_temperature(samples) if len(samples) >= 30 else 1.0
        def window_brier(window):
            if not window:
                return None
            total = 0.0
            for row in window:
                probs = [row["home_prob"] / 100.0, row["draw_prob"] / 100.0, row["away_prob"] / 100.0]
                actual_idx = {"H": 0, "D": 1, "A": 2}[row["actual"]]
                total += sum((probs[idx] - (1.0 if idx == actual_idx else 0.0)) ** 2 for idx in range(3)) / 3.0
            return total / len(window)

        recent_brier = window_brier(rows[:50])
        previous_brier = window_brier(rows[50:100])
        if previous_brier is None:
            drift_status = "İzleme için veri birikiyor"
        elif recent_brier > previous_brier + 0.03:
            drift_status = "Performans düşüşü algılandı"
        else:
            drift_status = "Model dengeli"
        component_brier = {key: round(total / count, 4) for key, (total, count) in component_losses.items() if count >= 30}
        adaptive_weights = None
        if len(component_brier) == 3:
            learned_raw = {key: 1.0 / max(0.03, loss) for key, loss in component_brier.items()}
            learned_total = sum(learned_raw.values())
            learned = {key: value / learned_total for key, value in learned_raw.items()}
            defaults = {"neural": 0.08, "dixon_coles": 0.62, "elo": 0.30}
            adaptive_weights = {key: round(defaults[key] * 0.70 + learned[key] * 0.30, 4) for key in defaults}
        calibration_by_league = {}
        for league, league_rows in league_samples.items():
            if len(league_rows) < 30:
                continue
            raw_temperature = self._best_temperature(league_rows)
            shrink = min(1.0, max(0.0, (len(league_rows) - 20) / 80.0))
            calibration_by_league[league] = {
                "samples": len(league_rows),
                "temperature": round(1.0 + (raw_temperature - 1.0) * shrink, 2),
            }
        league_backtest = sorted(
            ({"league": league, "brier": round(total / count, 4), "samples": count,
              "temperature": calibration_by_league.get(league, {}).get("temperature", 1.0),
              "grade": "A" if count >= 100 else ("B" if count >= 30 else "C")}
             for league, (total, count) in league_scores.items() if count >= 5),
            key=lambda item: item["samples"], reverse=True,
        )[:12]
        reliability_bins = []
        for index, bucket in enumerate(bins):
            if not bucket:
                continue
            reliability_bins.append({
                "range": f"{index * 10}-{(index + 1) * 10}", "samples": len(bucket),
                "confidence_pct": round(sum(x[0] for x in bucket) / len(bucket) * 100, 1),
                "accuracy_pct": round(sum(x[1] for x in bucket) / len(bucket) * 100, 1),
            })
        return {
            "settled_predictions": len(rows), "brier_score": round(brier_total / len(rows), 4),
            "log_loss": round(log_total / len(rows), 4), "accuracy_pct": round(correct / len(rows) * 100, 1),
            "ece_pct": round(ece * 100, 1), "temperature": temperature, "learned_teams": team_count,
            "calibration_status": "Aktif kalibrasyon" if len(rows) >= 30 else f"Kalibrasyon için {30-len(rows)} sonuç daha gerekli",
            "recent_brier": round(recent_brier, 4) if recent_brier is not None else None,
            "previous_brier": round(previous_brier, 4) if previous_brier is not None else None,
            "drift_status": drift_status,
            "component_brier": component_brier,
            "adaptive_component_weights": adaptive_weights,
            "league_backtest": league_backtest,
            "locked_predictions": locked_count,
            "pending_settlements": pending_count,
            "calibration_by_league": calibration_by_league,
            "reliability_bins": reliability_bins,
        }

    def pending_settlement_dates(self, limit=21):
        """Dates whose locked pre-match predictions still need final scores."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with self._lock, self._db() as db:
            rows = db.execute("""
                SELECT DISTINCT kickoff FROM prediction_locks
                WHERE actual IS NULL AND kickoff IS NOT NULL AND kickoff < ?
                ORDER BY kickoff DESC LIMIT ?
            """, (cutoff, int(limit))).fetchall()
        dates = []
        for row in rows:
            try:
                day = datetime.fromisoformat(row["kickoff"]).astimezone(ISTANBUL_TZ).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                continue
            if day not in dates:
                dates.append(day)
        return dates

    def model_gate(self):
        """Compare candidate models only on their settled, matched pre-match sample."""
        with self._lock, self._db() as db:
            rows = db.execute("""
                SELECT model_version, home_prob, draw_prob, away_prob, actual
                FROM predictions WHERE phase='prematch' AND actual IS NOT NULL
                ORDER BY settled_at DESC LIMIT 10000
            """).fetchall()
        buckets = {}
        for row in rows:
            bucket = buckets.setdefault(row["model_version"], {"loss": 0.0, "correct": 0, "samples": 0})
            probs = [row["home_prob"] / 100.0, row["draw_prob"] / 100.0, row["away_prob"] / 100.0]
            actual = {"H": 0, "D": 1, "A": 2}[row["actual"]]
            bucket["loss"] += sum((probs[i] - (1.0 if i == actual else 0.0)) ** 2 for i in range(3)) / 3.0
            bucket["correct"] += int(max(range(3), key=lambda i: probs[i]) == actual)
            bucket["samples"] += 1
        models = sorted(({
            "version": version, "samples": data["samples"],
            "brier": round(data["loss"] / data["samples"], 4),
            "accuracy_pct": round(data["correct"] / data["samples"] * 100, 1),
        } for version, data in buckets.items()), key=lambda item: (-item["samples"], item["brier"]))
        eligible = [item for item in models if item["samples"] >= 100]
        recommended = min(eligible, key=lambda item: item["brier"])["version"] if eligible else None
        return {
            "models": models[:8], "minimum_samples": 100,
            "recommended_version": recommended,
            "status": "Karar için veri birikiyor" if not recommended else "Güvenli aday belirlendi",
            "automatic_promotion": False,
        }

    @staticmethod
    def _best_temperature(samples):
        best_t, best_loss = 1.0, float("inf")
        for step in range(65, 181, 5):
            temperature = step / 100.0
            loss = 0.0
            for probs, actual_idx in samples:
                logits = [math.log(max(1e-9, value)) / temperature for value in probs]
                peak = max(logits)
                exps = [math.exp(value - peak) for value in logits]
                calibrated = [value / sum(exps) for value in exps]
                loss += -math.log(max(1e-9, calibrated[actual_idx]))
            if loss < best_loss:
                best_t, best_loss = temperature, loss
        return round(best_t, 2)

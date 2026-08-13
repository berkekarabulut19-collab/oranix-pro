"""Leakage-safe historical warehouse and walk-forward evaluation laboratory."""

import csv
import json
import math
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from prediction_store import PredictionStore


def _iso(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise ValueError("timestamp missing")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = None
            for pattern in ("%d/%m/%Y", "%d/%m/%y", "%d.%m.%Y", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
            if parsed is None:
                raise ValueError(f"invalid timestamp: {text}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _number(value):
    if value in (None, ""):
        return None
    return float(str(value).replace(",", "."))


class HistoricalModelLab:
    """Stores immutable pre-match snapshots and evaluates them in event order."""

    def __init__(self, db_path):
        self.db_path = os.path.abspath(str(db_path))
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.RLock()
        self._status_cache = None
        self._status_cache_at = 0.0
        self._ensure_schema()

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=12)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=12000")
        return db

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
                CREATE TABLE IF NOT EXISTS historical_fixtures (
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    kickoff TEXT NOT NULL,
                    feature_cutoff TEXT NOT NULL,
                    result_observed_at TEXT NOT NULL,
                    league TEXT NOT NULL,
                    home_name TEXT NOT NULL,
                    away_name TEXT NOT NULL,
                    home_score INTEGER NOT NULL,
                    away_score INTEGER NOT NULL,
                    home_odds REAL,
                    draw_odds REAL,
                    away_odds REAL,
                    payload_json TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    PRIMARY KEY(source, external_id)
                );
                CREATE INDEX IF NOT EXISTS idx_history_kickoff ON historical_fixtures(kickoff);
                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    run_id TEXT PRIMARY KEY,
                    model_version TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    train_minimum INTEGER NOT NULL,
                    evaluated_matches INTEGER NOT NULL,
                    brier_score REAL,
                    log_loss REAL,
                    accuracy_pct REAL,
                    ece_pct REAL,
                    report_json TEXT NOT NULL
                );
            """)

    @staticmethod
    def _normalized_record(record, source):
        kickoff = _iso(record.get("kickoff") or record.get("iso_date") or record.get("date"))
        feature_cutoff = _iso(record.get("feature_cutoff") or record.get("captured_at") or kickoff)
        observed_value = record.get("result_observed_at") or record.get("settled_at")
        result_observed = _iso(observed_value) if observed_value else (datetime.fromisoformat(kickoff) + timedelta(hours=3)).isoformat()
        if feature_cutoff > kickoff:
            raise ValueError("feature cutoff is after kickoff")
        if result_observed < kickoff:
            raise ValueError("result was observed before kickoff")
        home = str(record.get("home_name") or record.get("home", {}).get("name") or "").strip()
        away = str(record.get("away_name") or record.get("away", {}).get("name") or "").strip()
        if not home or not away:
            raise ValueError("team names missing")
        home_score = int(record.get("home_score", record.get("fthg")))
        away_score = int(record.get("away_score", record.get("ftag")))
        external_id = str(record.get("external_id") or record.get("id") or f"{kickoff}|{home}|{away}")
        return {
            "source": str(source or record.get("source") or "historical-import"),
            "external_id": external_id,
            "kickoff": kickoff,
            "feature_cutoff": feature_cutoff,
            "result_observed_at": result_observed,
            "league": str(record.get("league") or "Diğer Ligler"),
            "home_name": home,
            "away_name": away,
            "home_score": home_score,
            "away_score": away_score,
            "home_odds": _number(record.get("home_odds")),
            "draw_odds": _number(record.get("draw_odds")),
            "away_odds": _number(record.get("away_odds")),
            "payload": dict(record.get("payload") or {}),
        }

    def import_records(self, records, source="historical-import"):
        accepted, rejected, errors = [], 0, []
        for index, record in enumerate(records or []):
            try:
                accepted.append(self._normalized_record(record, source))
            except (TypeError, ValueError, KeyError) as exc:
                rejected += 1
                if len(errors) < 10:
                    errors.append({"row": index + 1, "reason": str(exc)})
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._db() as db:
            before = db.total_changes
            db.executemany("""
                INSERT OR IGNORE INTO historical_fixtures
                (source, external_id, kickoff, feature_cutoff, result_observed_at, league,
                 home_name, away_name, home_score, away_score, home_odds, draw_odds,
                 away_odds, payload_json, imported_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                row["source"], row["external_id"], row["kickoff"], row["feature_cutoff"],
                row["result_observed_at"], row["league"], row["home_name"], row["away_name"],
                row["home_score"], row["away_score"], row["home_odds"], row["draw_odds"],
                row["away_odds"], json.dumps(row["payload"], ensure_ascii=False), now,
            ) for row in accepted])
            inserted = db.total_changes - before
        if inserted:
            self._status_cache = None
        return {"inserted": inserted, "duplicates": len(accepted) - inserted, "rejected": rejected, "errors": errors}

    def import_csv(self, path, source="csv-import"):
        aliases = {
            "Date": "kickoff", "date": "kickoff", "HomeTeam": "home_name", "AwayTeam": "away_name",
            "FTHG": "home_score", "FTAG": "away_score", "B365H": "home_odds", "B365D": "draw_odds",
            "B365A": "away_odds", "Div": "league",
        }
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            rows = []
            for raw in csv.DictReader(handle):
                row = {aliases.get(key, key): value for key, value in raw.items()}
                row.setdefault("feature_cutoff", row.get("kickoff"))
                row.setdefault("result_observed_at", row.get("kickoff"))
                rows.append(row)
        return self.import_records(rows, source)

    @staticmethod
    def _fixture(row):
        payload = json.loads(row["payload_json"] or "{}")
        odds = (row["home_odds"], row["draw_odds"], row["away_odds"])
        match = {
            "id": f"hist:{row['source']}:{row['external_id']}", "status": "SCHEDULED",
            "iso_date": row["kickoff"], "league": row["league"], "data_source": row["source"],
            "home": {"name": row["home_name"], "form": []},
            "away": {"name": row["away_name"], "form": []},
            "home_odds": odds[0], "draw_odds": odds[1], "away_odds": odds[2],
            "odds_available": all(value is not None and value > 1.01 for value in odds),
            "odds_are_estimated": False,
        }
        for key, value in payload.items():
            if key not in {"live_score", "status", "result", "home_score", "away_score"}:
                if key in {"home", "away"} and isinstance(value, dict):
                    match[key].update({item_key: item_value for item_key, item_value in value.items() if item_key != "name"})
                else:
                    match[key] = value
        return match

    def run_walk_forward(self, predictor_factory, minimum_history=30, limit=5000):
        started = datetime.now(timezone.utc).isoformat()
        with self._lock, self._db() as db:
            rows = db.execute("SELECT * FROM historical_fixtures ORDER BY kickoff, external_id LIMIT ?", (int(limit),)).fetchall()
        if len(rows) <= minimum_history:
            return {"status": "insufficient_data", "available": len(rows), "required": minimum_history + 1}

        samples, league_scores = [], {}
        correct = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            learner = PredictionStore(os.path.join(temp_dir, "walk_forward.sqlite3"))
            predictor = predictor_factory()
            for index, row in enumerate(rows):
                match = self._fixture(row)
                learner.enrich_matches([match])
                analysis = predictor.analyze_match(match)
                actual = 0 if row["home_score"] > row["away_score"] else (2 if row["away_score"] > row["home_score"] else 1)
                if index >= minimum_history:
                    vector = analysis.get("probs", {})
                    probs = [float(vector["home_win"]) / 100, float(vector["draw"]) / 100, float(vector["away_win"]) / 100]
                    samples.append((probs, actual, row["league"]))
                    predicted = max(range(3), key=lambda idx: probs[idx])
                    correct += int(predicted == actual)
                    target = [1.0 if idx == actual else 0.0 for idx in range(3)]
                    loss = sum((probs[idx] - target[idx]) ** 2 for idx in range(3)) / 3
                    bucket = league_scores.setdefault(row["league"], [0.0, 0])
                    bucket[0] += loss
                    bucket[1] += 1
                settled = dict(match)
                settled.update({"status": "POST", "live_score": {"home": row["home_score"], "away": row["away_score"]}})
                learner.settle_match(settled)

        count = len(samples)
        brier = sum(sum((p[idx] - (1 if idx == actual else 0)) ** 2 for idx in range(3)) / 3 for p, actual, _ in samples) / count
        log_loss = sum(-math.log(max(1e-9, p[actual])) for p, actual, _ in samples) / count
        bins = [[] for _ in range(10)]
        for probs, actual, _ in samples:
            predicted = max(range(3), key=lambda idx: probs[idx])
            confidence = probs[predicted]
            bins[min(9, int(confidence * 10))].append((confidence, int(predicted == actual)))
        ece = sum((len(bucket) / count) * abs(sum(x[0] for x in bucket) / len(bucket) - sum(x[1] for x in bucket) / len(bucket)) for bucket in bins if bucket)
        league_report = sorted(({
            "league": league, "samples": amount, "brier": round(total / amount, 4),
            "evidence": "verified" if amount >= 100 else ("developing" if amount >= 30 else "insufficient"),
        } for league, (total, amount) in league_scores.items()), key=lambda item: item["samples"], reverse=True)
        report = {"leagues": league_report, "leakage_guard": True, "chronological": True}
        run_id = str(uuid.uuid4())
        completed = datetime.now(timezone.utc).isoformat()
        model_version = getattr(predictor, "version", getattr(predictor, "VERSION", predictor.__class__.__name__))
        with self._lock, self._db() as db:
            db.execute("""INSERT INTO evaluation_runs
                (run_id, model_version, started_at, completed_at, train_minimum, evaluated_matches,
                 brier_score, log_loss, accuracy_pct, ece_pct, report_json)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, str(model_version), started, completed, minimum_history, count, round(brier, 4),
                 round(log_loss, 4), round(correct / count * 100, 1), round(ece * 100, 1), json.dumps(report, ensure_ascii=False)))
        self._status_cache = None
        return {"status": "complete", "run_id": run_id, "evaluated_matches": count,
                "brier_score": round(brier, 4), "log_loss": round(log_loss, 4),
                "accuracy_pct": round(correct / count * 100, 1), "ece_pct": round(ece * 100, 1), **report}

    def status(self):
        if self._status_cache is not None and time.monotonic() - self._status_cache_at < 30:
            return self._status_cache
        with self._lock, self._db() as db:
            summary = db.execute("SELECT COUNT(*) count, MIN(kickoff) first_date, MAX(kickoff) last_date, COUNT(DISTINCT league) leagues FROM historical_fixtures").fetchone()
            sources = [dict(row) for row in db.execute("SELECT source, COUNT(*) matches FROM historical_fixtures GROUP BY source ORDER BY matches DESC")]
            latest = db.execute("SELECT * FROM evaluation_runs ORDER BY completed_at DESC LIMIT 1").fetchone()
        count = int(summary["count"] or 0)
        readiness = "verified" if count >= 1000 else ("developing" if count >= 100 else "collecting")
        latest_run = None
        if latest:
            latest_run = {key: latest[key] for key in ("run_id", "model_version", "completed_at", "evaluated_matches", "brier_score", "log_loss", "accuracy_pct", "ece_pct")}
            latest_run["report"] = json.loads(latest["report_json"] or "{}")
        result = {"historical_matches": count, "leagues": int(summary["leagues"] or 0),
                "first_date": summary["first_date"], "last_date": summary["last_date"],
                "sources": sources, "readiness": readiness, "leakage_guard": True,
                "latest_walk_forward": latest_run}
        self._status_cache, self._status_cache_at = result, time.monotonic()
        return result

    def evidence_for(self, league):
        status = self.status()
        latest = status.get("latest_walk_forward") or {}
        report = latest.get("report") or {}
        row = next((item for item in report.get("leagues", []) if item.get("league") == league), None)
        if not row:
            return {"grade": "UNVERIFIED", "label": "Lig testi bekleniyor", "samples": 0}
        grade = {"verified": "A", "developing": "B", "insufficient": "C"}.get(row.get("evidence"), "C")
        return {"grade": grade, "label": "Walk-forward doğrulandı" if grade == "A" else "Kanıt birikiyor",
                "samples": row["samples"], "brier": row["brier"]}

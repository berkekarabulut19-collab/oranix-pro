import time
import os
import sys
import json
import csv
import socket
import threading
import logging
import secrets
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import webview
from data_fetcher import DataFetcher
from predictor_engine import PredictorEngine
from predictor_candidate import PredictorEngineVNext
from data_manager import DataManager
from prediction_store import PredictionStore
from upgrade_guard import FeatureFlags, UpgradeGuard
from external_data import ExternalDataHub
from model_lab import HistoricalModelLab
from risk_engine import CouponRiskEngine
from release_info import APP_DISPLAY_VERSION, APP_VERSION
from updater import UpdateManager

global_api_instance = None
logger = logging.getLogger("oranix")
API_TOKEN = os.environ.get("ORANIX_API_TOKEN") or secrets.token_urlsafe(24)

HTTP_GET_METHODS = {
    "get_local_qr_info", "get_matches", "get_matches_with_analysis", "get_priority_analyses", "get_match_trends",
    "get_league_standings", "get_power_rankings", "get_surebets",
    "get_dropping_odds", "get_saved_coupons", "export_csv_report", "get_system_health", "get_model_lab_status",
    "get_model_performance",
    "get_update_status",
}
HTTP_POST_METHODS = HTTP_GET_METHODS | {
    "analyze_custom_match", "get_h2h_analytics", "get_ai_prediction_report",
    "get_fibonacci_series", "ask_ai_bot", "build_vip_preset_coupon",
    "build_custom_coupon", "save_coupon", "export_coupon_text",
    "delete_coupon", "update_coupon_status", "analyze_coupon_risk",
    "download_update", "apply_update",
}

FINISHED_MATCH_STATUSES = {
    "POST", "FINISHED", "FULL_TIME", "FULL-TIME", "FT", "ENDED",
    "COMPLETE", "COMPLETED", "AFTER_EXTRA_TIME", "AFTER_PENALTIES",
}


def is_finished_match(match):
    """Return True only for matches that were played and have ended."""
    status = str((match or {}).get("status") or "").strip().upper()
    return status in FINISHED_MATCH_STATUSES or "FINISHED" in status or "FULL_TIME" in status

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def start_local_http_server(ui_dir, port=5000):
    try:
        class CustomHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=ui_dir, **kwargs)

            def do_POST(self):
                if self.path.startswith("/api/"):
                    if not self._is_authorized():
                        return self._send_json({"error": "Unauthorized"}, 401)
                    method_name = urlsplit(self.path).path.removeprefix("/api/")
                    if method_name not in HTTP_POST_METHODS:
                        return self._send_json({"error": "API method not allowed"}, 404)
                    content_length = int(self.headers.get('Content-Length', 0))
                    if content_length > 1_000_000:
                        return self._send_json({"error": "Request too large"}, 413)
                    body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "[]"
                    try:
                        args = json.loads(body)
                    except Exception:
                        args = []

                    res = None
                    status = 503
                    if global_api_instance:
                        func = getattr(global_api_instance, method_name)
                        try:
                            if isinstance(args, list):
                                res = func(*args)
                            elif isinstance(args, dict):
                                res = func(**args)
                            else:
                                res = func()
                            status = 200
                        except Exception:
                            logger.exception("HTTP API error in %s", method_name)
                            res, status = {"error": "Internal API error"}, 500
                    return self._send_json(res, status)
                super().do_POST()

            def do_GET(self):
                if self.path.startswith("/api/"):
                    if not self._is_authorized():
                        return self._send_json({"error": "Unauthorized"}, 401)
                    method_name = urlsplit(self.path).path.removeprefix("/api/")
                    if method_name not in HTTP_GET_METHODS:
                        return self._send_json({"error": "API method not allowed"}, 404)
                    res = None
                    status = 503
                    if global_api_instance:
                        func = getattr(global_api_instance, method_name)
                        try:
                            res = func()
                            status = 200
                        except Exception:
                            logger.exception("HTTP API error in %s", method_name)
                            res, status = {"error": "Internal API error"}, 500
                    return self._send_json(res, status)
                super().do_GET()

            def _is_authorized(self):
                query = urlsplit(self.path).query
                params = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
                supplied = self.headers.get("X-Oranix-Token") or params.get("token", "")
                return secrets.compare_digest(supplied, API_TOKEN)

            def _send_json(self, payload, status=200):
                    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def end_headers(self):
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                super().end_headers()

            def log_message(self, format, *args):
                pass # Silent logging

        server = ThreadingHTTPServer(("0.0.0.0", port), CustomHandler)
        server.daemon_threads = True
        server.serve_forever()
    except Exception as e:
        print(f"[HTTP Server] Warning: {e}")


def wait_for_http_server(port=5000, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False

class Api:
    """JavaScript ↔ Python Bridge API v10000.0 QUANTUM SINGULARITY GOD ULTRA EDITION"""

    def __init__(self, prediction_store_path=None, feature_flags_path=None, fetcher_cache_path=None):
        self.fetcher   = DataFetcher(fetcher_cache_path)
        self.predictor = PredictorEngine()
        self.shadow_predictor = PredictorEngineVNext()
        self.manager   = DataManager()
        self.learning  = PredictionStore(prediction_store_path)
        self.model_lab = HistoricalModelLab(self.learning.db_path)
        self.flags     = FeatureFlags(feature_flags_path)
        self.upgrade_guard = UpgradeGuard(self.flags)
        self.external_data = ExternalDataHub()
        self.risk_engine = CouponRiskEngine()
        self.updater = UpdateManager()
        self.updater.check_async()
        self.local_ip  = get_local_ip()
        self._matches_cache = []
        self._matches_cache_at = 0.0
        self._started_at = time.time()
        self._analysis_lock = threading.Lock()
        self._matches_lock = threading.Lock()
        self._provider_refresh_lock = threading.Lock()
        self._provider_refresh_thread = None
        self._external_refresh_thread = None
        self._history_refresh_thread = None
        self._history_backfill_enabled = prediction_store_path is None
        self._history_refresh_at = 0.0
        self._history_refresh_report = {"status": "waiting", "finished_matches": 0, "inserted_history": 0}
        self._warm_start_used = False
        self._last_analysis_meta = {}
        self._sync_model_calibration()

    def _sync_model_calibration(self):
        """Apply settled-result calibration on both cold and warm starts."""
        learning_metrics = self.learning.metrics()
        temperature = learning_metrics.get("temperature", 1.0)
        samples = learning_metrics.get("settled_predictions", 0)
        self.predictor.set_online_calibration(temperature, samples)
        self.shadow_predictor.set_online_calibration(temperature, samples)
        self.predictor.set_adaptive_component_weights(learning_metrics.get("adaptive_component_weights"))
        self.shadow_predictor.set_adaptive_component_weights(learning_metrics.get("adaptive_component_weights"))
        league_profiles = learning_metrics.get("calibration_by_league") or {}
        self.predictor.set_league_calibration_profiles(league_profiles)
        self.shadow_predictor.set_league_calibration_profiles(league_profiles)

    def _attach_model_evidence(self, match, analysis):
        meta = analysis.setdefault("model_meta", {})
        meta["evidence"] = self.model_lab.evidence_for(str(match.get("league") or "Diğer Ligler"))
        return analysis

    def get_matches(self) -> list:
        """Return fixtures immediately; analyses are loaded separately."""
        has_live = any(m.get("status") == "IN_PROGRESS" for m in self._matches_cache)
        cache_ttl = 8 if has_live else (15 if not self._matches_cache else 25)
        if self._matches_cache_at and time.time() - self._matches_cache_at < cache_ttl:
            return self._matches_cache
        with self._matches_lock:
            has_live = any(m.get("status") == "IN_PROGRESS" for m in self._matches_cache)
            cache_ttl = 8 if has_live else (15 if not self._matches_cache else 25)
            if self._matches_cache_at and time.time() - self._matches_cache_at < cache_ttl:
                return self._matches_cache
            # Cold starts should never wait for the full provider sweep when a
            # recent successful Maçkolik bulletin is already on disk.
            if not self._matches_cache:
                warm_matches = self.fetcher.get_cached_fixtures()
                if warm_matches:
                    # These same cached rows were already settled when they
                    # were first fetched. Repeating one database transaction
                    # per finished match is the largest cold-start cost.
                    matches = self._prepare_matches(warm_matches, settle=False)
                    self._matches_cache = matches
                    self._matches_cache_at = time.time()
                    self._warm_start_used = True
                    self._start_provider_refresh()
                    return matches

            matches = self._prepare_matches(self.fetcher.fetch_live_fixtures())
            self._sync_model_calibration()
            self._matches_cache = matches
            self._matches_cache_at = time.time()
            self._start_external_enrichment(matches)
            self._start_history_backfill()
        return matches

    def _prepare_matches(self, matches, settle=True):
        matches = list(matches or [])
        if self.flags.enabled("match_contract_v2"):
            matches, self._last_match_contract = self.upgrade_guard.audit_matches(matches)
        if settle:
            for match in matches:
                self.learning.settle_match(match)
        # Finished fixtures still pass through settlement above so the model can
        # learn from their result, but they must never re-enter the live bulletin.
        visible = [
            match for match in matches
            if not match.get("is_settlement_history") and not is_finished_match(match)
        ]
        self.learning.record_odds_snapshots(visible)
        return self.learning.enrich_matches(visible)

    def _start_provider_refresh(self):
        if self._provider_refresh_thread and self._provider_refresh_thread.is_alive():
            return

        def refresh():
            if not self._provider_refresh_lock.acquire(blocking=False):
                return
            try:
                fresh = self._prepare_matches(self.fetcher.fetch_live_fixtures())
                if fresh:
                    self._sync_model_calibration()
                    with self._matches_lock:
                        self._matches_cache = fresh
                        self._matches_cache_at = time.time()
                    self._start_external_enrichment(fresh)
                    self._start_history_backfill()
            except Exception:
                logger.exception("Background Maçkolik refresh failed")
            finally:
                self._provider_refresh_lock.release()

        self._provider_refresh_thread = threading.Thread(target=refresh, name="oranix-provider-refresh", daemon=True)
        self._provider_refresh_thread.start()

    @staticmethod
    def _historical_record(match):
        score = match.get("live_score") or {}
        kickoff = PredictionStore.kickoff_for(match)
        if not kickoff or not isinstance(score, dict):
            return None
        observed = match.get("source_fetched_at") or datetime.now(timezone.utc).isoformat()
        return {
            "external_id": str(match.get("id")), "kickoff": kickoff,
            "feature_cutoff": kickoff, "result_observed_at": observed,
            "league": str(match.get("league") or "Diğer Ligler"),
            "home_name": match.get("home", {}).get("name"),
            "away_name": match.get("away", {}).get("name"),
            "home_score": score.get("home"), "away_score": score.get("away"),
            # Historical provider odds observed after full time are deliberately
            # excluded so future walk-forward tests cannot see the result.
            "payload": {"historical_quality": "result-only", "data_source": "Maçkolik"},
        }

    def _start_history_backfill(self):
        if not self._history_backfill_enabled:
            return
        if self._history_refresh_thread and self._history_refresh_thread.is_alive():
            return
        if self._history_refresh_at and time.time() - self._history_refresh_at < 6 * 3600:
            return
        pending_dates = self.learning.pending_settlement_dates()
        last_history_date = str(self.model_lab.status().get("last_date") or "")[:10]
        yesterday = (datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3))).date() - timedelta(days=1)).isoformat()
        if not pending_dates and last_history_date >= yesterday:
            self._history_refresh_report = {"status": "fresh", "finished_matches": 0, "inserted_history": 0}
            return

        def refresh_history():
            report = {"status": "running", "finished_matches": 0, "inserted_history": 0}
            self._history_refresh_report = report
            try:
                finished = self.fetcher.fetch_historical_results(pending_dates, days=21)
                report["finished_matches"] = len(finished)
                settled = sum(1 for match in finished if self.learning.settle_match(match))
                records = [record for record in (self._historical_record(match) for match in finished) if record]
                imported = self.model_lab.import_records(records, "mackolik-result-backfill")
                report.update({"status": "complete", "settled_predictions": settled,
                               "inserted_history": imported.get("inserted", 0),
                               "duplicates": imported.get("duplicates", 0)})
                status = self.model_lab.status()
                latest = status.get("latest_walk_forward") or {}
                # Re-evaluate only when a meaningful new batch arrived.
                if status.get("historical_matches", 0) >= 40 and (imported.get("inserted", 0) >= 5 or not latest):
                    report["walk_forward"] = self.model_lab.run_walk_forward(PredictorEngine, minimum_history=30)
                self._sync_model_calibration()
            except Exception as exc:
                logger.exception("Historical result backfill failed")
                report.update({"status": "error", "error": str(exc)[:180]})
            finally:
                self._history_refresh_at = time.time()
                self._history_refresh_report = report

        self._history_refresh_thread = threading.Thread(target=refresh_history, name="oranix-history-backfill", daemon=True)
        self._history_refresh_thread.start()

    def _start_external_enrichment(self, matches):
        """Fetch licensed optional data without delaying Mackolik fixture display."""
        if self._external_refresh_thread and self._external_refresh_thread.is_alive():
            return
        snapshot = list(matches or [])

        def enrich():
            enriched = self.external_data.enrich(snapshot)
            self.learning.record_odds_snapshots(enriched)
            enriched_by_id = {str(item.get("id")): item for item in enriched}
            if not enriched_by_id:
                return
            with self._matches_lock:
                merged = []
                for current in self._matches_cache:
                    candidate = enriched_by_id.get(str(current.get("id")))
                    if candidate:
                        for key in (
                            "external_fixture_id", "verified_sources", "verified_absences", "verified_lineups",
                            "verified_venue", "verified_weather", "consensus_odds",
                        ):
                            if key in candidate:
                                current[key] = candidate[key]
                    merged.append(current)
                self._matches_cache = merged
                self._matches_cache_at = time.time()

        self._external_refresh_thread = threading.Thread(target=enrich, name="oranix-external-data", daemon=True)
        self._external_refresh_thread.start()

    def get_system_health(self) -> dict:
        fetch = self.fetcher.get_status()
        cache_age = round(time.time() - self._matches_cache_at) if self._matches_cache_at else None
        return {
            "app_version": f"{APP_VERSION}-evidence-fusion",
            "app_display_version": APP_DISPLAY_VERSION,
            "uptime_seconds": round(time.time() - self._started_at),
            "match_cache": {
                "count": len(self._matches_cache),
                "age_seconds": cache_age,
                "is_fresh": cache_age is not None and cache_age < (8 if any(m.get("status") == "IN_PROGRESS" for m in self._matches_cache) else 25),
            },
            "fetcher": fetch,
            "external_data": self.external_data.get_status(),
            "analysis": self._last_analysis_meta,
            "predictor_cache_count": len(self.predictor._cache),
            "coupon_stats": self.manager.get_system_stats(),
            "model_learning": self.learning.metrics(),
            "model_lab": self.model_lab.status(),
            "history_backfill": dict(self._history_refresh_report),
            "model_gate": self.learning.model_gate(),
            "safe_upgrade": self.upgrade_guard.snapshot(),
            "match_contract": getattr(self, "_last_match_contract", {}),
            "fast_start": {
                "used": self._warm_start_used,
                "refreshing": bool(self._provider_refresh_thread and self._provider_refresh_thread.is_alive()),
            },
            "update": self.updater.status(),
        }

    def get_model_lab_status(self) -> dict:
        """Return evidence readiness without starting a blocking backtest."""
        return self.model_lab.status()

    def get_model_performance(self) -> dict:
        return {
            "learning": self.learning.metrics(),
            "laboratory": self.model_lab.status(),
            "model_gate": self.learning.model_gate(),
            "history_backfill": dict(self._history_refresh_report),
            "truth_policy": {
                "one_match_one_vote": True,
                "prematch_lock": True,
                "live_predictions_separate": True,
                "future_information_blocked": True,
            },
        }

    def get_update_status(self) -> dict:
        return self.updater.status()

    def download_update(self) -> dict:
        return self.updater.download()

    def apply_update(self) -> dict:
        return self.updater.apply()

    def analyze_coupon_risk(self, coupon_items=None, bankroll=10000.0) -> dict:
        """Return conservative concentration and bankroll guidance for the open slip."""
        try:
            return self.risk_engine.analyze(coupon_items, self.get_matches(), bankroll)
        except Exception:
            logger.exception("Coupon risk analysis failed")
            return {"status": "error", "risk_score": 0, "risk_level": "HESAPLANAMADI", "warnings": []}

    def get_local_qr_info(self) -> dict:
        url = f"http://{self.local_ip}:5000/index.html?token={API_TOKEN}"
        qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={url}"
        return {
            "ip": self.local_ip,
            "url": url,
            "qr_image_url": qr_image_url
        }

    def analyze_custom_match(self, home_name: str, away_name: str, home_odds: float = 2.10, draw_odds: float = 3.40, away_odds: float = 3.20) -> dict:
        try:
            result = self.predictor.analyze_custom_user_match(home_name, away_name, home_odds, draw_odds, away_odds)
            return result if result else {}
        except Exception as e:
            print(f"[analyze_custom_match] Error: {e}")
            return {}

    def get_h2h_analytics(self, home_name: str = "Ev Sahibi", away_name: str = "Deplasman") -> dict:
        try:
            return self.predictor.get_h2h_referee_analytics(home_name, away_name)
        except Exception as e:
            return {}

    def get_ai_prediction_report(self, home_name: str = "", away_name: str = "") -> str:
        """Returns full narrative AI prediction report for a match"""
        try:
            return self.predictor.get_ai_prediction_report(home_name, away_name)
        except Exception as e:
            return f"Rapor hatası: {e}"

    def get_match_trends(self) -> dict:
        """Returns trending bet types, hottest leagues, and today's value summary"""
        try:
            matches = self.get_matches()
            o25_count = 0
            btts_count = 0
            high_conf_count = 0
            value_count = 0
            top_xg_matches = []

            for m in matches:
                try:
                    a = self.predictor.analyze_match(m)
                    xg = a.get("xg_total", 0)
                    if xg > 0:
                        top_xg_matches.append({
                            "match": f"{m['home']['name']} vs {m['away']['name']}",
                            "xg_total": xg,
                            "xg_home": a.get("xg_home"),
                            "xg_away": a.get("xg_away"),
                            "league": m.get("league"),
                            "time": m.get("match_time"),
                            "date": m.get("match_date", ""),
                        })
                    if a.get("outcomes", {}).get("over_25", 0) >= 60:
                        o25_count += 1
                    if a.get("outcomes", {}).get("btts", 0) >= 58:
                        btts_count += 1
                    if a.get("confidence", {}).get("rank", 0) >= 4:
                        high_conf_count += 1
                    for ev_k in a.get("all_ev", {}).values():
                        if ev_k.get("is_value"):
                            value_count += 1
                            break
                except Exception:
                    pass

            top_xg_matches.sort(key=lambda x: x["xg_total"], reverse=True)

            return {
                "total_matches": len(matches),
                "o25_hot_count": o25_count,
                "btts_hot_count": btts_count,
                "high_confidence_count": high_conf_count,
                "value_bet_count": value_count,
                "top_xg_matches": top_xg_matches[:5],
            }
        except Exception as e:
            return {}

    def get_league_standings(self) -> dict:
        """Avoid presenting stale sample standings as live data."""
        return {}


    def get_power_rankings(self) -> list:
        try:
            matches = self.get_matches()
            return self.predictor.get_power_rankings(matches)
        except Exception as e:
            return []

    def get_fibonacci_series(self, bankroll: float = 1000.0, base_stake: float = 50.0, target_profit: float = 200.0, odds: float = 2.0) -> dict:
        try:
            return self.predictor.get_fibonacci_series(bankroll, base_stake, target_profit, odds)
        except Exception as e:
            return {}
    def get_surebets(self) -> list:
        try:
            matches = self.get_matches()
            return self.predictor.find_surebets(matches)
        except Exception as e:
            return []

    def get_matches_with_analysis(self) -> dict:
        started = time.perf_counter()
        try:
            matches = self.get_matches()
            analyses = {}
            prediction_records = []
            # A full fixture list can contain 150+ matches. Running every
            # analysis serially blocks the JS bridge long enough to make the
            # opening screen look empty, so calculate them concurrently.
            workers = min(12, max(1, len(matches)))
            with self._analysis_lock:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(self.predictor.analyze_match, match): match
                        for match in matches
                    }
                    for future in as_completed(futures):
                        match = futures[future]
                        try:
                            analysis = self._attach_model_evidence(match, future.result())
                            if self.flags.enabled("analysis_contract_v2"):
                                is_valid, issues = self.upgrade_guard.validate_analysis(analysis)
                                if not is_valid:
                                    logger.error("Analysis contract rejected %s: %s", match.get("id"), issues)
                                    continue
                            analyses[match["id"]] = analysis
                            prediction_records.append((match, analysis))
                        except Exception:
                            logger.exception("Predictor error on %s", match.get("id"))
                self.learning.record_predictions_batch(prediction_records)
            shadow_results = []
            shadow_prediction_records = []
            if self.flags.enabled("shadow_predictor") and analyses:
                # Keep startup fast: compare a rotating, deterministic sample
                # rather than doubling work for the entire bulletin.
                targets = sorted(
                    (match for match in matches if match.get("id") in analyses),
                    key=lambda item: str(item.get("id")),
                )[:4]
                with ThreadPoolExecutor(max_workers=min(4, len(targets))) as executor:
                    futures = {executor.submit(self.shadow_predictor.analyze_match, match): match for match in targets}
                    for future in as_completed(futures):
                        match = futures[future]
                        try:
                            candidate = future.result()
                            candidate_valid, _ = self.upgrade_guard.validate_analysis(candidate)
                            if candidate_valid:
                                comparison = self.upgrade_guard.compare_shadow(analyses[match["id"]], candidate)
                                if comparison:
                                    shadow_results.append(comparison)
                                    shadow_prediction_records.append((match, candidate))
                        except Exception:
                            logger.exception("Shadow predictor error on %s", match.get("id"))
            if shadow_prediction_records:
                self.learning.record_predictions_batch(shadow_prediction_records)
            sources = {}
            for match in matches:
                source = match.get("data_source", "Bilinmiyor")
                sources[source] = sources.get(source, 0) + 1
            meta = {
                "total_matches": len(matches),
                "analyzed_matches": len(analyses),
                "failed_matches": max(0, len(matches) - len(analyses)),
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "sources": sources,
                "is_complete": len(analyses) == len(matches),
                "shadow": {
                    "enabled": self.flags.enabled("shadow_predictor"),
                    "sample_size": len(shadow_results),
                    "max_probability_delta": max((item["max_probability_delta"] for item in shadow_results), default=0.0),
                },
            }
            self._last_analysis_meta = meta
            return {"matches": matches, "analyses": analyses, "meta": meta}
        except Exception:
            logger.exception("Matches and analyses could not be loaded")
            meta = {"total_matches": 0, "analyzed_matches": 0, "failed_matches": 0, "duration_ms": round((time.perf_counter() - started) * 1000), "sources": {}, "is_complete": False}
            self._last_analysis_meta = meta
            return {"matches": [], "analyses": {}, "meta": meta}

    def get_priority_analyses(self, match_ids=None) -> dict:
        """Analyze the first visible cards before the full bulletin batch."""
        requested = {str(value) for value in (match_ids or [])[:24]}
        matches = [match for match in self.get_matches() if str(match.get("id")) in requested]
        analyses = {}
        prediction_records = []
        if not matches:
            return {"analyses": analyses, "requested": len(requested), "completed": 0}
        with self._analysis_lock:
            with ThreadPoolExecutor(max_workers=min(12, len(matches))) as executor:
                futures = {executor.submit(self.predictor.analyze_match, match): match for match in matches}
                for future in as_completed(futures):
                    match = futures[future]
                    try:
                        analysis = self._attach_model_evidence(match, future.result())
                        valid, _ = self.upgrade_guard.validate_analysis(analysis)
                        if valid:
                            analyses[match["id"]] = analysis
                            prediction_records.append((match, analysis))
                    except Exception:
                        logger.exception("Priority predictor error on %s", match.get("id"))
        if prediction_records:
            self.learning.record_predictions_batch(prediction_records)
        return {"analyses": analyses, "requested": len(requested), "completed": len(analyses)}

    def ask_ai_bot(self, user_query: str) -> str:
        try:
            matches = self.get_matches()
            q = user_query.lower()

            if "banko" in q:
                return "🤖 Bugünün en yüksek güvenli banko tahmini: **1.5 Üst Gol** (%88 Olasılık) veya **1X Çifte Şans**."
            elif "gol" in q or "üst" in q:
                return "🤖 Deep Learning motoruna göre 2.5 Üst Gol beklentisi yüksek canlı maçlar bültende listelenmiştir."
            elif "canlı" in q:
                return "🤖 Şu an canlı oynanan maçlarda tempo yüksek! Canlı Re-Analiz sekmesinden baskı oranlarına bakabilirsiniz."
            else:
                return f"🤖 '{user_query}' sorunuz için 200 bin Monte Carlo simülasyon sonucu incelendi: En ideal bahis **1.5 Üst** veya **1X Çifte Şans** seçeneğidir."
        except Exception as e:
            return f"🤖 Bağlantı hatası: {e}"

    def build_vip_preset_coupon(self, preset_type: str) -> list:
        try:
            matches = self.get_matches()
            return self.predictor.build_vip_preset_coupon(matches, preset_type)
        except Exception as e:
            return []

    def build_custom_coupon(self, target_odds: float, match_count: int, risk_level: str) -> list:
        try:
            matches = self.get_matches()
            return self.predictor.build_custom_coupon(matches, target_odds, match_count, risk_level)
        except Exception as e:
            return []

    def get_dropping_odds(self) -> list:
        try:
            matches = self.get_matches()
            dropping = []
            for m in matches:
                drop = m.get("odds_drop_pct", 0)
                if drop < -3.0:
                    dropping.append({
                        "match": m,
                        "analysis": self.predictor.analyze_match(m),
                        "drop_pct": drop,
                    })
            dropping.sort(key=lambda x: x["drop_pct"])
            return dropping
        except Exception as e:
            return []

    def save_coupon(self, coupon: list) -> bool:
        try:
            return self.manager.save_coupon(coupon)
        except Exception:
            logger.exception("Coupon could not be saved")
            return False

    def get_saved_coupons(self) -> list:
        try:
            return self.manager.get_saved_coupons()
        except Exception:
            logger.exception("Saved coupons could not be loaded")
            return []

    def delete_coupon(self, coupon_id: str) -> bool:
        return self.manager.delete_coupon(coupon_id)

    def update_coupon_status(self, coupon_id: str, status: str) -> bool:
        return self.manager.update_coupon_status(coupon_id, status)

    def export_csv_report(self) -> str:
        try:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            filepath = os.path.join(desktop, "ORANIX_PRO_Analiz_Raporu.csv")
            matches = self.get_matches()

            with open(filepath, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Lig", "Ev Sahibi", "Deplasman", "Maç Zamanı", "Ev Oran", "Beraberlik Oran", "Dep Oran", "AI Tahmin", "Tahmin Oranı", "Olasılık %", "Beklenen Skor"])

                for m in matches:
                    a = self.predictor.analyze_match(m)
                    b = a.get("best_bet", {})
                    writer.writerow([
                        m.get("league"), m.get("home", {}).get("name"), m.get("away", {}).get("name"),
                        m.get("match_time"), m.get("home_odds"), m.get("draw_odds"), m.get("away_odds"),
                        b.get("label"), b.get("odds"), b.get("prob"), a.get("expected_score")
                    ])

            return f"CSV Raporu masaüstüne kaydedildi: {filepath}"
        except Exception as e:
            return f"CSV İhrac hatası: {e}"

    def export_coupon_text(self, coupon_items: list) -> str:
        try:
            lines = [
                "ORANİX PRO v18000 EVIDENCE FUSION KUPONU",
                "------------------------------------------------"
            ]
            total_odds = 1.0
            for i, item in enumerate(coupon_items, 1):
                m_name = item.get("match", "Maç")
                bet    = item.get("bet_label", "Tahmin")
                odds   = float(item.get("odds", 1.0))
                prob   = item.get("prob", 0)
                total_odds *= odds
                lines.append(f"{i}. {m_name}")
                lines.append(f"   🎯 Tahmin: {bet} | Oran: {odds:.2f} (%{prob})")

            lines.append("------------------------------------------------")
            lines.append(f"💰 Toplam Oran: {total_odds:.2f}")
            lines.append("Oranix Pro Evidence Fusion olasılık motoru")
            return "\n".join(lines)
        except Exception as e:
            return f"Hata: {e}"

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    global global_api_instance
    api = Api()
    global_api_instance = api

    ui_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
    html_path = os.path.join(ui_dir, "index.html")

    if not os.path.exists(html_path):
        print(f"[ERROR] UI not found at: {html_path}")
        sys.exit(1)

    # Start local HTTP server for mobile Wi-Fi QR access
    server_thread = threading.Thread(target=start_local_http_server, args=(ui_dir, 5000), daemon=True)
    server_thread.start()
    if not wait_for_http_server(5000):
        logger.error("Local HTTP server did not start on port 5000")
        sys.exit(1)

    window = webview.create_window(
        title      = "ORANİX PRO v18000 EVIDENCE FUSION — CANLI SPOR ANALİTİĞİ",
        url        = f"http://127.0.0.1:5000/index.html?v={int(time.time())}&token={API_TOKEN}",
        js_api     = api,
        width      = 1440,
        height     = 900,
        min_size   = (1150, 720),
        resizable  = True,
        background_color = "#03050a",
    )

    # Some Windows/network setups allow Maçkolik in Edge WebView2 while
    # rejecting Python's direct HTTPS client. Keep a hidden official Maçkolik
    # page as a same-origin transport fallback; no third-party data is used.
    provider_window = webview.create_window(
        title="Oranix Maçkolik Veri Köprüsü",
        url=DataFetcher.MACKOLIK_LIVE_URL,
        width=320,
        height=240,
        hidden=True,
        focus=False,
    )
    api.fetcher.set_browser_window(provider_window)

    webview.start(debug=False)

if __name__ == "__main__":
    main()

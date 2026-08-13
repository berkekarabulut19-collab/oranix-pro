"""Safe rollout primitives for large Oranix upgrades.

The guard is deliberately dependency-free and sits between provider data,
prediction output and the UI bridge.  It observes current behaviour first;
future engines can be enabled behind flags without replacing the stable path.
"""

import json
import math
import os
import threading
from copy import deepcopy


class FeatureFlags:
    DEFAULTS = {
        "match_contract_v2": True,
        "analysis_contract_v2": True,
        "shadow_predictor": True,
        "candidate_predictor": False,
    }

    def __init__(self, path=None):
        app_data = os.environ.get("LOCALAPPDATA") or os.path.dirname(__file__)
        self.path = path or os.path.join(app_data, "OranixPro", "feature_flags.json")
        self._lock = threading.RLock()
        self._flags = dict(self.DEFAULTS)
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as stream:
                stored = json.load(stream)
            if isinstance(stored, dict):
                for key in self.DEFAULTS:
                    if isinstance(stored.get(key), bool):
                        self._flags[key] = stored[key]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    def enabled(self, name):
        env_name = f"ORANIX_{str(name).upper()}"
        env_value = os.environ.get(env_name)
        if env_value is not None:
            return env_value.strip().lower() in {"1", "true", "yes", "on"}
        with self._lock:
            return bool(self._flags.get(name, False))

    def snapshot(self):
        with self._lock:
            return {name: self.enabled(name) for name in self.DEFAULTS}


class UpgradeGuard:
    VALID_STATUSES = {"SCHEDULED", "IN_PROGRESS", "HALFTIME", "IN_PLAY", "POST"}

    def __init__(self, flags=None):
        self.flags = flags or FeatureFlags()
        self._lock = threading.RLock()
        self._stats = {
            "match_rows_seen": 0,
            "match_rows_rejected": 0,
            "match_warnings": 0,
            "analyses_seen": 0,
            "analyses_rejected": 0,
            "shadow_compared": 0,
            "shadow_failures": 0,
            "shadow_mean_delta": 0.0,
            "last_error": "",
        }

    @staticmethod
    def _team_name(match, side):
        team = match.get(side)
        return str(team.get("name", "")).strip() if isinstance(team, dict) else ""

    def audit_matches(self, matches):
        """Return safe rows and a non-destructive contract report."""
        accepted = []
        report = {"seen": 0, "accepted": 0, "rejected": 0, "warnings": 0, "issues": {}}
        for original in matches if isinstance(matches, list) else []:
            report["seen"] += 1
            issues = []
            fatal = []
            if not isinstance(original, dict):
                fatal.append("row_not_object")
                match = {}
            else:
                match = original
            if not str(match.get("id", "")).strip():
                fatal.append("missing_id")
            if not self._team_name(match, "home"):
                fatal.append("missing_home")
            if not self._team_name(match, "away"):
                fatal.append("missing_away")

            status = str(match.get("status", "SCHEDULED")).upper()
            if status not in self.VALID_STATUSES:
                issues.append("unknown_status")
            score = match.get("live_score")
            if score is not None:
                if not isinstance(score, dict):
                    fatal.append("score_not_object")
                else:
                    for side in ("home", "away"):
                        value = score.get(side)
                        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                            fatal.append(f"invalid_{side}_score")
                    if match.get("score_orientation") not in (None, "home-away"):
                        fatal.append("score_orientation")
            elif status in {"IN_PROGRESS", "HALFTIME", "IN_PLAY", "POST"}:
                issues.append("active_without_score")

            for issue in set(fatal + issues):
                report["issues"][issue] = report["issues"].get(issue, 0) + 1
            report["warnings"] += len(issues)
            if fatal:
                report["rejected"] += 1
                continue
            accepted.append(match)
            report["accepted"] += 1

        with self._lock:
            self._stats["match_rows_seen"] += report["seen"]
            self._stats["match_rows_rejected"] += report["rejected"]
            self._stats["match_warnings"] += report["warnings"]
            if report["rejected"]:
                self._stats["last_error"] = ", ".join(sorted(report["issues"]))[:240]
        return accepted, report

    def validate_analysis(self, analysis):
        issues = []
        if not isinstance(analysis, dict):
            issues.append("analysis_not_object")
        probs = analysis.get("probs", {}) if isinstance(analysis, dict) else {}
        values = [probs.get(key) for key in ("home_win", "draw", "away_win")]
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in values):
            issues.append("invalid_probabilities")
        else:
            if any(value < 0 or value > 100 for value in values):
                issues.append("probability_range")
            if abs(sum(values) - 100.0) > 0.2:
                issues.append("probability_sum")
        with self._lock:
            self._stats["analyses_seen"] += 1
            if issues:
                self._stats["analyses_rejected"] += 1
                self._stats["last_error"] = ", ".join(issues)
        return not issues, issues

    def compare_shadow(self, stable, candidate):
        stable_probs = stable.get("probs", {})
        candidate_probs = candidate.get("probs", {})
        try:
            deltas = [abs(float(stable_probs[key]) - float(candidate_probs[key])) for key in ("home_win", "draw", "away_win")]
            mean_delta = sum(deltas) / len(deltas)
        except (KeyError, TypeError, ValueError):
            with self._lock:
                self._stats["shadow_failures"] += 1
            return None
        with self._lock:
            count = self._stats["shadow_compared"]
            previous = self._stats["shadow_mean_delta"]
            self._stats["shadow_compared"] = count + 1
            self._stats["shadow_mean_delta"] = round((previous * count + mean_delta) / (count + 1), 4)
        return {"mean_probability_delta": round(mean_delta, 4), "max_probability_delta": round(max(deltas), 4)}

    def snapshot(self):
        with self._lock:
            result = deepcopy(self._stats)
        result["flags"] = self.flags.snapshot()
        result["safe_mode"] = not result["flags"]["candidate_predictor"]
        return result

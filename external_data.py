"""Optional licensed football-data enrichers for Oranix.

All providers fail closed: a missing key, ambiguous team match or provider outage
leaves the verified Mackolik row untouched. Network work is called only from the
Api background refresh path.
"""

import copy
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import requests


def _normalized_team(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\b(fc|fk|sk|cf|ac|afc|club|spor|football|futbol)\b", " ", text.casefold())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _team_similarity(left, right):
    a, b = _normalized_team(left), _normalized_team(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    tokens_a, tokens_b = set(a.split()), set(b.split())
    token_score = len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))
    return max(SequenceMatcher(None, a, b).ratio(), token_score)


class ApiFootballProvider:
    base_url = "https://v3.football.api-sports.io"

    def __init__(self, api_key=None, http_get=None):
        self.api_key = api_key or os.environ.get("ORANIX_API_FOOTBALL_KEY") or os.environ.get("API_FOOTBALL_KEY")
        self.http_get = http_get or requests.get

    @property
    def enabled(self):
        return bool(self.api_key)

    def _get(self, endpoint, params):
        response = self.http_get(
            f"{self.base_url}/{endpoint}", params=params,
            headers={"x-apisports-key": self.api_key}, timeout=6,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("response", []) if isinstance(payload, dict) else []

    @staticmethod
    def _safe_fixture_match(match, fixtures):
        home_name = match.get("home", {}).get("name")
        away_name = match.get("away", {}).get("name")
        ranked = []
        for fixture in fixtures:
            teams = fixture.get("teams", {})
            home_score = _team_similarity(home_name, teams.get("home", {}).get("name"))
            away_score = _team_similarity(away_name, teams.get("away", {}).get("name"))
            reverse_score = (_team_similarity(home_name, teams.get("away", {}).get("name")) +
                             _team_similarity(away_name, teams.get("home", {}).get("name"))) / 2.0
            direct_score = (home_score + away_score) / 2.0
            if min(home_score, away_score) >= 0.76 and direct_score >= 0.84 and direct_score > reverse_score + 0.08:
                ranked.append((direct_score, fixture))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked or (len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.04):
            return None
        return ranked[0][1]

    def enrich(self, matches):
        if not self.enabled:
            return matches, {"enabled": False, "reason": "API anahtarı yok", "enriched": 0}
        by_date = {}
        for match in matches:
            date = str(match.get("local_date") or match.get("iso_date") or "")[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                by_date.setdefault(date, []).append(match)
        fixtures_by_date = {}
        for date in sorted(by_date)[:8]:
            fixtures_by_date[date] = self._get("fixtures", {"date": date, "timezone": "Europe/Istanbul"})

        mapped = {}
        for date, date_matches in by_date.items():
            for match in date_matches:
                fixture = self._safe_fixture_match(match, fixtures_by_date.get(date, []))
                if fixture:
                    fixture_id = fixture.get("fixture", {}).get("id")
                    if fixture_id:
                        mapped[str(match.get("id"))] = (fixture_id, fixture)

        relevant = []
        now = datetime.now(timezone.utc)
        for match in matches:
            item = mapped.get(str(match.get("id")))
            if not item:
                continue
            match["external_fixture_id"] = item[0]
            venue = item[1].get("fixture", {}).get("venue") or {}
            if venue.get("city") or venue.get("name"):
                match["verified_venue"] = {
                    "name": venue.get("name"), "city": venue.get("city"),
                    "source": "API-Football", "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            match.setdefault("verified_sources", []).append("API-Football fixture")
            try:
                kickoff = datetime.fromisoformat(str(item[1].get("fixture", {}).get("date", "")).replace("Z", "+00:00"))
                hours = (kickoff - now).total_seconds() / 3600.0
            except (TypeError, ValueError):
                hours = 99
            if match.get("status") == "IN_PROGRESS" or -1 <= hours <= 4:
                relevant.append((match, item[0]))

        fixture_ids = [fixture_id for _, fixture_id in relevant[:20]]
        injuries = self._get("injuries", {"ids": "-".join(map(str, fixture_ids))}) if fixture_ids else []
        injuries_by_fixture = {}
        for row in injuries:
            fixture_id = row.get("fixture", {}).get("id")
            injuries_by_fixture.setdefault(fixture_id, []).append(row)

        def get_lineup(item):
            match, fixture_id = item
            try:
                return fixture_id, self._get("fixtures/lineups", {"fixture": fixture_id})
            except Exception:
                return fixture_id, []

        with ThreadPoolExecutor(max_workers=min(6, max(1, len(relevant[:12])))) as executor:
            lineups_by_fixture = dict(executor.map(get_lineup, relevant[:12])) if relevant else {}

        enriched = 0
        for match, fixture_id in relevant:
            home_name, away_name = match.get("home", {}).get("name"), match.get("away", {}).get("name")
            absences = {"home": [], "away": []}
            for row in injuries_by_fixture.get(fixture_id, []):
                team_name = row.get("team", {}).get("name")
                side = "home" if _team_similarity(team_name, home_name) >= 0.80 else ("away" if _team_similarity(team_name, away_name) >= 0.80 else None)
                if side:
                    absences[side].append({
                        "player": row.get("player", {}).get("name"),
                        "type": row.get("player", {}).get("type"),
                        "reason": row.get("player", {}).get("reason"),
                    })
            lineups = lineups_by_fixture.get(fixture_id, [])
            if absences["home"] or absences["away"]:
                match["verified_absences"] = {**absences, "source": "API-Football", "fetched_at": datetime.now(timezone.utc).isoformat()}
            if len(lineups) >= 2:
                match["verified_lineups"] = {
                    "confirmed": True, "source": "API-Football",
                    "home_count": len(lineups[0].get("startXI", [])),
                    "away_count": len(lineups[1].get("startXI", [])),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            if match.get("verified_absences") or match.get("verified_lineups"):
                match.setdefault("verified_sources", []).append("API-Football squad")
                enriched += 1
        return matches, {"enabled": True, "mapped": len(mapped), "enriched": enriched, "checked": len(matches)}


class TheOddsProvider:
    base_url = "https://api.the-odds-api.com/v4"
    league_keys = {
        "premier league": "soccer_epl", "la liga": "soccer_spain_la_liga",
        "bundesliga": "soccer_germany_bundesliga", "serie a": "soccer_italy_serie_a",
        "ligue 1": "soccer_france_ligue_one", "champions league": "soccer_uefa_champs_league",
        "şampiyonlar ligi": "soccer_uefa_champs_league", "europa league": "soccer_uefa_europa_league",
    }

    def __init__(self, api_key=None, http_get=None):
        self.api_key = api_key or os.environ.get("ORANIX_ODDS_API_KEY") or os.environ.get("THE_ODDS_API_KEY")
        self.http_get = http_get or requests.get

    @property
    def enabled(self):
        return bool(self.api_key)

    def enrich(self, matches):
        if not self.enabled:
            return matches, {"enabled": False, "reason": "API anahtarı yok", "enriched": 0}
        sport_matches = {}
        for match in matches:
            league = str(match.get("league", "")).casefold()
            sport = next((key for name, key in self.league_keys.items() if name in league), None)
            if sport:
                sport_matches.setdefault(sport, []).append(match)
        enriched = 0
        for sport, targets in list(sport_matches.items())[:5]:
            response = self.http_get(
                f"{self.base_url}/sports/{sport}/odds",
                params={"apiKey": self.api_key, "regions": "eu,uk", "markets": "h2h", "oddsFormat": "decimal"},
                timeout=6,
            )
            response.raise_for_status()
            for event in response.json():
                event_time = None
                try:
                    event_time = datetime.fromisoformat(str(event.get("commence_time", "")).replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    pass
                time_matched_targets = []
                for target in targets:
                    try:
                        target_time = datetime.fromisoformat(str(target.get("iso_date", "")).replace("Z", "+00:00"))
                        if target_time.tzinfo is None:
                            target_time = target_time.replace(tzinfo=timezone.utc)
                        if event_time and abs((target_time - event_time).total_seconds()) > 12 * 3600:
                            continue
                    except (TypeError, ValueError):
                        if event_time:
                            continue
                    time_matched_targets.append(target)
                target = ApiFootballProvider._safe_fixture_match(
                    {"home": {"name": event.get("home_team")}, "away": {"name": event.get("away_team")}},
                    [{"teams": {"home": target.get("home", {}), "away": target.get("away", {})}, "target": target} for target in time_matched_targets],
                )
                if not target:
                    continue
                match = target.get("target")
                prices = {event.get("home_team"): [], event.get("away_team"): [], "Draw": []}
                for book in event.get("bookmakers", []):
                    market = next((m for m in book.get("markets", []) if m.get("key") == "h2h"), None)
                    for outcome in (market or {}).get("outcomes", []):
                        if outcome.get("name") in prices and isinstance(outcome.get("price"), (int, float)):
                            prices[outcome["name"]].append(float(outcome["price"]))
                def median(values):
                    values = sorted(values)
                    return values[len(values) // 2] if values else None
                trio = (median(prices[event.get("home_team")]), median(prices["Draw"]), median(prices[event.get("away_team")]))
                if all(value and value > 1.01 for value in trio):
                    match["consensus_odds"] = {"home": trio[0], "draw": trio[1], "away": trio[2], "source": "The Odds API"}
                    match.setdefault("verified_sources", []).append("The Odds API")
                    enriched += 1
        return matches, {"enabled": True, "enriched": enriched, "sports_checked": len(sport_matches)}


class OpenMeteoProvider:
    """Keyless weather enrichment, used only when a verified venue city exists."""

    geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
    forecast_url = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, http_get=None):
        self.http_get = http_get or requests.get
        self._geo_cache = {}

    @property
    def enabled(self):
        return True

    def _json(self, url, params):
        response = self.http_get(url, params=params, timeout=6)
        response.raise_for_status()
        return response.json()

    def _coordinates(self, city):
        key = _normalized_team(city)
        if not key:
            return None
        cached = self._geo_cache.get(key)
        if cached and time.time() - cached[0] < 30 * 86400:
            return cached[1]
        payload = self._json(self.geocoding_url, {"name": city, "count": 1, "language": "tr", "format": "json"})
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        if not rows:
            return None
        coords = (rows[0].get("latitude"), rows[0].get("longitude"))
        if not all(isinstance(value, (int, float)) for value in coords):
            return None
        self._geo_cache[key] = (time.time(), coords)
        return coords

    def enrich(self, matches):
        grouped = {}
        for match in matches:
            venue = match.get("verified_venue") or {}
            city = venue.get("city")
            if city:
                grouped.setdefault(str(city), []).append(match)
        enriched = 0
        for city, targets in list(grouped.items())[:12]:
            coords = self._coordinates(city)
            if not coords:
                continue
            payload = self._json(self.forecast_url, {
                "latitude": coords[0], "longitude": coords[1], "timezone": "Europe/Istanbul",
                "forecast_days": 16,
                "hourly": "temperature_2m,precipitation_probability,wind_speed_10m",
            })
            hourly = payload.get("hourly", {}) if isinstance(payload, dict) else {}
            times = hourly.get("time", [])
            index = {str(value): i for i, value in enumerate(times)}
            for match in targets:
                raw = str(match.get("iso_date") or "")
                try:
                    kickoff = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    if kickoff.tzinfo is None:
                        kickoff = kickoff.replace(tzinfo=timezone.utc)
                    local = kickoff.astimezone(timezone(timedelta(hours=3)))
                    # Provider times are local clock strings. Match date/time fields
                    # are preferred because Maçkolik already normalized them to TR.
                    date = str(match.get("local_date") or raw[:10])[:10]
                    hour = int(str(match.get("match_time") or local.strftime("%H:%M"))[:2])
                    key = f"{date}T{hour:02d}:00"
                except (TypeError, ValueError):
                    continue
                pos = index.get(key)
                if pos is None:
                    continue
                def at(name):
                    values = hourly.get(name, [])
                    return values[pos] if pos < len(values) else None
                weather = {
                    "temperature_c": at("temperature_2m"),
                    "precipitation_probability": at("precipitation_probability"),
                    "wind_kmh": at("wind_speed_10m"),
                    "city": city, "source": "Open-Meteo",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                if any(isinstance(weather[key], (int, float)) for key in ("temperature_c", "precipitation_probability", "wind_kmh")):
                    match["verified_weather"] = weather
                    match.setdefault("verified_sources", []).append("Open-Meteo weather")
                    enriched += 1
        return matches, {"enabled": True, "enriched": enriched, "cities_checked": len(grouped)}


class ExternalDataHub:
    def __init__(self, api_football=None, odds_provider=None, weather_provider=None):
        self.api_football = api_football or ApiFootballProvider()
        self.odds_provider = odds_provider or TheOddsProvider()
        self.weather_provider = weather_provider or OpenMeteoProvider()
        self._lock = threading.Lock()
        self._status = {"state": "idle", "last_duration_ms": 0, "providers": {}}
        self._failures = {}
        self._retry_after = {}

    def enrich(self, matches):
        started = time.perf_counter()
        result = copy.deepcopy(matches)
        statuses = {}
        providers = (
            ("api_football", self.api_football),
            ("open_meteo", self.weather_provider),
            ("the_odds_api", self.odds_provider),
        )
        for name, provider in providers:
            if time.time() < self._retry_after.get(name, 0):
                statuses[name] = {
                    "enabled": provider.enabled, "state": "cooldown", "enriched": 0,
                    "retry_in_seconds": round(self._retry_after[name] - time.time()),
                }
                continue
            try:
                result, statuses[name] = provider.enrich(result)
                self._failures[name] = 0
                statuses[name]["state"] = "ready"
            except Exception as exc:
                error = str(exc)
                if getattr(provider, "api_key", None):
                    error = error.replace(str(provider.api_key), "***")
                failures = self._failures.get(name, 0) + 1
                self._failures[name] = failures
                if failures >= 3:
                    self._retry_after[name] = time.time() + min(900, 60 * (2 ** (failures - 3)))
                statuses[name] = {
                    "enabled": provider.enabled, "state": "error", "error": error[:180],
                    "enriched": 0, "consecutive_failures": failures,
                }
        with self._lock:
            self._status = {
                "state": "ready", "last_updated": datetime.now(timezone.utc).isoformat(),
                "last_duration_ms": round((time.perf_counter() - started) * 1000), "providers": statuses,
                "verified_match_count": sum(1 for match in result if match.get("verified_sources")),
            }
        return result

    def get_status(self):
        with self._lock:
            return copy.deepcopy(self._status)

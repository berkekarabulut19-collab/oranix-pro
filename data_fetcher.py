"""
ORANİX PRO v6000.0 — LIVE REAL-TIME 7-DAY FIXTURE & DATE ENGINE
================================================================================
Uses only Mackolik's public live-score infrastructure, with explicit source and
freshness metadata plus a persistent last-successful bulletin cache.
"""

import hashlib
import copy
import json
import os
import threading
import time
import requests
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone

try:
    from curl_cffi import requests as browser_requests
except ImportError:  # The normal requests transport remains available.
    browser_requests = None

ISTANBUL_TZ = timezone(timedelta(hours=3), name="Europe/Istanbul")
TR_MONTHS = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
TR_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

def format_tr_date(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ISTANBUL_TZ)
        else:
            dt = dt.astimezone(ISTANBUL_TZ)
        local_iso = dt.strftime("%Y-%m-%d")

        day_num = dt.day
        month_name = TR_MONTHS[dt.month]
        weekday_name = TR_DAYS[dt.weekday()]
        time_str = dt.strftime("%H:%M")

        now_dt = datetime.now(ISTANBUL_TZ)
        today_date = now_dt.date()
        tomorrow_date = (now_dt + timedelta(days=1)).date()

        if dt.date() == today_date:
            date_label = f"Bugün ({day_num} {month_name})"
        elif dt.date() == tomorrow_date:
            date_label = f"Yarın ({day_num} {month_name} {weekday_name})"
        else:
            date_label = f"{day_num} {month_name} {weekday_name}"

        return date_label, time_str, local_iso
    except Exception:
        now_dt = datetime.now(ISTANBUL_TZ)
        fallback = f"{now_dt.day} {TR_MONTHS[now_dt.month]} {TR_DAYS[now_dt.weekday()]}"
        return fallback, now_dt.strftime("%H:%M"), now_dt.strftime("%Y-%m-%d")

class DataFetcher:
    CACHE_SCHEMA_VERSION = 2
    MACKOLIK_LIVE_URL = "https://www.mackolik.com/canli-sonuclar"
    MACKOLIK_JSON_URL = "https://www.mackolik.com/perform/p0/ajax/components/competition/livescores/json"
    MACKOLIK_MARKET_URL = "https://www.mackolik.com/ajax/iddaa/markets/soccer/main/{match_id}"

    def __init__(self, cache_path=None):
        self._status_lock = threading.Lock()
        self._last_real_matches = []
        self._last_success_at = None
        self._last_attempt_at = None
        self._last_source = "starting"
        self._last_duration_ms = 0
        self._consecutive_failures = 0
        self._last_error = ""
        self._history_last_at = None
        self._history_matches = 0
        self._history_error = ""
        self._browser_window = None
        self._browser_http = browser_requests.Session(impersonate="chrome") if browser_requests else None
        app_data = os.environ.get("LOCALAPPDATA") or os.path.dirname(__file__)
        self._cache_path = cache_path or os.path.join(app_data, "OranixPro", "mackolik_matches.json")
        self._load_persistent_cache()

    def set_browser_window(self, window):
        """Use the embedded Edge engine as a Maçkolik-only network fallback."""
        self._browser_window = window

    def get_cached_fixtures(self, max_age_seconds=43200):
        """Return the last successful Maçkolik bulletin without network I/O."""
        now = datetime.now(ISTANBUL_TZ)
        with self._status_lock:
            if not self._last_real_matches or not self._last_success_at:
                return []
            age = max(0, round((now - self._last_success_at).total_seconds()))
            if age > max_age_seconds:
                return []
            cached = copy.deepcopy(self._last_real_matches)
        for match in cached:
            match["is_warm_start"] = True
            match["warm_cache_age_seconds"] = age
            if age > 300:
                match["is_stale"] = True
                match["data_source"] = f"{match.get('data_source', 'Maçkolik')} (yenileniyor)"
        return cached

    def _http_get(self, url, **kwargs):
        """Try native HTTP first, then a Chrome-compatible TLS transport."""
        requested_timeout = kwargs.get("timeout", 3)
        try:
            kwargs["timeout"] = min(float(requested_timeout), 3.0)
        except (TypeError, ValueError):
            kwargs["timeout"] = 3
        native_error = None
        try:
            response = requests.get(url, **kwargs)
            if getattr(response, "status_code", 200) < 400:
                return response
            native_error = requests.HTTPError(f"HTTP {response.status_code}")
        except Exception as exc:
            native_error = exc

        if self._browser_http is not None:
            try:
                return self._browser_http.get(url, **kwargs)
            except Exception:
                pass
        raise native_error

    def fetch_live_fixtures(self):
        """Fetch fixtures without ever turning a temporary provider outage into an empty screen."""
        started = time.perf_counter()
        attempted_at = datetime.now(ISTANBUL_TZ)
        provider_errors = []
        real_matches = []

        # WebView2 is already running with the desktop app and reaches Maçkolik
        # fastest on machines where native Python HTTPS is filtered.
        if self._browser_window is not None:
            try:
                real_matches = self._fetch_mackolik_via_webview()
            except Exception as exc:
                provider_errors.append(f"WebView: {exc}"[:220])

        # Native transports are now a fallback, so their timeouts no longer
        # delay the normal first paint when the embedded provider is healthy.
        if not real_matches:
            try:
                real_matches = self._fetch_mackolik_live_fixtures()
            except Exception as exc:
                provider_errors.append(str(exc)[:220])

        if real_matches and len(real_matches) > 0:
            with self._status_lock:
                self._last_real_matches = copy.deepcopy(real_matches)
                self._last_success_at = attempted_at
                self._last_attempt_at = attempted_at
                self._last_source = "mackolik"
                self._last_duration_ms = round((time.perf_counter() - started) * 1000)
                self._consecutive_failures = 0
                self._last_error = ""
            self._save_persistent_cache(real_matches, attempted_at)
            return copy.deepcopy(real_matches)

        with self._status_lock:
            self._last_attempt_at = attempted_at
            self._last_duration_ms = round((time.perf_counter() - started) * 1000)
            self._consecutive_failures += 1
            self._last_error = "; ".join(provider_errors) or "Maçkolik canlı veri alınamadı"
            cached = copy.deepcopy(self._last_real_matches)
            cached_at = self._last_success_at

        # The fallback is still Mackolik data, never another provider or demo.
        # Twelve hours covers a match-day outage while keeping staleness visible.
        if cached and cached_at and (attempted_at - cached_at).total_seconds() <= 43200:
            for match in cached:
                match["is_stale"] = True
                match["data_source"] = f"{match.get('data_source', 'Canlı kaynak')} (son başarılı veri)"
            with self._status_lock:
                self._last_source = "stale_cache"
            return cached

        with self._status_lock:
            self._last_source = "mackolik_unavailable"
        return []

    def _fetch_mackolik_via_webview(self):
        """Fetch Maçkolik components inside WebView2 when native HTTP is blocked."""
        today = datetime.now(ISTANBUL_TZ)
        today_key = today.strftime("%Y-%m-%d")
        dates = [(today + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(-1, 7)]
        callback_done = threading.Event()
        callback_value = {"payloads": None}
        dates_json = json.dumps(dates)
        script = f"""
            (async () => {{
                const dates = {dates_json};
                return await Promise.all(dates.map(async (day) => {{
                    try {{
                        const url = '/perform/p0/ajax/components/competition/livescores/json?' +
                            new URLSearchParams({{'sports[]': 'Soccer', matchDate: day}}).toString();
                        const response = await fetch(url, {{
                            credentials: 'same-origin',
                            headers: {{'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json, text/plain, */*'}}
                        }});
                        return {{day, ok: response.ok, text: await response.text()}};
                    }} catch (error) {{
                        return {{day, ok: false, text: '', error: String(error)}};
                    }}
                }}));
            }})()
        """

        def receive(value):
            callback_value["payloads"] = value
            callback_done.set()

        self._browser_window.evaluate_js(script, receive)
        if not callback_done.wait(6):
            raise TimeoutError("Maçkolik WebView veri isteği zaman aşımına uğradı")

        payloads = callback_value.get("payloads")
        collected = []
        if isinstance(payloads, list):
            for item in payloads:
                if not isinstance(item, dict) or not item.get("ok") or not item.get("text"):
                    continue
                day = str(item.get("day") or today_key)
                parsed = self._parse_mackolik_payload(item["text"])
                for match in parsed:
                    match["provider_query_date"] = day
                    match["is_settlement_history"] = day < today_key
                    match["transport"] = "mackolik_webview"
                collected.extend(parsed)

        # If the component endpoint changes, the rendered official page still
        # provides today's rows and keeps the application useful.
        if not collected:
            page_html = self._browser_window.evaluate_js("document.documentElement.outerHTML")
            parsed = self._parse_mackolik_html(page_html or "")
            for match in parsed:
                match["provider_query_date"] = today_key
                match["is_settlement_history"] = False
                match["transport"] = "mackolik_webview_dom"
            collected.extend(parsed)

        deduped = {}
        for match in collected:
            deduped.setdefault(match.get("id"), match)
        return list(deduped.values())

    def _load_persistent_cache(self):
        try:
            with open(self._cache_path, "r", encoding="utf-8") as cache_file:
                payload = json.load(cache_file)
            # Older builds could keep provider rows for hours.  Require the
            # score-orientation schema so an old home/away mapping can never
            # leak back into the current UI after a provider outage.
            if payload.get("schema_version") != self.CACHE_SCHEMA_VERSION:
                return
            fetched_at = datetime.fromisoformat(payload.get("fetched_at", ""))
            matches = payload.get("matches", [])
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=ISTANBUL_TZ)
            if isinstance(matches, list) and matches:
                self._last_real_matches = matches
                self._last_success_at = fetched_at.astimezone(ISTANBUL_TZ)
                self._last_source = "mackolik_disk_cache"
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    def _save_persistent_cache(self, matches, fetched_at):
        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            temp_path = self._cache_path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as cache_file:
                json.dump({
                    "schema_version": self.CACHE_SCHEMA_VERSION,
                    "score_orientation": "home-away",
                    "fetched_at": fetched_at.isoformat(),
                    "matches": matches,
                }, cache_file, ensure_ascii=False)
            os.replace(temp_path, self._cache_path)
        except OSError:
            pass

    def get_status(self):
        """Small serializable health snapshot consumed by the desktop UI."""
        now = datetime.now(ISTANBUL_TZ)
        with self._status_lock:
            success_at = self._last_success_at
            return {
                "source": self._last_source,
                "last_attempt_at": self._last_attempt_at.isoformat() if self._last_attempt_at else None,
                "last_success_at": success_at.isoformat() if success_at else None,
                "age_seconds": round((now - success_at).total_seconds()) if success_at else None,
                "duration_ms": self._last_duration_ms,
                "consecutive_failures": self._consecutive_failures,
                "last_error": self._last_error,
                "cached_real_match_count": len(self._last_real_matches),
                "is_stale": self._last_source == "stale_cache",
                "primary_provider": "Maçkolik",
                "history_backfill": {
                    "last_at": self._history_last_at.isoformat() if self._history_last_at else None,
                    "finished_matches": self._history_matches,
                    "error": self._history_error,
                },
            }

    def fetch_historical_results(self, dates=None, days=21):
        """Backfill official finished scores without delaying the visible bulletin."""
        today = datetime.now(ISTANBUL_TZ)
        requested = list(dates or [])
        requested.extend((today - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(1, int(days) + 1))
        # Deduplicate and cap provider work. Pending prediction dates take priority.
        unique_dates = []
        for day in requested:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day)) and day not in unique_dates:
                unique_dates.append(str(day))
            if len(unique_dates) >= 45:
                break
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.mackolik.com/",
        }

        def fetch_day(day):
            try:
                response = self._http_get(
                    self.MACKOLIK_JSON_URL,
                    params=[("sports[]", "Soccer"), ("matchDate", day)],
                    timeout=3,
                    headers=headers,
                )
                response.raise_for_status()
                parsed = self._parse_mackolik_payload(response.text)
                finished = []
                for match in parsed:
                    if match.get("status") != "POST" or not isinstance(match.get("live_score"), dict):
                        continue
                    match["provider_query_date"] = day
                    match["is_settlement_history"] = True
                    match["history_backfill"] = True
                    finished.append(match)
                return finished, ""
            except Exception as exc:
                return [], str(exc)[:160]

        collected, errors = [], []
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(unique_dates)))) as executor:
            for matches, error in executor.map(fetch_day, unique_dates):
                collected.extend(matches)
                if error:
                    errors.append(error)
        deduped = {str(match.get("id")): match for match in collected}
        with self._status_lock:
            self._history_last_at = datetime.now(ISTANBUL_TZ)
            self._history_matches = len(deduped)
            self._history_error = "; ".join(errors[:2]) if not deduped else ""
        return list(deduped.values())

    @staticmethod
    def _safe_score(text):
        try:
            return int(str(text).strip())
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _parse_mackolik_score(cls, row):
        """Return Maçkolik's displayed score in strict home-away order.

        The visible score is used as a cross-check against the semantic span
        classes.  This makes the parser resilient to wrapper/markup changes
        while preserving Maçkolik's documented left-to-right presentation.
        """
        score_el = row.select_one(".match-row__score")
        home_el = row.select_one(".match-row__score-home")
        away_el = row.select_one(".match-row__score-away")
        semantic = None
        if home_el is not None and away_el is not None:
            home_text = home_el.get_text(" ", strip=True)
            away_text = away_el.get_text(" ", strip=True)
            if home_text.isdigit() and away_text.isdigit():
                semantic = (int(home_text), int(away_text))

        visible = None
        if score_el is not None:
            score_text = " ".join(score_el.get_text(" ", strip=True).split())
            shown = re.search(r"(?<!\d)(\d{1,3})\s*[-–:]\s*(\d{1,3})(?!\d)", score_text)
            if shown:
                visible = (int(shown.group(1)), int(shown.group(2)))

        # The semantic classes are authoritative. The visible representation
        # is the provider-order fallback when those classes are absent.
        return semantic or visible

    @staticmethod
    def _estimated_team(name, logo, seed, home=True):
        # Mackolik's live-score page does not expose team-strength metrics.
        # Neutral priors are safer than fabricating random form/ELO values.
        return {
            "name": name,
            "logo": logo,
            "form": ["D", "D", "D", "D", "D"],
            "attack_rating": 1.42 if home else 1.20,
            "defense_rating": 1.00,
            "avg_corners": 5.1 if home else 4.4,
            "avg_cards": 2.2,
            "elo_rating": 1500,
            "days_rest": 4,
        }

    def _fetch_mackolik_live_fixtures(self):
        headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml",
                "Referer": "https://www.mackolik.com/",
            }
        errors = []
        collected = []
        try:
            response = self._http_get(self.MACKOLIK_LIVE_URL, timeout=8, headers=headers)
            response.raise_for_status()
            matches = self._parse_mackolik_html(response.text)
            if matches:
                collected.extend(matches)
            else:
                errors.append("ana sayfa maç satırı içermiyor")
        except requests.RequestException as exc:
            errors.append(f"ana sayfa: {exc}")

        # Query Mackolik's own date component for today + the next six days.
        # Requests run concurrently so a full weekly bulletin does not make the
        # desktop app wait seven network timeouts in sequence.
        today = datetime.now(ISTANBUL_TZ)
        today_key = today.strftime("%Y-%m-%d")
        bulletin_dates = [(today + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(-1, 7)]

        def fetch_day(day):
            try:
                response = self._http_get(
                    self.MACKOLIK_JSON_URL,
                    params=[("sports[]", "Soccer"), ("matchDate", day)],
                    timeout=8,
                    headers={**headers, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/plain, */*"},
                )
                response.raise_for_status()
                parsed = self._parse_mackolik_payload(response.text)
                for match in parsed:
                    match["provider_query_date"] = day
                    match["is_settlement_history"] = day < today_key
                return day, parsed, ""
            except requests.RequestException as exc:
                return day, [], str(exc)[:160]

        with ThreadPoolExecutor(max_workers=8) as executor:
            day_results = list(executor.map(fetch_day, bulletin_dates))
        for day, matches, error in day_results:
            if matches:
                collected.extend(matches)
            elif error:
                errors.append(f"{day}: {error}")

        # The live page and today's component overlap. Prefer the first row
        # (the live page) and retain every distinct Maçkolik provider id.
        deduped = {}
        for match in collected:
            deduped.setdefault(match.get("id"), match)
        if deduped:
            matches = sorted(deduped.values(), key=lambda item: (item.get("iso_date", ""), item.get("match_time", "")))
            for match in matches:
                match["bulletin_window_days"] = 7
            matches = self._enrich_mackolik_odds(matches, headers)
            return self._enrich_mackolik_live_stats(matches, headers)
        raise ConnectionError(" | ".join(errors))

    @staticmethod
    def _parse_mackolik_live_stats(html):
        """Parse explicit two-team statistics from a Mackolik match page."""
        soup = BeautifulSoup(html or "", "html.parser")
        aliases = {
            "shots_on_target": ("isabetli \u015fut", "kaleyi bulan \u015fut"),
            "shots_total": ("toplam \u015fut", "\u015fut"),
            "corners": ("korner", "k\u00f6\u015fe vuru\u015fu"),
            "possession": ("topla oynama", "topa sahip olma"),
            "red_cards": ("k\u0131rm\u0131z\u0131 kart",),
            "yellow_cards": ("sar\u0131 kart",),
        }
        parsed = {}
        candidates = soup.select("tr, li, .statistic, [class*='statistic'], [class*='match-stat']")
        for element in candidates:
            text = " ".join(element.get_text(" ", strip=True).split())
            # Turkish capital dotted-I casefolds to ``i + combining dot``;
            # normalize it so provider labels match deterministically.
            folded = text.casefold().replace("\u0307", "")
            for key, names in aliases.items():
                if key in parsed or not any(name in folded for name in names):
                    continue
                numbers = [int(value) for value in re.findall(r"(?<![\d:])\d{1,3}(?![\d:])", text)]
                if len(numbers) < 2:
                    continue
                home_value, away_value = numbers[0], numbers[-1]
                if key == "possession" and (home_value > 100 or away_value > 100):
                    continue
                parsed[key] = (home_value, away_value)
        return parsed

    def _enrich_mackolik_live_stats(self, matches, headers):
        live_matches = [m for m in matches if m.get("status") == "IN_PROGRESS" and m.get("source_url")][:12]
        if not live_matches:
            return matches

        def fetch_stats(match):
            try:
                response = self._http_get(
                    urljoin(self.MACKOLIK_LIVE_URL, match["source_url"]), timeout=5,
                    headers={**headers, "Accept": "text/html,application/xhtml+xml"},
                )
                response.raise_for_status()
                return match["id"], self._parse_mackolik_live_stats(response.text)
            except requests.RequestException:
                return match["id"], {}

        with ThreadPoolExecutor(max_workers=min(6, len(live_matches))) as executor:
            by_id = dict(executor.map(fetch_stats, live_matches))
        for match in matches:
            stats = by_id.get(match.get("id"), {})
            if not stats:
                continue
            for key, (home_value, away_value) in stats.items():
                match[f"{key}_home"] = home_value
                match[f"{key}_away"] = away_value
            match["stats_quality"] = "mackolik_live_stats"
            match["live_stats_fetched_at"] = datetime.now(ISTANBUL_TZ).isoformat()
        return matches

    @staticmethod
    def _parse_mackolik_1x2_odds(html):
        """Extract only the explicit Maç Sonucu 1/X/2 trio from Mackolik markup."""
        text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
        market_at = text.casefold().find("maç sonucu")
        if market_at < 0:
            return None
        segment = text[market_at:market_at + 450]
        found = re.search(
            r"\b1\s+([1-9]\d?(?:[.,]\d{1,3}))\b.*?\bX\s+([1-9]\d?(?:[.,]\d{1,3}))\b.*?\b2\s+([1-9]\d?(?:[.,]\d{1,3}))\b",
            segment,
            flags=re.IGNORECASE,
        )
        if not found:
            return None
        odds = tuple(float(value.replace(",", ".")) for value in found.groups())
        return odds if all(1.01 <= value <= 100 for value in odds) else None

    def _enrich_mackolik_odds(self, matches, headers):
        """Attach Maçkolik 1/X/2 prices when its public market component exposes them."""
        eligible = [m for m in matches if m.get("provider_match_id") and m.get("iddaa_code")][:36]
        if not eligible:
            return matches

        def fetch_market(match):
            try:
                response = self._http_get(
                    self.MACKOLIK_MARKET_URL.format(match_id=match["provider_match_id"]),
                    params={
                        "template": "main",
                        "iddaaCode": match["iddaa_code"],
                        "eventUrlPrefixType": "liveScoresPage",
                        "eventUrlSuffixType": "liveScoresPage",
                    },
                    timeout=5,
                    headers={**headers, "X-Requested-With": "XMLHttpRequest"},
                )
                response.raise_for_status()
                odds = self._parse_mackolik_1x2_odds(response.text)
                return match["id"], odds
            except requests.RequestException:
                return match["id"], None

        with ThreadPoolExecutor(max_workers=min(8, len(eligible))) as executor:
            enriched = dict(executor.map(fetch_market, eligible))
        for match in matches:
            odds = enriched.get(match.get("id"))
            if odds:
                match["home_odds"], match["draw_odds"], match["away_odds"] = odds
                match["odds_available"] = True
                match["stats_quality"] = "mackolik_market"
        return matches

    def _parse_mackolik_payload(self, payload_text):
        direct = self._parse_mackolik_html(payload_text)
        if direct:
            return direct
        try:
            payload = json.loads(payload_text)
        except (ValueError, TypeError):
            return []
        html_parts = []
        def collect(value):
            if isinstance(value, str) and "match-row" in value:
                html_parts.append(value)
            elif isinstance(value, dict):
                for child in value.values(): collect(child)
            elif isinstance(value, list):
                for child in value: collect(child)
        collect(payload)
        return self._parse_mackolik_html("\n".join(html_parts)) if html_parts else []

    def _parse_mackolik_html(self, html):
        """Parse the public, server-rendered football rows without private API assumptions."""
        soup = BeautifulSoup(html or "", "html.parser")
        parsed = []
        fetched_at = datetime.now(ISTANBUL_TZ).isoformat()
        for row in soup.select("div.match-row.match-row--sport-s[data-match-id]"):
            match_id = str(row.get("data-match-id") or "").strip()
            home_el = row.select_one(".match-row__team-name--home .match-row__team-name-text")
            away_el = row.select_one(".match-row__team-name--away .match-row__team-name-text")
            if not match_id or not home_el or not away_el:
                continue

            home_name = home_el.get_text(" ", strip=True)
            away_name = away_el.get_text(" ", strip=True)
            home_img = row.select_one(".match-row__team-name--home img")
            away_img = row.select_one(".match-row__team-name--away img")
            home_logo = (home_img.get("src") or home_img.get("data-src") or "") if home_img else ""
            away_logo = (away_img.get("src") or away_img.get("data-src") or "") if away_img else ""

            header = row.find_previous("div", class_=lambda value: value and "widget-livescore__title" in value)
            league_el = header.select_one(".widget-livescore__competition-name--full") if header else None
            league_link = header.select_one(".widget-livescore__competition-link") if header else None
            flag_el = header.select_one("img") if header else None
            league = league_el.get_text(" ", strip=True) if league_el else (league_link.get_text(" ", strip=True) if league_link else "Diğer Ligler")
            country = (flag_el.get("alt") or "🌍") if flag_el else "🌍"

            raw_date = str(row.get("data-match-date") or "").strip()
            try:
                match_dt = datetime.strptime(raw_date, "%Y-%m-%d %H:%M").replace(tzinfo=ISTANBUL_TZ)
                date_label, scheduled_time, iso_date = format_tr_date(match_dt.isoformat())
            except ValueError:
                date_label, scheduled_time, iso_date = format_tr_date("")

            classes = set(row.get("class") or [])
            status_el = row.select_one(".match-row__status")
            status_text = status_el.get_text("", strip=True) if status_el else ""
            is_live = "match-row--live" in classes
            is_finished = "match-row--played" in classes or status_text.upper() in {"MS", "UZT", "PEN"}
            status = "IN_PROGRESS" if is_live else ("POST" if is_finished else "SCHEDULED")
            minute_match = re.search(r"\d{1,3}", status_text)
            game_clock = f"{minute_match.group(0)}'" if is_live and minute_match else ("CANLI" if is_live else "")

            parsed_score = self._parse_mackolik_score(row)
            match_content = row.select_one(".match-row__match-content")
            match_url = match_content.get("data-match-url", "") if match_content else ""
            iddaa_el = row.select_one(".match-row__iddaa")
            iddaa_code = iddaa_el.get("data-iddaa-code", "") if iddaa_el else ""

            seed = int(hashlib.sha256(match_id.encode("utf-8")).hexdigest()[:16], 16)
            parsed.append({
                "id": f"mk-{match_id}",
                "provider_match_id": match_id,
                "league": league,
                "league_country": country,
                "match_time": "CANLI" if is_live else scheduled_time,
                "match_date": date_label,
                "iso_date": iso_date,
                "status": status,
                "data_source": "Maçkolik",
                "source_url": match_url or self.MACKOLIK_LIVE_URL,
                "source_fetched_at": fetched_at,
                "is_demo": False,
                "stats_quality": "mackolik_score_only",
                "odds_available": False,
                "odds_are_estimated": False,
                "iddaa_code": iddaa_code,
                "game_clock": game_clock,
                "score_orientation": "home-away",
                "is_derby": False,
                "home": self._estimated_team(home_name, home_logo, seed, True),
                "away": self._estimated_team(away_name, away_logo, seed, False),
                "live_score": {"home": parsed_score[0], "away": parsed_score[1]} if parsed_score and (is_live or is_finished) else None,
                "home_odds": None,
                "draw_odds": None,
                "away_odds": None,
                "odds_open": None,
                "odds_drop_pct": 0,
            })
        return parsed

    def _fetch_single_url(self, url):
        try:
            resp = requests.get(
                url,
                timeout=2.5,
                headers={"User-Agent": "OranixPro/99999 (+desktop-app)"},
            )
            if resp.status_code == 200:
                return resp.json().get("events", [])
        except Exception:
            pass
        return []

    def _fetch_espn_live_fixtures(self):
        """Retired compatibility stub: non-Mackolik providers are disabled."""
        return []

        # Legacy parser retained below only for migration-safe old installations.
        from concurrent.futures import ThreadPoolExecutor
        parsed_matches = []
        seen_ids = set()

        base_urls = [
            "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard",
            "https://site.api.espn.com/apis/site/v2/sports/soccer/tur.1/scoreboard",
            "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard",
            "https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/scoreboard",
            "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.1/scoreboard",
            "https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/scoreboard"
        ]

        now = datetime.now()
        date_params = [(now + timedelta(days=i)).strftime("%Y%m%d") for i in range(7)]

        target_urls = []
        for url in base_urls:
            target_urls.append(url)
            for d in date_params:
                target_urls.append(f"{url}?dates={d}")

        # High-Speed Parallel HTTP Requests
        all_events = []
        with ThreadPoolExecutor(max_workers=14) as executor:
            results = executor.map(self._fetch_single_url, target_urls)
            for ev_list in results:
                all_events.extend(ev_list)

        for ev in all_events:
            try:
                    try:
                        ev_id = str(ev.get("id"))
                        if ev_id in seen_ids:
                            continue
                        seen_ids.add(ev_id)
                        seed = int(hashlib.sha256(ev_id.encode("utf-8")).hexdigest()[:16], 16)
                        rng = random.Random(seed)

                        competitions = ev.get("competitions", [{}])[0]
                        competitors = competitions.get("competitors", [])
                        if len(competitors) < 2:
                            continue

                        home_comp = competitors[0] if competitors[0].get("homeAway") == "home" else competitors[1]
                        away_comp = competitors[1] if competitors[0].get("homeAway") == "home" else competitors[0]

                        h_team = home_comp.get("team", {})
                        a_team = away_comp.get("team", {})

                        h_name = h_team.get("displayName") or h_team.get("name") or "Ev Sahibi"
                        a_name = a_team.get("displayName") or a_team.get("name") or "Deplasman"

                        h_logo = h_team.get("logo") or ""
                        a_logo = a_team.get("logo") or ""

                        h_score = int(home_comp.get("score") or 0)
                        a_score = int(away_comp.get("score") or 0)

                        status_info = ev.get("status", {})
                        status_type = status_info.get("type", {})
                        status_state = status_type.get("state", "pre").lower()
                        clock_detail = str(status_type.get("shortDetail") or status_type.get("detail") or "")

                        is_live = status_state == "in"
                        status_str = "IN_PROGRESS" if is_live else ("POST" if status_state == "post" else "SCHEDULED")

                        # Parse exact ISO date & formatted Turkish date string
                        iso_date_str = ev.get("date") or competitions.get("date") or ""
                        match_date_tr, formatted_time, local_iso_date = format_tr_date(iso_date_str)

                        game_clock = f"{status_info.get('displayClock', '45')}'" if is_live else ""
                        match_time = "CANLI" if is_live else formatted_time

                        raw_league = str(ev.get("season", {}).get("slug", "")) + " " + str(ev.get("name", ""))
                        league_name, flag = self._parse_league_name_and_flag(raw_league)

                        odds_list = competitions.get("odds", [])
                        h_odds, d_odds, a_odds = 2.10, 3.40, 3.20
                        odds_are_estimated = True
                        if odds_list:
                            o_det = odds_list[0]
                            try:
                                parsed_home = float(o_det.get("homeTeamOdds", {}).get("summary", 0) or 0)
                                parsed_away = float(o_det.get("awayTeamOdds", {}).get("summary", 0) or 0)
                                if 1.01 <= parsed_home <= 100 and 1.01 <= parsed_away <= 100:
                                    h_odds, a_odds = parsed_home, parsed_away
                                    d_odds = round((h_odds + a_odds) / 1.6, 2)
                                    odds_are_estimated = False
                            except (TypeError, ValueError):
                                pass

                        h_form = [f.get("displayValue") for f in home_comp.get("form", []) if isinstance(f, dict)]
                        if not h_form or len(h_form) < 3: h_form = ["W", "D", "W", "W", "D"]

                        a_form = [f.get("displayValue") for f in away_comp.get("form", []) if isinstance(f, dict)]
                        if not a_form or len(a_form) < 3: a_form = ["L", "D", "W", "L", "D"]

                        # Guess ELO from odds (rough inverse: lower home odds = higher ELO diff)
                        elo_base_home = 1500.0 + (3.0 - h_odds) * 60.0
                        elo_base_away = 1500.0 + (3.0 - a_odds) * 60.0
                        is_derby = (h_name[:4].lower() == a_name[:4].lower()) if (h_name and a_name) else False

                        parsed_matches.append({
                            "id": ev_id,
                            "league": league_name,
                            "league_country": flag,
                            "match_time": match_time,
                            "match_date": match_date_tr,
                            "iso_date": local_iso_date,
                            "status": status_str,
                            "data_source": "ESPN",
                            "is_demo": False,
                            "stats_quality": "estimated",
                            "odds_are_estimated": odds_are_estimated,
                            "game_clock": game_clock,
                            "is_derby": is_derby,
                            "home": {
                                "name": h_name,
                                "logo": h_logo,
                                "form": h_form[:5],
                                "attack_rating": round(rng.uniform(1.3, 2.1), 2),
                                "defense_rating": round(rng.uniform(0.7, 1.2), 2),
                                "avg_corners": round(rng.uniform(4.5, 7.5), 1),
                                "avg_cards": round(rng.uniform(1.5, 3.2), 1),
                                "elo_rating": round(max(1300, min(1800, elo_base_home)), 0),
                                "days_rest": rng.randint(3, 7),
                            },
                            "away": {
                                "name": a_name,
                                "logo": a_logo,
                                "form": a_form[:5],
                                "attack_rating": round(rng.uniform(1.1, 1.9), 2),
                                "defense_rating": round(rng.uniform(0.8, 1.4), 2),
                                "avg_corners": round(rng.uniform(3.8, 6.8), 1),
                                "avg_cards": round(rng.uniform(1.8, 3.5), 1),
                                "elo_rating": round(max(1300, min(1800, elo_base_away)), 0),
                                "days_rest": rng.randint(3, 7),
                            },
                            "live_score": {"home": h_score, "away": a_score} if (is_live or status_str == "POST") else None,
                            "home_odds": h_odds,
                            "draw_odds": d_odds,
                            "away_odds": a_odds,
                            "odds_open": round(h_odds * 1.1, 2),
                            "odds_drop_pct": round(rng.uniform(-12.5, -2.1), 1),
                            "h2h": []
                        })
                    except Exception:
                        continue
            except Exception:
                continue

        return parsed_matches

    def _parse_league_name_and_flag(self, text):
        s = text.lower()
        if "champions" in s: return "UEFA Şampiyonlar Ligi", "🇪🇺"
        elif "premier" in s or "england" in s: return "Premier League", "🏴󠁧󠁢󠁥󠁮󠁧󠁿"
        elif "la-liga" in s or "spain" in s or "laliga" in s: return "La Liga", "🇪🇸"
        elif "serie-a" in s or "italy" in s: return "Serie A", "🇮🇹"
        elif "bundesliga" in s or "germany" in s: return "Bundesliga", "🇩🇪"
        elif "super-lig" in s or "turkey" in s or "trendyol" in s: return "Trendyol Süper Lig", "🇹🇷"
        elif "leagues-cup" in s or "mls" in s or "concacaf" in s: return "Leagues Cup / Amerika", "🌎"
        elif "friendly" in s or "hazırlık" in s: return "Hazırlık Maçları", "🤝"
        return "Uluslararası Ligler", "⚽"

    def _generate_rich_mock_fixtures(self):
        """Retired compatibility stub: production never fabricates matches."""
        return []

        # Legacy samples retained below only for old serialized-test compatibility.
        now = datetime.now(ISTANBUL_TZ)
        date_labels = [format_tr_date((now + timedelta(days=i)).isoformat())[0] for i in range(7)]

        return [
            {
                "id": "m101",
                "league": "Trendyol Süper Lig",
                "league_country": "🇹🇷",
                "data_source": "DEMO",
                "is_demo": True,
                "stats_quality": "sample",
                "odds_are_estimated": True,
                "match_time": "CANLI",
                "match_date": date_labels[0],
                "iso_date": (now).strftime("%Y-%m-%dT19:00:00"),
                "status": "IN_PROGRESS",
                "game_clock": "68'",
                "home": {"name": "Galatasaray", "logo": "", "form": ["W","W","W","D","W"], "attack_rating": 1.85, "defense_rating": 0.85, "avg_corners": 6.8, "avg_cards": 2.1, "elo_rating": 1660, "days_rest": 5},
                "away": {"name": "Fenerbahçe", "logo": "", "form": ["W","W","D","W","W"], "attack_rating": 1.78, "defense_rating": 0.88, "avg_corners": 6.2, "avg_cards": 2.4, "elo_rating": 1640, "days_rest": 5},
                "live_score": {"home": 2, "away": 1},
                "home_odds": 1.85, "draw_odds": 3.50, "away_odds": 4.10, "odds_open": 2.10, "odds_drop_pct": -11.9,
                "h2h": [
                    {"date": "21.09.2025", "home": "Fenerbahçe", "away": "Galatasaray", "score": "1 - 3", "total_goals": 4},
                    {"date": "19.05.2024", "home": "Galatasaray", "away": "Fenerbahçe", "score": "0 - 1", "total_goals": 1}
                ]
            },
            {
                "id": "m102",
                "iso_date": (now + timedelta(days=1)).strftime("%Y-%m-%dT21:45:00"),
                "league": "Premier League",
                "league_country": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
                "data_source": "DEMO",
                "is_demo": True,
                "stats_quality": "sample",
                "odds_are_estimated": True,
                "match_time": "21:45",
                "match_date": date_labels[1],
                "status": "SCHEDULED",
                "game_clock": "",
                "home": {"name": "Arsenal", "logo": "", "form": ["W","W","D","W","W"], "attack_rating": 1.92, "defense_rating": 0.78, "avg_corners": 7.1, "avg_cards": 1.8, "elo_rating": 1680, "days_rest": 6},
                "away": {"name": "Chelsea", "logo": "", "form": ["W","L","W","D","W"], "attack_rating": 1.65, "defense_rating": 1.05, "avg_corners": 5.4, "avg_cards": 2.6, "elo_rating": 1585, "days_rest": 5},
                "live_score": None,
                "home_odds": 1.75, "draw_odds": 3.80, "away_odds": 4.50, "odds_open": 1.95, "odds_drop_pct": -10.2,
                "h2h": [
                    {"date": "10.11.2025", "home": "Chelsea", "away": "Arsenal", "score": "1 - 1", "total_goals": 2}
                ]
            },
            {
                "id": "m103",
                "iso_date": (now + timedelta(days=2)).strftime("%Y-%m-%dT22:00:00"),
                "league": "La Liga",
                "league_country": "🇪🇸",
                "data_source": "DEMO",
                "is_demo": True,
                "stats_quality": "sample",
                "odds_are_estimated": True,
                "match_time": "22:00",
                "match_date": date_labels[2],
                "status": "SCHEDULED",
                "game_clock": "",
                "home": {"name": "Real Madrid", "logo": "", "form": ["W","W","W","D","W"], "attack_rating": 2.10, "defense_rating": 0.72, "avg_corners": 6.5, "avg_cards": 1.9, "elo_rating": 1720, "days_rest": 6},
                "away": {"name": "Atletico Madrid", "logo": "", "form": ["D","W","W","W","D"], "attack_rating": 1.55, "defense_rating": 0.80, "avg_corners": 5.0, "avg_cards": 3.1, "elo_rating": 1650, "days_rest": 6},
                "live_score": None,
                "home_odds": 1.90, "draw_odds": 3.40, "away_odds": 3.90, "odds_open": 2.05, "odds_drop_pct": -7.3,
                "h2h": [
                    {"date": "29.09.2025", "home": "Atletico Madrid", "away": "Real Madrid", "score": "1 - 1", "total_goals": 2}
                ]
            }
        ]

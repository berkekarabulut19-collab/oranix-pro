import unittest
import os
import tempfile
from datetime import datetime
from unittest.mock import patch

from data_fetcher import DataFetcher, format_tr_date


class DataFetcherContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.fetcher = DataFetcher(os.path.join(self.temp_dir.name, "mackolik.json"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_legacy_fallbacks_are_disabled(self):
        self.assertEqual(self.fetcher._fetch_espn_live_fixtures(), [])
        self.assertEqual(self.fetcher._generate_rich_mock_fixtures(), [])

    def test_invalid_date_falls_back_to_today(self):
        _, time_text, iso_date = format_tr_date("invalid")
        self.assertEqual(iso_date, datetime.now().strftime("%Y-%m-%d"))
        self.assertRegex(time_text, r"^\d{2}:\d{2}$")

    def test_provider_failure_never_returns_other_provider_or_demo(self):
        self.fetcher._fetch_mackolik_live_fixtures = lambda: []
        matches = self.fetcher.fetch_live_fixtures()
        status = self.fetcher.get_status()
        self.assertEqual(matches, [])
        self.assertEqual(status["source"], "mackolik_unavailable")
        self.assertEqual(status["consecutive_failures"], 1)

    def test_recent_real_data_is_used_as_explicit_stale_fallback(self):
        real = [{"id": "real-1", "data_source": "Maçkolik", "home": {}, "away": {}}]
        self.fetcher._fetch_mackolik_live_fixtures = lambda: real
        self.fetcher._fetch_espn_live_fixtures = lambda: []
        self.assertEqual(self.fetcher.fetch_live_fixtures()[0]["id"], "real-1")
        self.fetcher._fetch_mackolik_live_fixtures = lambda: []
        self.fetcher._fetch_espn_live_fixtures = lambda: []
        stale = self.fetcher.fetch_live_fixtures()
        self.assertTrue(stale[0]["is_stale"])
        self.assertEqual(self.fetcher.get_status()["source"], "stale_cache")

    def test_successful_mackolik_bulletin_survives_app_restart(self):
        real = [{"id": "mk-persist", "data_source": "Maçkolik", "home": {"name": "A"}, "away": {"name": "B"}}]
        self.fetcher._fetch_mackolik_live_fixtures = lambda: real
        self.assertEqual(self.fetcher.fetch_live_fixtures()[0]["id"], "mk-persist")
        restarted = DataFetcher(self.fetcher._cache_path)
        restarted._fetch_mackolik_live_fixtures = lambda: []
        cached = restarted.fetch_live_fixtures()
        self.assertEqual(cached[0]["id"], "mk-persist")
        self.assertTrue(cached[0]["is_stale"])
        self.assertTrue(cached[0]["data_source"].startswith("Maçkolik"))

    def test_recent_persistent_bulletin_can_be_read_without_network(self):
        real = [{"id": "mk-fast", "data_source": "Maçkolik", "home": {"name": "A"}, "away": {"name": "B"}}]
        self.fetcher._fetch_mackolik_live_fixtures = lambda: real
        self.fetcher.fetch_live_fixtures()
        restarted = DataFetcher(self.fetcher._cache_path)
        warm = restarted.get_cached_fixtures()
        self.assertEqual(warm[0]["id"], "mk-fast")
        self.assertTrue(warm[0]["is_warm_start"])

    def test_json_component_html_payload_is_supported(self):
        row = '<div class="match-row match-row--sport-s" data-match-id="j1" data-match-date="2026-08-12 20:00"><span class="match-row__team-name--home"><span class="match-row__team-name-text">A</span></span><span class="match-row__team-name--away"><span class="match-row__team-name-text">B</span></span></div>'
        matches = self.fetcher._parse_mackolik_payload('{"content": ' + __import__("json").dumps(row) + '}')
        self.assertEqual(matches[0]["provider_match_id"], "j1")

    def test_webview_transport_recovers_when_native_https_is_blocked(self):
        row = '<div class="match-row match-row--sport-s" data-match-id="wv1" data-match-date="2026-08-12 20:00"><span class="match-row__team-name--home"><span class="match-row__team-name-text">A</span></span><span class="match-row__team-name--away"><span class="match-row__team-name-text">B</span></span></div>'
        payload = '{"content": ' + __import__("json").dumps(row) + '}'

        class FakeWindow:
            def evaluate_js(self, script, callback=None):
                if callback:
                    callback([{"day": "2026-08-12", "ok": True, "text": payload}])
                    return None
                return "<html></html>"

        self.fetcher.set_browser_window(FakeWindow())
        native_calls = {"count": 0}
        def native_fetch():
            native_calls["count"] += 1
            return []
        self.fetcher._fetch_mackolik_live_fixtures = native_fetch
        matches = self.fetcher.fetch_live_fixtures()
        self.assertEqual(matches[0]["id"], "mk-wv1")
        self.assertEqual(matches[0]["transport"], "mackolik_webview")
        self.assertEqual(native_calls["count"], 0)
        self.assertEqual(self.fetcher.get_status()["source"], "mackolik")

    def test_mackolik_match_result_odds_parser(self):
        html = "<section><h3>Maç Sonucu</h3><span>1 1,33</span><span>X 3.31</span><span>2 5.49</span></section>"
        self.assertEqual(self.fetcher._parse_mackolik_1x2_odds(html), (1.33, 3.31, 5.49))
        self.assertIsNone(self.fetcher._parse_mackolik_1x2_odds("<p>Toplam Gol 2.5</p>"))

    def test_mackolik_live_statistics_parser(self):
        html = """
        <div class="match-statistic"><b>5</b><span>İsabetli Şut</span><b>2</b></div>
        <div class="match-statistic"><b>61%</b><span>Topla Oynama</span><b>39%</b></div>
        <div class="match-statistic"><b>1</b><span>Kırmızı Kart</span><b>0</b></div>
        """
        stats = self.fetcher._parse_mackolik_live_stats(html)
        self.assertEqual(stats["shots_on_target"], (5, 2))
        self.assertEqual(stats["possession"], (61, 39))
        self.assertEqual(stats["red_cards"], (1, 0))

    def test_mackolik_weekly_bulletin_queries_history_plus_seven_days(self):
        requested_days = []

        class Response:
            def __init__(self, text): self.text = text
            def raise_for_status(self): return None

        def fake_get(url, params=None, **kwargs):
            if url == self.fetcher.MACKOLIK_LIVE_URL:
                return Response("<html></html>")
            day = dict(params)["matchDate"]
            requested_days.append(day)
            row = f'<div class="match-row match-row--sport-s" data-match-id="{day}" data-match-date="{day} 20:00"><span class="match-row__team-name--home"><span class="match-row__team-name-text">A</span></span><span class="match-row__team-name--away"><span class="match-row__team-name-text">B</span></span></div>'
            return Response('{"content": ' + __import__("json").dumps(row) + '}')

        with patch("data_fetcher.requests.get", side_effect=fake_get):
            matches = self.fetcher._fetch_mackolik_live_fixtures()
        self.assertEqual(len(set(requested_days)), 8)
        self.assertEqual(len(matches), 8)
        self.assertTrue(all(match["bulletin_window_days"] == 7 for match in matches))
        self.assertEqual(sum(bool(match.get("is_settlement_history")) for match in matches), 1)

    def test_mackolik_html_contract_is_parsed_as_live_football(self):
        html = """
        <div class="widget-livescore__title widget-livescore__title--sport-s">
          <a class="widget-livescore__competition-link"><img alt="Avrupa">
            <span class="widget-livescore__competition-name--full">Konferans Ligi</span></a>
        </div>
        <div class="match-row match-row--live match-row--sport-s" data-match-id="abc123" data-match-date="2026-08-12 19:00">
          <div class="match-row__match-content" data-match-url="https://www.mackolik.com/mac/a-vs-b/abc123"></div>
          <a class="match-row__status">23<span>\u0027</span></a>
          <a class="match-row__team-name--home"><img src="https://img/a"><span class="match-row__team-name-text">Takım A</span></a>
          <a class="match-row__score"><span class="match-row__score-home">1</span>-<span class="match-row__score-away">0</span></a>
          <a class="match-row__team-name--away"><img src="https://img/b"><span class="match-row__team-name-text">Takım B</span></a>
          <a class="match-row__iddaa" data-iddaa-code="12345"></a>
        </div>
        """
        matches = self.fetcher._parse_mackolik_html(html)
        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match["id"], "mk-abc123")
        self.assertEqual(match["data_source"], "Maçkolik")
        self.assertEqual(match["league"], "Konferans Ligi")
        self.assertEqual(match["status"], "IN_PROGRESS")
        self.assertEqual(match["game_clock"], "23'")
        self.assertEqual(match["live_score"], {"home": 1, "away": 0})
        self.assertEqual(match["score_orientation"], "home-away")
        self.assertFalse(match["odds_are_estimated"])
        self.assertFalse(match["odds_available"])
        self.assertIsNone(match["home_odds"])

    def test_mackolik_visible_score_fallback_keeps_home_away_order(self):
        html = """
        <div class="match-row match-row--played match-row--sport-s" data-match-id="score1" data-match-date="2026-08-12 19:15">
          <span class="match-row__status">MS</span>
          <span class="match-row__team-name--home"><span class="match-row__team-name-text">Everton</span></span>
          <a class="match-row__score"><span>3</span>-<span>1</span></a>
          <span class="match-row__team-name--away"><span class="match-row__team-name-text">Newcastle</span></span>
        </div>
        """
        match = self.fetcher._parse_mackolik_html(html)[0]
        self.assertEqual(match["home"]["name"], "Everton")
        self.assertEqual(match["away"]["name"], "Newcastle")
        self.assertEqual(match["live_score"], {"home": 3, "away": 1})

    def test_old_cache_schema_is_not_loaded(self):
        import json
        cache_path = self.fetcher._cache_path
        with open(cache_path, "w", encoding="utf-8") as cache_file:
            json.dump({"fetched_at": datetime.now().isoformat(), "matches": [{"id": "old"}]}, cache_file)
        restarted = DataFetcher(cache_path)
        self.assertEqual(restarted.get_status()["cached_real_match_count"], 0)

    def test_history_backfill_keeps_only_finished_scores(self):
        finished = '''<div class="match-row match-row--played match-row--sport-s" data-match-id="done1" data-match-date="2026-08-01 20:00"><span class="match-row__status">MS</span><span class="match-row__team-name--home"><span class="match-row__team-name-text">A</span></span><span class="match-row__score"><span class="match-row__score-home">2</span>-<span class="match-row__score-away">1</span></span><span class="match-row__team-name--away"><span class="match-row__team-name-text">B</span></span></div>'''
        scheduled = '''<div class="match-row match-row--sport-s" data-match-id="future1" data-match-date="2026-08-01 22:00"><span class="match-row__team-name--home"><span class="match-row__team-name-text">C</span></span><span class="match-row__team-name--away"><span class="match-row__team-name-text">D</span></span></div>'''
        class Response:
            text = '{"content": ' + __import__("json").dumps(finished + scheduled) + '}'
            def raise_for_status(self): return None
        self.fetcher._http_get = lambda *args, **kwargs: Response()
        results = self.fetcher.fetch_historical_results(["2026-08-01"], days=0)
        self.assertEqual([item["id"] for item in results], ["mk-done1"])
        self.assertTrue(results[0]["is_settlement_history"])
        self.assertEqual(self.fetcher.get_status()["history_backfill"]["finished_matches"], 1)


if __name__ == "__main__":
    unittest.main()

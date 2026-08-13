import unittest
from datetime import datetime, timezone

from external_data import ApiFootballProvider, ExternalDataHub, OpenMeteoProvider, TheOddsProvider, _team_similarity


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class ExternalDataTests(unittest.TestCase):
    def test_team_matching_handles_accents_but_rejects_reversed_fixture(self):
        self.assertGreater(_team_similarity("Fenerbahçe SK", "Fenerbahce"), 0.95)
        match = {"home": {"name": "Galatasaray"}, "away": {"name": "Fenerbahçe"}}
        fixtures = [{"teams": {"home": {"name": "Fenerbahce"}, "away": {"name": "Galatasaray"}}}]
        self.assertIsNone(ApiFootballProvider._safe_fixture_match(match, fixtures))

    def test_api_football_enriches_only_verified_fixture(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        kickoff = datetime.now(timezone.utc).isoformat()

        def fake_get(url, params=None, headers=None, timeout=None):
            if url.endswith("/fixtures"):
                return FakeResponse({"response": [{
                    "fixture": {"id": 77, "date": kickoff},
                    "teams": {"home": {"name": "Galatasaray"}, "away": {"name": "Fenerbahce"}},
                }]})
            if url.endswith("/injuries"):
                return FakeResponse({"response": [{
                    "fixture": {"id": 77}, "team": {"name": "Galatasaray"},
                    "player": {"name": "Oyuncu A", "type": "Missing Fixture", "reason": "Injury"},
                }]})
            if url.endswith("/fixtures/lineups"):
                return FakeResponse({"response": [{"startXI": [{}] * 11}, {"startXI": [{}] * 11}]})
            raise AssertionError(url)

        provider = ApiFootballProvider("key", fake_get)
        matches = [{
            "id": "m1", "iso_date": today, "status": "IN_PROGRESS",
            "home": {"name": "Galatasaray SK"}, "away": {"name": "Fenerbahçe SK"},
        }]
        enriched, status = provider.enrich(matches)
        self.assertEqual(status["mapped"], 1)
        self.assertEqual(enriched[0]["external_fixture_id"], 77)
        self.assertEqual(enriched[0]["verified_absences"]["home"][0]["player"], "Oyuncu A")
        self.assertTrue(enriched[0]["verified_lineups"]["confirmed"])

    def test_odds_provider_adds_consensus_without_overwriting_mackolik(self):
        def fake_get(url, params=None, timeout=None):
            return FakeResponse([{
                "home_team": "Arsenal", "away_team": "Chelsea",
                "bookmakers": [{"markets": [{"key": "h2h", "outcomes": [
                    {"name": "Arsenal", "price": 1.90}, {"name": "Draw", "price": 3.50},
                    {"name": "Chelsea", "price": 4.10},
                ]}]}],
            }])

        provider = TheOddsProvider("key", fake_get)
        matches = [{"id": "o1", "league": "Premier League", "home_odds": 2.0,
                    "iso_date": datetime.now(timezone.utc).isoformat(),
                    "home": {"name": "Arsenal FC"}, "away": {"name": "Chelsea FC"}}]
        enriched, status = provider.enrich(matches)
        self.assertEqual(status["enriched"], 1)
        self.assertEqual(enriched[0]["home_odds"], 2.0)
        self.assertEqual(enriched[0]["consensus_odds"]["home"], 1.90)

    def test_missing_keys_are_visible_and_do_not_change_matches(self):
        hub = ExternalDataHub(ApiFootballProvider(""), TheOddsProvider(""))
        result = hub.enrich([{"id": "safe"}])
        self.assertEqual(result, [{"id": "safe"}])
        self.assertFalse(hub.get_status()["providers"]["api_football"]["enabled"])

    def test_open_meteo_enriches_only_verified_venue(self):
        def fake_get(url, params=None, timeout=None):
            if "geocoding" in url:
                return FakeResponse({"results": [{"latitude": 41.01, "longitude": 28.97}]})
            return FakeResponse({"hourly": {
                "time": ["2026-08-13T20:00"], "temperature_2m": [29.0],
                "precipitation_probability": [75], "wind_speed_10m": [36.0],
            }})

        provider = OpenMeteoProvider(fake_get)
        matches = [{
            "id": "weather-1", "iso_date": "2026-08-13T17:00:00+00:00",
            "local_date": "2026-08-13", "match_time": "20:00",
            "verified_venue": {"city": "İstanbul", "source": "API-Football"},
        }]
        enriched, status = provider.enrich(matches)
        self.assertEqual(status["enriched"], 1)
        self.assertEqual(enriched[0]["verified_weather"]["source"], "Open-Meteo")
        self.assertEqual(enriched[0]["verified_weather"]["wind_kmh"], 36.0)


if __name__ == "__main__":
    unittest.main()

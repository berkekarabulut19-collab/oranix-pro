from data_fetcher import DataFetcher
from predictor_engine import PredictorEngine
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

df = DataFetcher()
matches = df.fetch_live_fixtures()
print("Total matches fetched:", len(matches))
if matches:
    m = matches[0]
    print("Sample match:", m["home"]["name"], "vs", m["away"]["name"])
    print("  Home logo:", m["home"]["logo"])
    print("  Away logo:", m["away"]["logo"])
    print("  League:", m["league"])
    print("  Time:", m["match_time"])
    print("  Status:", m["status"])

    pe = PredictorEngine()
    a = pe.analyze_match(m)
    print("Analysis:")
    print("  xG home/away:", a["xg_home"], "/", a["xg_away"])
    print("  Probs:", a["probs"])
    print("  Best bet:", a["best_bet"])
    print("  Confidence:", a["confidence"])
    print("  Top scores:", a["top_scores"][:3])
    print("  Insights count:", len(a.get("insights", [])))
    print("  Goal markets:", a.get("goal_markets", {}))

    assert a.get("best_bet"), "Tahmin motoru en iyi bahis üretmedi"
    assert a.get("probs"), "Tahmin motoru olasılık üretmedi"

print("ALL OK!")

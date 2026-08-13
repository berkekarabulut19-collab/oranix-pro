"""Conservative accumulator and bankroll risk analysis for Oranix."""

import math
from collections import Counter


class CouponRiskEngine:
    """Scores coupon concentration without pretending selections are independent."""

    def analyze(self, picks, matches=None, bankroll=10000.0):
        picks = [dict(item) for item in (picks or []) if isinstance(item, dict)]
        match_map = {str(item.get("id")): item for item in (matches or [])}
        bankroll = max(0.0, float(bankroll or 0.0))
        normalized = []
        warnings = []

        for item in picks[:20]:
            try:
                odds = float(item.get("odds"))
                probability = float(item.get("prob")) / 100.0
            except (TypeError, ValueError):
                continue
            if not (1.01 < odds < 100 and 0 < probability < 1):
                continue
            match_id = str(item.get("matchId") or item.get("match_id") or "")
            match = match_map.get(match_id, {})
            normalized.append({
                "match_id": match_id,
                "odds": odds,
                "probability": probability,
                "league": str(match.get("league") or item.get("league") or "Bilinmiyor"),
                "date": str(match.get("local_date") or match.get("iso_date") or item.get("date") or "")[:10],
            })

        if not normalized:
            return {
                "status": "empty", "risk_score": 0, "risk_level": "HESAPLANAMADI",
                "recommended_stake": 0.0, "warnings": ["Geçerli oran ve olasılık bulunamadı."],
            }

        match_counts = Counter(item["match_id"] for item in normalized if item["match_id"])
        duplicate_matches = sum(count - 1 for count in match_counts.values() if count > 1)
        if duplicate_matches:
            warnings.append("Aynı maçtan birden fazla seçim bağımsız kabul edilemez.")

        cluster_counts = Counter((item["league"], item["date"]) for item in normalized if item["date"])
        correlated_pairs = sum(count * (count - 1) // 2 for count in cluster_counts.values() if count > 1)
        if correlated_pairs:
            warnings.append("Aynı lig ve gündeki seçimler ortak koşullardan etkilenebilir.")

        total_odds = math.prod(item["odds"] for item in normalized)
        naive_probability = math.prod(item["probability"] for item in normalized)
        # Haircut explicitly compensates for calibration error and dependence.
        dependency_haircut = max(0.45, 1.0 - 0.035 * max(0, len(normalized) - 1)
                                 - 0.025 * correlated_pairs - 0.12 * duplicate_matches)
        adjusted_probability = naive_probability * dependency_haircut
        expected_return = adjusted_probability * total_odds - 1.0

        risk_score = 12 + max(0, len(normalized) - 1) * 11
        risk_score += min(24, correlated_pairs * 4) + duplicate_matches * 25
        risk_score += min(18, max(0.0, total_odds - 3.0) * 1.8)
        risk_score += sum(5 for item in normalized if item["probability"] < 0.50)
        risk_score = int(max(0, min(100, round(risk_score))))

        if risk_score < 30:
            level = "DÜŞÜK"
        elif risk_score < 55:
            level = "ORTA"
        elif risk_score < 75:
            level = "YÜKSEK"
        else:
            level = "ÇOK YÜKSEK"

        b = total_odds - 1.0
        kelly = max(0.0, (b * adjusted_probability - (1.0 - adjusted_probability)) / max(0.01, b))
        # Quarter-Kelly plus hard 2% bankroll cap; accumulators receive an
        # additional risk discount. A negative edge always yields zero stake.
        stake_fraction = min(0.02, kelly * 0.25 * max(0.15, 1.0 - risk_score / 110.0))
        recommended_stake = round(bankroll * stake_fraction, 2) if expected_return > 0 else 0.0
        if expected_return <= 0:
            warnings.append("Temkinli birleşik hesaplamada pozitif değer kanıtlanmadı.")
        if len(normalized) >= 5:
            warnings.append("Beş veya daha fazla seçim kupon riskini keskin biçimde artırır.")

        return {
            "status": "ready", "selection_count": len(normalized),
            "total_odds": round(total_odds, 2),
            "naive_win_probability_pct": round(naive_probability * 100, 2),
            "adjusted_win_probability_pct": round(adjusted_probability * 100, 2),
            "dependency_haircut_pct": round((1.0 - dependency_haircut) * 100, 1),
            "expected_value_pct": round(expected_return * 100, 1),
            "risk_score": risk_score, "risk_level": level,
            "recommended_stake": recommended_stake,
            "recommended_bankroll_pct": round(stake_fraction * 100, 2),
            "correlated_pairs": correlated_pairs, "warnings": warnings,
            "disclaimer": "Kupon olasılığı yaklaşık ve temkinli bir risk ölçümüdür; kazanç garantisi değildir.",
        }

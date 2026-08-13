import os
import json
import threading
import math
from datetime import datetime
from uuid import uuid4
from typing import List, Dict, Any

COUPONS_FILE = os.path.join(os.path.dirname(__file__), "saved_coupons.json")

class DataManager:
    """
    Manages saved coupons, favorites, and performance stats.
    """
    def __init__(self, storage_path: str = COUPONS_FILE):
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self._ensure_storage()

    def _ensure_storage(self):
        if not os.path.exists(self.storage_path):
            default_data = {
                "saved_coupons": [
                    {
                        "coupon_id": "OX-78412",
                        "date": "2026-08-11",
                        "total_odds": 14.85,
                        "status": "BEKLEYEN",
                        "picks": [
                            {"match": "Galatasaray vs Fenerbahçe", "tip": "İY/MS: 1/1", "odds": 3.40},
                            {"match": "Real Madrid vs Manchester City", "tip": "KG Var & 2.5 Üstü", "odds": 2.25},
                            {"match": "Arsenal vs Bayern München", "tip": "Maç Sonucu 1", "odds": 2.10}
                        ]
                    }
                ],
                "favorites": [101, 201]
            }
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(default_data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _default_data():
        return {"saved_coupons": [], "favorites": []}

    def _read_data(self):
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else self._default_data()
        except (OSError, ValueError, TypeError):
            return self._default_data()

    def _write_data(self, data):
        temp_path = self.storage_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, self.storage_path)

    def get_saved_coupons(self) -> List[Dict[str, Any]]:
        with self._lock:
            coupons = self._read_data().get("saved_coupons", [])
        return coupons if isinstance(coupons, list) else []

    def save_coupon(self, coupon_data: Any) -> bool:
        try:
            if isinstance(coupon_data, list):
                coupon_data = {
                    "coupon_id": f"OX-{uuid4().hex[:8].upper()}",
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "status": "BEKLEYEN",
                    "picks": coupon_data,
                }
            elif not isinstance(coupon_data, dict):
                return False

            picks = coupon_data.get("picks")
            if not isinstance(picks, list) or not picks:
                return False
            coupon_data = dict(coupon_data)
            coupon_data.setdefault("coupon_id", f"OX-{uuid4().hex[:8].upper()}")
            coupon_data.setdefault("date", datetime.now().strftime("%Y-%m-%d %H:%M"))
            coupon_data["status"] = str(coupon_data.get("status", "BEKLEYEN")).upper()
            if coupon_data["status"] not in {"BEKLEYEN", "KAZANDI", "KAYBETTİ", "İPTAL"}:
                coupon_data["status"] = "BEKLEYEN"
            coupon_data["total_odds"] = round(self._total_odds(picks), 2)

            with self._lock:
                data = self._read_data()
                coupons = data.get("saved_coupons", [])
                coupons.insert(0, coupon_data)
                data["saved_coupons"] = coupons[:200]
                self._write_data(data)
            return True
        except Exception as e:
            print("Error saving coupon:", e)
            return False

    @staticmethod
    def _total_odds(picks: List[Dict[str, Any]]) -> float:
        total = 1.0
        for pick in picks:
            try:
                total *= float(pick.get("odds", 1.0))
            except (AttributeError, TypeError, ValueError):
                continue
        return total

    def delete_coupon(self, coupon_id: str) -> bool:
        if not coupon_id:
            return False
        with self._lock:
            data = self._read_data()
            coupons = data.get("saved_coupons", [])
            kept = [c for c in coupons if str(c.get("coupon_id")) != str(coupon_id)]
            if len(kept) == len(coupons):
                return False
            data["saved_coupons"] = kept
            self._write_data(data)
        return True

    def update_coupon_status(self, coupon_id: str, status: str) -> bool:
        normalized = str(status or "").upper()
        if normalized not in {"BEKLEYEN", "KAZANDI", "KAYBETTİ", "İPTAL"}:
            return False
        with self._lock:
            data = self._read_data()
            changed = False
            for coupon in data.get("saved_coupons", []):
                if str(coupon.get("coupon_id")) == str(coupon_id):
                    coupon["status"] = normalized
                    changed = True
                    break
            if changed:
                self._write_data(data)
        return changed

    def get_system_stats(self) -> Dict[str, Any]:
        """Returns honest coupon history statistics instead of fixed sample numbers."""
        coupons = self.get_saved_coupons()
        settled = [c for c in coupons if c.get("status") in {"KAZANDI", "KAYBETTİ"}]
        won = [c for c in settled if c.get("status") == "KAZANDI"]
        odds = [float(c.get("total_odds", 0)) for c in coupons if isinstance(c.get("total_odds"), (int, float)) and math.isfinite(float(c.get("total_odds", 0)))]
        return {
            "saved_coupons": len(coupons),
            "settled_coupons": len(settled),
            "won_coupons": len(won),
            "success_rate": round(len(won) / len(settled) * 100, 1) if settled else None,
            "average_coupon_odds": round(sum(odds) / len(odds), 2) if odds else 0,
        }

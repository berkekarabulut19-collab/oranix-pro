import json
import os
import tempfile
import unittest

from data_manager import DataManager


class DataManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = os.path.join(self.temp_dir.name, "coupons.json")
        self.manager = DataManager(self.storage_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_list_coupon_is_normalized_and_persisted(self):
        picks = [
            {"matchName": "A vs B", "betLabel": "1", "odds": 2.0},
            {"matchName": "C vs D", "betLabel": "Üst", "odds": 1.5},
        ]

        self.assertTrue(self.manager.save_coupon(picks))
        saved = self.manager.get_saved_coupons()[0]
        self.assertEqual(saved["picks"], picks)
        self.assertEqual(saved["total_odds"], 3.0)
        self.assertTrue(saved["coupon_id"].startswith("OX-"))

        with open(self.storage_path, encoding="utf-8") as storage:
            self.assertEqual(json.load(storage)["saved_coupons"][0], saved)

    def test_empty_or_invalid_coupon_is_rejected(self):
        self.assertFalse(self.manager.save_coupon([]))
        self.assertFalse(self.manager.save_coupon("invalid"))

    def test_coupon_status_and_delete_lifecycle(self):
        self.assertTrue(self.manager.save_coupon([{"match": "A-B", "odds": 2.1}]))
        coupon_id = self.manager.get_saved_coupons()[0]["coupon_id"]
        self.assertTrue(self.manager.update_coupon_status(coupon_id, "KAZANDI"))
        self.assertEqual(self.manager.get_saved_coupons()[0]["status"], "KAZANDI")
        self.assertFalse(self.manager.update_coupon_status(coupon_id, "GEÇERSİZ"))
        self.assertTrue(self.manager.delete_coupon(coupon_id))
        self.assertFalse(self.manager.delete_coupon(coupon_id))

    def test_corrupt_storage_recovers_without_crashing(self):
        with open(self.storage_path, "w", encoding="utf-8") as storage:
            storage.write("{broken")
        self.assertEqual(self.manager.get_saved_coupons(), [])
        self.assertTrue(self.manager.save_coupon([{"match": "A-B", "odds": 1.5}]))
        self.assertEqual(len(self.manager.get_saved_coupons()), 1)


if __name__ == "__main__":
    unittest.main()

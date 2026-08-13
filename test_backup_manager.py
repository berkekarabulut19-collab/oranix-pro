import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backup_manager import BackupManager


class BackupManagerTests(unittest.TestCase):
    def test_create_list_and_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coupons = root / "saved_coupons.json"
            database = root / "history.sqlite3"
            backups = root / "backups"
            coupons.write_text(json.dumps({"saved_coupons": [{"coupon_id": "OX-1"}]}), encoding="utf-8")
            db = sqlite3.connect(database)
            try:
                db.execute("CREATE TABLE sample(value TEXT)")
                db.execute("INSERT INTO sample VALUES ('before')")
                db.commit()
            finally:
                db.close()
            manager = BackupManager(str(coupons), str(database), str(backups))

            created = manager.create_backup("test")
            self.assertEqual(created["status"], "created")
            self.assertEqual(len(manager.list_backups()), 1)

            coupons.write_text("{}", encoding="utf-8")
            db = sqlite3.connect(database)
            try:
                db.execute("DELETE FROM sample")
                db.commit()
            finally:
                db.close()
            restored = manager.restore_backup(created["backup"]["id"])
            self.assertEqual(restored["status"], "restored")
            self.assertIn("saved_coupons.json", restored["files"])
            self.assertEqual(json.loads(coupons.read_text(encoding="utf-8"))["saved_coupons"][0]["coupon_id"], "OX-1")
            db = sqlite3.connect(database)
            try:
                self.assertEqual(db.execute("SELECT value FROM sample").fetchone()[0], "before")
            finally:
                db.close()

    def test_restore_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = BackupManager(str(root / "coupons.json"), str(root / "history.sqlite3"), str(root / "backups"))
            result = manager.restore_backup("..\\outside.orxbackup")
            self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()

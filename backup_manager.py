"""Safe, local backup and restore for Oranix user data.

Backups are ZIP archives containing only user-owned state: saved coupons and
the prediction history database.  Build artefacts, API keys and source files
are deliberately excluded.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


class BackupManager:
    FORMAT_VERSION = 1

    def __init__(self, coupon_path: str, prediction_db_path: str, backup_dir: str | None = None):
        app_data = os.environ.get("LOCALAPPDATA") or os.path.dirname(os.path.abspath(coupon_path))
        self.coupon_path = Path(coupon_path).resolve()
        self.prediction_db_path = Path(prediction_db_path).resolve()
        requested_dir = Path(backup_dir) if backup_dir else (Path(app_data) / "OranixPro" / "backups")
        self.backup_dir = requested_dir.resolve()
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # Sandboxed installs and locked-down Windows profiles may deny the
            # roaming app-data folder. Keep the feature usable beside the data
            # file instead of making the whole API fail at startup.
            self.backup_dir = (self.coupon_path.parent / "backups").resolve()
            self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _safe_archive(self, archive: Path) -> Path:
        archive = archive.resolve()
        if archive.parent != self.backup_dir or archive.suffix.lower() != ".orxbackup":
            raise ValueError("Geçersiz yedek yolu")
        return archive

    def list_backups(self) -> list[dict]:
        rows = []
        for archive in sorted(self.backup_dir.glob("*.orxbackup"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                stat = archive.stat()
                with zipfile.ZipFile(archive) as bundle:
                    metadata = json.loads(bundle.read("metadata.json").decode("utf-8"))
                rows.append({
                    "id": archive.name,
                    "name": metadata.get("name", archive.name),
                    "created_at": metadata.get("created_at"),
                    "size_bytes": stat.st_size,
                    "path": str(archive),
                })
            except (OSError, KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError):
                continue
        return rows[:20]

    def create_backup(self, label: str | None = None) -> dict:
        now = datetime.now(timezone.utc)
        stamp = now.strftime("%Y%m%d-%H%M%S")
        safe_label = "".join(ch for ch in (label or "manual") if ch.isalnum() or ch in "-_ ").strip().replace(" ", "-")[:40]
        archive = self._safe_archive(self.backup_dir / f"oranix-{stamp}-{safe_label or 'manual'}.orxbackup")
        metadata = {
            "format_version": self.FORMAT_VERSION,
            "name": archive.stem,
            "created_at": now.isoformat(),
            "files": [],
        }
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for source, member in ((self.coupon_path, "saved_coupons.json"), (self.prediction_db_path, "prediction_history.sqlite3")):
                if source.exists() and source.is_file():
                    bundle.write(source, member)
                    metadata["files"].append(member)
            bundle.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        return {"status": "created", "backup": self._describe(archive)}

    def restore_backup(self, backup_id: str) -> dict:
        archive = self._safe_archive(self.backup_dir / Path(str(backup_id)).name)
        if not archive.exists():
            return {"status": "error", "error": "Yedek bulunamadı"}
        with tempfile.TemporaryDirectory(prefix="oranix-restore-") as temp_dir:
            temp = Path(temp_dir)
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
                if "metadata.json" not in names:
                    return {"status": "error", "error": "Yedek biçimi geçersiz"}
                for name in names - {"metadata.json"}:
                    target = (temp / name).resolve()
                    if target.parent != temp or name not in {"saved_coupons.json", "prediction_history.sqlite3"}:
                        return {"status": "error", "error": "Yedekte güvenli olmayan dosya var"}
                    bundle.extract(name, temp)
            db_copy = temp / "prediction_history.sqlite3"
            if db_copy.exists():
                db = sqlite3.connect(db_copy)
                try:
                    check = db.execute("PRAGMA quick_check").fetchone()[0]
                finally:
                    db.close()
                if check != "ok":
                    return {"status": "error", "error": "Tahmin geçmişi veritabanı doğrulanamadı"}
            restored = []
            for source, target in ((temp / "saved_coupons.json", self.coupon_path), (db_copy, self.prediction_db_path)):
                if source.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temp_target = target.with_suffix(target.suffix + ".restore.tmp")
                    shutil.copy2(source, temp_target)
                    os.replace(temp_target, target)
                    restored.append(target.name)
        return {"status": "restored", "backup": self._describe(archive), "files": restored}

    @staticmethod
    def _describe(archive: Path) -> dict:
        return {"id": archive.name, "name": archive.stem, "path": str(archive), "size_bytes": archive.stat().st_size}

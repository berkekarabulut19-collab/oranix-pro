"""Safe, non-blocking update checker for the packaged Oranix app.

The app only downloads an update when an HTTPS manifest is configured. The
manifest must provide a newer numeric version, HTTPS download URL and SHA-256
hash. No remote file is executed until its digest matches exactly.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

import requests

from release_info import APP_VERSION, UPDATE_MANIFEST_ENV


def _version_key(value: Any) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in parts) or (0,)


class UpdateManager:
    def __init__(self, manifest_url: str | None = None, http_get=None):
        self.manifest_url = (manifest_url or os.environ.get(UPDATE_MANIFEST_ENV) or "").strip()
        self.http_get = http_get or requests.get
        self._lock = threading.Lock()
        self._status: dict[str, Any] = {
            "state": "disabled" if not self.manifest_url else "waiting",
            "current_version": APP_VERSION,
            "manifest_url_configured": bool(self.manifest_url),
            "update_available": False,
            "downloaded": False,
        }
        self._download_path: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.manifest_url)

    def _set(self, **values):
        with self._lock:
            self._status.update(values)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def check(self) -> dict[str, Any]:
        if not self.enabled:
            self._set(state="disabled", reason="Güncelleme adresi yapılandırılmadı")
            return self.status()
        if not self.manifest_url.lower().startswith("https://"):
            self._set(state="error", error="Güncelleme manifesti yalnızca HTTPS olabilir")
            return self.status()
        try:
            response = self.http_get(self.manifest_url, timeout=5, headers={"Accept": "application/json"})
            response.raise_for_status()
            manifest = response.json()
            version = str(manifest.get("version") or "")
            download_url = str(manifest.get("download") or manifest.get("url") or "")
            sha256 = str(manifest.get("sha256") or "").lower()
            if not version or not download_url or not re.fullmatch(r"[0-9a-f]{64}", sha256):
                raise ValueError("Manifest sürüm, HTTPS indirme adresi veya SHA256 alanı içermiyor")
            if not download_url.lower().startswith("https://"):
                raise ValueError("İndirme adresi yalnızca HTTPS olabilir")
            available = _version_key(version) > _version_key(APP_VERSION)
            self._set(
                state="update_available" if available else "up_to_date",
                latest_version=version,
                download_url=download_url,
                sha256=sha256,
                notes=str(manifest.get("notes") or ""),
                update_available=available,
                checked_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                error=None,
            )
        except Exception as exc:
            self._set(state="error", error=str(exc)[:180], update_available=False)
        return self.status()

    def check_async(self):
        if not self.enabled:
            return
        thread = threading.Thread(target=self.check, name="oranix-update-check", daemon=True)
        thread.start()

    def download(self) -> dict[str, Any]:
        current = self.status()
        if current.get("state") != "update_available":
            return current
        url, expected = current.get("download_url"), current.get("sha256")
        try:
            response = self.http_get(url, timeout=20, stream=True)
            response.raise_for_status()
            fd, path = tempfile.mkstemp(prefix="oranix-update-", suffix=".exe")
            digest = hashlib.sha256()
            with os.fdopen(fd, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        digest.update(chunk)
                        handle.write(chunk)
            actual = digest.hexdigest().lower()
            if actual != expected:
                Path(path).unlink(missing_ok=True)
                raise ValueError("İndirilen güncellemenin güvenlik özeti eşleşmedi")
            self._download_path = path
            self._set(state="downloaded", downloaded=True, downloaded_path=path, error=None)
        except Exception as exc:
            self._set(state="error", error=str(exc)[:180], downloaded=False)
        return self.status()

    def apply(self) -> dict[str, Any]:
        """Schedule the verified installer, then close this process cleanly."""
        path = self._download_path
        if self.status().get("state") != "downloaded" or not path or not Path(path).exists():
            self._set(state="error", error="Önce doğrulanmış güncelleme indirilmeli")
            return self.status()
        if os.name != "nt":
            self._set(state="error", error="Bu kurulum akışı yalnızca Windows içindir")
            return self.status()
        try:
            script = Path(tempfile.mktemp(prefix="oranix-update-", suffix=".cmd"))
            script.write_text(
                "@echo off\r\n"
                f"timeout /t 2 /nobreak >nul\r\n"
                f"start \"\" \"{path}\"\r\n"
                f"del \"%~f0\"\r\n",
                encoding="utf-8",
            )
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(["cmd.exe", "/d", "/c", str(script)], creationflags=flags,
                             close_fds=True)
            self._set(state="restarting", restart_scheduled=True)
            return self.status()
        except Exception as exc:
            self._set(state="error", error=str(exc)[:180])
            return self.status()

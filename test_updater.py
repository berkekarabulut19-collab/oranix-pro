import hashlib
import unittest

from updater import UpdateManager


class FakeResponse:
    def __init__(self, payload=None, content=b""):
        self.payload = payload
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_content(self, chunk_size=1):
        yield self.content


class UpdateManagerTests(unittest.TestCase):
    def test_missing_manifest_is_safe_and_disabled(self):
        status = UpdateManager("").check()
        self.assertEqual(status["state"], "disabled")
        self.assertFalse(status["update_available"])

    def test_new_manifest_is_detected_and_hash_verified(self):
        payload = b"installer-bytes"
        digest = hashlib.sha256(payload).hexdigest()

        def fake_get(url, **kwargs):
            if url.endswith("manifest.json"):
                return FakeResponse({"version": "18001.0", "download": "https://updates.example/app.exe", "sha256": digest})
            return FakeResponse(content=payload)

        manager = UpdateManager("https://updates.example/manifest.json", fake_get)
        self.assertEqual(manager.check()["state"], "update_available")
        status = manager.download()
        self.assertEqual(status["state"], "downloaded")

    def test_http_manifest_is_rejected(self):
        status = UpdateManager("http://updates.example/manifest.json").check()
        self.assertEqual(status["state"], "error")


if __name__ == "__main__":
    unittest.main()

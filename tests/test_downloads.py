from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dfpm.downloads import acquire
from dfpm.errors import VerificationError
from dfpm.manifest import Package
from dfpm.storage import Storage

PAYLOAD = b"artifact bytes for dfpm tests"


class FakeResponse(io.BytesIO):
    """Stands in for an HTTPS response, including the URL finally resolved."""

    def __init__(self, data: bytes, url: str) -> None:
        super().__init__(data)
        self._url = url

    def geturl(self) -> str:
        return self._url


class ArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")
        self.source = self.base / "payload.zip"
        self.source.write_bytes(PAYLOAD)
        self.package = Package(str(self.source), hashlib.sha256(PAYLOAD).hexdigest(), len(PAYLOAD))

    def partials(self) -> list[Path]:
        return list(self.storage.cache.glob("*.partial")) if self.storage.cache.is_dir() else []

    def test_copies_and_verifies_a_local_path(self) -> None:
        cached = acquire(self.package, str(self.source), self.storage)
        self.assertEqual(cached.name, self.package.sha256)
        self.assertEqual(cached.read_bytes(), PAYLOAD)

    def test_accepts_a_file_url(self) -> None:
        cached = acquire(self.package, self.source.as_uri(), self.storage)
        self.assertEqual(cached.read_bytes(), PAYLOAD)

    def test_rejects_a_digest_mismatch_and_leaves_no_partial_behind(self) -> None:
        wrong = Package(str(self.source), "0" * 64, len(PAYLOAD))
        with self.assertRaises(VerificationError) as caught:
            acquire(wrong, str(self.source), self.storage)
        self.assertIn("SHA-256", str(caught.exception))
        self.assertEqual(self.partials(), [])
        self.assertEqual(list(self.storage.cache.iterdir()), [])

    def test_rejects_a_size_mismatch(self) -> None:
        wrong = Package(str(self.source), self.package.sha256, len(PAYLOAD) + 1)
        with self.assertRaises(VerificationError) as caught:
            acquire(wrong, str(self.source), self.storage)
        self.assertIn("size mismatch", str(caught.exception))
        self.assertEqual(self.partials(), [])

    def test_rejects_an_unsupported_scheme(self) -> None:
        with self.assertRaises(VerificationError) as caught:
            acquire(self.package, "ftp://example.org/payload.zip", self.storage)
        self.assertIn("HTTPS", str(caught.exception))

    def test_reuses_a_cached_artifact_without_the_source(self) -> None:
        acquire(self.package, str(self.source), self.storage)
        self.source.unlink()
        self.assertEqual(acquire(self.package, str(self.source), self.storage).read_bytes(), PAYLOAD)

    def test_detects_a_cached_artifact_that_no_longer_matches_its_digest(self) -> None:
        cached = acquire(self.package, str(self.source), self.storage)
        cached.write_bytes(b"tampered")
        with self.assertRaises(VerificationError):
            acquire(self.package, str(self.source), self.storage)

    def test_downloads_over_https(self) -> None:
        url = "https://example.org/payload.zip"
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(PAYLOAD, url)):
            cached = acquire(self.package, url, self.storage)
        self.assertEqual(cached.read_bytes(), PAYLOAD)

    def test_refuses_an_https_download_that_redirects_to_plain_http(self) -> None:
        """The digest alone cannot protect a download that silently left TLS."""
        redirected = FakeResponse(PAYLOAD, "http://mirror.example.org/payload.zip")
        with mock.patch("urllib.request.urlopen", return_value=redirected):
            with self.assertRaises(VerificationError) as caught:
                acquire(self.package, "https://example.org/payload.zip", self.storage)
        self.assertIn("insecure", str(caught.exception))
        self.assertEqual(self.partials(), [])
        self.assertEqual(list(self.storage.cache.iterdir()), [])

    def test_reports_a_download_that_fails_midway(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=OSError("connection reset")):
            with self.assertRaises(VerificationError) as caught:
                acquire(self.package, "https://example.org/payload.zip", self.storage)
        self.assertIn("connection reset", str(caught.exception))
        self.assertEqual(self.partials(), [])


if __name__ == "__main__":
    unittest.main()

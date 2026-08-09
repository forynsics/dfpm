from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from dfpm import cache
from dfpm.doctor import inspect
from dfpm.errors import VerificationError
from dfpm.installer import install
from dfpm.inventory import read_package
from dfpm.manifest import Manifest
from dfpm.storage import Storage
from tests import helpers
from tests.helpers import create_package

BODY = "@echo hi\r\n"
ACCEPT = lambda expected, actual: True  # noqa: E731 - a policy, stated once
REFUSE = lambda expected, actual: False  # noqa: E731


class MismatchFixture(unittest.TestCase):
    """A catalog entry whose URL now serves something other than what it pinned."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.storage = Storage(self.base / "dfpm-data")

    def stale_entry(self, stability: str | None = None) -> Manifest:
        """Build a package, then republish different bytes at the same location.

        This is what a rolling upstream does between one review and the next: the
        entry is untouched and correct about where to look, and wrong about what
        is there.
        """
        _, manifest_path = create_package(self.base, body=BODY, stability=stability)
        manifest = Manifest.load(manifest_path)
        archive = Path(manifest.package_url())
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("example-tool/bin/example-tool.cmd", BODY)
            output.writestr("example-tool/data/readme.txt", helpers.README_TEXT)
            output.writestr("example-tool/data/added-upstream.txt", "a later build shipped this\n")
        self.arrived = hashlib.sha256(archive.read_bytes()).hexdigest()
        return manifest


class RollingInstallTests(MismatchFixture):
    """Installing a package whose publisher replaces the file at its URL."""

    def test_a_changed_artifact_is_still_refused_by_default(self) -> None:
        with self.assertRaises(VerificationError) as caught:
            install(self.stale_entry("rolling"), self.storage)
        self.assertIn("rolling upstream URL", str(caught.exception))
        self.assertFalse(self.storage.package_version("example.tool", "1.0.0").exists())

    def test_refusing_the_offer_installs_nothing(self) -> None:
        with self.assertRaises(VerificationError):
            install(self.stale_entry("rolling"), self.storage, on_mismatch=REFUSE)
        self.assertFalse(self.storage.package_version("example.tool", "1.0.0").exists())

    def test_accepting_installs_the_bytes_that_arrived(self) -> None:
        manifest = self.stale_entry("rolling")
        destination = install(manifest, self.storage, on_mismatch=ACCEPT)
        self.assertTrue((destination / "data" / "added-upstream.txt").is_file())

    def test_the_record_keeps_what_was_reviewed_and_what_landed(self) -> None:
        # Collapsing these into one field would mean the record could not answer
        # either question afterwards: not what is installed, not what was approved.
        manifest = self.stale_entry("rolling")
        install(manifest, self.storage, on_mismatch=ACCEPT)
        record = read_package(self.storage, "example.tool")
        self.assertEqual(record["package_sha256"], self.arrived)
        self.assertEqual(record["catalog_sha256"], manifest.package.sha256)
        self.assertFalse(record["digest_verified"])

    def test_an_ordinary_install_records_both_digests_the_same(self) -> None:
        _, manifest_path = create_package(self.base, body=BODY)
        manifest = Manifest.load(manifest_path)
        install(manifest, self.storage)
        record = read_package(self.storage, "example.tool")
        self.assertTrue(record["digest_verified"])
        self.assertEqual(record["package_sha256"], record["catalog_sha256"])
        self.assertEqual(record["package_sha256"], manifest.package.sha256)

    def test_the_cache_still_knows_which_package_needs_the_artifact(self) -> None:
        # The cache is addressed by digest and cross-references installs through
        # the recorded one. If the two ever disagree, 'cache prune' deletes an
        # artifact that is in use while reporting it as needed by nothing.
        install(self.stale_entry("rolling"), self.storage, on_mismatch=ACCEPT)
        entry = cache.find(cache.survey(self.storage), self.arrived)
        self.assertEqual(entry.status, "installed")
        self.assertIn("example.tool 1.0.0", entry.referenced_by)

    def test_doctor_keeps_saying_so_afterwards(self) -> None:
        # The decision was taken once, possibly long ago. Nothing on disk shows
        # it, so the record is the only thing that can still report it.
        install(self.stale_entry("rolling"), self.storage, on_mismatch=ACCEPT)
        findings = inspect(self.storage)
        self.assertEqual([item.status for item in findings], ["unverified"])
        self.assertIn(self.arrived, findings[0].detail)

    def test_the_recorded_size_and_count_are_not_held_against_a_different_artifact(self) -> None:
        # Those figures describe the reviewed file. Enforcing them here would
        # fail the install a moment after the mismatch was deliberately accepted,
        # with a message about something else entirely.
        _, manifest_path = create_package(
            self.base, body=BODY, stability="rolling", extracted_size=1, entries=1
        )
        manifest = Manifest.load(manifest_path)
        archive = Path(manifest.package_url())
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("example-tool/bin/example-tool.cmd", BODY)
            output.writestr("example-tool/data/readme.txt", helpers.README_TEXT)
            output.writestr("example-tool/data/added-upstream.txt", "a later build shipped this\n")
        destination = install(manifest, self.storage, on_mismatch=ACCEPT)
        self.assertTrue((destination / "data" / "readme.txt").is_file())


class ImmutableInstallTests(MismatchFixture):
    """A URL that should never change, changing."""

    def test_the_mismatch_is_reported_as_abnormal(self) -> None:
        with self.assertRaises(VerificationError) as caught:
            install(self.stale_entry(), self.storage)
        self.assertIn("expected to be immutable", str(caught.exception))

    def test_no_decision_is_offered_and_none_is_honoured(self) -> None:
        # Wording the two cases differently would mean nothing if the outcome
        # were the same either way.
        asked = []

        def record_and_accept(expected: str, actual: str) -> bool:
            asked.append(actual)
            return True

        with self.assertRaises(VerificationError):
            install(self.stale_entry(), self.storage, on_mismatch=record_and_accept)
        self.assertEqual(asked, [])
        self.assertFalse(self.storage.package_version("example.tool", "1.0.0").exists())

    def test_immutable_is_what_a_package_gets_without_saying_so(self) -> None:
        _, manifest_path = create_package(self.base, body=BODY)
        self.assertFalse(Manifest.load(manifest_path).package.rolling)


if __name__ == "__main__":
    unittest.main()

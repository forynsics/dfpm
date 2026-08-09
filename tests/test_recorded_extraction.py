from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dfpm.errors import InstallError, ManifestError
from dfpm.installer import _discard_staging, install
from dfpm.manifest import Manifest
from dfpm.storage import Storage
from tests import helpers
from tests.helpers import create_package

BODY = "@echo hi\r\n"
INSTALLED_SIZE = len(BODY.encode()) + len(helpers.README_TEXT.encode())
INSTALLED_ENTRIES = 2


class RecordedExtractionTests(unittest.TestCase):
    """A manifest may record what it costs on disk, so the plan can show it before fetching."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")

    def install_with(self, **kwargs) -> Path:
        _, manifest_path = create_package(self.base, body=BODY, **kwargs)
        return install(Manifest.load(manifest_path), self.storage)

    def test_a_manifest_that_matches_the_archive_installs(self) -> None:
        destination = self.install_with(extracted_size=INSTALLED_SIZE, entries=INSTALLED_ENTRIES)
        self.assertTrue((destination / "data" / "readme.txt").is_file())

    def test_recording_nothing_still_installs(self) -> None:
        destination = self.install_with()
        self.assertTrue((destination / "data" / "readme.txt").is_file())

    def test_a_disagreeing_file_count_refuses_the_install(self) -> None:
        with self.assertRaises(InstallError) as caught:
            self.install_with(entries=99)
        message = str(caught.exception)
        self.assertIn("records 99", message)
        self.assertIn("does not describe this artifact", message)

    def test_a_disagreeing_size_refuses_the_install(self) -> None:
        with self.assertRaises(InstallError) as caught:
            self.install_with(extracted_size=INSTALLED_SIZE + 1)
        self.assertIn("does not describe this artifact", str(caught.exception))

    def test_a_refused_install_leaves_nothing_behind(self) -> None:
        with self.assertRaises(InstallError):
            self.install_with(entries=99)
        self.assertFalse(self.storage.package_version("example.tool", "1.0.0").exists())
        self.assertEqual(list((self.storage.root / "staging").iterdir()), [])

    def test_a_negative_recorded_size_is_rejected_by_the_manifest(self) -> None:
        _, manifest_path = create_package(self.base, body=BODY, extracted_size=-1)
        with self.assertRaises(ManifestError) as caught:
            Manifest.load(manifest_path)
        self.assertIn("install.extracted_size", str(caught.exception))


class StagingTests(unittest.TestCase):
    """An install cleans up after itself and leaves every other run's work alone."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")
        self.staging = self.storage.root / "staging"

    def test_a_successful_install_does_not_leave_its_own_staging_behind(self) -> None:
        # Publishing moves the staging directory rather than copying it, so a
        # successful install has nothing left to clean up.
        _, manifest_path = create_package(self.base, body=BODY)
        install(Manifest.load(manifest_path), self.storage)
        self.assertEqual(list(self.staging.iterdir()), [])

    def test_an_install_never_touches_another_runs_staging_directory(self) -> None:
        # A second dfpm may be mid-install right now, and dfpm takes no lock, so
        # an install has no way to tell an abandoned directory from a live one.
        self.staging.mkdir(parents=True)
        other = self.staging / "example.tool-0.9.0-someone-else"
        other.mkdir()
        (other / "half-extracted.bin").write_bytes(b"in flight")
        _, manifest_path = create_package(self.base, body=BODY)
        install(Manifest.load(manifest_path), self.storage)
        self.assertTrue((other / "half-extracted.bin").is_file())


class StagingDiscardTests(unittest.TestCase):
    """Antivirus and the search indexer hold a freshly written executable briefly."""

    def test_a_transient_lock_is_retried_until_it_clears(self) -> None:
        attempts = []

        def flaky(path, *args, **kwargs):
            attempts.append(path)
            if len(attempts) < 3:
                raise PermissionError(32, "The process cannot access the file")

        with (
            mock.patch("dfpm.installer.shutil.rmtree", side_effect=flaky),
            mock.patch("dfpm.installer.time.sleep"),
        ):
            self.assertTrue(_discard_staging(Path("staging-dir")))
        self.assertEqual(len(attempts), 3)

    def test_a_directory_that_never_unlocks_is_given_up_on(self) -> None:
        with (
            mock.patch("dfpm.installer.shutil.rmtree", side_effect=PermissionError(32, "locked")),
            mock.patch("dfpm.installer.time.sleep"),
        ):
            self.assertFalse(_discard_staging(Path("staging-dir")))

    def test_an_already_gone_directory_counts_as_cleaned(self) -> None:
        with mock.patch("dfpm.installer.shutil.rmtree", side_effect=FileNotFoundError):
            self.assertTrue(_discard_staging(Path("staging-dir")))

    def test_a_failed_cleanup_does_not_mask_why_the_install_failed(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        storage = Storage(base / "dfpm-data")
        _, manifest_path = create_package(base, body=BODY, entries=99)
        with (
            mock.patch("dfpm.installer.shutil.rmtree", side_effect=PermissionError(32, "locked")),
            mock.patch("dfpm.installer.time.sleep"),
            self.assertRaises(InstallError) as caught,
        ):
            install(Manifest.load(manifest_path), storage)
        self.assertIn("does not describe this artifact", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

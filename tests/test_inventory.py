from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dfpm import shims
from dfpm.doctor import inspect
from dfpm.inventory import list_packages, read_package, write_package
from dfpm.launcher import resolve
from dfpm.storage import Storage

LEGACY_RECORD = {
    "id": "yara",
    "name": "YARA",
    "kind": "tool",
    "active_version": "4.5.5",
    "activation_history": [{"version": "4.5.5", "activated_at": "2026-08-08T17:23:32+00:00"}],
    "versions": {
        "4.5.5": {
            "artifact_sha256": "3" * 64,
            "manifest_digest": "4" * 64,
            "installed_at": "2026-08-08T17:23:32+00:00",
            "entrypoints": [{"name": "yara", "path": "yara64.exe"}],
            "health_checks": [],
            "files": [{"path": "yara64.exe", "size": 3, "sha256": "5" * 64}],
            "platform": {"os": "windows", "arch": "x64"},
        }
    },
}


class LegacyRecordTests(unittest.TestCase):
    """A record written before one-version-per-package must keep an install working."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")
        self.storage.initialize()
        path = self.storage.package_state("yara")
        path.write_text(json.dumps(LEGACY_RECORD), encoding="utf-8")

    def test_the_installed_version_is_readable(self) -> None:
        record = read_package(self.storage, "yara")
        self.assertEqual(record["version"], "4.5.5")
        self.assertEqual(record["name"], "YARA")
        self.assertEqual(record["artifact_sha256"], "3" * 64)
        self.assertEqual(record["platform"], {"os": "windows", "arch": "x64"})
        self.assertNotIn("versions", record)
        self.assertNotIn("activation_history", record)
        self.assertEqual(list_packages(self.storage)[0]["version"], "4.5.5")

    def test_its_commands_are_still_found(self) -> None:
        planned = shims.planned(self.storage)
        self.assertIn("yara", planned)
        self.assertEqual(planned["yara"].version, "4.5.5")
        self.assertEqual(resolve(self.storage, "yara").package, "yara")

    def test_its_shims_are_not_treated_as_stale(self) -> None:
        shims.reconcile(self.storage)
        shim = self.storage.bin / "yara.cmd"
        self.assertTrue(shim.is_file())
        self.assertEqual(shims.reconcile(self.storage), [], "a known package's shim must never be swept away")
        self.assertTrue(shim.is_file())

    def test_doctor_checks_it_rather_than_skipping_it(self) -> None:
        findings = inspect(self.storage)
        self.assertTrue(findings, "a legacy record must not be silently skipped")
        self.assertEqual({item.version for item in findings}, {"4.5.5"})
        self.assertIn("Missing managed file: yara64.exe", [item.detail for item in findings])

    def test_a_current_record_is_left_untouched(self) -> None:
        current = {"id": "other", "name": "Other", "version": "1.0.0", "entrypoints": [], "files": []}
        write_package(self.storage, "other", current)
        self.assertEqual(read_package(self.storage, "other"), current)


if __name__ == "__main__":
    unittest.main()

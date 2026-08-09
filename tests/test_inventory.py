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
            "package_sha256": "3" * 64,
            "manifest_digest": "4" * 64,
            "installed_at": "2026-08-08T17:23:32+00:00",
            "entrypoints": [{"name": "yara", "path": "yara64.exe"}],
            "verify": [],
            "file_count": 1,
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
        self.assertEqual(record["package_sha256"], "3" * 64)
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
        self.assertIn("Missing command shortcut: yara.cmd", [item.detail for item in findings])

    def test_a_current_record_is_left_untouched(self) -> None:
        current = {"id": "other", "name": "Other", "version": "1.0.0", "entrypoints": [], "file_count": 0}
        write_package(self.storage, "other", current)
        self.assertEqual(read_package(self.storage, "other"), current)




class RenamedFieldTests(unittest.TestCase):
    """Records written before the artifact/package rename must keep working."""

    def test_an_old_record_is_read_under_the_new_names(self) -> None:
        from dfpm.inventory import _normalize

        old = {
            "id": "yara", "name": "YARA", "version": "4.5.5",
            "artifact_sha256": "3" * 64,
            "health_checks": [{"type": "file", "path": "yara64.exe"}],
            "entrypoints": [{"name": "yara", "path": "yara64.exe"}],
        }
        record = _normalize(old)
        # Without this the cache would think the file yara needs is unused, and
        # doctor would find nothing left to check.
        self.assertEqual(record["package_sha256"], "3" * 64)
        self.assertEqual(record["verify"], [{"type": "file", "path": "yara64.exe"}])
        self.assertNotIn("artifact_sha256", record)
        self.assertNotIn("health_checks", record)

    def test_a_current_record_is_left_alone(self) -> None:
        from dfpm.inventory import _normalize

        current = {"id": "yara", "version": "4.5.5", "package_sha256": "a" * 64, "verify": []}
        self.assertEqual(_normalize(dict(current)), current)


if __name__ == "__main__":
    unittest.main()


class RecordedDescriptionTests(unittest.TestCase):
    """What is installed should be able to describe itself with no catalog present."""

    def test_the_description_is_written_into_the_record(self) -> None:
        from dfpm.catalog import resolve as resolve_manifest
        from dfpm.installer import install
        from dfpm.storage import Storage
        from tests.helpers import create_package

        base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        catalog, _ = create_package(base)
        storage = Storage(base / "data")
        install(resolve_manifest(catalog, "example.tool"), storage)

        record = read_package(storage, "example.tool")
        self.assertEqual(record["description"], "A synthetic package used to verify dfpm safely.")

    def test_a_record_written_before_descriptions_still_reads(self) -> None:
        # Nothing is repaired retroactively; the field is simply absent, and
        # everything that reads a record has to cope with that.
        from dfpm.inventory import _normalize

        record = _normalize({"id": "yara", "version": "4.5.5", "package_sha256": "a" * 64, "verify": []})
        self.assertIsNone(record.get("description"))

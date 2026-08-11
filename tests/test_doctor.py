from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from dfpm import shims, sync
from dfpm.catalog import INDEX_NAME, build_index
from dfpm.cli import main
from dfpm.doctor import STALE_SECONDS, apply_repairs, inspect, repair_plan
from dfpm.installer import install
from dfpm.inventory import read_package
from dfpm.manifest import Manifest
from dfpm.storage import Storage, remove_tree
from tests.helpers import create_package


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.storage = Storage(self.base / "dfpm-data")

    def install_version(self, version: str = "1.0.0") -> Path:
        _, manifest_path = create_package(self.base, version=version)
        return install(Manifest.load(manifest_path), self.storage)

    def failures(self) -> list[str]:
        return [item.detail for item in inspect(self.storage) if item.status == "failed"]

    def test_a_clean_install_passes(self) -> None:
        self.install_version()
        self.assertEqual([item.status for item in inspect(self.storage)], ["passing"])

    def test_reports_a_missing_command_shortcut(self) -> None:
        self.install_version()
        (self.storage.bin / "example-tool.cmd").unlink()
        self.assertIn("Missing command shortcut: example-tool.cmd", self.failures())

    def test_reports_a_shortcut_replaced_by_a_file_dfpm_does_not_own(self) -> None:
        self.install_version()
        (self.storage.bin / "example-tool.cmd").write_bytes(b"@echo something else\r\n")
        self.assertIn("Command shortcut was replaced by an unmanaged file: example-tool.cmd", self.failures())

    def test_reports_a_failed_file_health_check(self) -> None:
        destination = self.install_version()
        (destination / "data" / "readme.txt").unlink()
        problems = self.failures()
        self.assertIn("Health check failed: data/readme.txt", problems)
        self.assertIn("Health check failed: data/readme.txt", problems)

    def test_only_the_installed_version_is_reported(self) -> None:
        self.install_version("1.0.0")
        self.install_version("1.1.0")
        findings = inspect(self.storage)
        self.assertEqual([item.version for item in findings], ["1.1.0"])

    def test_an_empty_installation_has_nothing_to_report(self) -> None:
        self.assertEqual(inspect(self.storage), [])

    def test_repair_recreates_a_missing_managed_shortcut(self) -> None:
        self.install_version()
        shortcut = self.storage.bin / "example-tool.cmd"
        shortcut.unlink()
        actions = repair_plan(self.storage)
        self.assertIn("reconcile-shims", [action.kind for action in actions])
        apply_repairs(self.storage, actions)
        self.assertTrue(shortcut.is_file())
        self.assertEqual([item.status for item in inspect(self.storage)], ["passing"])

    def test_repair_refreshes_a_stale_owned_shortcut(self) -> None:
        self.install_version()
        shortcut = self.storage.bin / "example-tool.cmd"
        shortcut.write_text(f"{shims.MARKER} stale\r\n", encoding="utf-8")
        self.assertIn("Command shortcut is stale", "\n".join(self.failures()))
        apply_repairs(self.storage, repair_plan(self.storage))
        self.assertNotIn("stale", shortcut.read_text(encoding="utf-8"))

    def test_repair_never_replaces_an_unmanaged_shortcut(self) -> None:
        self.install_version()
        shortcut = self.storage.bin / "example-tool.cmd"
        shortcut.write_text("@echo unmanaged\r\n", encoding="utf-8")
        before = shortcut.read_bytes()
        apply_repairs(self.storage, repair_plan(self.storage))
        self.assertEqual(shortcut.read_bytes(), before)

    def test_repair_removes_only_old_install_staging_directories(self) -> None:
        staging = self.storage.root / "staging"
        old = staging / "old-install"
        recent = staging / "active-install"
        old.mkdir(parents=True)
        recent.mkdir()
        timestamp = time.time() - STALE_SECONDS - 60
        os.utime(old, (timestamp, timestamp))
        apply_repairs(self.storage, repair_plan(self.storage))
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_repair_forgets_a_record_whose_install_directory_is_gone(self) -> None:
        destination = self.install_version()
        self.assertTrue(remove_tree(destination))
        apply_repairs(self.storage, repair_plan(self.storage))
        self.assertIsNone(read_package(self.storage, "example.tool"))
        self.assertFalse((self.storage.bin / "example-tool.cmd").exists())

    def test_repair_quarantines_a_corrupt_cached_artifact(self) -> None:
        self.storage.initialize()
        corrupt = self.storage.cache / ("a" * 64)
        corrupt.write_bytes(b"not the named digest")
        actions = repair_plan(self.storage)
        self.assertIn("quarantine-cache", [action.kind for action in actions])
        apply_repairs(self.storage, actions)
        self.assertFalse(corrupt.exists())
        self.assertTrue((self.storage.root / "quarantine" / "cache" / f"{'a' * 64}.corrupt").exists())

    def test_repair_restores_a_catalog_backup_left_by_interruption(self) -> None:
        create_package(self.storage.root)
        (self.storage.catalog / INDEX_NAME).write_text(
            json.dumps(build_index(self.storage.catalog), indent=2) + "\n", encoding="utf-8"
        )
        backup = sync.backup_directory(self.storage.catalog)
        sync.os.replace(self.storage.catalog, backup)
        timestamp = time.time() - STALE_SECONDS - 60
        os.utime(backup, (timestamp, timestamp))
        actions = repair_plan(self.storage)
        self.assertIn("restore-catalog", [action.kind for action in actions])
        self.assertNotIn("remove-sync-staging", [action.kind for action in actions])
        apply_repairs(self.storage, actions)
        self.assertTrue((self.storage.catalog / "example.tool.json").exists())

    def test_unrecorded_package_directory_is_reported_but_not_removed(self) -> None:
        orphan = self.storage.tools / "unknown" / "1.0"
        orphan.mkdir(parents=True)
        details = [item.detail for item in inspect(self.storage)]
        self.assertTrue(any("Unrecorded package directory" in detail for detail in details))
        apply_repairs(self.storage, repair_plan(self.storage))
        self.assertTrue(orphan.exists())

    def test_unreadable_state_prevents_guessing_that_its_shim_is_stale(self) -> None:
        self.storage.initialize()
        (self.storage.state / "packages" / "broken.json").write_text("not json", encoding="utf-8")
        shortcut = self.storage.bin / "unknown.cmd"
        shortcut.write_text(f"{shims.MARKER} package=broken version=1.0\r\n", encoding="utf-8")
        actions = repair_plan(self.storage)
        self.assertNotIn("reconcile-shims", [action.kind for action in actions])
        apply_repairs(self.storage, actions)
        self.assertTrue(shortcut.exists())

    def test_cli_displays_and_confirms_the_repair_plan(self) -> None:
        self.install_version()
        shortcut = self.storage.bin / "example-tool.cmd"
        shortcut.unlink()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["--root", str(self.storage.root), "doctor", "--repair", "--yes"])
        self.assertEqual(result, 0)
        self.assertIn("Doctor repair plan", output.getvalue())
        self.assertTrue(shortcut.exists())

    def test_declined_repair_plan_changes_nothing(self) -> None:
        self.install_version()
        shortcut = self.storage.bin / "example-tool.cmd"
        shortcut.unlink()
        with mock.patch("builtins.input", return_value="n"), contextlib.redirect_stdout(io.StringIO()):
            result = main(["--root", str(self.storage.root), "doctor", "--repair"])
        self.assertEqual(result, 0)
        self.assertFalse(shortcut.exists())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfpm.doctor import inspect
from dfpm.installer import install
from dfpm.manifest import Manifest
from dfpm.storage import Storage
from tests.helpers import create_package


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
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
        self.assertIn("Missing managed file: data/readme.txt", problems)
        self.assertIn("Health check failed: data/readme.txt", problems)

    def test_only_the_installed_version_is_reported(self) -> None:
        self.install_version("1.0.0")
        self.install_version("1.1.0")
        findings = inspect(self.storage)
        self.assertEqual([item.version for item in findings], ["1.1.0"])

    def test_an_empty_installation_has_nothing_to_report(self) -> None:
        self.assertEqual(inspect(self.storage), [])


if __name__ == "__main__":
    unittest.main()

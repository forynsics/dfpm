from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfpm import removal
from dfpm.errors import InstallError
from dfpm.installer import install
from dfpm.inventory import read_package
from dfpm.manifest import Manifest
from dfpm.storage import Storage
from tests.helpers import create_package


class RemovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")

    def install_version(self, version: str = "1.0.0", *, commands=("example-tool",)) -> Path:
        _, manifest_path = create_package(self.base, version=version, commands=commands)
        return install(Manifest.load(manifest_path), self.storage)

    def uninstall(self, *, force: bool = False) -> removal.RemovalPlan:
        plan = removal.plan(self.storage, "example.tool")
        removal.execute(self.storage, plan, force=force)
        return plan

    def test_removes_recorded_files_shims_and_directories(self) -> None:
        destination = self.install_version()
        plan = self.uninstall()

        self.assertEqual(plan.commands, ("example-tool",))
        self.assertFalse(destination.exists())
        self.assertFalse((self.storage.tools / "example.tool").exists())
        self.assertFalse((self.storage.bin / "example-tool.cmd").exists())
        self.assertIsNone(read_package(self.storage, "example.tool"))

    def test_files_dfpm_never_installed_are_preserved(self) -> None:
        destination = self.install_version()
        stray = destination / "data" / "analyst-notes.txt"
        stray.write_text("case notes\n", encoding="utf-8")

        plan = self.uninstall()

        self.assertEqual(plan.unknown, ("data/analyst-notes.txt",))
        self.assertEqual(stray.read_text(encoding="utf-8"), "case notes\n")
        self.assertFalse((destination / "bin" / "example-tool.cmd").exists())
        self.assertFalse((destination / ".dfpm-install.json").exists())
        self.assertIsNone(read_package(self.storage, "example.tool"))

    def test_modified_managed_files_are_kept_by_default(self) -> None:
        destination = self.install_version()
        changed = destination / "data" / "readme.txt"
        changed.write_text("edited by the analyst\n", encoding="utf-8")

        plan = removal.plan(self.storage, "example.tool")
        self.assertEqual(plan.modified, ("data/readme.txt",))
        removal.execute(self.storage, plan)
        self.assertEqual(changed.read_text(encoding="utf-8"), "edited by the analyst\n")

    def test_force_removes_modified_managed_files(self) -> None:
        destination = self.install_version()
        (destination / "data" / "readme.txt").write_text("edited\n", encoding="utf-8")
        self.uninstall(force=True)
        self.assertFalse(destination.exists())

    def test_reinstall_is_refused_while_preserved_files_remain(self) -> None:
        destination = self.install_version()
        (destination / "data" / "readme.txt").write_text("edited\n", encoding="utf-8")
        self.uninstall()
        with self.assertRaises(InstallError) as caught:
            self.install_version()
        self.assertIn("preserved during removal", str(caught.exception))

    def test_rejects_a_package_that_is_not_installed(self) -> None:
        with self.assertRaises(InstallError):
            removal.plan(self.storage, "missing.tool")

    def test_removing_one_package_leaves_another_alone(self) -> None:
        self.install_version(commands=("example-tool",))
        _, other = create_package(self.base, package_id="other.tool", version="2.0.0", commands=("other-tool",))
        install(Manifest.load(other), self.storage)

        self.uninstall()

        self.assertIsNone(read_package(self.storage, "example.tool"))
        self.assertEqual(read_package(self.storage, "other.tool")["version"], "2.0.0")
        self.assertTrue((self.storage.bin / "other-tool.cmd").is_file())


if __name__ == "__main__":
    unittest.main()

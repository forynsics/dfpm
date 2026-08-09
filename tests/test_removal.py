from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from dfpm import removal
from dfpm.errors import DfpmError, InstallError
from dfpm.installer import install
from dfpm.inventory import read_package
from dfpm.manifest import Manifest
from dfpm.storage import Storage, remove_tree
from tests.helpers import create_package


class RemovalTests(unittest.TestCase):
    """The version directory is the package, so removing one is removing that directory."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")

    def install_version(self, version: str = "1.0.0", *, commands=("example-tool",)) -> Path:
        _, manifest_path = create_package(self.base, version=version, commands=commands)
        return install(Manifest.load(manifest_path), self.storage)

    def uninstall(self) -> removal.RemovalPlan:
        plan = removal.plan(self.storage, "example.tool")
        removal.execute(self.storage, plan)
        return plan

    def test_removes_the_directory_shims_and_record(self) -> None:
        destination = self.install_version()
        plan = self.uninstall()

        self.assertEqual(plan.commands, ("example-tool",))
        self.assertFalse(destination.exists())
        self.assertFalse((self.storage.tools / "example.tool").exists())
        self.assertFalse((self.storage.bin / "example-tool.cmd").exists())
        self.assertIsNone(read_package(self.storage, "example.tool"))

    def test_the_plan_measures_what_is_there_now(self) -> None:
        destination = self.install_version()
        plan = removal.plan(self.storage, "example.tool")
        # dfpm's own install record is not counted, so this compares like with like.
        self.assertEqual(plan.file_count, 2)
        self.assertEqual(plan.installed_count, 2)
        self.assertFalse(plan.grew)
        self.assertGreater(plan.total_size, 0)
        self.assertEqual(plan.root, destination)

    def test_files_added_after_installation_are_removed_with_the_package(self) -> None:
        # A tool that updates its own rules, or anything dropped in by hand,
        # lives in the package's directory and goes when the package goes.
        destination = self.install_version()
        (destination / "rules").mkdir()
        (destination / "rules" / "updated.yml").write_text("rule\n", encoding="utf-8")

        plan = removal.plan(self.storage, "example.tool")
        self.assertTrue(plan.grew)
        self.assertEqual(plan.installed_count, 2)
        self.assertEqual(plan.file_count, 3)

        removal.execute(self.storage, plan)
        self.assertFalse(destination.exists())

    def test_a_modified_file_does_not_change_anything(self) -> None:
        destination = self.install_version()
        (destination / "data" / "readme.txt").write_text("edited by the analyst\n", encoding="utf-8")
        plan = removal.plan(self.storage, "example.tool")
        self.assertFalse(plan.grew)
        removal.execute(self.storage, plan)
        self.assertFalse(destination.exists())

    def test_the_same_version_can_be_installed_again_afterwards(self) -> None:
        # Nothing is preserved, so nothing is left behind to block a reinstall.
        destination = self.install_version()
        (destination / "data" / "readme.txt").write_text("edited\n", encoding="utf-8")
        self.uninstall()
        self.assertTrue(self.install_version().is_dir())

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

    def test_a_directory_that_will_not_delete_is_reported(self) -> None:
        from unittest import mock

        self.install_version()
        plan = removal.plan(self.storage, "example.tool")
        with (
            mock.patch("dfpm.removal.remove_tree", return_value=False),
            self.assertRaises(InstallError) as caught,
        ):
            removal.execute(self.storage, plan)
        self.assertIn("in use by another program", str(caught.exception))
        # The record survives, so the package is not silently forgotten.
        self.assertIsNotNone(read_package(self.storage, "example.tool"))


class ReadOnlyFileTests(unittest.TestCase):
    """Real packages ship read-only files, and Windows will not delete those."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")

    def test_a_read_only_file_does_not_block_removal(self) -> None:
        _, manifest_path = create_package(self.base)
        destination = install(Manifest.load(manifest_path), self.storage)
        # Stands in for a version control pack file, which is marked read-only
        # because it is immutable. No amount of waiting makes it deletable, so
        # retrying around it never succeeds; the flag has to be cleared.
        os.chmod(destination / "data" / "readme.txt", stat.S_IREAD)

        plan = removal.plan(self.storage, "example.tool")
        removal.execute(self.storage, plan)
        self.assertFalse(destination.exists())

    def test_a_read_only_file_does_not_block_a_replacement_either(self) -> None:
        _, first = create_package(self.base, version="1.0.0")
        old = install(Manifest.load(first), self.storage)
        os.chmod(old / "data" / "readme.txt", stat.S_IREAD)

        _, second = create_package(self.base, version="1.1.0")
        install(Manifest.load(second), self.storage)
        self.assertFalse(old.exists(), "the superseded version is still removed")


class RemovalSafetyTests(unittest.TestCase):
    """Recursive deletion is the one place a bug is unrecoverable."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")
        self.storage.initialize()

    def test_a_package_name_that_climbs_out_is_refused(self) -> None:
        # A removal takes its package name from a command line or an API
        # request, neither of which has been near a manifest.
        for attempt in ("../../escape", "..\..\escape", "/etc/passwd", ".."):
            with self.assertRaises(DfpmError, msg=attempt):
                self.storage.package_state(attempt)
            with self.assertRaises(DfpmError, msg=attempt):
                self.storage.package_version(attempt, "1.0.0")

    def test_a_version_that_climbs_out_is_refused(self) -> None:
        with self.assertRaises(DfpmError):
            self.storage.package_version("example.tool", "../../..")

    def test_only_a_package_directory_counts_as_inside_the_store(self) -> None:
        tools = self.storage.tools
        self.assertTrue(self.storage.contains_package(tools / "example.tool" / "1.0.0"))
        # The store itself, a package folder holding versions, and anything
        # above or beside it are all refused.
        self.assertFalse(self.storage.contains_package(tools))
        self.assertFalse(self.storage.contains_package(tools / "example.tool"))
        self.assertFalse(self.storage.contains_package(tools.parent))
        self.assertFalse(self.storage.contains_package(self.base / "elsewhere"))
        self.assertFalse(self.storage.contains_package(tools / "a" / "b" / "c"))

    def test_execute_refuses_a_target_outside_the_store(self) -> None:
        outside = self.base / "important"
        outside.mkdir()
        (outside / "evidence.txt").write_text("keep", encoding="utf-8")
        plan = removal.RemovalPlan(
            package="example.tool", name="Example", version="1.0.0", root=outside,
            file_count=1, total_size=4, installed_count=1, installed_size=4, commands=(),
        )
        with self.assertRaises(InstallError) as caught:
            removal.execute(self.storage, plan)
        self.assertIn("Refusing to remove", str(caught.exception))
        self.assertTrue((outside / "evidence.txt").is_file())

    def test_a_junction_is_removed_without_touching_what_it_points_at(self) -> None:
        # Windows junctions are not symlinks and are easy to get wrong. If a
        # removal ever followed one it would delete an unrelated directory.
        if os.name != "nt":
            self.skipTest("junctions are a Windows construct")
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "evidence.txt").write_text("precious", encoding="utf-8")
        package = self.storage.package_version("example.tool", "1.0.0")
        package.mkdir(parents=True)
        (package / "tool.txt").write_text("package file", encoding="utf-8")
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(package / "linked"), str(outside)],
            capture_output=True, text=True,
        )
        if created.returncode != 0:
            self.skipTest(f"could not create a junction: {created.stdout}{created.stderr}")

        self.assertTrue(remove_tree(package))
        self.assertFalse(package.exists())
        self.assertTrue((outside / "evidence.txt").is_file(), "the junction target survived")

    def test_an_unexpected_error_is_not_forced_past(self) -> None:
        # The read-only handler must not become a catch-all that deletes
        # through problems nobody predicted.
        from dfpm.storage import _make_writable

        with self.assertRaises(OSError):
            _make_writable(lambda path: None, "somewhere", OSError("disk on fire"))


if __name__ == "__main__":
    unittest.main()

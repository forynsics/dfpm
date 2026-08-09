from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from dfpm import launcher
from dfpm.cli import main
from dfpm.errors import CommandNotFound, CommandNotRunnable, ManifestError
from dfpm.installer import install
from dfpm.manifest import Manifest
from dfpm.storage import Storage
from tests.helpers import create_package

# Reports the directory it was launched from, and exits with a code of its own.
REPORT_CWD = '@echo off\r\n@echo %CD% > "%~dp0..\\where.txt"\r\nexit /b 3\r\n'


class WorkingDirectoryTests(unittest.TestCase):
    """A tool that resolves its own data against the working directory has to find it."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.storage = Storage(self.base / "dfpm-data")
        self.elsewhere = self.base / "somewhere-else"
        self.elsewhere.mkdir()

    def install_with(self, working_directory: str | None = None) -> Path:
        _, manifest_path = create_package(
            self.base, body=REPORT_CWD, working_directory=working_directory
        )
        return install(Manifest.load(manifest_path), self.storage)

    def where_it_ran(self, destination: Path) -> Path:
        return Path((destination / "where.txt").read_text(encoding="utf-8").strip())

    def test_it_runs_beside_the_executable_by_default(self) -> None:
        destination = self.install_with()
        launcher.run(self.storage, "example-tool", [])
        self.assertEqual(self.where_it_ran(destination), destination / "bin")

    def test_a_manifest_can_ask_for_the_package_root(self) -> None:
        destination = self.install_with(working_directory=".")
        launcher.run(self.storage, "example-tool", [])
        self.assertEqual(self.where_it_ran(destination), destination)

    def test_a_manifest_can_name_another_directory(self) -> None:
        destination = self.install_with(working_directory="data")
        launcher.run(self.storage, "example-tool", [])
        self.assertEqual(self.where_it_ran(destination), destination / "data")

    def test_the_callers_directory_does_not_decide_it(self) -> None:
        # The whole point: running from an unrelated directory changes nothing.
        destination = self.install_with()
        import os

        previous = Path.cwd()
        os.chdir(self.elsewhere)
        try:
            launcher.run(self.storage, "example-tool", [])
        finally:
            os.chdir(previous)
        self.assertEqual(self.where_it_ran(destination), destination / "bin")

    def test_which_reports_where_it_will_run(self) -> None:
        destination = self.install_with(working_directory=".")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(["--root", str(self.storage.root), "which", "example-tool"])
        printed = output.getvalue()
        self.assertIn("Runs in:", printed)
        self.assertIn(str(destination), printed)

    def test_which_json_reports_it_too(self) -> None:
        destination = self.install_with()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(["--root", str(self.storage.root), "which", "example-tool", "--json"])
        self.assertEqual(json.loads(output.getvalue())["working_directory"], str(destination / "bin"))

    def test_the_shim_runs_in_the_same_place_and_leaves_the_caller_alone(self) -> None:
        destination = self.install_with(working_directory=".")
        shim = self.storage.bin / "example-tool.cmd"
        completed = subprocess.run([str(shim)], cwd=str(self.elsewhere), capture_output=True)
        self.assertEqual(completed.returncode, 3, "the tool's exit code survives the shim")
        self.assertEqual(self.where_it_ran(destination), destination)
        # setlocal scopes the directory change, so a shell running the shim stays put.
        after = subprocess.run(
            ["cmd", "/c", "echo %CD%"], cwd=str(self.elsewhere), capture_output=True, text=True
        )
        self.assertEqual(Path(after.stdout.strip()), self.elsewhere)


class ExitCodeTests(unittest.TestCase):
    """dfpm run returns the tool's code, so its own failures must not collide."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.storage = Storage(self.base / "dfpm-data")

    def install_version(self, body: str) -> Path:
        _, manifest_path = create_package(self.base, body=body)
        return install(Manifest.load(manifest_path), self.storage)

    def test_the_tools_own_exit_code_passes_through(self) -> None:
        self.install_version("@exit /b 1\r\n")
        self.assertEqual(launcher.run(self.storage, "example-tool", []), 1)

    def test_an_unresolvable_command_is_127(self) -> None:
        with self.assertRaises(CommandNotFound) as caught:
            launcher.resolve(self.storage, "nosuchtool")
        self.assertEqual(caught.exception.exit_code, 127)

    def test_a_command_that_cannot_be_launched_is_126(self) -> None:
        destination = self.install_version("@exit /b 0\r\n")
        (destination / "bin" / "example-tool.cmd").unlink()
        with self.assertRaises(CommandNotRunnable) as caught:
            launcher.run(self.storage, "example-tool", [])
        self.assertEqual(caught.exception.exit_code, 126)

    def test_a_missing_working_directory_is_126(self) -> None:
        destination = self.install_version("@exit /b 0\r\n")
        import shutil

        shutil.rmtree(destination / "bin")
        with self.assertRaises(CommandNotRunnable) as caught:
            launcher.run(self.storage, "example-tool", [])
        self.assertEqual(caught.exception.exit_code, 126)

    def test_an_undeliverable_argument_is_126(self) -> None:
        self.install_version("@exit /b 0\r\n")
        with self.assertRaises(CommandNotRunnable) as caught:
            launcher.run(self.storage, "example-tool", ["a&whoami"])
        self.assertEqual(caught.exception.exit_code, 126)

    def test_the_cli_surfaces_those_codes(self) -> None:
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = main(["--root", str(self.storage.root), "run", "nosuchtool"])
        self.assertEqual(code, 127)


class WorkingDirectoryManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def with_value(self, value: str) -> Path:
        _, manifest_path = create_package(self.base, working_directory=value)
        return manifest_path

    def test_a_relative_directory_is_accepted(self) -> None:
        manifest = Manifest.load(self.with_value("data"))
        self.assertEqual(manifest.entrypoints[0].working_directory, "data")

    def test_the_package_root_is_accepted(self) -> None:
        manifest = Manifest.load(self.with_value("."))
        self.assertEqual(manifest.entrypoints[0].working_directory, ".")

    def test_omitting_it_leaves_it_unset(self) -> None:
        _, manifest_path = create_package(self.base)
        self.assertIsNone(Manifest.load(manifest_path).entrypoints[0].working_directory)

    def test_escaping_the_package_is_rejected(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            Manifest.load(self.with_value("../../elsewhere"))
        self.assertIn("working_directory", str(caught.exception))

    def test_an_absolute_directory_is_rejected(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            Manifest.load(self.with_value("C:/Windows"))
        self.assertIn("working_directory", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

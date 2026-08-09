from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from dfpm import launcher
from dfpm.cli import main
from dfpm.errors import DfpmError
from dfpm.installer import install
from dfpm.manifest import Manifest
from dfpm.storage import Storage
from tests.helpers import create_package


class LauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")

    def install_version(self, version: str = "1.0.0", *, commands=("example-tool",), body=None) -> Path:
        _, manifest_path = create_package(self.base, version=version, commands=commands, body=body)
        return install(Manifest.load(manifest_path), self.storage)

    def test_resolves_the_installed_version_target(self) -> None:
        destination = self.install_version("1.0.0")
        resolution = launcher.resolve(self.storage, "example-tool")
        self.assertEqual(resolution.package, "example.tool")
        self.assertEqual(resolution.version, "1.0.0")
        self.assertEqual(resolution.target, destination / "bin" / "example-tool.cmd")
        self.assertTrue(resolution.shim_exists)

    def test_resolution_follows_a_replacement_install(self) -> None:
        self.install_version("1.0.0")
        destination = self.install_version("1.1.0")
        resolution = launcher.resolve(self.storage, "example-tool")
        self.assertEqual(resolution.version, "1.1.0")
        self.assertEqual(resolution.target, destination / "bin" / "example-tool.cmd")

    def test_unknown_command_lists_what_is_available(self) -> None:
        self.install_version("1.0.0")
        with self.assertRaises(DfpmError) as caught:
            launcher.resolve(self.storage, "nosuchtool")
        self.assertIn("example-tool", str(caught.exception))

    def test_run_returns_the_exit_code_of_the_tool(self) -> None:
        self.install_version("1.0.0", body="@exit /b 42\r\n")
        self.assertEqual(launcher.run(self.storage, "example-tool", []), 42)

    def test_run_forwards_arguments_to_the_tool(self) -> None:
        destination = self.install_version("1.0.0", body='@echo %* > "%~dp0args.txt"\r\n')
        self.assertEqual(launcher.run(self.storage, "example-tool", ["--scan", "some path"]), 0)
        recorded = (destination / "bin" / "args.txt").read_text(encoding="utf-8").strip()
        self.assertIn("--scan", recorded)
        self.assertIn("some path", recorded)

    def test_run_refuses_an_argument_cmd_would_reinterpret(self) -> None:
        # Windows runs a .cmd through cmd.exe, which executes the text after an
        # ampersand instead of handing it to the tool. Refusing beats mangling.
        self.install_version("1.0.0")
        with self.assertRaises(DfpmError) as caught:
            launcher.run(self.storage, "example-tool", ["C:/evidence & more"])
        message = str(caught.exception)
        self.assertIn("'&'", message)
        self.assertIn("example-tool.cmd", message)

    def test_run_accepts_arguments_that_survive_cmd_intact(self) -> None:
        destination = self.install_version("1.0.0", body='@echo %* > "%~dp0args.txt"\r\n')
        arguments = ["--rules", r"D:\cases\2026\rules", "a name with spaces", "bang!value"]
        self.assertEqual(launcher.run(self.storage, "example-tool", arguments), 0)
        recorded = (destination / "bin" / "args.txt").read_text(encoding="utf-8").strip()
        self.assertIn(r"D:\cases\2026\rules", recorded)
        self.assertIn("a name with spaces", recorded)

    def test_run_reports_a_recorded_command_whose_file_vanished(self) -> None:
        destination = self.install_version("1.0.0")
        (destination / "bin" / "example-tool.cmd").unlink()
        with self.assertRaises(DfpmError) as caught:
            launcher.run(self.storage, "example-tool", [])
        self.assertIn("doctor", str(caught.exception))

    def test_path_status_reports_an_unreachable_shortcut(self) -> None:
        self.install_version("1.0.0")
        status, _ = launcher.path_status(self.storage, "example-tool")
        self.assertEqual(status, "unreachable")

    def test_which_explains_how_to_run_a_command_that_is_not_on_path(self) -> None:
        self.install_version("1.0.0")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--root", str(self.storage.root), "which", "example-tool"]), 0)
        printed = output.getvalue()
        self.assertIn("example.tool 1.0.0", printed)
        self.assertIn("not reachable", printed)
        self.assertIn("dfpm run example-tool", printed)

    def test_cli_run_passes_arguments_and_exit_code_through(self) -> None:
        self.install_version("1.0.0", body="@exit /b 7\r\n")
        self.assertEqual(main(["--root", str(self.storage.root), "run", "example-tool", "--flag", "value"]), 7)

    def test_cli_run_reports_an_unknown_command(self) -> None:
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(main(["--root", str(self.storage.root), "run", "nosuchtool"]), 1)
        self.assertIn("No installed package provides", errors.getvalue())


if __name__ == "__main__":
    unittest.main()

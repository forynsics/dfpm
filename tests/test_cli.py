from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dfpm.cli import main
from tests.helpers import create_package


class CliTests(unittest.TestCase):
    def test_cli_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            catalog, _ = create_package(base)
            root = base / "data"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--root", str(root), "--catalog", str(catalog), "install", "example.tool", "--yes"]), 0)
                self.assertEqual(main(["--root", str(root), "list"]), 0)
                self.assertEqual(main(["--root", str(root), "doctor"]), 0)
                self.assertEqual(main(["--root", str(root), "which", "example-tool"]), 0)
                self.assertEqual(main(["--root", str(root), "--catalog", str(catalog), "cache", "list"]), 0)
                self.assertEqual(main(["--root", str(root), "--catalog", str(catalog), "uninstall", "example.tool", "--yes"]), 0)
            printed = output.getvalue()
            self.assertIn("Installed to", printed)
            self.assertIn("Removed example.tool 1.0.0", printed)

    def test_declining_a_plan_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            catalog, _ = create_package(base)
            root = base / "data"
            output = io.StringIO()
            with contextlib.redirect_stdout(output), mock.patch("builtins.input", return_value="n"):
                self.assertEqual(main(["--root", str(root), "--catalog", str(catalog), "install", "example.tool"]), 2)
            self.assertIn("No changes made.", output.getvalue())
            self.assertFalse((root / "tools").exists())


class PlanProvenanceTests(unittest.TestCase):
    """The plan should say which catalog vouched for the entry it is about to install.

    A digest proves the bytes match what the entry claimed. It says nothing
    about whether that entry should be believed, and the entry is what names
    the URL, so where the entry came from is part of what is being agreed to.
    """

    def setUp(self) -> None:
        # These tests turn on where an entry is read from when nothing says, and
        # DFPM_CATALOG is one of the answers. The documented way to work against
        # this repository's catalog sets it for the shell, so a suite that
        # inherited it would fail for a reason that has nothing to do with dfpm.
        self.enterContext(mock.patch.dict("os.environ", {}, clear=False))
        __import__("os").environ.pop("DFPM_CATALOG", None)
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.catalog, _ = create_package(self.base)
        self.root = self.base / "data"

    def plan_for(self, *arguments: str) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch("builtins.input", return_value="n"):
            main(["--root", str(self.root), *arguments, "install", "example.tool"])
        return output.getvalue()

    def test_an_entry_from_elsewhere_is_named(self) -> None:
        printed = self.plan_for("--catalog", str(self.catalog))
        self.assertIn(f"Entry from:  {self.catalog}", printed)
        self.assertIn("entries you trust", printed)

    def test_the_machine_s_own_catalog_is_not_remarked_on(self) -> None:
        # Saying it every time would train people to skip the line that matters.
        machine_catalog = self.root / "catalog"
        machine_catalog.mkdir(parents=True)
        (machine_catalog / "example.tool.json").write_bytes((self.catalog / "example.tool.json").read_bytes())
        for name in ("artifacts",):
            source = self.catalog / name
            if source.is_dir():
                shutil.copytree(source, machine_catalog / name)

        printed = self.plan_for()
        self.assertIn("Install plan", printed)
        self.assertNotIn("Entry from:", printed)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dfpm.cli import main
from tests.helpers import create_package


class CliTests(unittest.TestCase):
    def test_cli_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
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
            base = Path(temporary)
            catalog, _ = create_package(base)
            root = base / "data"
            output = io.StringIO()
            with contextlib.redirect_stdout(output), mock.patch("builtins.input", return_value="n"):
                self.assertEqual(main(["--root", str(root), "--catalog", str(catalog), "install", "example.tool"]), 2)
            self.assertIn("No changes made.", output.getvalue())
            self.assertFalse((root / "tools").exists())


if __name__ == "__main__":
    unittest.main()

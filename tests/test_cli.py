from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

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
                result = main(["--root", str(root), "--catalog", str(catalog), "install", "example.tool", "--yes"])
                self.assertEqual(result, 0)
                self.assertEqual(main(["--root", str(root), "list"]), 0)
                self.assertEqual(main(["--root", str(root), "doctor"]), 0)
                self.assertEqual(main(["--root", str(root), "environment", "export", str(base / "lock.json")]), 0)
            self.assertIn("Installed to", output.getvalue())
            self.assertTrue((base / "lock.json").is_file())


if __name__ == "__main__":
    unittest.main()

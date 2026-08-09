from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dfpm.cli import main
from dfpm.platforms import current
from dfpm.storage import Storage
from tests.helpers import create_package


class DownloadTests(unittest.TestCase):
    """Getting the release file itself, for a machine dfpm is not running on."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.catalog = self.base / "catalog"
        self.storage = Storage(self.base / "data")
        self.saved = self.base / "saved"
        self.saved.mkdir()
        self.system, self.architecture = current()
        create_package(self.base, platform={"os": self.system, "arch": self.architecture})

    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--root", str(self.storage.root), "--catalog", str(self.catalog), *arguments])
        return code, out.getvalue(), err.getvalue()

    def add_build(self, os_name: str, arch: str) -> None:
        path = self.catalog / "example.tool.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        elsewhere = json.loads(json.dumps(data["builds"][0]))
        elsewhere["platform"] = {"os": os_name, "arch": arch}
        data["builds"].append(elsewhere)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_the_file_lands_under_the_name_its_project_published(self) -> None:
        code, printed, errors = self.run_cli("download", "example.tool", "--to", str(self.saved))
        self.assertEqual((code, errors), (0, ""))
        self.assertEqual([path.name for path in self.saved.iterdir()], ["example.tool-1.0.0.zip"])
        self.assertIn("Saved", printed)

    def test_a_build_for_another_machine_can_be_downloaded_here(self) -> None:
        # The whole point: this is a file, not an install, so nothing about it
        # has to suit the machine doing the downloading.
        self.add_build("macos", "arm64")
        code, _, errors = self.run_cli(
            "download", "example.tool", "--platform", "macos/arm64", "--to", str(self.saved)
        )
        self.assertEqual((code, errors), (0, ""))
        self.assertTrue(any(self.saved.iterdir()))

    def test_nothing_is_installed_cached_or_unpacked(self) -> None:
        self.run_cli("download", "example.tool", "--to", str(self.saved))
        self.assertFalse(self.storage.root.exists() and any(self.storage.root.iterdir()))
        self.assertEqual([path.suffix for path in self.saved.iterdir()], [".zip"])

    def test_it_saves_beside_you_by_default(self) -> None:
        with mock.patch("dfpm.cli.Path.cwd", return_value=self.saved):
            code, _, errors = self.run_cli("download", "example.tool")
        self.assertEqual((code, errors), (0, ""))
        self.assertTrue(any(self.saved.iterdir()))

    def test_an_existing_file_is_never_overwritten(self) -> None:
        (self.saved / "example.tool-1.0.0.zip").write_text("already here", encoding="utf-8")
        code, _, errors = self.run_cli("download", "example.tool", "--to", str(self.saved))
        self.assertEqual(code, 1)
        self.assertIn("Refusing to overwrite", errors)
        self.assertEqual((self.saved / "example.tool-1.0.0.zip").read_text(encoding="utf-8"), "already here")

    def test_bytes_that_do_not_match_the_pinned_digest_are_not_kept(self) -> None:
        path = self.catalog / "example.tool.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["builds"][0]["package"]["sha256"] = "b" * 64
        path.write_text(json.dumps(data), encoding="utf-8")

        code, _, errors = self.run_cli("download", "example.tool", "--to", str(self.saved))
        self.assertEqual(code, 1)
        self.assertNotEqual(errors, "")
        self.assertEqual(list(self.saved.iterdir()), [], "a partial or wrong file must not be left behind")

    def test_a_platform_with_no_build_is_reported(self) -> None:
        code, _, errors = self.run_cli(
            "download", "example.tool", "--platform", "linux/arm64", "--to", str(self.saved)
        )
        self.assertEqual(code, 1)
        self.assertIn("no build for linux/arm64", errors)

    def test_a_destination_that_is_not_a_directory_is_reported(self) -> None:
        code, _, errors = self.run_cli("download", "example.tool", "--to", str(self.base / "nowhere"))
        self.assertEqual(code, 1)
        self.assertIn("Not a directory", errors)


if __name__ == "__main__":
    unittest.main()

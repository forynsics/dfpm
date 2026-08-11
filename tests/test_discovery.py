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
from tests.helpers import create_package
from tests.test_catalog import build_of


class CatalogDiscoveryTests(unittest.TestCase):
    """Someone new has to be able to find what a tool is and what else it ships."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.catalog = self.base / "catalog"
        self.system, self.architecture = current()
        self.other = "linux" if self.system != "linux" else "macos"

    def run_cli(self, *arguments: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch("builtins.input", return_value="n"):
            code = main(["--root", str(self.base / "data"), "--catalog", str(self.catalog), *arguments])
        return code, output.getvalue()

    def multi_platform(self) -> None:
        create_package(
            self.base,
            platform={"os": self.system, "arch": self.architecture},
            extra_builds=[build_of("1.0.0", self.other, self.architecture)],
        )

    def test_the_listing_says_which_platforms_a_tool_ships_for(self) -> None:
        self.multi_platform()
        _, printed = self.run_cli("catalog")
        self.assertIn(f"{self.system}/{self.architecture}", printed)
        self.assertIn(f"{self.other}/{self.architecture}", printed)

    def test_the_listing_points_at_the_detail_view(self) -> None:
        self.multi_platform()
        _, printed = self.run_cli("catalog")
        self.assertIn("dfpm catalog <package>", printed)

    def test_the_detail_view_lists_every_build(self) -> None:
        self.multi_platform()
        _, printed = self.run_cli("catalog", "example.tool")
        self.assertIn(f"{self.system}/{self.architecture}", printed)
        self.assertIn(f"{self.other}/{self.architecture}", printed)
        self.assertIn("installs on this machine", printed)

    def test_the_detail_view_reports_an_unknown_package(self) -> None:
        create_package(self.base)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = main(["--catalog", str(self.catalog), "catalog", "nosuch.tool"])
        self.assertEqual(code, 1)
        self.assertIn("not found in catalog", errors.getvalue())

    def test_the_install_plan_says_a_choice_was_made(self) -> None:
        # Without this, a tool shipping for three systems looks like it only
        # exists for the one being installed.
        self.multi_platform()
        _, printed = self.run_cli("install", "example.tool")
        self.assertIn("1 of 2 builds", printed)
        self.assertIn("dfpm catalog example.tool", printed)

    def test_a_single_build_plan_says_nothing_extra(self) -> None:
        create_package(self.base, platform={"os": self.system, "arch": self.architecture})
        _, printed = self.run_cli("install", "example.tool")
        self.assertNotIn("builds", printed)

    def test_the_json_feed_carries_platforms_and_versions(self) -> None:
        self.multi_platform()
        _, printed = self.run_cli("catalog", "--json")
        entry = json.loads(printed)["packages"][0]
        self.assertEqual(len(entry["platforms"]), 2)
        self.assertEqual(entry["versions"], ["1.0.0"])

    def test_the_json_feed_can_be_narrowed_to_one_package(self) -> None:
        self.multi_platform()
        create_package(self.base, package_id="other.tool", commands=("other",))
        _, printed = self.run_cli("catalog", "example.tool", "--json")
        packages = json.loads(printed)["packages"]
        self.assertEqual([entry["id"] for entry in packages], ["example.tool"])

    def test_search_finds_a_package_by_description(self) -> None:
        create_package(self.base)
        _, printed = self.run_cli("search", "verify", "dfpm")
        self.assertIn("example.tool", printed)

    def test_search_finds_a_package_by_classification_alias(self) -> None:
        _, manifest_path = create_package(self.base)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["evidence"] = ["windows-event-logs"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        _, printed = self.run_cli("search", "evtx")
        self.assertIn("example.tool", printed)

    def test_search_json_reports_an_empty_result(self) -> None:
        create_package(self.base)
        code, printed = self.run_cli("search", "definitely-absent", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(printed)["packages"], [])


if __name__ == "__main__":
    unittest.main()

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

    def only_for(self, package_id: str, system: str) -> None:
        create_package(
            self.base,
            package_id=package_id,
            commands=(package_id.split(".")[0],),
            platform={"os": system, "arch": self.architecture},
        )

    def listed(self, printed: str) -> set[str]:
        return {line.split()[0] for line in printed.splitlines() if line.startswith(("here.", "elsewhere."))}

    def test_the_listing_shows_only_what_installs_on_this_machine(self) -> None:
        self.only_for("here.tool", self.system)
        self.only_for("elsewhere.tool", self.other)
        _, printed = self.run_cli("catalog")
        self.assertEqual(self.listed(printed), {"here.tool"})
        self.assertIn(f"Showing 1 of 2 packages: those with a build for {self.system}/{self.architecture}.", printed)
        self.assertIn("--all", printed)

    def test_all_lists_every_platform(self) -> None:
        self.only_for("here.tool", self.system)
        self.only_for("elsewhere.tool", self.other)
        _, printed = self.run_cli("catalog", "--all")
        self.assertEqual(self.listed(printed), {"here.tool", "elsewhere.tool"})
        self.assertNotIn("Showing", printed)

    def test_a_listing_can_be_for_another_machine(self) -> None:
        self.only_for("here.tool", self.system)
        self.only_for("elsewhere.tool", self.other)
        _, printed = self.run_cli("catalog", "--platform", f"{self.other}/{self.architecture}")
        self.assertEqual(self.listed(printed), {"elsewhere.tool"})

    def test_an_unknown_platform_is_refused_rather_than_matching_nothing(self) -> None:
        create_package(self.base)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = main(["--catalog", str(self.catalog), "catalog", "--platform", "plan9/x64"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown platform", errors.getvalue())

    def test_a_listing_with_nothing_for_this_machine_says_so(self) -> None:
        self.only_for("elsewhere.tool", self.other)
        _, printed = self.run_cli("catalog")
        self.assertEqual(self.listed(printed), set())
        self.assertIn(f"No packages with a build for {self.system}/{self.architecture}; 1 for other platforms.", printed)

    def test_the_json_listing_follows_the_same_scope(self) -> None:
        self.only_for("here.tool", self.system)
        self.only_for("elsewhere.tool", self.other)
        _, narrowed = self.run_cli("catalog", "--json")
        _, everything = self.run_cli("catalog", "--json", "--all")
        self.assertEqual([entry["id"] for entry in json.loads(narrowed)["packages"]], ["here.tool"])
        self.assertEqual(
            sorted(entry["id"] for entry in json.loads(everything)["packages"]), ["elsewhere.tool", "here.tool"]
        )

    def test_the_detail_view_is_never_narrowed(self) -> None:
        self.only_for("elsewhere.tool", self.other)
        code, printed = self.run_cli("catalog", "elsewhere.tool")
        self.assertEqual(code, 0)
        self.assertIn(f"None of these run on {self.system}/{self.architecture}.", printed)

    def test_search_is_narrowed_the_same_way(self) -> None:
        self.only_for("here.tool", self.system)
        self.only_for("elsewhere.tool", self.other)
        _, printed = self.run_cli("search", "synthetic")
        self.assertEqual(self.listed(printed), {"here.tool"})
        self.assertIn("Showing 1 of 2 matches", printed)
        _, everything = self.run_cli("search", "synthetic", "--all")
        self.assertEqual(self.listed(everything), {"here.tool", "elsewhere.tool"})

    def test_search_says_when_every_match_is_for_another_platform(self) -> None:
        self.only_for("elsewhere.tool", self.other)
        _, printed = self.run_cli("search", "synthetic")
        self.assertEqual(self.listed(printed), set())
        self.assertIn(f"No matches with a build for {self.system}/{self.architecture}; 1 for other platforms.", printed)

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

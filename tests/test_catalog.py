from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfpm.catalog import describe, load_catalog, resolve, version_key
from dfpm.errors import ManifestError
from dfpm.manifest import Tool
from dfpm.platforms import current
from tests.helpers import create_package


class VersionOrderTests(unittest.TestCase):
    def test_orders_by_number_rather_than_by_text(self) -> None:
        """Plain string sorting would put 1.10.0 before 1.9.0."""
        versions = ["1.9.0", "1.10.0", "1.0.0", "2.0.0"]
        self.assertEqual(sorted(versions, key=version_key), ["1.0.0", "1.9.0", "1.10.0", "2.0.0"])

    def test_ranks_a_prerelease_below_its_release(self) -> None:
        self.assertLess(version_key("1.0.0-rc1"), version_key("1.0.0"))
        self.assertLess(version_key("1.0.0"), version_key("1.0.1-rc1"))

    def test_orders_versions_of_differing_length(self) -> None:
        self.assertLess(version_key("1.2"), version_key("1.2.1"))
        self.assertLess(version_key("4.5.5"), version_key("4.5.8"))


def build_of(version: str, os_name: str, arch: str) -> dict:
    """A second build of the same synthetic package, for selection tests."""
    return {
        "version": version,
        "platform": {"os": os_name, "arch": arch},
        "package": {"url": "https://example.org/other.zip", "sha256": "b" * 64, "size": 10},
        "install": {
            "strategy": "portable-zip",
            "strip_components": 1,
            "entrypoints": [{"name": "example-tool", "path": "bin/example-tool"}],
        },
    }


class SelectionTests(unittest.TestCase):
    """A tool ships several builds; exactly one of them can be installed here."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.catalog = self.base / "catalog"
        self.system, self.architecture = current()

    def test_the_build_for_this_machine_is_chosen(self) -> None:
        # The bug this replaces: two builds of one version differ only in what
        # they run on, and whichever sorted last used to win.
        create_package(
            self.base,
            platform={"os": self.system, "arch": self.architecture},
            extra_builds=[build_of("1.0.0", "linux" if self.system != "linux" else "macos", self.architecture)],
        )
        chosen = resolve(self.catalog, "example.tool")
        self.assertEqual(chosen.platform.system, self.system)

    def test_another_platform_can_be_asked_for_by_name(self) -> None:
        # Staging a machine you are not sitting at is a real workflow.
        other = "linux" if self.system != "linux" else "macos"
        create_package(
            self.base,
            platform={"os": self.system, "arch": self.architecture},
            extra_builds=[build_of("1.0.0", other, self.architecture)],
        )
        chosen = resolve(self.catalog, "example.tool", platform=f"{other}/{self.architecture}")
        self.assertEqual(chosen.platform.system, other)

    def test_a_platform_with_no_build_says_what_is_offered(self) -> None:
        create_package(self.base, platform={"os": self.system, "arch": self.architecture})
        with self.assertRaises(ManifestError) as caught:
            resolve(self.catalog, "example.tool", platform="linux/arm64")
        message = str(caught.exception)
        self.assertIn("no build for linux/arm64", message)
        self.assertIn("ships builds for", message)

    def test_a_malformed_platform_is_reported(self) -> None:
        create_package(self.base)
        with self.assertRaises(ManifestError) as caught:
            resolve(self.catalog, "example.tool", platform="windows")
        self.assertIn("os/arch", str(caught.exception))

    def test_a_build_without_a_platform_installs_anywhere(self) -> None:
        create_package(self.base)
        self.assertIsNone(resolve(self.catalog, "example.tool").platform)

    def test_the_newest_version_is_chosen(self) -> None:
        create_package(
            self.base,
            version="1.9.0",
            extra_builds=[
                {**build_of("1.10.0", self.system, self.architecture), "platform": None} | {"platform": None},
            ],
        )
        # The extra build carries no platform, so it is installable here too.
        self.assertEqual(resolve(self.catalog, "example.tool").version, "1.10.0")

    def test_an_explicit_version_is_honoured(self) -> None:
        create_package(
            self.base,
            version="1.9.0",
            extra_builds=[{**build_of("1.10.0", self.system, self.architecture), "platform": None}],
        )
        self.assertEqual(resolve(self.catalog, "example.tool", "1.9.0").version, "1.9.0")

    def test_a_version_that_is_not_listed_says_which_are(self) -> None:
        create_package(self.base, version="1.9.0")
        with self.assertRaises(ManifestError) as caught:
            resolve(self.catalog, "example.tool", "2.0.0")
        self.assertIn("1.9.0", str(caught.exception))

    def test_two_builds_cannot_claim_the_same_version_and_platform(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            create_package(
                self.base,
                platform={"os": self.system, "arch": self.architecture},
                extra_builds=[build_of("1.0.0", self.system, self.architecture)],
            )
            Tool.load(self.catalog / "example.tool.json")
        self.assertIn("same version and platform", str(caught.exception))


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_resolve_reports_a_package_that_is_not_listed(self) -> None:
        create_package(self.base)
        with self.assertRaises(ManifestError) as caught:
            resolve(self.base / "catalog", "missing.tool")
        self.assertIn("not found in catalog", str(caught.exception))

    def test_missing_catalog_directory_is_reported(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            load_catalog(self.base / "nowhere")
        message = str(caught.exception)
        self.assertIn("No catalog on this machine", message)
        # A fresh install has no catalog, so the message has to say what fixes it.
        self.assertIn("--catalog", message)

    def test_describe_omits_optional_sections_that_are_absent(self) -> None:
        _, manifest_path = create_package(self.base)
        entry = describe(Tool.load(manifest_path))
        self.assertEqual(entry["id"], "example.tool")
        self.assertEqual(entry["platforms"], [])
        self.assertNotIn("project", entry)

    def test_describe_reports_the_platforms_a_tool_ships_for(self) -> None:
        # A property of the tool, derived from its builds rather than declared
        # again where the two could disagree.
        create_package(
            self.base,
            platform={"os": "windows", "arch": "x64"},
            extra_builds=[build_of("1.0.0", "linux", "x64")],
        )
        entry = describe(Tool.load(self.base / "catalog" / "example.tool.json"))
        self.assertEqual(
            entry["platforms"],
            [{"os": "windows", "arch": "x64"}, {"os": "linux", "arch": "x64"}],
        )


if __name__ == "__main__":
    unittest.main()

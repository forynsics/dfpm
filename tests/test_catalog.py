from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfpm.catalog import describe, load_catalog, resolve, version_key
from dfpm.errors import ManifestError
from dfpm.manifest import Manifest
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


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_resolve_picks_the_highest_version_when_none_is_asked_for(self) -> None:
        for version in ("1.0.0", "1.10.0", "1.9.0"):
            create_package(self.base, version=version)
        catalog = self.base / "catalog"
        self.assertEqual(resolve(catalog, "example.tool").version, "1.10.0")

    def test_resolve_honours_an_explicit_version(self) -> None:
        for version in ("1.0.0", "1.10.0"):
            create_package(self.base, version=version)
        self.assertEqual(resolve(self.base / "catalog", "example.tool", "1.0.0").version, "1.0.0")

    def test_resolve_reports_a_package_that_is_not_listed(self) -> None:
        create_package(self.base)
        with self.assertRaises(ManifestError) as caught:
            resolve(self.base / "catalog", "missing.tool")
        self.assertIn("not found in catalog", str(caught.exception))

    def test_missing_catalog_directory_is_reported(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            load_catalog(self.base / "nowhere")
        self.assertIn("does not exist", str(caught.exception))

    def test_describe_omits_optional_sections_that_are_absent(self) -> None:
        _, manifest_path = create_package(self.base)
        entry = describe(Manifest.load(manifest_path))
        self.assertEqual(entry["id"], "example.tool")
        self.assertNotIn("platform", entry)
        self.assertNotIn("project", entry)


if __name__ == "__main__":
    unittest.main()

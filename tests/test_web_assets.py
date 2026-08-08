from __future__ import annotations

import unittest
from pathlib import Path

from dfpm.gui import ASSET_DIRECTORY, ASSETS, SHARED_STYLESHEETS

REPOSITORY = Path(__file__).resolve().parents[1]


class WebAssetTests(unittest.TestCase):
    def test_shared_stylesheets_match_the_public_site(self) -> None:
        """The interface reuses the site's visual system, so the copies must not drift."""
        for name in SHARED_STYLESHEETS:
            with self.subTest(stylesheet=name):
                source = REPOSITORY / name
                copy = ASSET_DIRECTORY / name
                self.assertTrue(source.is_file(), f"{source} is missing")
                self.assertEqual(
                    copy.read_bytes(),
                    source.read_bytes(),
                    f"{copy} has drifted from {source}. Copy the site stylesheet over it again, "
                    f"and keep interface-only rules in local.css.",
                )

    def test_every_served_asset_exists(self) -> None:
        for name, _ in ASSETS.values():
            with self.subTest(asset=name):
                self.assertTrue((ASSET_DIRECTORY / name).is_file())

    def test_the_page_links_only_assets_that_are_served(self) -> None:
        page = (ASSET_DIRECTORY / "index.html").read_text(encoding="utf-8")
        served = {name for name, _ in ASSETS.values()}
        for name in served:
            if name != "index.html":
                self.assertIn(name, page, f"{name} is served but never referenced by the page")


if __name__ == "__main__":
    unittest.main()

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

    def test_the_interface_references_every_asset_it_serves(self) -> None:
        # The page links its stylesheets and script; the script names anything
        # it loads later, such as an image. Either counts as being used, and an
        # asset named by neither is one the interface no longer needs.
        referenced = "".join(
            (ASSET_DIRECTORY / name).read_text(encoding="utf-8") for name in ("index.html", "app.js")
        )
        for name, _ in ASSETS.values():
            if name in {"index.html", "app.js"}:
                continue
            with self.subTest(asset=name):
                self.assertIn(name, referenced, f"{name} is served but never referenced by the interface")


if __name__ == "__main__":
    unittest.main()

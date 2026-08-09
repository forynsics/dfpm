from __future__ import annotations

import json
import unittest
from pathlib import Path

from dfpm.catalog import describe, load_catalog
from dfpm.classification import vocabulary

REPOSITORY = Path(__file__).resolve().parents[1]
FEED = REPOSITORY / "catalog.json"
REGENERATE = "Regenerate it with: dfpm catalog --json > catalog.json"


class SiteFeedTests(unittest.TestCase):
    """The public site reads catalog.json, which has to keep saying what the catalog says.

    A static page cannot run dfpm, so the feed is generated and committed. That
    is the only copy of the catalog outside catalog/ itself, and a copy nothing
    checks is a copy that goes stale the first time a manifest changes.
    """

    def setUp(self) -> None:
        self.assertTrue(FEED.is_file(), f"{FEED} is missing. {REGENERATE}")
        self.feed = json.loads(FEED.read_text(encoding="utf-8"))

    def test_the_feed_matches_the_catalog_it_was_generated_from(self) -> None:
        expected = [describe(tool) for tool in load_catalog(REPOSITORY / "catalog")]
        self.assertEqual(self.feed.get("packages"), expected, f"catalog.json has drifted. {REGENERATE}")

    def test_the_feed_carries_the_vocabulary(self) -> None:
        # The site offers disciplines a reader can browse by, including ones
        # nothing is catalogued under yet, so it must not keep its own list.
        self.assertEqual(self.feed.get("vocabulary"), vocabulary(), f"catalog.json has drifted. {REGENERATE}")

    def test_the_site_reads_the_feed_rather_than_a_copy_of_it(self) -> None:
        script = (REPOSITORY / "app.js").read_text(encoding="utf-8")
        self.assertIn("catalog.json", script)
        for tool in load_catalog(REPOSITORY / "catalog"):
            self.assertNotIn(
                f'"{tool.id}"',
                script,
                f"app.js names {tool.id} directly, which means the page is describing a package "
                f"from something other than the feed.",
            )

    def test_the_feed_is_shaped_the_way_the_page_reads_it(self) -> None:
        for package in self.feed["packages"]:
            with self.subTest(package=package["id"]):
                self.assertIsInstance(package.get("platforms"), list)
                for platform in package["platforms"]:
                    self.assertEqual(set(platform), {"os", "arch"})
                for item in package.get("disciplines", []):
                    self.assertEqual(set(item), {"key", "label"})


if __name__ == "__main__":
    unittest.main()

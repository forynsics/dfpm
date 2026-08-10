from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from dfpm.catalog import INDEX_NAME, SHIPPED, build_index, describe, load_catalog
from dfpm.classification import vocabulary

REPOSITORY = Path(__file__).resolve().parents[1]
SITE = REPOSITORY / "docs"
CATALOG = REPOSITORY / "catalog"


class SiteFeedTests(unittest.TestCase):
    """The feed the public site reads is generated when the site is deployed.

    It is not committed, so there is nothing to keep in step and nothing to go
    stale. What has to keep working is the generating: the command has to run,
    and what it produces has to be shaped the way the page reads it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        produced = subprocess.run(
            [sys.executable, "-m", "dfpm", "--catalog", str(CATALOG), "catalog", "--json"],
            capture_output=True,
            text=True,
            cwd=REPOSITORY,
        )
        if produced.returncode != 0:
            raise AssertionError(f"generating the site feed failed:\n{produced.stderr}")
        cls.feed = json.loads(produced.stdout)

    def test_the_feed_describes_every_reviewed_package(self) -> None:
        expected = [describe(tool) for tool in load_catalog(CATALOG)]
        self.assertEqual(self.feed.get("packages"), expected)

    def test_the_feed_carries_the_vocabulary(self) -> None:
        # The site offers disciplines a reader can browse by, including ones
        # nothing is catalogued under yet, so it must not keep its own list.
        self.assertEqual(self.feed.get("vocabulary"), vocabulary())

    def test_the_site_reads_the_feed_rather_than_a_copy_of_it(self) -> None:
        script = (SITE / "app.js").read_text(encoding="utf-8")
        self.assertIn("catalog.json", script)
        for tool in load_catalog(CATALOG):
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

    def test_the_deploy_generates_the_feed_the_page_asks_for(self) -> None:
        """The workflow and the page have to agree on the filename, or the site loads nothing."""
        workflow = (REPOSITORY / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("docs/catalog.json", workflow)
        self.assertIn('CATALOG_FEED = "catalog.json"', (SITE / "app.js").read_text(encoding="utf-8"))


class PublishedIndexTests(unittest.TestCase):
    """The index is the one derived file that has to be committed.

    `dfpm sync` fetches it straight from the repository over HTTPS, so it cannot
    be built at deploy time the way the site feed is.
    """

    def test_the_published_index_matches_the_entries(self) -> None:
        """A stale index makes a reviewed entry invisible to everyone syncing.

        The digests are of the entry files exactly as they are stored, which is
        why line endings are pinned in .gitattributes: an index generated from a
        CRLF checkout would not match what a static host serves.
        """
        written = json.loads((CATALOG / INDEX_NAME).read_text(encoding="utf-8"))
        self.assertEqual(
            written,
            build_index(CATALOG),
            f"{CATALOG / INDEX_NAME} is stale. Regenerate it with: dfpm catalog --index > catalog\\index.json",
        )


class ShippedEntriesTests(unittest.TestCase):
    """dfpm carries the reviewed entries, so installing it is enough to have something to install.

    The build stages them, so what is on disk here reflects the last build and
    is expected to lag a catalog that has just been edited. Holding it to
    catalog/ would put back the chore this replaced: an entry added, a test
    failing, and a reinstall run for no reason but to quiet it. Whether a built
    package really carries the catalog is asserted where a build has just
    happened, in the test workflow.
    """

    def test_the_shipped_entries_load(self) -> None:
        # They are what a fresh machine reads, so a broken one is not a
        # cosmetic problem: nothing would be installable at all.
        self.assertTrue(load_catalog(SHIPPED))


if __name__ == "__main__":
    unittest.main()


class LineEndingTests(unittest.TestCase):
    """Catalog files are hashed as bytes, so their line endings are not cosmetic."""

    def test_every_catalog_file_uses_one_line_ending(self) -> None:
        # The index records a digest of each file's bytes. A working copy that
        # writes CRLF where the repository holds LF produces an index nobody
        # else can reproduce, which fails on a build machine and nowhere near
        # the person who caused it.
        catalog = REPOSITORY / "catalog"
        files = list(catalog.glob("*.json")) + list((catalog / "collections").glob("*.json"))
        offenders = [path.name for path in files if b"\r\n" in path.read_bytes()]
        self.assertEqual(offenders, [], "these carry CRLF; .gitattributes asks for LF")

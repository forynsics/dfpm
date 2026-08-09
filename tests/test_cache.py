from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from dfpm import cache
from dfpm.cli import main
from dfpm.errors import DfpmError
from dfpm.installer import install
from dfpm.manifest import Manifest
from dfpm.storage import Storage
from tests.helpers import create_package


class CacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.storage = Storage(self.base / "dfpm-data")
        self.catalog, self.manifest_path = create_package(self.base)

    def install_it(self, version: str = "1.0.0") -> Path:
        _, manifest_path = create_package(self.base, version=version)
        return install(Manifest.load(manifest_path), self.storage)

    def test_classifies_installed_catalog_and_orphaned_artifacts(self) -> None:
        self.install_it()
        entry = cache.survey(self.storage, self.catalog).entries[0]
        self.assertEqual(entry.status, "installed")
        self.assertEqual(entry.installed_by, ("example.tool 1.0.0",))
        self.assertEqual(entry.listed_by, ("example.tool 1.0.0",))

        with contextlib.redirect_stdout(io.StringIO()):
            main(["--root", str(self.storage.root), "--catalog", str(self.catalog), "uninstall", "example.tool", "--yes"])
        entry = cache.survey(self.storage, self.catalog).entries[0]
        self.assertEqual(entry.status, "catalog", "an artifact the catalog still lists is pre-seeded, not garbage")

        self.manifest_path.unlink()
        self.assertEqual(cache.survey(self.storage, self.catalog).entries[0].status, "orphan")

    def test_prune_clears_anything_no_installed_package_needs(self) -> None:
        self.install_it()
        with contextlib.redirect_stdout(io.StringIO()):
            main(["--root", str(self.storage.root), "--catalog", str(self.catalog), "uninstall", "example.tool", "--yes"])
        current = cache.survey(self.storage, self.catalog)
        self.assertEqual(len(cache.removable(current)), 1, "nothing is installed, so nothing needs it")
        self.assertEqual(cache.removable(current, keep_catalog=True), (), "the catalog still lists it")

    def test_prune_keeps_an_artifact_an_installed_package_needs(self) -> None:
        self.install_it()
        self.assertEqual(cache.removable(cache.survey(self.storage, self.catalog)), ())

    def test_prune_removes_orphans_and_interrupted_downloads(self) -> None:
        self.install_it()
        self.manifest_path.unlink()
        leftover = self.storage.cache / "abc.partial"
        leftover.write_bytes(b"half a download")
        with contextlib.redirect_stdout(io.StringIO()):
            main(["--root", str(self.storage.root), "--catalog", str(self.catalog), "uninstall", "example.tool", "--yes"])
            self.assertEqual(main(["--root", str(self.storage.root), "--catalog", str(self.catalog), "cache", "prune", "--yes"]), 0)
        self.assertEqual(cache.survey(self.storage, self.catalog).entries, ())
        self.assertFalse(leftover.exists())

    def test_prune_refuses_when_asked_to_keep_a_catalog_it_cannot_read(self) -> None:
        self.install_it()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(io.StringIO()):
            result = main([
                "--root", str(self.storage.root), "--catalog", str(self.base / "missing"),
                "cache", "prune", "--keep-catalog", "--yes",
            ])
        self.assertEqual(result, 1)
        self.assertIn("--ignore-catalog", errors.getvalue())

    def test_verify_detects_a_corrupted_artifact(self) -> None:
        self.install_it()
        entry = cache.survey(self.storage, self.catalog).entries[0]
        entry.path.write_bytes(b"not the bytes that were verified")
        results = cache.verify(self.storage, self.catalog)
        self.assertEqual(results[0][1], "content does not match its digest")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--root", str(self.storage.root), "--catalog", str(self.catalog), "cache", "verify"]), 1)
        self.assertIn("FAIL", output.getvalue())

    def test_verify_passes_for_an_untouched_cache(self) -> None:
        self.install_it()
        self.assertEqual([problem for _, problem in cache.verify(self.storage, self.catalog)], [None])

    def test_remove_refuses_an_artifact_an_installed_package_needs(self) -> None:
        self.install_it()
        digest = cache.survey(self.storage, self.catalog).entries[0].digest
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(io.StringIO()):
            result = main(["--root", str(self.storage.root), "--catalog", str(self.catalog), "cache", "remove", digest[:12], "--yes"])
        self.assertEqual(result, 1)
        self.assertIn("--force", errors.getvalue())
        self.assertEqual(len(cache.survey(self.storage, self.catalog).entries), 1)

    def test_remove_accepts_an_unambiguous_digest_prefix_with_force(self) -> None:
        self.install_it()
        digest = cache.survey(self.storage, self.catalog).entries[0].digest
        with contextlib.redirect_stdout(io.StringIO()):
            result = main(["--root", str(self.storage.root), "--catalog", str(self.catalog), "cache", "remove", digest[:12], "--force", "--yes"])
        self.assertEqual(result, 0)
        self.assertEqual(cache.survey(self.storage, self.catalog).entries, ())

    def test_unknown_digest_is_reported(self) -> None:
        self.install_it()
        with self.assertRaises(DfpmError):
            cache.find(cache.survey(self.storage, self.catalog), "ffffffff")

    def test_the_digest_shown_by_list_can_be_pasted_straight_back(self) -> None:
        self.install_it()
        current = cache.survey(self.storage, self.catalog)
        shown = cache.short(current.entries[0].digest)
        self.assertNotIn("…", shown)
        self.assertEqual(cache.find(current, shown).digest, current.entries[0].digest)
        self.assertEqual(cache.find(current, f" {shown.upper()}… ").digest, current.entries[0].digest)

    def test_a_value_that_is_not_a_digest_is_rejected_clearly(self) -> None:
        self.install_it()
        current = cache.survey(self.storage, self.catalog)
        with self.assertRaises(DfpmError) as caught:
            cache.find(current, "yara 4.5.5")
        self.assertIn("is not a digest", str(caught.exception))

    def test_files_dfpm_does_not_recognize_are_left_alone(self) -> None:
        self.install_it()
        self.manifest_path.unlink()
        stray = self.storage.cache / "analyst-notes.txt"
        stray.write_text("do not delete me\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            main(["--root", str(self.storage.root), "--catalog", str(self.catalog), "uninstall", "example.tool", "--yes"])
            main(["--root", str(self.storage.root), "--catalog", str(self.catalog), "cache", "prune", "--yes"])
        self.assertTrue(stray.is_file())
        self.assertIn(stray, cache.survey(self.storage, self.catalog).unrecognized)

    def test_list_reports_an_empty_cache(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--root", str(self.storage.root), "--catalog", str(self.catalog), "cache", "list"]), 0)
        self.assertIn("cache is empty", output.getvalue())


if __name__ == "__main__":
    unittest.main()

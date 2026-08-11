from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dfpm import sync
from dfpm.catalog import INDEX_NAME, build_index, load_catalog
from dfpm.errors import DfpmError
from tests.helpers import create_package


class SyncFixture(unittest.TestCase):
    """A published catalog and a machine that can sync from it."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.published, _ = create_package(self.base)
        self.local = self.base / "machine" / "catalog"
        self.republish()

    def republish(self) -> None:
        """Rewrite the index, as publishing the catalog would."""
        index = build_index(self.published)
        (self.published / INDEX_NAME).write_text(json.dumps(index, indent=2), encoding="utf-8")

    def source(self) -> str:
        return f"{self.published}/"

    def sync(self) -> list[sync.Change]:
        return sync.apply(sync.plan(self.source(), self.local))

    def edit_published(self, **changes: object) -> None:
        path = self.published / "example.tool.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(changes)
        path.write_text(json.dumps(data), encoding="utf-8")
        self.republish()


class SyncTests(SyncFixture):
    """Bringing a machine's catalog into line with a published one."""

    def test_a_machine_with_no_catalog_gets_one(self) -> None:
        applied = self.sync()
        self.assertEqual([change.kind for change in applied], [sync.ADDED])
        self.assertTrue(load_catalog(self.local))

    def test_an_unchanged_entry_is_never_downloaded_twice(self) -> None:
        # The digest in the index is what makes this cheap, and it is the whole
        # reason syncing is something you can do often.
        self.sync()
        second = sync.plan(self.source(), self.local)
        self.assertEqual([change.kind for change in second.changes], [sync.UNCHANGED])
        self.assertEqual(second.fetches, [])
        self.assertFalse(second.changes_anything)

    def test_a_published_change_is_fetched(self) -> None:
        self.sync()
        self.edit_published(description="Now described differently.")
        current = sync.plan(self.source(), self.local)
        self.assertEqual([change.kind for change in current.changes], [sync.UPDATED])
        sync.apply(current)
        self.assertEqual(load_catalog(self.local)[0].description, "Now described differently.")

    def test_an_entry_changed_on_this_machine_is_called_out(self) -> None:
        # Overwriting somebody's edit silently is worse than saying so first.
        self.sync()
        path = self.local / "example.tool.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["description"] = "Edited here."
        path.write_text(json.dumps(data), encoding="utf-8")

        current = sync.plan(self.source(), self.local)
        self.assertEqual([change.kind for change in current.changes], [sync.EDITED])

    def test_an_entry_withdrawn_upstream_is_removed(self) -> None:
        self.sync()
        (self.published / "example.tool.json").unlink()
        create_package(self.base, package_id="second.tool", commands=("second-tool",))
        self.republish()

        current = sync.plan(self.source(), self.local)
        self.assertEqual(
            {change.id: change.kind for change in current.changes},
            {"second.tool": sync.ADDED, "example.tool": sync.REMOVED},
        )
        sync.apply(current)
        self.assertFalse((self.local / "example.tool.json").exists())
        self.assertEqual([tool.id for tool in load_catalog(self.local)], ["second.tool"])

    def test_a_collection_withdrawn_upstream_is_removed_transactionally(self) -> None:
        collections = self.published / "collections"
        collections.mkdir()
        collection = collections / "example-set.json"
        collection.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "example-set",
                    "name": "Example set",
                    "description": "Fixture",
                    "packages": ["example.tool"],
                }
            ),
            encoding="utf-8",
        )
        self.republish()
        self.sync()
        self.assertTrue((self.local / "collections" / collection.name).exists())

        collection.unlink()
        self.republish()
        current = sync.plan(self.source(), self.local)
        self.assertEqual(current.of(sync.REMOVED)[0].file, f"collections/{collection.name}")
        sync.apply(current)
        self.assertFalse((self.local / "collections" / collection.name).exists())

    def test_the_index_is_written_so_the_next_sync_can_compare(self) -> None:
        self.sync()
        written = json.loads((self.local / INDEX_NAME).read_text(encoding="utf-8"))
        self.assertEqual(written["schema_version"], 1)
        self.assertEqual([entry["id"] for entry in written["entries"]], ["example.tool"])

    def test_the_index_is_not_treated_as_a_package(self) -> None:
        self.sync()
        self.assertEqual([tool.id for tool in load_catalog(self.local)], ["example.tool"])

    def test_publish_failure_restores_the_complete_previous_snapshot(self) -> None:
        self.sync()
        previous = (self.local / "example.tool.json").read_bytes()
        self.edit_published(description="A newer snapshot that must not land halfway.")
        current = sync.plan(self.source(), self.local)
        real_replace = sync.os.replace
        backup = sync.backup_directory(self.local)

        def fail_new_snapshot(source, destination):
            if Path(destination) == self.local and Path(source) != backup:
                raise OSError("simulated publish failure")
            return real_replace(source, destination)

        with mock.patch.object(sync.os, "replace", side_effect=fail_new_snapshot), self.assertRaises(DfpmError):
            sync.apply(current)
        self.assertEqual((self.local / "example.tool.json").read_bytes(), previous)
        self.assertFalse(backup.exists())
        self.assertEqual(sync.staging_directories(self.local), [])

    def test_next_sync_recovers_a_backup_left_between_directory_renames(self) -> None:
        self.sync()
        backup = sync.backup_directory(self.local)
        sync.os.replace(self.local, backup)
        self.assertFalse(self.local.exists())

        applied = self.sync()
        self.assertTrue(applied)
        self.assertTrue(load_catalog(self.local))
        self.assertFalse(backup.exists())

    def test_snapshot_staging_failure_never_touches_the_active_catalog(self) -> None:
        self.sync()
        previous = (self.local / "example.tool.json").read_bytes()
        self.edit_published(description="Will fail while staging.")
        with mock.patch.object(sync, "_write_snapshot_file", side_effect=DfpmError("disk full")), self.assertRaises(DfpmError):
            self.sync()
        self.assertEqual((self.local / "example.tool.json").read_bytes(), previous)
        self.assertEqual(sync.staging_directories(self.local), [])


class SyncRefusalTests(SyncFixture):
    """What a published catalog is not allowed to talk dfpm into."""

    def corrupt_index(self, **changes: object) -> None:
        path = self.published / INDEX_NAME
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(changes)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_an_index_naming_a_path_is_refused(self) -> None:
        # The index decides filenames that get written into a directory.
        for name in ("../escape.json", "sub/dir.json", ".hidden.json", "notjson.txt"):
            with self.subTest(name=name):
                self.corrupt_index(entries=[{"file": name, "id": "x", "sha256": "a" * 64}])
                with self.assertRaises(DfpmError) as caught:
                    sync.plan(self.source(), self.local)
                self.assertIn("will not write", str(caught.exception))

    def test_an_index_cannot_list_itself(self) -> None:
        self.corrupt_index(entries=[{"file": INDEX_NAME, "id": "x", "sha256": "a" * 64}])
        with self.assertRaises(DfpmError):
            sync.plan(self.source(), self.local)

    def test_a_later_index_schema_is_refused_rather_than_guessed_at(self) -> None:
        self.corrupt_index(schema_version=99)
        with self.assertRaises(DfpmError) as caught:
            sync.plan(self.source(), self.local)
        self.assertIn("cannot read", str(caught.exception))

    def test_an_entry_that_does_not_match_its_digest_is_refused(self) -> None:
        # The published entry changed without the index being regenerated, or
        # something rewrote it in between.
        (self.published / "example.tool.json").write_text('{"tampered": true}', encoding="utf-8")
        with self.assertRaises(DfpmError) as caught:
            self.sync()
        self.assertIn("does not match the digest", str(caught.exception))
        self.assertFalse(self.local.exists() and any(self.local.glob("*.json")))

    def test_an_entry_that_is_not_a_manifest_is_refused(self) -> None:
        # Digest intact, so this is a publisher serving something that parses as
        # JSON and is not an entry. It has to be refused on content, not on
        # transport, and refused before it is stored rather than at install.
        body = b'{"schema_version": 1, "id": "x"}'
        (self.published / "example.tool.json").write_bytes(body)
        index = self.published / INDEX_NAME
        data = json.loads(index.read_text(encoding="utf-8"))
        data["entries"][0]["sha256"] = hashlib.sha256(body).hexdigest()
        index.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaises(DfpmError) as caught:
            self.sync()
        self.assertIn("not a usable entry", str(caught.exception))
        self.assertFalse(self.local.exists() and any(self.local.glob("*.json")))

    def test_nothing_lands_when_one_entry_fails(self) -> None:
        # A source that breaks halfway leaves the catalog as it was.
        create_package(self.base, package_id="second.tool", commands=("second-tool",))
        self.republish()
        (self.published / "second.tool.json").write_text('{"tampered": true}', encoding="utf-8")
        with self.assertRaises(DfpmError):
            self.sync()
        self.assertFalse(self.local.exists() and any(self.local.glob("*.json")))

    def test_a_source_that_is_not_https_or_a_directory_is_refused(self) -> None:
        for location in ("http://example.org/catalog/", "ftp://example.org/catalog/"):
            with self.subTest(location=location):
                with self.assertRaises(DfpmError) as caught:
                    sync.plan(location, self.local)
                self.assertIn("HTTPS", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

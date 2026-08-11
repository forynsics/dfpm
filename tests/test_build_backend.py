from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build_backend


class CatalogStagingTests(unittest.TestCase):
    def test_a_previous_build_cannot_keep_a_withdrawn_entry(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        source = base / "catalog"
        shipped = base / "src" / "dfpm" / "entries"
        built = base / "build" / "lib" / "dfpm" / "entries"
        (source / "collections").mkdir(parents=True)
        shipped.mkdir(parents=True)
        built.mkdir(parents=True)
        (source / "current.json").write_text("{}", encoding="utf-8")
        (source / "collections" / "set.json").write_text("{}", encoding="utf-8")
        (shipped / "withdrawn.json").write_text("{}", encoding="utf-8")
        (built / "withdrawn.json").write_text("{}", encoding="utf-8")

        with mock.patch.multiple(build_backend, SOURCE=source, SHIPPED=shipped, BUILT=built):
            build_backend._stage_entries()

        self.assertFalse(built.exists())
        self.assertEqual({path.name for path in shipped.glob("*.json")}, {"current.json"})
        self.assertTrue((shipped / "collections" / "set.json").is_file())


if __name__ == "__main__":
    unittest.main()

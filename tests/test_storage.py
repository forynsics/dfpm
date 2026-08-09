from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfpm.cli import catalog_directory
from dfpm.storage import Storage


class DefaultRootTests(unittest.TestCase):
    """Where dfpm keeps its data must follow the operating system, not an environment variable."""

    def test_windows_root_sits_under_local_app_data(self) -> None:
        storage = Storage.default(environ={"LOCALAPPDATA": r"C:\Users\example\AppData\Local"}, system="nt")
        self.assertEqual(storage.root, Path(r"C:\Users\example\AppData\Local") / "dfpm")

    def test_posix_root_follows_xdg_data_home(self) -> None:
        storage = Storage.default(environ={"XDG_DATA_HOME": "/home/example/.local/share"}, system="posix")
        self.assertEqual(storage.root, Path("/home/example/.local/share") / "dfpm")

    def test_posix_root_ignores_local_app_data_inherited_from_windows(self) -> None:
        # WSL exports Windows variables through WSLENV. Keying the root on
        # LOCALAPPDATA would put a Linux install on /mnt/c, where the executable
        # bit does not stick and the filesystem is case-insensitive.
        storage = Storage.default(
            environ={"LOCALAPPDATA": r"C:\Users\example\AppData\Local", "XDG_DATA_HOME": "/home/example/.local/share"},
            system="posix",
        )
        self.assertEqual(storage.root, Path("/home/example/.local/share") / "dfpm")

    def test_posix_root_falls_back_to_local_share(self) -> None:
        storage = Storage.default(environ={}, system="posix")
        self.assertEqual(storage.root, Path.home() / ".local" / "share" / "dfpm")

    def test_windows_root_falls_back_under_the_home_directory(self) -> None:
        storage = Storage.default(environ={}, system="nt")
        self.assertEqual(storage.root, Path.home() / "AppData" / "Local" / "dfpm")

    def test_every_directory_stays_inside_one_root(self) -> None:
        # An analyst should be able to archive or hand over a single directory,
        # and the cache in particular must not live somewhere a cleaner will take it.
        storage = Storage(Path("/srv/dfpm"))
        for directory in (storage.tools, storage.cache, storage.state, storage.bin):
            self.assertEqual(directory.parts[: len(storage.root.parts)], storage.root.parts)


if __name__ == "__main__":
    unittest.main()


class CatalogLocationTests(unittest.TestCase):
    """Where entries are read from, now that it is a location rather than a guess."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "data")

    def test_the_machine_has_a_catalog_of_its_own(self) -> None:
        self.assertEqual(self.storage.catalog, self.storage.root / "catalog")

    def test_it_falls_back_to_that_catalog(self) -> None:
        # Without this, dfpm can only install from a directory that happens to
        # sit beside the working directory.
        self.assertEqual(catalog_directory(None, self.storage, {}), self.storage.catalog)

    def test_the_environment_overrides_the_machine_catalog(self) -> None:
        chosen = catalog_directory(None, self.storage, {"DFPM_CATALOG": str(self.base / "source")})
        self.assertEqual(chosen, self.base / "source")

    def test_the_flag_beats_everything(self) -> None:
        chosen = catalog_directory(self.base / "explicit", self.storage, {"DFPM_CATALOG": str(self.base / "source")})
        self.assertEqual(chosen, self.base / "explicit")

    def test_the_catalog_is_not_under_state(self) -> None:
        # What is available and what is installed move independently, which is
        # only true if they are not in each other's directories.
        self.assertNotIn(self.storage.state, self.storage.catalog.parents)
        self.assertNotIn(self.storage.catalog, self.storage.state.parents)

from __future__ import annotations

import unittest
from pathlib import Path

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

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dfpm.catalog import SHIPPED
from dfpm import configuration
from dfpm.cli import catalog_directory, main
from dfpm.errors import DfpmError
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


class PersistentRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.environ = {"LOCALAPPDATA": str(self.base / "local")}

    def test_configuration_file_has_a_fixed_bootstrap_location(self) -> None:
        self.assertEqual(
            configuration.file(self.environ, "nt"),
            self.base / "local" / "dfpm" / "config.json",
        )

    def test_a_root_round_trips_through_the_saved_configuration(self) -> None:
        root = self.base / "chosen"
        configuration.set_root(root, self.environ, "nt")
        self.assertEqual(configuration.configured_root(self.environ, "nt"), root)
        self.assertTrue(configuration.unset_root(self.environ, "nt"))
        self.assertIsNone(configuration.configured_root(self.environ, "nt"))

    def test_the_command_persists_a_root_for_later_commands(self) -> None:
        root = self.base / "chosen"
        with mock.patch.dict("os.environ", self.environ, clear=False):
            self._main_output(["config", "set", "root", str(root)])
            output = self._main_output(["paths"])
        self.assertIn(f"Root:               {root} (saved configuration)", output)
        self.assertIn(f"Tools:              {root / 'tools'}", output)

    def test_the_command_line_override_beats_the_saved_root(self) -> None:
        saved = self.base / "saved"
        override = self.base / "one-command"
        configuration.set_root(saved, self.environ, "nt")
        with mock.patch.dict("os.environ", self.environ, clear=False):
            output = self._main_output(["--root", str(override), "paths"])
        self.assertIn(f"Root:               {override} (command line)", output)

    def test_config_show_reports_the_saved_root_and_bootstrap_file(self) -> None:
        saved = self.base / "saved"
        path = configuration.file(self.environ, "nt")
        configuration.set_root(saved, self.environ, "nt")
        with mock.patch.dict("os.environ", self.environ, clear=False):
            output = self._main_output(["config", "show"])
        self.assertIn(f"Root:               {saved} (saved configuration)", output)
        self.assertIn(f"Configuration:      {path}", output)

    def test_unset_returns_future_commands_to_the_platform_default(self) -> None:
        configuration.set_root(self.base / "chosen", self.environ, "nt")
        default = self.base / "local" / "dfpm"
        with mock.patch.dict("os.environ", self.environ, clear=False):
            self._main_output(["config", "unset", "root"])
            output = self._main_output(["paths"])
        self.assertIn(f"Root:               {default} (platform default)", output)

    def test_setting_a_root_does_not_move_or_initialize_data(self) -> None:
        old_root = self.base / "local" / "dfpm"
        old_root.mkdir(parents=True)
        marker = old_root / "existing-tool.txt"
        marker.write_text("leave me here", encoding="utf-8")
        chosen = self.base / "chosen"
        with mock.patch.dict("os.environ", self.environ, clear=False):
            self._main_output(["config", "set", "root", str(chosen)])
        self.assertEqual(marker.read_text(encoding="utf-8"), "leave me here")
        self.assertFalse(chosen.exists())

    def test_an_unreadable_setting_fails_loudly_but_can_be_replaced(self) -> None:
        path = configuration.file(self.environ, "nt")
        path.parent.mkdir(parents=True)
        path.write_text("not json", encoding="utf-8")
        with self.assertRaises(DfpmError):
            configuration.configured_root(self.environ, "nt")
        chosen = self.base / "replacement"
        with mock.patch.dict("os.environ", self.environ, clear=False):
            self._main_output(["config", "set", "root", str(chosen)])
        self.assertEqual(configuration.configured_root(self.environ, "nt"), chosen)

    @staticmethod
    def _main_output(arguments: list[str]) -> str:
        import contextlib
        import io

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(arguments)
        if result != 0:
            raise AssertionError(f"dfpm returned {result}: {output.getvalue()}")
        return output.getvalue()


if __name__ == "__main__":
    unittest.main()


class CatalogLocationTests(unittest.TestCase):
    """Where entries are read from, now that it is a location rather than a guess."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.storage = Storage(self.base / "data")

    def test_the_machine_has_a_catalog_of_its_own(self) -> None:
        self.assertEqual(self.storage.catalog, self.storage.root / "catalog")

    def test_a_curated_catalog_is_used(self) -> None:
        # Without this, dfpm can only install from a directory that happens to
        # sit beside the working directory.
        self.storage.catalog.mkdir(parents=True)
        (self.storage.catalog / "example.tool.json").write_text("{}", encoding="utf-8")
        self.assertEqual(catalog_directory(None, self.storage, {}), self.storage.catalog)

    def test_a_machine_with_no_catalog_reads_the_entries_dfpm_shipped(self) -> None:
        # A fresh install would otherwise have an empty directory and nothing
        # to install from, which is the state every new user starts in.
        self.assertEqual(catalog_directory(None, self.storage, {}), SHIPPED)

    def test_an_empty_catalog_directory_is_read_straight_past(self) -> None:
        # Existing but empty is what a directory looks like before anyone has
        # put anything in it, and is not a decision to have no packages.
        self.storage.catalog.mkdir(parents=True)
        self.assertEqual(catalog_directory(None, self.storage, {}), SHIPPED)

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

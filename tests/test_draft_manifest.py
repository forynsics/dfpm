from __future__ import annotations

import importlib.util
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from dfpm.manifest import Tool

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    """Import the maintainer script, which lives outside the package and is not importable by name."""
    spec = importlib.util.spec_from_file_location("draft_manifest", ROOT / "scripts" / "draft-manifest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


draft = load_script()


def fake_executable(machine: int = 0x8664, version: tuple[int, int, int, int] | None = (2026, 5, 0, 0)) -> bytes:
    """A file with just enough of a PE in it to be read the way a real one is."""
    header = bytearray(b"MZ" + b"\0" * 0x3E)
    struct.pack_into("<I", header, 0x3C, 0x40)
    body = bytearray(b"PE\0\0" + struct.pack("<H", machine) + b"\0" * 32)
    if version is not None:
        major, minor, build, revision = version
        body += draft.VERSION_SIGNATURE + b"\0" * 4
        body += struct.pack("<II", (major << 16) | minor, (build << 16) | revision)
    return bytes(header + body)


class ArchiveShapeTests(unittest.TestCase):
    """Working out how deep an archive unpacks, which decides where everything lands."""

    def test_a_flat_archive_needs_nothing_stripped(self) -> None:
        self.assertEqual(draft.common_depth(["Tool.exe", "Tool.dll"]), 0)

    def test_one_shared_wrapping_folder_is_stripped(self) -> None:
        self.assertEqual(draft.common_depth(["Tool/Tool.exe", "Tool/Maps/a.map"]), 1)

    def test_a_file_beside_the_folder_stops_it_being_stripped(self) -> None:
        # Stripping here would silently drop the loose file rather than fail.
        self.assertEqual(draft.common_depth(["Tool/Tool.exe", "README.txt"]), 0)

    def test_two_top_level_folders_are_not_a_wrapper(self) -> None:
        self.assertEqual(draft.common_depth(["One/a.exe", "Two/b.exe"]), 0)


class CommandNameTests(unittest.TestCase):
    """Shim names become filenames, so they are held to what dfpm will accept."""

    def test_a_name_is_taken_from_the_executable_and_lowercased(self) -> None:
        self.assertEqual(draft.command_name("EvtxECmd.exe"), "evtxecmd")

    def test_a_nested_executable_keeps_only_its_own_name(self) -> None:
        self.assertEqual(draft.command_name("bin/Some Tool.exe"), "some-tool")

    def test_a_name_that_would_be_nothing_still_produces_something(self) -> None:
        self.assertEqual(draft.command_name("---.exe"), "tool")


class BinaryReadingTests(unittest.TestCase):
    """What a Windows executable says about itself, which is often the only place it is said."""

    def test_the_version_resource_is_read(self) -> None:
        self.assertEqual(draft.file_version(fake_executable()), "2026.5.0.0")

    def test_a_binary_with_no_version_resource_reports_nothing(self) -> None:
        self.assertIsNone(draft.file_version(fake_executable(version=None)))

    def test_the_architecture_is_read_from_the_pe_header(self) -> None:
        for machine, expected in ((0x8664, "x64"), (0x014C, "x86"), (0xAA64, "arm64")):
            with self.subTest(machine=machine):
                self.assertEqual(draft.MACHINES[draft.machine_type(fake_executable(machine))], expected)

    def test_something_that_is_not_a_pe_reports_nothing(self) -> None:
        self.assertIsNone(draft.machine_type(b"not an executable at all"))


class DraftTests(unittest.TestCase):
    """The whole draft, against archives shaped like the ones the catalog holds."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def archive(self, members: dict[str, bytes]) -> Path:
        path = self.base / "artifact.zip"
        with zipfile.ZipFile(path, "w") as bundle:
            for name, body in members.items():
                bundle.writestr(name, body)
        return path

    def draft_for(self, members: dict[str, bytes]) -> dict:
        path = self.archive(members)
        entry, _ = draft.describe(path, "a" * 64, path.stat().st_size, "https://example.org/tool.zip", "tool", "Tool")
        return entry

    def test_a_wrapping_archive_resolves_the_executable_to_the_package_root(self) -> None:
        # The directory and the file inside it need not agree on capitalisation,
        # which is invisible in a listing and easy to copy wrongly by hand.
        entry = self.draft_for(
            {
                "Toolkit/ToolKit.exe": fake_executable(),
                "Toolkit/Maps/one.map": b"map\n",
            }
        )
        build = entry["builds"][0]
        self.assertEqual(build["install"]["strip_components"], 1)
        self.assertEqual(build["install"]["entrypoints"], [{"name": "toolkit", "path": "ToolKit.exe"}])

    def test_the_recorded_cost_counts_files_and_not_directories(self) -> None:
        entry = self.draft_for({"Tool.exe": fake_executable(), "notes.txt": b"12345"})
        install = entry["builds"][0]["install"]
        self.assertEqual(install["entries"], 2)
        self.assertEqual(install["extracted_size"], len(fake_executable()) + 5)

    def test_a_runtime_is_read_from_what_the_package_ships_beside_itself(self) -> None:
        config = json.dumps({"runtimeOptions": {"framework": {"name": "Microsoft.NETCore.App", "version": "9.0.0"}}})
        entry = self.draft_for({"Tool.exe": fake_executable(), "Tool.runtimeconfig.json": config.encode()})
        self.assertEqual(
            entry["builds"][0]["requires"], [{"runtime": "dotnet", "flavor": "base", "version": ">=9"}]
        )

    def test_the_more_specific_framework_wins_when_both_are_declared(self) -> None:
        # A desktop application declares both, and the base runtime does not
        # satisfy it. dfpm accepts each runtime once, so one has to be chosen.
        config = json.dumps(
            {
                "runtimeOptions": {
                    "frameworks": [
                        {"name": "Microsoft.NETCore.App", "version": "9.0.0"},
                        {"name": "Microsoft.WindowsDesktop.App", "version": "9.0.0"},
                    ]
                }
            }
        )
        entry = self.draft_for({"Tool.exe": fake_executable(), "Tool.runtimeconfig.json": config.encode()})
        self.assertEqual(entry["builds"][0]["requires"][0]["flavor"], "desktop")

    def test_nothing_is_claimed_that_the_archive_cannot_settle(self) -> None:
        entry = self.draft_for({"Tool.exe": fake_executable()})
        self.assertEqual(entry["description"], "")
        for field in ("about", "disciplines", "capabilities", "use_cases", "evidence", "project"):
            self.assertNotIn(field, entry)
        self.assertNotIn("stability", entry["builds"][0]["package"])

    def test_an_unreadable_version_is_left_blank_rather_than_invented(self) -> None:
        entry = self.draft_for({"Tool.exe": fake_executable(version=None)})
        self.assertEqual(entry["builds"][0]["version"], "")

    def test_the_draft_loads_as_a_manifest_once_the_judgement_is_filled_in(self) -> None:
        # The point of the script is to produce something a reviewer completes,
        # so what it emits has to be valid the moment the prose is added.
        entry = self.draft_for({"Toolkit/ToolKit.exe": fake_executable(), "Toolkit/Maps/one.map": b"map\n"})
        entry["description"] = "A tool used to check the draft is usable."
        entry["builds"][0]["package"]["sha256"] = "b" * 64
        path = self.base / "tool.json"
        path.write_text(json.dumps(entry), encoding="utf-8")
        loaded = Tool.load(path)
        self.assertEqual(loaded.builds[0].entrypoints[0].name, "toolkit")
        self.assertFalse(loaded.builds[0].package.rolling)


if __name__ == "__main__":
    unittest.main()

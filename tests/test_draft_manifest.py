from __future__ import annotations

import importlib.util
import json
import io
import struct
import tarfile
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


def fake_elf(machine: int = 0x3E, big_endian: bool = False) -> bytes:
    """The identifying part of an ELF header, which is all the draft reads."""
    order = ">" if big_endian else "<"
    ident = b"\x7fELF" + bytes([2, 2 if big_endian else 1, 1]) + b"\0" * 9
    return ident + struct.pack(order + "HH", 2, machine) + b"\0" * 44


def fake_macho(cpu: int = 0x0100000C, filetype: int = 2) -> bytes:
    return b"\xcf\xfa\xed\xfe" + struct.pack("<IIII", cpu, 0, filetype, 0) + b"\0" * 12


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

    def test_a_release_file_name_loses_its_version_and_platform(self) -> None:
        for released, expected in (
            ("velociraptor-v0.77.2-linux-amd64-musl", "velociraptor"),
            ("velociraptor-v0.77.2-windows-amd64.exe", "velociraptor"),
            ("hayabusa-4.1.0-lin-x64-musl", "hayabusa"),
            ("tool_linux_arm64", "tool"),
            ("Tool.x64.exe", "tool"),
        ):
            with self.subTest(released=released):
                self.assertEqual(draft.command_name(released), expected)

    def test_a_name_that_merely_contains_a_platform_word_keeps_it(self) -> None:
        self.assertEqual(draft.command_name("winpmem.exe"), "winpmem")
        self.assertEqual(draft.command_name("x64dbg.exe"), "x64dbg")

    def test_a_name_that_would_be_nothing_still_produces_something(self) -> None:
        self.assertEqual(draft.command_name("---.exe"), "tool")


class BinaryReadingTests(unittest.TestCase):
    """What a Windows executable says about itself, which is often the only place it is said."""

    def test_the_system_and_architecture_are_read_from_any_supported_header(self) -> None:
        cases = (
            (fake_executable(0xAA64), ("windows", "arm64")),
            (fake_elf(0x3E), ("linux", "x64")),
            (fake_elf(0xB7), ("linux", "arm64")),
            (fake_elf(0xB7, big_endian=True), ("linux", "arm64")),
            (fake_macho(), ("macos", "arm64")),
        )
        for binary, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(draft.binary_platform(binary), expected)

    def test_an_unknown_machine_is_still_recognised_as_a_program(self) -> None:
        self.assertEqual(draft.binary_platform(fake_elf(0xF3)), ("linux", None))

    def test_a_file_that_is_no_program_reports_nothing(self) -> None:
        for body in (b"#!/bin/sh\n", b"PK\x03\x04", b""):
            with self.subTest(body=body):
                self.assertIsNone(draft.binary_platform(body))

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


class OtherArtifactTests(unittest.TestCase):
    """Tar archives, bare executables and ZIPs made on Unix, which is how most Linux builds are published."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def tarball(self, members: dict[str, tuple[bytes, int]]) -> Path:
        path = self.base / "tool.tar.gz"
        with tarfile.open(path, "w:gz") as bundle:
            for name, (body, mode) in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(body)
                info.mode = mode
                bundle.addfile(info, io.BytesIO(body))
        return path

    def zipped(self, members: dict[str, tuple[bytes, int | None]]) -> Path:
        path = self.base / "tool.zip"
        with zipfile.ZipFile(path, "w") as bundle:
            for name, (body, mode) in members.items():
                info = zipfile.ZipInfo(name)
                info.create_system = 0 if mode is None else 3
                if mode is not None:
                    info.external_attr = (0o100000 | mode) << 16
                bundle.writestr(info, body)
        return path

    def bare(self, body: bytes) -> Path:
        path = self.base / "download"
        path.write_bytes(body)
        return path

    def describe(self, path: Path, url: str) -> tuple[dict, list[str]]:
        return draft.describe(path, "a" * 64, path.stat().st_size, url, "tool", "Tool")

    def entrypoints(self, entry: dict) -> list[str]:
        return [item["path"] for item in entry["builds"][0]["install"]["entrypoints"]]

    def test_a_tar_archive_is_drafted_as_one(self) -> None:
        path = self.tarball(
            {
                "tool-1.0/tool": (fake_elf(), 0o755),
                "tool-1.0/libhelper.so.1": (fake_elf(), 0o755),
                "tool-1.0/README": (b"read me\n", 0o644),
            }
        )
        entry, unknowns = self.describe(path, "https://example.org/tool.tar.gz")
        build = entry["builds"][0]
        self.assertEqual(build["install"]["strategy"], "portable-tar")
        self.assertEqual(build["install"]["strip_components"], 1)
        self.assertEqual(build["install"]["entries"], 3)
        self.assertEqual(build["install"]["entrypoints"], [{"name": "tool", "path": "tool"}])
        self.assertEqual(build["platform"], {"os": "linux", "arch": "x64"})
        self.assertEqual(build["version"], "")
        self.assertTrue(any(item.startswith("version -") for item in unknowns))

    def test_a_program_the_archive_does_not_mark_executable_is_not_a_command(self) -> None:
        path = self.tarball({"tool": (fake_elf(), 0o755), "debug-symbols": (fake_elf(), 0o644)})
        entry, _ = self.describe(path, "https://example.org/tool.tar.gz")
        self.assertEqual(self.entrypoints(entry), ["tool"])

    def test_a_leading_dot_directory_is_not_mistaken_for_a_wrapper(self) -> None:
        path = self.tarball({"./tool": (fake_elf(), 0o755), "./rules/a.yml": (b"a\n", 0o644)})
        entry, _ = self.describe(path, "https://example.org/tool.tar.gz")
        self.assertEqual(entry["builds"][0]["install"]["strip_components"], 0)
        self.assertEqual(self.entrypoints(entry), ["tool"])

    def test_a_tar_archive_holding_a_link_is_refused(self) -> None:
        # dfpm refuses to install it, so a draft would only be a dead end.
        path = self.base / "linked.tar"
        with tarfile.open(path, "w") as bundle:
            info = tarfile.TarInfo("tool")
            info.type = tarfile.SYMTYPE
            info.linkname = "elsewhere"
            bundle.addfile(info)
        with self.assertRaises(SystemExit):
            self.describe(path, "https://example.org/linked.tar")

    def test_a_zip_without_permissions_is_read_by_header_and_says_so(self) -> None:
        path = self.zipped({"capa": (fake_elf(), None), "notes.txt": (b"notes", None), "libx.so": (fake_elf(), None)})
        entry, unknowns = self.describe(path, "https://example.org/capa-linux.zip")
        build = entry["builds"][0]
        self.assertEqual(build["install"]["strategy"], "portable-zip")
        self.assertEqual(self.entrypoints(entry), ["capa"])
        self.assertEqual(build["platform"], {"os": "linux", "arch": "x64"})
        self.assertTrue(any("marks no program executable" in item for item in unknowns))

    def test_a_zip_with_permissions_honours_them(self) -> None:
        path = self.zipped({"tool": (fake_elf(), 0o755), "tool-debug": (fake_elf(), 0o644)})
        entry, unknowns = self.describe(path, "https://example.org/tool.zip")
        self.assertEqual(self.entrypoints(entry), ["tool"])
        self.assertFalse(any("marks no program executable" in item for item in unknowns))

    def test_an_archive_marking_nothing_executable_still_yields_its_program(self) -> None:
        # Some publishers record 0644 for every file, the binary included.
        path = self.zipped({"tool-1.0-lin-x64": (fake_elf(), 0o644), "rules/a.yml": (b"a", 0o644)})
        entry, unknowns = self.describe(path, "https://example.org/tool.zip")
        self.assertEqual(entry["builds"][0]["install"]["entrypoints"], [{"name": "tool", "path": "tool-1.0-lin-x64"}])
        self.assertTrue(any("marks no program executable" in item for item in unknowns))

    def test_a_macos_archive_takes_only_programs(self) -> None:
        path = self.tarball({"tool": (fake_macho(), 0o755), "libtool.dylib": (fake_macho(filetype=6), 0o755)})
        entry, _ = self.describe(path, "https://example.org/tool-mac.tar.gz")
        self.assertEqual(self.entrypoints(entry), ["tool"])
        self.assertEqual(entry["builds"][0]["platform"], {"os": "macos", "arch": "arm64"})

    def test_a_bare_executable_is_drafted_as_a_standalone_file(self) -> None:
        path = self.bare(fake_elf(0xB7))
        entry, unknowns = self.describe(path, "https://example.org/releases/tool-v1.2.3-linux-arm64?raw=1")
        build = entry["builds"][0]
        self.assertEqual(
            build["install"],
            {
                "strategy": "standalone-file",
                "strip_components": 0,
                "extracted_size": path.stat().st_size,
                "entries": 1,
                "entrypoints": [{"name": "tool", "path": "tool-v1.2.3-linux-arm64"}],
            },
        )
        self.assertEqual(build["platform"], {"os": "linux", "arch": "arm64"})
        self.assertFalse(any(item.startswith("verify -") for item in unknowns))

    def test_a_bare_windows_executable_still_reports_its_version(self) -> None:
        entry, _ = self.describe(self.bare(fake_executable()), "https://example.org/tool.exe")
        build = entry["builds"][0]
        self.assertEqual(build["install"]["strategy"], "standalone-file")
        self.assertEqual(build["version"], "2026.5.0.0")
        self.assertEqual(build["platform"], {"os": "windows", "arch": "x64"})

    def test_something_that_is_neither_archive_nor_program_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            self.describe(self.bare(b"<html>not found</html>"), "https://example.org/tool")

    def test_these_drafts_load_as_manifests(self) -> None:
        tarball = self.tarball({"tool-1.0/tool": (fake_elf(), 0o755), "tool-1.0/rules/a.yml": (b"a", 0o644)})
        bare = self.bare(fake_elf())
        for path, url in ((tarball, "https://example.org/tool.tar.gz"), (bare, "https://example.org/tool-linux")):
            with self.subTest(url=url):
                entry, _ = self.describe(path, url)
                entry["builds"][0]["version"] = "1.0.0"
                entry["description"] = "A tool used to check the draft is usable."
                manifest = self.base / "tool.json"
                manifest.write_text(json.dumps(entry), encoding="utf-8")
                self.assertEqual(Tool.load(manifest).builds[0].entrypoints[0].name, "tool")


if __name__ == "__main__":
    unittest.main()

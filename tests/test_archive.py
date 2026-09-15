from __future__ import annotations

import io
import os
import stat
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from collections import namedtuple
from collections.abc import Iterable
from pathlib import Path
from unittest import mock

from dfpm.archive import ArchiveLimits, check_path_lengths, extract_tar, extract_zip
from dfpm.errors import InstallError


def build(base: Path, entries: Iterable[tuple[str | zipfile.ZipInfo, str | bytes]], name: str = "test.zip") -> Path:
    path = base / name
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for entry, data in entries:
                output.writestr(entry, data)
    return path


def entry(name: str, *, mode: int = 0) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    if mode:
        info.external_attr = mode << 16
    return info


def mark_encrypted(path: Path) -> Path:
    """Set the encryption flag in place, since zipfile rewrites flag bits as it writes."""
    data = bytearray(path.read_bytes())
    data[data.index(b"PK\x03\x04") + 6] |= 0x01
    data[data.index(b"PK\x01\x02") + 8] |= 0x01
    path.write_bytes(bytes(data))
    return path


class ArchiveTests(unittest.TestCase):
    def extract(self, entries, *, strip: int = 0, limits: ArchiveLimits | None = None) -> list[dict[str, str | int]]:
        base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        archive = build(base, entries)
        destination = base / "out"
        destination.mkdir()
        return extract_zip(archive, destination, strip, limits or ArchiveLimits())

    def assertRejected(self, entries, message: str, *, strip: int = 0, limits: ArchiveLimits | None = None) -> None:
        with self.assertRaises(InstallError) as caught:
            self.extract(entries, strip=strip, limits=limits)
        self.assertIn(message, str(caught.exception))

    def test_records_every_extracted_file(self) -> None:
        files = self.extract([("tool/bin/tool.cmd", "@echo tool\r\n"), ("tool/readme.txt", "notes\n")], strip=1)
        self.assertEqual([item["path"] for item in files], ["bin/tool.cmd", "readme.txt"])
        self.assertEqual(files[1]["size"], len("notes\n"))

    def test_rejects_parent_traversal(self) -> None:
        self.assertRejected([("../outside.txt", "unsafe")], "parent or self reference")

    def test_rejects_absolute_path(self) -> None:
        self.assertRejected([("/etc/passwd", "unsafe")], "absolute path")

    def test_rejects_drive_qualified_path(self) -> None:
        self.assertRejected([("C:/Windows/evil.txt", "unsafe")], "not allowed in a file name")

    def test_rejects_reserved_device_name(self) -> None:
        self.assertRejected([("bin/nul.txt", "unsafe")], "reserved Windows device name")

    def test_rejects_trailing_space(self) -> None:
        self.assertRejected([("bin/tool.exe ", "unsafe")], "ends with a space or a dot")

    def test_rejects_duplicate_paths(self) -> None:
        self.assertRejected([("bin/tool.cmd", "first"), ("bin/tool.cmd", "second")], "same location")

    def test_rejects_case_colliding_paths(self) -> None:
        self.assertRejected([("bin/Tool.cmd", "first"), ("bin/tool.cmd", "second")], "differ only by capitalization")

    def test_rejects_paths_that_collide_after_stripping(self) -> None:
        self.assertRejected(
            [("one/tool.cmd", "first"), ("two/tool.cmd", "second")],
            "same location",
            strip=1,
        )

    def test_rejects_case_collisions_created_by_stripping(self) -> None:
        self.assertRejected(
            [("one/Tool.cmd", "first"), ("two/tool.cmd", "second")],
            "differ only by capitalization",
            strip=1,
        )

    def test_rejects_path_used_as_file_and_directory(self) -> None:
        self.assertRejected([("bin/tool/", ""), ("bin/tool", "data")], "both a file and a directory")

    def test_rejects_symbolic_link(self) -> None:
        self.assertRejected([(entry("bin/link", mode=stat.S_IFLNK | 0o777), "target")], "symbolic link")

    def test_rejects_special_file(self) -> None:
        self.assertRejected([(entry("bin/pipe", mode=stat.S_IFIFO | 0o644), "")], "special file")

    def test_rejects_encrypted_entry(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        archive = mark_encrypted(build(base, [("bin/tool.cmd", "data")]))
        destination = base / "out"
        destination.mkdir()
        with self.assertRaises(InstallError) as caught:
            extract_zip(archive, destination, 0)
        self.assertIn("encrypted entry", str(caught.exception))

    def test_rejects_more_entries_than_it_will_extract(self) -> None:
        entries = [(f"bin/tool{index}.cmd", "data") for index in range(4)]
        self.assertRejected(entries, "above the 3", limits=ArchiveLimits(max_entries=3))

    def test_writes_binary_content_byte_for_byte(self) -> None:
        payload = os.urandom(4096)
        base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        archive = build(base, [("bin/tool.bin", payload)])
        destination = base / "out"
        destination.mkdir()
        files = extract_zip(archive, destination, 0)
        self.assertEqual(files[0]["size"], 4096)
        self.assertEqual((destination / "bin" / "tool.bin").read_bytes(), payload)

    def test_rejects_archive_with_nothing_left_after_stripping(self) -> None:
        self.assertRejected([("readme.txt", "notes")], "did not contain any installable files", strip=1)

    def test_an_empty_result_points_at_strip_components(self) -> None:
        self.assertRejected([("tool/readme.txt", "notes")], "strip_components", strip=4)


@unittest.skipIf(os.name == "nt", "Windows has no execute permission to carry")
class ZipModeTests(unittest.TestCase):
    def test_an_executable_member_stays_executable_and_others_do_not_become_so(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        archive = build(base, [
            (entry("bin/tool", mode=stat.S_IFREG | 0o755), "#!/bin/sh\n"),
            (entry("share/notes.txt", mode=stat.S_IFREG | 0o644), "notes\n"),
            ("share/no-mode.txt", "made where modes are not recorded\n"),
        ])
        destination = base / "out"
        destination.mkdir()
        extract_zip(archive, destination, 0)
        self.assertTrue(os.access(destination / "bin" / "tool", os.X_OK))
        self.assertFalse(os.access(destination / "share" / "notes.txt", os.X_OK))
        self.assertFalse(os.access(destination / "share" / "no-mode.txt", os.X_OK))


def member(name: str, *, kind: bytes = tarfile.REGTYPE, mode: int = 0o644, linkname: str = "") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.mode = mode
    info.linkname = linkname
    return info


def build_tar(
    base: Path,
    members: Iterable[tuple[tarfile.TarInfo, bytes | None]],
    name: str = "test.tar.gz",
    mode: str = "w:gz",
) -> Path:
    path = base / name
    with tarfile.open(path, mode) as output:
        for info, data in members:
            if data is None:
                output.addfile(info)
            else:
                info.size = len(data)
                output.addfile(info, io.BytesIO(data))
    return path


class TarArchiveTests(unittest.TestCase):
    """A tarball is held to exactly the rules a ZIP is."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.destination = self.base / "out"
        self.destination.mkdir()

    def extract(self, members, *, strip: int = 0, limits: ArchiveLimits | None = None, mode: str = "w:gz"):
        archive = build_tar(self.base, members, mode=mode)
        return extract_tar(archive, self.destination, strip, limits or ArchiveLimits())

    def assertRejected(self, members, message: str, **kwargs) -> None:
        with self.assertRaises(InstallError) as caught:
            self.extract(members, **kwargs)
        self.assertIn(message, str(caught.exception))

    def test_a_top_level_directory_is_stripped_like_any_other(self) -> None:
        files = self.extract([
            (member("chainsaw/", kind=tarfile.DIRTYPE, mode=0o755), None),
            (member("chainsaw/chainsaw", mode=0o755), b"\x7fELF binary"),
            (member("chainsaw/mappings/sigma.yml"), b"groups: []\n"),
        ], strip=1)
        self.assertEqual([item["path"] for item in files], ["chainsaw", "mappings/sigma.yml"])
        self.assertEqual((self.destination / "chainsaw").read_bytes(), b"\x7fELF binary")

    def test_the_archive_root_recorded_as_a_member_is_passed_over(self) -> None:
        files = self.extract([(member("./", kind=tarfile.DIRTYPE, mode=0o755), None), (member("./yr"), b"yr")])
        self.assertEqual([item["path"] for item in files], ["yr"])

    def test_every_compression_tarfile_reads_is_accepted(self) -> None:
        for mode, name in (("w", "plain.tar"), ("w:gz", "t.tar.gz"), ("w:bz2", "t.tar.bz2"), ("w:xz", "t.tar.xz")):
            with self.subTest(mode=mode):
                archive = build_tar(self.base, [(member("tool"), b"payload")], name=name, mode=mode)
                destination = self.base / f"out-{name}"
                destination.mkdir()
                files = extract_tar(archive, destination, 0)
                self.assertEqual(files, [{"path": "tool", "size": len(b"payload")}])

    def test_rejects_a_symbolic_link(self) -> None:
        self.assertRejected([(member("lib/libfoo.so", kind=tarfile.SYMTYPE, linkname="/etc/passwd"), None)], "unsupported link")

    def test_rejects_a_hard_link(self) -> None:
        self.assertRejected(
            [(member("a"), b"data"), (member("b", kind=tarfile.LNKTYPE, linkname="a"), None)], "unsupported link"
        )

    def test_rejects_special_files(self) -> None:
        for kind in (tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE):
            with self.subTest(kind=kind):
                self.assertRejected([(member("dev/thing", kind=kind), None)], "special file")

    def test_rejects_absolute_and_escaping_paths(self) -> None:
        self.assertRejected([(member("/etc/cron.d/job"), b"x")], "absolute path")
        self.assertRejected([(member("../outside"), b"x")], "parent or self reference")
        self.assertRejected([(member("tool/../../outside"), b"x")], "parent or self reference")

    def test_rejects_case_colliding_paths(self) -> None:
        self.assertRejected([(member("bin/Tool"), b"1"), (member("bin/tool"), b"2")], "differ only by capitalization")

    def test_rejects_more_entries_than_it_will_extract(self) -> None:
        members = [(member(f"f{index}"), b"x") for index in range(4)]
        self.assertRejected(members, "above the 3", limits=ArchiveLimits(max_entries=3))

    def test_rejects_something_that_is_not_a_tar_archive(self) -> None:
        archive = self.base / "fake.tar.gz"
        archive.write_bytes(os.urandom(512))
        with self.assertRaises(InstallError) as caught:
            extract_tar(archive, self.destination, 0)
        self.assertIn("not a valid tar archive", str(caught.exception))

    def test_a_truncated_archive_fails_cleanly(self) -> None:
        archive = build_tar(self.base, [(member("tool"), os.urandom(64 * 1024))], mode="w")
        archive.write_bytes(archive.read_bytes()[: 32 * 1024])
        with self.assertRaises(InstallError):
            extract_tar(archive, self.destination, 0)

    @unittest.skipIf(os.name == "nt", "Windows has no execute permission to carry")
    def test_execute_permission_is_kept_but_never_setuid(self) -> None:
        self.extract([
            (member("bin/tool", mode=0o4755), b"\x7fELF"),
            (member("share/data.bin", mode=0o666), b"data"),
        ])
        tool = (self.destination / "bin" / "tool").stat().st_mode
        self.assertTrue(tool & stat.S_IXUSR)
        self.assertFalse(tool & (stat.S_ISUID | stat.S_ISGID))
        data = (self.destination / "share" / "data.bin").stat().st_mode
        self.assertFalse(data & stat.S_IXUSR)
        self.assertFalse(data & stat.S_IWOTH, "an archive does not get to make a file world-writable")


def fake_usage(free: int):
    """Stand in for shutil.disk_usage so space behaviour is deterministic."""
    usage = namedtuple("usage", "total used free")
    return mock.patch("dfpm.archive.shutil.disk_usage", return_value=usage(free * 2, free, free))


class FreeSpaceTests(unittest.TestCase):
    """Free space is what decides whether extraction hurts, so it is what dfpm measures."""

    def extract(self, entries, *, limits: ArchiveLimits | None = None, expected_size: int | None = None):
        base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        archive = build(base, entries)
        destination = base / "out"
        destination.mkdir()
        return extract_zip(archive, destination, 0, limits or ArchiveLimits(), expected_size)

    def test_refuses_when_the_volume_has_no_room(self) -> None:
        limits = ArchiveLimits(free_space_margin=1024)
        with fake_usage(free=2048), self.assertRaises(InstallError) as caught:
            self.extract([("bin/tool.bin", b"x" * 8192)], limits=limits)
        message = str(caught.exception)
        self.assertIn("free", message)
        self.assertIn("in reserve", message)

    def test_extracts_when_the_volume_has_room(self) -> None:
        limits = ArchiveLimits(free_space_margin=1024)
        with fake_usage(free=10 * 1024**2):
            files = self.extract([("bin/tool.bin", b"x" * 8192)], limits=limits)
        self.assertEqual(files[0]["size"], 8192)

    def test_stops_when_the_recorded_sizes_understate_the_archive(self) -> None:
        # Passes the up-front check on the strength of a small declared size,
        # then runs past the room actually available while being written.
        limits = ArchiveLimits(free_space_margin=1024)
        with fake_usage(free=1024 + 128), self.assertRaises(InstallError) as caught:
            self.extract([("bin/tool.bin", b"x" * 8192)], limits=limits, expected_size=64)
        self.assertIn("understate", str(caught.exception))

    def test_a_pinned_size_is_preferred_over_the_archives_own_claim(self) -> None:
        # 8 KiB of content fits the volume, but the manifest says the install is
        # far larger, and the manifest is the reviewed figure.
        limits = ArchiveLimits(free_space_margin=0)
        with fake_usage(free=64 * 1024), self.assertRaises(InstallError) as caught:
            self.extract([("bin/tool.bin", b"x" * 8192)], limits=limits, expected_size=1024**3)
        self.assertIn("Extracting needs", str(caught.exception))

    def test_an_unmeasurable_volume_falls_back_to_the_declared_size(self) -> None:
        with mock.patch("dfpm.archive.shutil.disk_usage", side_effect=OSError("no such device")):
            files = self.extract([("bin/tool.bin", b"x" * 8192)])
        self.assertEqual(files[0]["size"], 8192)


class PathLengthTests(unittest.TestCase):
    """Windows gives up past 260 characters, part-way through, with an opaque error."""

    def test_a_path_beyond_the_limit_is_refused_and_named(self) -> None:
        files = [{"path": "rules/sigma/builtin/security/a_very_long_detection_rule_name.yml", "size": 1}]
        with self.assertRaises(InstallError) as caught:
            check_path_lengths(
                Path(r"C:\Users\an-analyst\AppData\Local\dfpm\tools\hayabusa\4.0.0"),
                files,
                ArchiveLimits(max_path_length=80),
                system="nt",
            )
        message = str(caught.exception)
        self.assertIn("characters long", message)
        self.assertIn("a_very_long_detection_rule_name.yml", message)

    def test_a_path_inside_the_limit_is_allowed(self) -> None:
        files = [{"path": "yara64.exe", "size": 1}]
        check_path_lengths(Path(r"C:\dfpm\tools\yara\4.5.5"), files, system="nt")

    def test_the_limit_does_not_apply_off_windows(self) -> None:
        files = [{"path": "nested/" * 40 + "leaf.txt", "size": 1}]
        check_path_lengths(Path("/home/analyst/.local/share/dfpm/tools/example/1.0.0"), files, system="posix")

    def test_the_longest_path_decides_even_when_it_is_not_first(self) -> None:
        files = [
            {"path": "a.txt", "size": 1},
            {"path": "deeply/nested/directory/tree/holding/one/long/name.txt", "size": 1},
            {"path": "b.txt", "size": 1},
        ]
        with self.assertRaises(InstallError) as caught:
            check_path_lengths(Path(r"C:\dfpm\tools\example\1.0.0"), files, ArchiveLimits(max_path_length=60), system="nt")
        self.assertIn("name.txt", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

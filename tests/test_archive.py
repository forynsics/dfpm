from __future__ import annotations

import os
import stat
import tempfile
import unittest
import warnings
import zipfile
from collections.abc import Iterable
from pathlib import Path

from dfpm.archive import ArchiveLimits, extract_zip
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
        base = Path(self.enterContext(tempfile.TemporaryDirectory()))
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
        self.assertEqual(len(files[0]["sha256"]), 64)

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
        self.assertRejected([("bin/tool.cmd", "first"), ("bin/tool.cmd", "second")], "duplicate path")

    def test_rejects_case_colliding_paths(self) -> None:
        self.assertRejected([("bin/Tool.cmd", "first"), ("bin/tool.cmd", "second")], "collide on Windows")

    def test_rejects_path_used_as_file_and_directory(self) -> None:
        self.assertRejected([("bin/tool/", ""), ("bin/tool", "data")], "both a file and a directory")

    def test_rejects_symbolic_link(self) -> None:
        self.assertRejected([(entry("bin/link", mode=stat.S_IFLNK | 0o777), "target")], "symbolic link")

    def test_rejects_special_file(self) -> None:
        self.assertRejected([(entry("bin/pipe", mode=stat.S_IFIFO | 0o644), "")], "special file")

    def test_rejects_encrypted_entry(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        archive = mark_encrypted(build(base, [("bin/tool.cmd", "data")]))
        destination = base / "out"
        destination.mkdir()
        with self.assertRaises(InstallError) as caught:
            extract_zip(archive, destination, 0)
        self.assertIn("encrypted entry", str(caught.exception))

    def test_rejects_too_many_entries(self) -> None:
        entries = [(f"bin/tool{index}.cmd", "data") for index in range(4)]
        self.assertRejected(entries, "above the limit of 3", limits=ArchiveLimits(max_entries=3))

    def test_rejects_archive_above_total_size_limit(self) -> None:
        self.assertRejected([("bin/tool.cmd", "x" * 4096)], "extraction limit", limits=ArchiveLimits(max_total_size=1024))

    def test_rejects_zip_bomb_expansion_ratio(self) -> None:
        limits = ArchiveLimits(max_expansion_ratio=4, ratio_exemption=1024)
        self.assertRejected([("bin/bomb.bin", "\0" * 200000)], "expands more than 4 times", limits=limits)

    def test_accepts_incompressible_data_within_ratio(self) -> None:
        limits = ArchiveLimits(max_expansion_ratio=4, ratio_exemption=1024)
        files = self.extract([("bin/tool.bin", os.urandom(4096))], limits=limits)
        self.assertEqual(files[0]["size"], 4096)

    def test_rejects_archive_with_nothing_left_after_stripping(self) -> None:
        self.assertRejected([("readme.txt", "notes")], "did not contain any installable files", strip=1)


if __name__ == "__main__":
    unittest.main()

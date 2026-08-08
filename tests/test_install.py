from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from dfpm import platforms
from dfpm.doctor import inspect
from dfpm.errors import InstallError, VerificationError
from dfpm.installer import install
from dfpm.inventory import read_package
from dfpm.manifest import Manifest
from dfpm.storage import Storage
from tests.helpers import create_package


class InstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")

    def install_version(self, version: str = "1.0.0", **kwargs) -> Path:
        _, manifest_path = create_package(self.base, version=version, **kwargs)
        return install(Manifest.load(manifest_path), self.storage)

    def test_install_tracks_files_and_writes_a_shim(self) -> None:
        destination = self.install_version()
        self.assertEqual((destination / "data" / "readme.txt").read_text(encoding="utf-8"), "Synthetic dfpm test package\n")
        self.assertTrue((self.storage.bin / "example-tool.cmd").is_file())

        state = read_package(self.storage, "example.tool")
        self.assertEqual(state["version"], "1.0.0")
        self.assertEqual(len(state["files"]), 2)
        self.assertEqual(inspect(self.storage)[0].status, "passing")

    def test_installing_a_newer_version_replaces_the_old_one(self) -> None:
        old = self.install_version("1.0.0")
        new = self.install_version("1.1.0")

        self.assertFalse(old.exists(), "the superseded version is removed from disk")
        self.assertTrue(new.is_dir())
        self.assertEqual(read_package(self.storage, "example.tool")["version"], "1.1.0")
        self.assertIn("1.1.0", (self.storage.bin / "example-tool.cmd").read_text(encoding="utf-8"))
        self.assertEqual(sorted(path.name for path in (self.storage.tools / "example.tool").iterdir()), ["1.1.0"])

    def test_installing_an_older_version_replaces_the_newer_one(self) -> None:
        self.install_version("1.1.0")
        self.install_version("1.0.0")
        self.assertEqual(read_package(self.storage, "example.tool")["version"], "1.0.0")
        self.assertEqual(sorted(path.name for path in (self.storage.tools / "example.tool").iterdir()), ["1.0.0"])

    def test_reinstalling_the_same_version_is_refused(self) -> None:
        self.install_version("1.0.0")
        with self.assertRaises(InstallError) as caught:
            self.install_version("1.0.0")
        self.assertIn("already installed", str(caught.exception))

    def test_a_stale_shim_is_removed_when_a_command_disappears(self) -> None:
        self.install_version("1.0.0", commands=("alpha", "beta"))
        self.assertTrue((self.storage.bin / "beta.cmd").is_file())
        self.install_version("1.1.0", commands=("alpha",))
        self.assertFalse((self.storage.bin / "beta.cmd").exists())

    def test_wrong_digest_never_creates_an_install_directory(self) -> None:
        _, manifest_path = create_package(self.base)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["artifact"]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(VerificationError):
            install(Manifest.load(manifest_path), self.storage)
        self.assertFalse(self.storage.package_version("example.tool", "1.0.0").exists())

    def test_a_failed_install_leaves_the_previous_version_in_place(self) -> None:
        self.install_version("1.0.0")
        self.storage.initialize()
        (self.storage.bin / "example-tool.cmd").unlink()
        (self.storage.bin / "example-tool.cmd").write_bytes(b"@echo not managed by dfpm\r\n")

        with self.assertRaises(InstallError):
            self.install_version("1.1.0")
        self.assertEqual(read_package(self.storage, "example.tool")["version"], "1.0.0")
        self.assertTrue(self.storage.package_version("example.tool", "1.0.0").is_dir())
        self.assertFalse(self.storage.package_version("example.tool", "1.1.0").exists())

    def test_archive_path_traversal_is_rejected(self) -> None:
        catalog, manifest_path = create_package(self.base)
        archive = catalog / "artifacts" / "example.tool-1.0.0.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("../outside.txt", "unsafe")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = archive.read_bytes()
        data["artifact"]["sha256"] = hashlib.sha256(payload).hexdigest()
        data["artifact"]["size"] = len(payload)
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(InstallError):
            install(Manifest.load(manifest_path), self.storage)
        self.assertFalse((self.base / "outside.txt").exists())

    def test_refuses_a_package_built_for_another_platform(self) -> None:
        system, architecture = platforms.current()
        _, manifest_path = create_package(self.base)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["platform"] = {"os": "linux" if system != "linux" else "windows", "arch": architecture}
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(InstallError) as caught:
            install(Manifest.load(manifest_path), self.storage)
        self.assertIn("this machine is", str(caught.exception))
        self.assertFalse(self.storage.package_version("example.tool", "1.0.0").exists())

    def test_records_platform_and_project_for_provenance(self) -> None:
        system, architecture = platforms.current()
        _, manifest_path = create_package(self.base)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["platform"] = {"os": system, "arch": architecture}
        data["project"] = {"source": "https://example.org/tool", "license": "BSD-3-Clause"}
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        install(Manifest.load(manifest_path), self.storage)

        state = read_package(self.storage, "example.tool")
        self.assertEqual(state["platform"], {"os": system, "arch": architecture})
        self.assertEqual(state["project"], {"source": "https://example.org/tool", "license": "BSD-3-Clause"})

    def test_install_refuses_to_replace_an_unmanaged_command(self) -> None:
        self.storage.initialize()
        (self.storage.bin / "example-tool.cmd").write_bytes(b"@echo not managed by dfpm\r\n")
        with self.assertRaises(InstallError):
            self.install_version("1.0.0")
        self.assertEqual((self.storage.bin / "example-tool.cmd").read_bytes(), b"@echo not managed by dfpm\r\n")
        self.assertIsNone(read_package(self.storage, "example.tool"))
        self.assertFalse(self.storage.package_version("example.tool", "1.0.0").exists())

    def test_install_refuses_a_command_name_another_package_owns(self) -> None:
        self.install_version("1.0.0", commands=("shared",))
        _, other = create_package(self.base, package_id="other.tool", version="2.0.0", commands=("shared",))
        with self.assertRaises(InstallError):
            install(Manifest.load(other), self.storage)
        self.assertIsNone(read_package(self.storage, "other.tool"))
        self.assertFalse(self.storage.package_version("other.tool", "2.0.0").exists())
        self.assertIn("example.tool", (self.storage.bin / "shared.cmd").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

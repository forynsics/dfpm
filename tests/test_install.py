from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from dfpm.doctor import inspect
from dfpm.errors import InstallError, VerificationError
from dfpm.installer import install
from dfpm.inventory import export_lock, read_package
from dfpm.manifest import Manifest
from dfpm.storage import Storage
from tests.helpers import create_package


class InstallTests(unittest.TestCase):
    def test_install_tracks_files_writes_shim_and_exports_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            _, manifest_path = create_package(base)
            storage = Storage(base / "dfpm-data")
            destination = install(Manifest.load(manifest_path), storage)

            self.assertEqual((destination / "data" / "readme.txt").read_text(encoding="utf-8"), "Synthetic DFPM test package\n")
            self.assertTrue((storage.bin / "example-tool.cmd").is_file())
            state = read_package(storage, "example.tool")
            self.assertIsNotNone(state)
            self.assertEqual(state["active_version"], "1.0.0")
            self.assertEqual(len(state["versions"]["1.0.0"]["files"]), 2)
            self.assertEqual(inspect(storage)[0].status, "passing")

            lock_path = base / "environment.lock.json"
            lock = export_lock(storage, lock_path)
            self.assertEqual(lock["reproducibility"], "hermetic")
            self.assertEqual(lock["packages"][0]["id"], "example.tool")
            self.assertTrue(lock_path.is_file())

    def test_doctor_detects_modified_managed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            _, manifest_path = create_package(base)
            storage = Storage(base / "dfpm-data")
            destination = install(Manifest.load(manifest_path), storage)
            (destination / "data" / "readme.txt").write_text("changed\n", encoding="utf-8")
            findings = inspect(storage)
            self.assertTrue(any(item.status == "failed" and "Modified managed file" in item.detail for item in findings))

    def test_wrong_digest_never_creates_install_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            _, manifest_path = create_package(base)
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["artifact"]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(data), encoding="utf-8")
            storage = Storage(base / "dfpm-data")
            with self.assertRaises(VerificationError):
                install(Manifest.load(manifest_path), storage)
            self.assertFalse(storage.package_version("example.tool", "1.0.0").exists())

    def test_archive_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            catalog, manifest_path = create_package(base)
            archive = catalog / "artifacts" / "example.tool-1.0.0.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../outside.txt", "unsafe")
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifact_bytes = archive.read_bytes()
            data["artifact"]["sha256"] = hashlib.sha256(artifact_bytes).hexdigest()
            data["artifact"]["size"] = len(artifact_bytes)
            manifest_path.write_text(json.dumps(data), encoding="utf-8")
            storage = Storage(base / "dfpm-data")
            with self.assertRaises(InstallError):
                install(Manifest.load(manifest_path), storage)
            self.assertFalse((base / "outside.txt").exists())

    def test_duplicate_install_does_not_overwrite_existing_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            _, manifest_path = create_package(base)
            storage = Storage(base / "dfpm-data")
            manifest = Manifest.load(manifest_path)
            install(manifest, storage)
            with self.assertRaises(InstallError):
                install(manifest, storage)


if __name__ == "__main__":
    unittest.main()


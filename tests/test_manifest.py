from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dfpm.errors import ManifestError
from dfpm.manifest import Manifest
from tests.helpers import create_package


class ManifestTests(unittest.TestCase):
    def test_loads_valid_manifest_and_resolves_local_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog, manifest_path = create_package(Path(temporary))
            manifest = Manifest.load(manifest_path)
            self.assertEqual(manifest.id, "example.tool")
            self.assertEqual(Path(manifest.artifact_source()), catalog / "artifacts" / "example.tool-1.0.0.zip")

    def test_rejects_parent_path_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, manifest_path = create_package(Path(temporary))
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["install"]["entrypoints"][0]["path"] = "../outside.exe"
            manifest_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ManifestError):
                Manifest.load(manifest_path)

    def test_rejects_unknown_install_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, manifest_path = create_package(Path(temporary))
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["install"]["strategy"] = "run-anything"
            manifest_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ManifestError):
                Manifest.load(manifest_path)


if __name__ == "__main__":
    unittest.main()


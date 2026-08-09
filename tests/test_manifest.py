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
            self.assertEqual(Path(manifest.package_url()), catalog / "artifacts" / "example.tool-1.0.0.zip")

    def test_rejects_parent_path_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, manifest_path = create_package(Path(temporary))
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["builds"][0]["install"]["entrypoints"][0]["path"] = "../outside.exe"
            manifest_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ManifestError):
                Manifest.load(manifest_path)

    def test_rejects_version_that_would_escape_the_tools_directory(self) -> None:
        for version in ("../../evil", "..", "1.0.0/extra", "nul"):
            with self.subTest(version=version):
                self.assertRaisesManifestError({"version": version})

    def test_rejects_entrypoint_name_that_would_escape_the_bin_directory(self) -> None:
        for name in ("../../evil", "sub/tool", "con", "my tool"):
            with self.subTest(name=name):
                self.assertRaisesManifestError({"install": {"entrypoints": [{"name": name, "path": "bin/example-tool.cmd"}]}})

    # Fields that describe one build rather than the tool as a whole.
    BUILD_FIELDS = frozenset({"version", "platform", "package", "install", "verify", "requires"})

    def assertRaisesManifestError(self, changes: dict) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, manifest_path = create_package(Path(temporary))
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for key, value in changes.items():
                target = data["builds"][0] if key in self.BUILD_FIELDS else data
                if isinstance(value, dict):
                    target.setdefault(key, {}).update(value)
                else:
                    target[key] = value
            manifest_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ManifestError):
                Manifest.load(manifest_path)

    def test_rejects_unsupported_platform_values(self) -> None:
        for platform in ({"os": "solaris", "arch": "x64"}, {"os": "windows", "arch": "sparc"}):
            with self.subTest(platform=platform):
                self.assertRaisesManifestError({"platform": platform})

    def test_rejects_project_links_that_are_not_https(self) -> None:
        for project in ({"repository": "http://example.org/tool"}, {"homepage": "ftp://example.org/tool"}):
            with self.subTest(project=project):
                self.assertRaisesManifestError({"project": project})

    def test_reads_platform_and_project_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, manifest_path = create_package(Path(temporary))
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["builds"][0]["platform"] = {"os": "Windows", "arch": "X64"}
            data["project"] = {"source": "https://example.org/tool", "license": "BSD-3-Clause"}
            manifest_path.write_text(json.dumps(data), encoding="utf-8")

            manifest = Manifest.load(manifest_path)
            self.assertEqual(str(manifest.platform), "windows/x64")
            self.assertEqual(manifest.project.license, "BSD-3-Clause")
            self.assertIsNone(manifest.project.homepage)

    def test_platform_and_project_stay_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, manifest_path = create_package(Path(temporary))
            manifest = Manifest.load(manifest_path)
            self.assertIsNone(manifest.platform)
            self.assertIsNone(manifest.project)

    def test_rejects_unknown_install_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, manifest_path = create_package(Path(temporary))
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["builds"][0]["install"]["strategy"] = "run-anything"
            manifest_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ManifestError):
                Manifest.load(manifest_path)


if __name__ == "__main__":
    unittest.main()


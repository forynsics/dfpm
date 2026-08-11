from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dfpm.catalog import select
from dfpm.errors import InstallError, ManifestError
from dfpm.installer import install
from dfpm.manifest import Manifest, Tool
from dfpm.storage import Storage

PAYLOAD = b"MZ" + b"\x00" * 4094
PUBLISHED = "tool-v1.0.0-windows-amd64.exe"


class ArtifactFixture(unittest.TestCase):
    """Some projects publish an archive; some publish the binary itself."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.storage = Storage(self.base / "root")
        self.payload = self.base / PUBLISHED
        self.payload.write_bytes(PAYLOAD)

    def entry(self, **install_overrides) -> dict:
        install_block = {
            "strategy": "standalone-file",
            "strip_components": 0,
            "extracted_size": len(PAYLOAD),
            "entries": 1,
            "entrypoints": [{"name": "demo", "path": PUBLISHED}],
        }
        install_block.update(install_overrides)
        return {
            "schema_version": 1,
            "id": "standalone.demo",
            "name": "Standalone Demo",
            "kind": "tool",
            "description": "A tool published as a bare executable.",
            "builds": [{
                "version": "1.0.0",
                "package": {
                    "url": str(self.payload),
                    "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
                    "size": len(PAYLOAD),
                },
                "install": install_block,
            }],
        }

    def write(self, entry: dict) -> Path:
        path = self.base / "demo.json"
        path.write_text(json.dumps(entry), encoding="utf-8")
        return path


class StandaloneFileTests(ArtifactFixture):
    def test_the_downloaded_file_becomes_the_package(self) -> None:
        destination = install(Manifest.load(self.write(self.entry())), self.storage)
        self.assertEqual((destination / PUBLISHED).read_bytes(), PAYLOAD)

    def test_it_keeps_the_name_the_project_published_it_under(self) -> None:
        # An archive names its own contents. Here dfpm would be choosing, and a
        # renamed file cannot be matched against the release it came from
        # without going through dfpm's records to find out what it used to be.
        destination = install(Manifest.load(self.write(self.entry())), self.storage)
        installed = {path.name for path in destination.iterdir() if path.name != ".dfpm-install.json"}
        self.assertEqual(installed, {PUBLISHED})

    def test_a_manifest_cannot_quietly_rename_the_file(self) -> None:
        entry = self.entry(entrypoints=[{"name": "demo", "path": "velociraptor.exe"}])
        with self.assertRaises(ManifestError) as caught:
            Tool.load(self.write(entry))
        self.assertIn(PUBLISHED, str(caught.exception))

    def test_a_command_is_published_for_it(self) -> None:
        install(Manifest.load(self.write(self.entry())), self.storage)
        self.assertTrue((self.storage.bin / "demo.cmd").is_file())

    def test_more_than_one_entrypoint_is_refused(self) -> None:
        # One file cannot be two commands, and a manifest saying so describes
        # something this strategy could never produce.
        entry = self.entry(entrypoints=[
            {"name": "demo", "path": PUBLISHED},
            {"name": "other", "path": "other.exe"},
        ])
        with self.assertRaises(ManifestError) as caught:
            Tool.load(self.write(entry))
        self.assertIn("exactly one entrypoint", str(caught.exception))

    def test_stripping_components_is_refused(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            Tool.load(self.write(self.entry(strip_components=1)))
        self.assertIn("nothing to strip", str(caught.exception))

    def test_a_nested_destination_is_refused(self) -> None:
        entry = self.entry(entrypoints=[{"name": "demo", "path": "bin/demo.exe"}])
        with self.assertRaises(ManifestError) as caught:
            Tool.load(self.write(entry))
        self.assertIn("cannot be nested", str(caught.exception))


class UnsupportedArtifactTests(ArtifactFixture):
    """What a project publishes and what this dfpm can install are two things."""

    def tool_with(self, *builds: tuple[str, str, str]) -> Tool:
        """Build a tool from (strategy, os, version) triples."""
        entry = self.entry()
        template = entry["builds"][0]
        entry["builds"] = []
        for strategy, system, version in builds:
            build = json.loads(json.dumps(template))
            build["install"]["strategy"] = strategy
            build["platform"] = {"os": system, "arch": "x64"}
            build["version"] = version
            entry["builds"].append(build)
        return Tool.load(self.write(entry))

    def test_an_entry_survives_a_build_this_version_cannot_install(self) -> None:
        # Refusing it would take the whole entry down, and with it every other
        # entry in the catalog, since they are loaded together.
        tool = self.tool_with(("standalone-file", "windows", "1.0.0"), ("portable-tar", "linux", "1.0.0"))
        self.assertEqual([build.installable for build in tool.builds], [True, False])

    def test_a_newer_build_in_an_unreadable_format_does_not_hide_an_older_usable_one(self) -> None:
        # Newest-wins runs after the filter, not before it, or a project
        # switching release format would make its whole history unreachable.
        tool = self.tool_with(("standalone-file", "windows", "1.0.0"), ("portable-tar", "windows", "2.0.0"))
        chosen = select([tool], "standalone.demo", platform="windows/x64")
        self.assertEqual((chosen.strategy, chosen.version), ("standalone-file", "1.0.0"))

    def test_a_platform_served_only_by_an_unreadable_format_says_so(self) -> None:
        tool = self.tool_with(("portable-tar", "windows", "1.0.0"))
        with self.assertRaises(ManifestError) as caught:
            select([tool], "standalone.demo", platform="windows/x64")
        message = str(caught.exception)
        self.assertIn("portable-tar", message)
        self.assertIn("cannot install", message)

    def test_installing_one_directly_is_still_refused(self) -> None:
        # Selection normally keeps these away, but nothing stops a caller
        # holding one, and materializing an unknown artifact is not a guess
        # worth making.
        entry = self.entry()
        entry["builds"][0]["install"]["strategy"] = "portable-tar"
        manifest = Manifest.load(self.write(entry))
        with self.assertRaises(InstallError) as caught:
            install(manifest, self.storage)
        self.assertIn("cannot install", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

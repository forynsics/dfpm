from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class InstalledWheelLifecycleTests(unittest.TestCase):
    """Prove a wheel works without importing anything from its checkout."""

    @unittest.skipUnless(os.name == "nt", "dfpm's install-and-run lifecycle currently targets Windows")
    def test_clean_wheel_lifecycle_with_both_artifact_strategies(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        source = base / "source"
        wheels = base / "wheels"
        clean_environment = base / "clean-environment"
        working_directory = base / "unrelated-working-directory"
        root = base / "dfpm-data"
        catalog = base / "fixture-catalog"

        self._copy_build_sources(source)
        wheels.mkdir()
        working_directory.mkdir()
        self._build_wheel(source, wheels)
        wheel = self._only_wheel(wheels)
        self._install_into_clean_environment(clean_environment, wheel)
        dfpm = clean_environment / "Scripts" / "dfpm.exe"
        self.assertTrue(dfpm.is_file())

        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("DFPM_CATALOG", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

        def run(*arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
            completed = subprocess.run(
                [str(dfpm), *arguments],
                cwd=working_directory,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                expected,
                f"dfpm {' '.join(arguments)} failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )
            return completed

        # With neither a catalog flag nor environment variable, these commands
        # can succeed only if the wheel contains the reviewed entries and its
        # collection subdirectory. Running elsewhere and clearing PYTHONPATH
        # prevents the checkout from quietly satisfying either import.
        paths = run("--root", str(root), "paths").stdout
        self.assertIn(str(clean_environment), paths)
        self.assertNotIn(str(PROJECT / "src"), paths)
        shipped = json.loads(run("--root", str(root), "catalog", "--json").stdout)
        self.assertGreater(len(shipped["packages"]), 0)
        self.assertIn("yara", {item["id"] for item in shipped["packages"]})
        self.assertIn("yara", run("--root", str(root), "search", "yara").stdout.lower())
        self.assertIn("@ez-tools", run("--root", str(root), "collection").stdout)

        self._write_fixture_catalog(catalog)

        def fixture(*arguments: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
            return run(
                "--root",
                str(root),
                "--catalog",
                str(catalog),
                *arguments,
                expected=expected,
            )

        found = json.loads(fixture("search", "synthetic", "--json").stdout)
        self.assertEqual(
            {item["id"] for item in found["packages"]},
            {"fixture.archive", "fixture.standalone"},
        )
        self.assertIn("@fixture-set", fixture("collection").stdout)

        installed = fixture("install", "@fixture-set", "--yes")
        self.assertIn("Installed 2 of 2 packages", installed.stdout)
        package_list = json.loads(fixture("list", "--json").stdout)
        self.assertEqual(
            {item["id"] for item in package_list},
            {"fixture.archive", "fixture.standalone"},
        )

        self.assertIn("archive:hello", fixture("run", "archive-demo", "hello").stdout)
        self.assertIn("standalone:hello", fixture("run", "standalone-demo", "hello").stdout)
        resolution = json.loads(fixture("which", "standalone-demo", "--json").stdout)
        self.assertEqual(resolution["package"], "fixture.standalone")
        self.assertTrue(resolution["target"].endswith("standalone-demo.cmd"))

        findings = json.loads(fixture("doctor", "--json").stdout)
        self.assertEqual({item["status"] for item in findings}, {"passing"})
        self.assertEqual(
            {item["package"] for item in findings},
            {"fixture.archive", "fixture.standalone"},
        )

        removed = fixture("uninstall", "--all", "--yes")
        self.assertIn("Removed fixture.archive 1.0.0", removed.stdout)
        self.assertIn("Removed fixture.standalone 1.0.0", removed.stdout)
        self.assertEqual(json.loads(fixture("list", "--json").stdout), [])
        self.assertFalse((root / "tools" / "fixture.archive").exists())
        self.assertFalse((root / "tools" / "fixture.standalone").exists())

    def _copy_build_sources(self, destination: Path) -> None:
        destination.mkdir()
        for name in ("pyproject.toml", "build_backend.py", "README.md", "LICENSE", "NOTICE"):
            shutil.copy2(PROJECT / name, destination / name)
        shutil.copytree(PROJECT / "src", destination / "src")
        shutil.copytree(PROJECT / "catalog", destination / "catalog")

    def _build_wheel(self, source: Path, wheels: Path) -> None:
        self._run_setup(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                ".",
                "--no-build-isolation",
                "--no-deps",
                "--wheel-dir",
                str(wheels),
            ],
            cwd=source,
        )

    def _install_into_clean_environment(self, environment: Path, wheel: Path) -> None:
        self._run_setup([sys.executable, "-m", "venv", "--without-pip", str(environment)])
        clean_python = environment / "Scripts" / "python.exe"
        self._run_setup(
            [
                sys.executable,
                "-m",
                "pip",
                "--python",
                str(clean_python),
                "install",
                "--no-deps",
                "--no-index",
                str(wheel),
            ]
        )

    def _run_setup(self, command: list[str], cwd: Path | None = None) -> None:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        completed = subprocess.run(
            command,
            cwd=cwd or PROJECT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"setup command failed: {command}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )

    def _only_wheel(self, directory: Path) -> Path:
        wheels = list(directory.glob("dfpm-*.whl"))
        self.assertEqual(len(wheels), 1, f"expected one dfpm wheel, found: {wheels}")
        return wheels[0]

    def _write_fixture_catalog(self, catalog: Path) -> None:
        artifacts = catalog / "artifacts"
        collections = catalog / "collections"
        artifacts.mkdir(parents=True)
        collections.mkdir()

        archive_command = b"@echo off\r\n@echo archive:%*\r\n"
        readme = b"Harmless wheel lifecycle fixture.\n"
        archive = artifacts / "archive-fixture.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("fixture/bin/archive-demo.cmd", archive_command)
            output.writestr("fixture/data/readme.txt", readme)
        self._write_manifest(
            catalog / "fixture.archive.json",
            package_id="fixture.archive",
            name="Archive Fixture",
            artifact=archive,
            strategy="portable-zip",
            entrypoint_name="archive-demo",
            entrypoint_path="bin/archive-demo.cmd",
            install_extra={
                "strip_components": 1,
                "extracted_size": len(archive_command) + len(readme),
                "entries": 2,
            },
            verify=[{"type": "file", "path": "data/readme.txt"}],
        )

        standalone = artifacts / "standalone-demo.cmd"
        standalone.write_bytes(b"@echo off\r\n@echo standalone:%*\r\n")
        self._write_manifest(
            catalog / "fixture.standalone.json",
            package_id="fixture.standalone",
            name="Standalone Fixture",
            artifact=standalone,
            strategy="standalone-file",
            entrypoint_name="standalone-demo",
            entrypoint_path=standalone.name,
            install_extra={
                "strip_components": 0,
                "extracted_size": standalone.stat().st_size,
                "entries": 1,
            },
            verify=[],
        )

        collection = {
            "schema_version": 1,
            "id": "fixture-set",
            "name": "Wheel lifecycle fixtures",
            "description": "Both harmless package formats used by the clean-wheel acceptance test.",
            "packages": ["fixture.archive", "fixture.standalone"],
        }
        (collections / "fixture-set.json").write_text(
            json.dumps(collection, indent=2) + "\n", encoding="utf-8"
        )

    def _write_manifest(
        self,
        path: Path,
        *,
        package_id: str,
        name: str,
        artifact: Path,
        strategy: str,
        entrypoint_name: str,
        entrypoint_path: str,
        install_extra: dict[str, int],
        verify: list[dict[str, str]],
    ) -> None:
        payload = artifact.read_bytes()
        manifest = {
            "schema_version": 1,
            "id": package_id,
            "name": name,
            "kind": "tool",
            "description": "A synthetic harmless fixture for installed-wheel verification.",
            "builds": [
                {
                    "version": "1.0.0",
                    "package": {
                        "url": f"artifacts/{artifact.name}",
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "size": len(payload),
                    },
                    "install": {
                        "strategy": strategy,
                        "entrypoints": [{"name": entrypoint_name, "path": entrypoint_path}],
                        **install_extra,
                    },
                    "verify": verify,
                }
            ],
        }
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

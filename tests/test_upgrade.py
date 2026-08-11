from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from dfpm.cli import main
from dfpm.inventory import read_package
from dfpm.storage import Storage
from tests.helpers import create_package


class UpgradeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.root = self.base / "root"
        self.storage = Storage(self.root)
        self.catalog, _ = create_package(self.base, package_id="alpha", version="1.0.0", commands=("alpha",))
        create_package(self.base, package_id="beta", version="1.0.0", commands=("beta",))

    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(["--root", str(self.root), "--catalog", str(self.catalog), *arguments])
        return code, output.getvalue(), errors.getvalue()

    def install(self, *packages: str) -> None:
        code, _, errors = self.run_cli("install", *packages, "--yes")
        self.assertEqual(code, 0, errors)

    def installed_version(self, package_id: str) -> str | None:
        record = read_package(self.storage, package_id)
        return record.get("version") if record else None

    def publish(self, package_id: str, version: str) -> Path:
        _, manifest = create_package(self.base, package_id=package_id, version=version, commands=(package_id,))
        return manifest

    def test_outdated_reports_only_packages_with_a_newer_version(self) -> None:
        self.install("alpha", "beta")
        self.publish("alpha", "1.1.0")

        code, output, errors = self.run_cli("outdated")

        self.assertEqual(code, 0, errors)
        self.assertIn("PACKAGE", output)
        self.assertIn("alpha", output)
        self.assertIn("1.0.0", output)
        self.assertIn("1.1.0", output)
        self.assertNotIn("beta", output)

    def test_outdated_json_has_installed_and_available_versions(self) -> None:
        self.install("alpha", "beta")
        self.publish("alpha", "1.1.0")

        code, output, errors = self.run_cli("outdated", "--json")

        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output), [{
            "available_version": "1.1.0",
            "id": "alpha",
            "installed_version": "1.0.0",
            "name": "Example Tool",
        }])

    def test_outdated_distinguishes_no_installs_from_no_updates(self) -> None:
        code, output, _ = self.run_cli("outdated")
        self.assertEqual(code, 0)
        self.assertIn("No packages are installed", output)

        self.install("alpha")
        code, output, _ = self.run_cli("outdated")
        self.assertEqual(code, 0)
        self.assertIn("up to date", output)

    def test_upgrade_replaces_a_named_installed_package(self) -> None:
        self.install("alpha")
        self.publish("alpha", "1.1.0")

        code, output, errors = self.run_cli("upgrade", "alpha", "--yes")

        self.assertEqual(code, 0, errors)
        self.assertIn("Replaces:    1.0.0", output)
        self.assertEqual(self.installed_version("alpha"), "1.1.0")

    def test_upgrade_all_changes_only_packages_with_updates(self) -> None:
        self.install("alpha", "beta")
        self.publish("alpha", "1.1.0")

        code, _, errors = self.run_cli("upgrade", "--all", "--yes")

        self.assertEqual(code, 0, errors)
        self.assertEqual(self.installed_version("alpha"), "1.1.0")
        self.assertEqual(self.installed_version("beta"), "1.0.0")

    def test_a_package_that_is_not_installed_blocks_the_whole_request(self) -> None:
        self.install("alpha")
        self.publish("alpha", "1.1.0")

        code, _, errors = self.run_cli("upgrade", "alpha", "beta", "--yes")

        self.assertEqual(code, 1)
        self.assertIn("beta", errors)
        self.assertIn("not installed", errors)
        self.assertIn("No changes were made", errors)
        self.assertEqual(self.installed_version("alpha"), "1.0.0")

    def test_upgrade_never_downgrades_to_an_older_catalog_version(self) -> None:
        self.publish("alpha", "2.0.0")
        self.install("alpha")
        self.publish("alpha", "1.0.0")

        code, output, errors = self.run_cli("upgrade", "alpha", "--yes")

        self.assertEqual(code, 0, errors)
        self.assertIn("already the newest version available", output)
        self.assertEqual(self.installed_version("alpha"), "2.0.0")

    def test_upgrade_requires_exactly_one_selection_mode(self) -> None:
        code, _, errors = self.run_cli("upgrade")
        self.assertEqual(code, 1)
        self.assertIn("or pass --all", errors)

        code, _, errors = self.run_cli("upgrade", "alpha", "--all")
        self.assertEqual(code, 1)
        self.assertIn("not both", errors)

    def test_bulk_upgrade_discloses_and_exhibits_partial_success(self) -> None:
        self.install("alpha", "beta")
        self.publish("alpha", "1.1.0")
        beta_manifest = self.publish("beta", "1.1.0")
        data = json.loads(beta_manifest.read_text(encoding="utf-8"))
        data["builds"][0]["package"]["sha256"] = "0" * 64
        beta_manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        code, output, errors = self.run_cli("upgrade", "--all", "--yes")

        self.assertEqual(code, 1)
        self.assertIn("packages are installed independently", output)
        self.assertIn("does not roll back", output)
        self.assertIn("Installed 1 of 2 packages", output)
        self.assertIn("beta", errors)
        self.assertEqual(self.installed_version("alpha"), "1.1.0")
        self.assertEqual(self.installed_version("beta"), "1.0.0")


if __name__ == "__main__":
    unittest.main()

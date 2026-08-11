from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("update_catalog", REPOSITORY / "scripts" / "update-catalog.py")
assert SPEC and SPEC.loader
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


class CatalogUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.catalog = self.base / "catalog"
        self.catalog.mkdir()
        shutil.copyfile(REPOSITORY / "catalog" / "yara.json", self.catalog / "yara.json")
        self.policy = updater.load_policy(REPOSITORY / "catalog" / "update-policies" / "yara.json")

    def release(self, version: str, name: str) -> dict:
        return {
            "tag_name": f"v{version}",
            "html_url": f"https://github.example/releases/v{version}",
            "assets": [{"name": name, "browser_download_url": f"https://github.example/{name}"}],
        }

    def rolling_policy(self, *, version_path: str = "MFTECmd.exe", etag: str = '"old"') -> dict:
        return {
            "schema_version": 1,
            "id": "mftecmd",
            "provider": "rolling-url",
            "package_version": {"source": "pe-file-version", "asset": 0, "path": version_path},
            "assets": [
                {
                    "name": "MFTECmd.zip",
                    "url": "https://publisher.example/MFTECmd.zip",
                    "etag": etag,
                    "platform": {"os": "windows", "arch": "x64"},
                }
            ],
        }

    def versioned_zip(self, version: tuple[int, int, int, int], *, executable: str = "MFTECmd.exe") -> Path:
        artifact = self.base / f"{executable}.zip"
        major, minor, patch, revision = version
        resource = updater.VERSION_SIGNATURE + b"\0" * 4 + struct.pack(
            "<II", (major << 16) | minor, (patch << 16) | revision
        )
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr(executable, b"MZ" + resource)
            archive.writestr("MFTECmd.runtimeconfig.json", b"{}")
            archive.writestr("MFTECmd.deps.json", b"{}")
        return artifact

    def test_a_current_release_changes_nothing(self) -> None:
        with mock.patch.object(
            updater,
            "latest_applicable_release",
            return_value=self.release("4.5.5", "yara-4.5.5-2500-win64.zip"),
        ):
            report = updater.update_one(self.catalog, self.policy, apply=True)
        self.assertEqual(report["status"], "current")
        self.assertEqual(report["release_tag"], "v4.5.5")
        self.assertEqual(report["assets"], [{"name": "yara-4.5.5-2500-win64.zip"}])
        self.assertEqual(json.loads((self.catalog / "yara.json").read_text())["builds"][0]["version"], "4.5.5")

    def test_a_matching_release_refreshes_only_mechanical_build_facts(self) -> None:
        artifact = self.base / "release.zip"
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr("yara64.exe", b"new yara")
            archive.writestr("yarac64.exe", b"new yarac")

        def provide(_url: str, target: Path) -> tuple[str, int]:
            shutil.copyfile(artifact, target)
            return "a" * 64, artifact.stat().st_size

        release = self.release("4.6.0", "yara-4.6.0-2500-win64.zip")
        with mock.patch.object(updater, "latest_applicable_release", return_value=release), mock.patch.object(
            updater, "download", side_effect=provide
        ):
            report = updater.update_one(self.catalog, self.policy, apply=True)

        written = json.loads((self.catalog / "yara.json").read_text())
        build = written["builds"][0]
        self.assertEqual(report["status"], "updated")
        self.assertEqual(build["version"], "4.6.0")
        self.assertEqual(build["package"]["sha256"], "a" * 64)
        self.assertEqual(build["install"]["entries"], 2)
        self.assertEqual(written["description"], "Scan files and memory for rules describing textual or binary patterns.")

    def test_a_changed_layout_is_not_guessed_at(self) -> None:
        artifact = self.base / "release.zip"
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr("renamed.exe", b"new yara")

        def provide(_url: str, target: Path) -> tuple[str, int]:
            shutil.copyfile(artifact, target)
            return "b" * 64, artifact.stat().st_size

        release = self.release("4.6.0", "yara-4.6.0-2500-win64.zip")
        with mock.patch.object(updater, "latest_applicable_release", return_value=release), mock.patch.object(
            updater, "download", side_effect=provide
        ), self.assertRaises(SystemExit) as caught:
            updater.update_one(self.catalog, self.policy, apply=True)
        self.assertIn("Expected installed path disappeared", str(caught.exception))

    def test_package_version_can_come_from_an_asset_name(self) -> None:
        policy = updater.load_policy(REPOSITORY / "catalog" / "update-policies" / "memprocfs.json")
        release = {
            "tag_name": "v5.18",
            "assets": [{"name": "MemProcFS_files_and_binaries_v5.18.3-win_x64-20260808.zip"}],
        }
        assets = updater.select_assets(policy, release, "5.18")
        self.assertEqual(updater.package_version(policy, release, assets), "5.18.3")

    def test_prereleases_need_both_opt_in_and_a_matching_tag(self) -> None:
        releases = [
            {
                "tag_name": "v3.0-nightly",
                "prerelease": True,
                "assets": [{"name": "tool-3.0-nightly.zip"}],
            },
            {
                "tag_name": "v3.0-rc1",
                "prerelease": True,
                "assets": [{"name": "tool-3.0-rc1.zip"}],
            },
        ]
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        policy = {
            "id": "tool",
            "repository": "owner/tool",
            "tag_prefix": "v",
            "include_prereleases": True,
            "prerelease_tag_pattern": "v*-rc*",
            "assets": [{"name": "tool-{release_version}.zip"}],
        }
        with mock.patch.object(updater.urllib.request, "urlopen", return_value=response), mock.patch.object(
            updater.json, "load", return_value=releases
        ):
            selected = updater.latest_applicable_release(policy)
        self.assertEqual(selected["tag_name"], "v3.0-rc1")
        self.assertEqual(selected["_dfpm_observation"]["checked"][0]["reason"], "prerelease-tag-mismatch")

    def test_failed_discovery_has_structured_observation_evidence(self) -> None:
        policies = self.base / "policies"
        policies.mkdir()
        shutil.copyfile(REPOSITORY / "catalog" / "update-policies" / "yara.json", policies / "yara.json")
        evidence = self.base / "evidence.json"
        error = updater.UpdatePolicyError(
            "yara",
            "release-discovery",
            "no usable release",
            checked=[{"tag": "v5.0", "reason": "asset-policy-mismatch"}],
        )
        with mock.patch.object(updater, "update_one", side_effect=error), contextlib.redirect_stdout(io.StringIO()):
            result = updater.main(
                ["--catalog", str(self.catalog), "--policies", str(policies), "--evidence", str(evidence)]
            )
        report = json.loads(evidence.read_text(encoding="utf-8"))["packages"][0]
        self.assertEqual(result, 1)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failure"]["stage"], "release-discovery")
        self.assertEqual(report["failure"]["checked"][0]["tag"], "v5.0")

    def test_failed_apply_restores_an_earlier_manifest_change(self) -> None:
        policies = self.base / "policies"
        policies.mkdir()
        first = dict(self.policy)
        second = dict(self.policy, id="yara-second")
        (policies / "a.json").write_text(json.dumps(first), encoding="utf-8")
        (policies / "b.json").write_text(json.dumps(second), encoding="utf-8")
        original = (self.catalog / "yara.json").read_bytes()

        def attempt(_catalog: Path, policy: dict, *, apply: bool) -> dict:
            self.assertTrue(apply)
            if policy["id"] == "yara":
                (self.catalog / "yara.json").write_text("temporarily changed", encoding="utf-8")
                return {"id": "yara", "status": "updated"}
            raise updater.UpdatePolicyError("yara-second", "asset-selection", "ambiguous assets")

        with mock.patch.object(updater, "update_one", side_effect=attempt), contextlib.redirect_stdout(io.StringIO()):
            result = updater.main(
                ["--catalog", str(self.catalog), "--policies", str(policies), "--apply"]
            )
        self.assertEqual(result, 1)
        self.assertEqual((self.catalog / "yara.json").read_bytes(), original)

    def test_partial_mode_keeps_successes_and_reports_failures(self) -> None:
        policies = self.base / "policies"
        policies.mkdir()
        (policies / "a.json").write_text(json.dumps(self.policy), encoding="utf-8")
        (policies / "b.json").write_text(json.dumps(dict(self.policy, id="broken")), encoding="utf-8")
        evidence = self.base / "evidence.json"

        def attempt(_catalog: Path, policy: dict, *, apply: bool) -> dict:
            if policy["id"] == "broken":
                raise updater.UpdatePolicyError("broken", "release-discovery", "publisher unavailable")
            manifest_path = self.catalog / "yara.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["description"] = "valid independent update"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            return {"id": "yara", "status": "updated"}

        with mock.patch.object(updater, "update_one", side_effect=attempt), contextlib.redirect_stdout(io.StringIO()):
            result = updater.main(
                [
                    "--catalog",
                    str(self.catalog),
                    "--policies",
                    str(policies),
                    "--apply",
                    "--continue-on-policy-error",
                    "--evidence",
                    str(evidence),
                ]
            )
        reports = json.loads(evidence.read_text(encoding="utf-8"))["packages"]
        self.assertEqual(result, 0)
        self.assertEqual(json.loads((self.catalog / "yara.json").read_text())["description"], "valid independent update")
        self.assertTrue((self.catalog / "index.json").exists())
        self.assertEqual([item["status"] for item in reports], ["updated", "failed"])

    def test_every_github_release_download_has_an_update_policy(self) -> None:
        policies = {path.stem for path in (REPOSITORY / "catalog" / "update-policies").glob("*.json")}
        missing = []
        for path in (REPOSITORY / "catalog").glob("*.json"):
            if path.name == "index.json":
                continue
            manifest = json.loads(path.read_text(encoding="utf-8"))
            urls = [build["package"]["url"] for build in manifest["builds"]]
            if any("github.com/" in url and "/releases/download/" in url for url in urls):
                if manifest["id"] not in policies:
                    missing.append(manifest["id"])
        self.assertEqual(missing, [], f"GitHub release packages without update policies: {missing}")

    def test_every_catalog_entry_has_an_update_policy(self) -> None:
        policies = {path.stem for path in (REPOSITORY / "catalog" / "update-policies").glob("*.json")}
        entries = {
            path.stem
            for path in (REPOSITORY / "catalog").glob("*.json")
            if path.name != "index.json"
        }
        self.assertEqual(entries - policies, set(), f"Catalog entries without update policies: {sorted(entries - policies)}")
        self.assertEqual(policies - entries, set(), f"Update policies without catalog entries: {sorted(policies - entries)}")

    def test_rolling_url_uses_etag_digest_pe_version_and_layout(self) -> None:
        shutil.copyfile(REPOSITORY / "catalog" / "mftecmd.json", self.catalog / "mftecmd.json")
        policy_path = self.base / "mftecmd-policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "mftecmd",
                    "provider": "rolling-url",
                    "package_version": {"source": "pe-file-version", "asset": 0, "path": "MFTECmd.exe"},
                    "assets": [
                        {
                            "name": "MFTECmd.zip",
                            "url": "https://publisher.example/MFTECmd.zip",
                            "platform": {"os": "windows", "arch": "x64"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        policy = updater.load_policy(policy_path)
        artifact = self.base / "release.zip"
        high = (2026 << 16) | 6
        low = 1 << 16
        version_resource = updater.VERSION_SIGNATURE + b"\0" * 4 + struct.pack("<II", high, low)
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr("MFTECmd.exe", b"MZ" + version_resource)
            archive.writestr("MFTECmd.runtimeconfig.json", b"{}")
            archive.writestr("MFTECmd.deps.json", b"{}")

        def provide(_url: str, target: Path) -> tuple[str, int]:
            shutil.copyfile(artifact, target)
            return "c" * 64, artifact.stat().st_size

        with mock.patch.object(updater, "rolling_metadata", return_value={"etag": '"new"'}), mock.patch.object(
            updater, "download", side_effect=provide
        ):
            report = updater.update_one(self.catalog, policy, apply=True, policy_path=policy_path)

        manifest = json.loads((self.catalog / "mftecmd.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "updated")
        self.assertEqual(manifest["builds"][0]["version"], "2026.6.1.0")
        self.assertEqual(manifest["builds"][0]["package"]["sha256"], "c" * 64)
        self.assertEqual(json.loads(policy_path.read_text(encoding="utf-8"))["assets"][0]["etag"], '"new"')

    def test_rolling_url_skips_download_when_etag_is_unchanged(self) -> None:
        policy = {
            "schema_version": 1,
            "id": "mftecmd",
            "provider": "rolling-url",
            "package_version": {"source": "pe-file-version", "asset": 0, "path": "MFTECmd.exe"},
            "assets": [
                {
                    "name": "MFTECmd.zip",
                    "url": "https://publisher.example/MFTECmd.zip",
                    "etag": '"same"',
                    "platform": {"os": "windows", "arch": "x64"},
                }
            ],
        }
        shutil.copyfile(REPOSITORY / "catalog" / "mftecmd.json", self.catalog / "mftecmd.json")
        with mock.patch.object(updater, "rolling_metadata", return_value={"etag": '"same"'}), mock.patch.object(
            updater, "download"
        ) as download:
            report = updater.update_one(self.catalog, policy, apply=False)
        self.assertEqual(report["status"], "current")
        download.assert_not_called()

    def test_changed_etag_with_same_digest_only_advances_cursor(self) -> None:
        shutil.copyfile(REPOSITORY / "catalog" / "mftecmd.json", self.catalog / "mftecmd.json")
        manifest_before = (self.catalog / "mftecmd.json").read_bytes()
        policy_path = self.base / "policy.json"
        policy = self.rolling_policy()
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        digest = json.loads(manifest_before)["builds"][0]["package"]["sha256"]

        with mock.patch.object(updater, "rolling_metadata", return_value={"etag": '"new"'}), mock.patch.object(
            updater, "download", return_value=(digest, 123)
        ):
            report = updater.update_one(self.catalog, policy, apply=True, policy_path=policy_path)
        self.assertEqual(report["status"], "current")
        self.assertTrue(report["state_updated"])
        self.assertEqual((self.catalog / "mftecmd.json").read_bytes(), manifest_before)
        self.assertEqual(json.loads(policy_path.read_text())["assets"][0]["etag"], '"new"')

    def test_republished_same_version_refreshes_digest_and_layout_facts(self) -> None:
        shutil.copyfile(REPOSITORY / "catalog" / "mftecmd.json", self.catalog / "mftecmd.json")
        policy_path = self.base / "policy.json"
        policy = self.rolling_policy()
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        artifact = self.versioned_zip((2026, 5, 0, 0))

        def provide(_url: str, target: Path) -> tuple[str, int]:
            shutil.copyfile(artifact, target)
            return "d" * 64, artifact.stat().st_size

        with mock.patch.object(updater, "rolling_metadata", return_value={"etag": '"new"'}), mock.patch.object(
            updater, "download", side_effect=provide
        ):
            report = updater.update_one(self.catalog, policy, apply=True, policy_path=policy_path)
        build = json.loads((self.catalog / "mftecmd.json").read_text())["builds"][0]
        self.assertEqual(report["status"], "updated")
        self.assertEqual(build["version"], "2026.5.0.0")
        self.assertEqual(build["package"]["sha256"], "d" * 64)
        self.assertEqual(build["install"]["entries"], 3)

    def test_rolling_version_rollback_is_rejected(self) -> None:
        shutil.copyfile(REPOSITORY / "catalog" / "mftecmd.json", self.catalog / "mftecmd.json")
        artifact = self.versioned_zip((2025, 12, 0, 0))
        policy = self.rolling_policy()

        def provide(_url: str, target: Path) -> tuple[str, int]:
            shutil.copyfile(artifact, target)
            return "e" * 64, artifact.stat().st_size

        with mock.patch.object(updater, "rolling_metadata", return_value={"etag": '"new"'}), mock.patch.object(
            updater, "download", side_effect=provide
        ), self.assertRaises(updater.UpdatePolicyError) as caught:
            updater.update_one(self.catalog, policy, apply=False)
        self.assertEqual(caught.exception.stage, "version")

    def test_corrupt_rolling_zip_has_structured_failure(self) -> None:
        shutil.copyfile(REPOSITORY / "catalog" / "mftecmd.json", self.catalog / "mftecmd.json")

        def provide(_url: str, target: Path) -> tuple[str, int]:
            target.write_bytes(b"not a zip")
            return "f" * 64, target.stat().st_size

        with mock.patch.object(updater, "rolling_metadata", return_value={"etag": '"new"'}), mock.patch.object(
            updater, "download", side_effect=provide
        ), self.assertRaises(updater.UpdatePolicyError) as caught:
            updater.update_one(self.catalog, self.rolling_policy(), apply=False)
        self.assertEqual(caught.exception.stage, "artifact-inspection")
        self.assertIn("valid ZIP", str(caught.exception))

    def test_missing_established_entrypoint_is_rejected(self) -> None:
        shutil.copyfile(REPOSITORY / "catalog" / "mftecmd.json", self.catalog / "mftecmd.json")
        artifact = self.versioned_zip((2026, 6, 0, 0), executable="Helper.exe")

        def provide(_url: str, target: Path) -> tuple[str, int]:
            shutil.copyfile(artifact, target)
            return "1" * 64, artifact.stat().st_size

        with mock.patch.object(updater, "rolling_metadata", return_value={"etag": '"new"'}), mock.patch.object(
            updater, "download", side_effect=provide
        ), self.assertRaises(updater.UpdatePolicyError) as caught:
            updater.update_one(self.catalog, self.rolling_policy(version_path="Helper.exe"), apply=False)
        self.assertEqual(caught.exception.stage, "layout-validation")
        self.assertIn("MFTECmd.exe", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

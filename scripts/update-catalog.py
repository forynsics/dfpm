#!/usr/bin/env python
"""Update policy-enabled catalog entries from publisher releases.

Policies live outside the shipped catalog under catalog/update-policies. An
update is mechanical only when the publisher, asset name and installed layout
still match the policy established when the package was admitted.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from dfpm.archive import ArchiveLimits, extract_zip
from dfpm.catalog import build_index, version_key
from dfpm.errors import DfpmError
from dfpm.manifest import STANDALONE_FILE, Tool

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"
POLICIES = CATALOG / "update-policies"
USER_AGENT = "dfpm-catalog-updater/1"
VERSION_SIGNATURE = b"\xbd\x04\xef\xfe"


def write_json(path: Path, document: object) -> None:
    """Write a JSON document with LF endings whatever platform this runs on.

    The index records a digest of each catalog file's bytes, so line endings
    are part of what is hashed. Text mode on Windows would translate every
    newline to CRLF, producing an entry that hashes differently from the LF
    copy the repository stores and that nobody else can reproduce.
    """
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")


class UpdatePolicyError(SystemExit):
    """A policy stopped safely, with structured evidence for its operator."""

    def __init__(self, package_id: str, stage: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.package_id = package_id
        self.stage = stage
        self.details = details


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--policies", type=Path, default=POLICIES)
    parser.add_argument("--package", action="append", default=[], help="Only check this package id; repeatable.")
    parser.add_argument("--apply", action="store_true", help="Write policy-conforming updates and regenerate the index.")
    parser.add_argument(
        "--continue-on-policy-error",
        action="store_true",
        help="Keep valid package updates when another policy fails; intended for unattended maintenance.",
    )
    parser.add_argument("--evidence", type=Path, help="Write a JSON report of checks and proposed changes.")
    args = parser.parse_args(argv)

    wanted = set(args.package)
    reports = []
    changed = False
    originals = {path: path.read_bytes() for path in args.catalog.rglob("*.json")} if args.apply else {}
    for path in sorted(args.policies.glob("*.json")):
        try:
            policy = load_policy(path)
        except (OSError, json.JSONDecodeError, SystemExit) as error:
            reports.append(
                {
                    "id": path.stem,
                    "status": "failed",
                    "failure": {"stage": "policy-validation", "message": str(error), "policy": str(path)},
                }
            )
            continue
        if wanted and policy["id"] not in wanted:
            continue
        try:
            options = {"apply": args.apply}
            if policy["provider"] == "rolling-url":
                options["policy_path"] = path
            report = update_one(args.catalog, policy, **options)
        except UpdatePolicyError as error:
            report = {
                "id": error.package_id,
                "status": "failed",
                "failure": {"stage": error.stage, "message": str(error), **error.details},
            }
        except SystemExit as error:
            report = {
                "id": policy["id"],
                "status": "failed",
                "failure": {"stage": "validation", "message": str(error)},
            }
        except (OSError, json.JSONDecodeError) as error:
            report = {
                "id": policy["id"],
                "status": "failed",
                "failure": {"stage": "local-catalog", "message": str(error)},
            }
        except DfpmError as error:
            report = {
                "id": policy["id"],
                "status": "failed",
                "failure": {"stage": "artifact-inspection", "message": str(error)},
            }
        reports.append(report)
        changed |= report["status"] == "updated"

    if wanted - {item["id"] for item in reports}:
        missing = ", ".join(sorted(wanted - {item["id"] for item in reports}))
        raise SystemExit(f"No update policy for: {missing}")
    failed = any(report["status"] == "failed" for report in reports)
    if args.apply and failed and not args.continue_on_policy_error:
        for path, content in originals.items():
            path.write_bytes(content)
        for report in reports:
            if report["status"] == "updated":
                report["status"] = "available"
                report["not_applied"] = "another policy failed"
    if args.apply and changed and (not failed or args.continue_on_policy_error):
        write_json(args.catalog / "index.json", build_index(args.catalog))
    document = {"schema_version": 1, "packages": reports}
    rendered = json.dumps(document, indent=2) + "\n"
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.evidence, document)
    print(rendered, end="")
    return 1 if failed and not args.continue_on_policy_error else 0


def load_policy(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "id", "provider", "assets"}
    if not isinstance(data, dict) or not required <= set(data):
        raise SystemExit(f"{path} is missing required update-policy fields")
    if data["schema_version"] != 1 or data["provider"] not in {"github-releases", "rolling-url"}:
        raise SystemExit(f"{path} uses an unsupported update policy")
    if data["provider"] == "github-releases" and not data.get("repository"):
        raise SystemExit(f"{path}: GitHub release policies need a repository")
    if not isinstance(data["assets"], list) or not data["assets"]:
        raise SystemExit(f"{path} must name at least one release asset")
    if "include_prereleases" in data and not isinstance(data["include_prereleases"], bool):
        raise SystemExit(f"{path}: include_prereleases must be true or false")
    if data.get("include_prereleases") and not data.get("prerelease_tag_pattern"):
        raise SystemExit(f"{path}: prerelease_tag_pattern is required when prereleases are enabled")
    version = data.get("package_version", {"source": "release-tag"})
    if not isinstance(version, dict):
        raise SystemExit(f"{path}: package_version must be an object")
    if version.get("source") not in {"release-tag", "asset-name", "pe-file-version"}:
        raise SystemExit(f"{path}: unsupported package_version source")
    if version.get("source") == "asset-name":
        if not isinstance(version.get("asset"), int) or version["asset"] < 0 or not version.get("regex"):
            raise SystemExit(f"{path}: asset-name package versions need an asset index and regex")
        try:
            expression = re.compile(version["regex"])
        except re.error as error:
            raise SystemExit(f"{path}: invalid package_version regex: {error}") from error
        if "version" not in expression.groupindex:
            raise SystemExit(f"{path}: package_version regex needs a named 'version' group")
    if data["provider"] == "rolling-url":
        version_path = Path(version.get("path", ""))
        if (
            version.get("source") != "pe-file-version"
            or version.get("asset", 0) != 0
            or not version.get("path")
            or version_path.is_absolute()
            or ".." in version_path.parts
        ):
            raise SystemExit(f"{path}: rolling URLs need a PE file-version path")
        if len(data["assets"]) != 1:
            raise SystemExit(f"{path}: rolling URL policies currently support exactly one asset")
        for asset in data["assets"]:
            if not isinstance(asset, dict) or not asset.get("name") or not asset.get("url", "").startswith("https://"):
                raise SystemExit(f"{path}: rolling assets need a name and HTTPS URL")
            if "etag" in asset and not isinstance(asset["etag"], str):
                raise SystemExit(f"{path}: rolling asset ETags must be strings")
    return data


def update_one(catalog: Path, policy: dict, *, apply: bool, policy_path: Path | None = None) -> dict:
    if policy["provider"] == "rolling-url":
        return update_rolling_one(catalog, policy, apply=apply, policy_path=policy_path)
    manifest_path = catalog / f"{policy['id']}.json"
    current = json.loads(manifest_path.read_text(encoding="utf-8"))
    tool = Tool.load(manifest_path)
    release = latest_applicable_release(policy)
    tag_version = release_version(policy, release)
    selected_assets = select_assets(policy, release, tag_version)
    version = package_version(policy, release, selected_assets)
    current_version = max((build.version for build in tool.builds), key=version_key)
    report = {
        "id": policy["id"],
        "current": current_version,
        "discovered": version,
        "release_tag": release["tag_name"],
        "release": release["html_url"],
        "status": "current",
        "assets": [{"name": asset["name"]} for asset in selected_assets],
    }
    if observation := release.get("_dfpm_observation"):
        report["discovery"] = observation
    if version_key(version) <= version_key(current_version):
        return report

    builds = []
    with tempfile.TemporaryDirectory(prefix=f"dfpm-update-{policy['id']}-") as temporary:
        workspace = Path(temporary)
        for position, (asset_policy, asset) in enumerate(zip(policy["assets"], selected_assets, strict=True)):
            target = workspace / asset["name"]
            try:
                digest, size = download(asset["browser_download_url"], target)
            except (OSError, urllib.error.URLError) as error:
                raise UpdatePolicyError(
                    policy["id"],
                    "artifact-download",
                    f"Could not download {asset['name']}: {error}",
                    asset=asset["name"],
                    url=asset["browser_download_url"],
                ) from error
            previous = matching_build(current["builds"], asset_policy, position)
            build = refreshed_build(
                previous,
                target,
                asset["browser_download_url"],
                digest,
                size,
                current_version,
                version,
                policy["id"],
            )
            builds.append(build)
            report["assets"][position].update({"sha256": digest, "size": size})

    proposed = dict(current)
    proposed["builds"] = builds
    with tempfile.TemporaryDirectory(prefix="dfpm-policy-check-") as temporary:
        candidate = Path(temporary) / manifest_path.name
        write_json(candidate, proposed)
        Tool.load(candidate)
    report["status"] = "updated" if apply else "available"
    if apply:
        write_json(manifest_path, proposed)
    return report


def update_rolling_one(catalog: Path, policy: dict, *, apply: bool, policy_path: Path | None) -> dict:
    manifest_path = catalog / f"{policy['id']}.json"
    current = json.loads(manifest_path.read_text(encoding="utf-8"))
    Tool.load(manifest_path)
    current_version = max((build["version"] for build in current["builds"]), key=version_key)
    report = {
        "id": policy["id"],
        "current": current_version,
        "discovered": current_version,
        "status": "current",
        "provider": "rolling-url",
        "assets": [],
    }
    proposed_builds = json.loads(json.dumps(current["builds"]))
    manifest_changed = False
    policy_changed = False

    with tempfile.TemporaryDirectory(prefix=f"dfpm-update-{policy['id']}-") as temporary:
        workspace = Path(temporary)
        for position, asset_policy in enumerate(policy["assets"]):
            metadata = rolling_metadata(policy["id"], asset_policy["url"])
            asset_report = {"name": asset_policy["name"], **metadata}
            report["assets"].append(asset_report)
            if asset_policy.get("etag") == metadata["etag"]:
                continue

            target = workspace / asset_policy["name"]
            try:
                digest, size = download(asset_policy["url"], target)
            except (OSError, urllib.error.URLError) as error:
                raise UpdatePolicyError(
                    policy["id"],
                    "artifact-download",
                    f"Could not download {asset_policy['name']}: {error}",
                    asset=asset_policy["name"],
                    url=asset_policy["url"],
                ) from error
            previous = matching_build(current["builds"], asset_policy, position)
            asset_report.update({"sha256": digest, "size": size})
            asset_policy["etag"] = metadata["etag"]
            policy_changed = True
            if digest == previous["package"]["sha256"]:
                continue

            try:
                version = artifact_pe_version(policy, target, previous)
            except DfpmError as error:
                raise UpdatePolicyError(
                    policy["id"],
                    "artifact-inspection",
                    str(error),
                    asset=asset_policy["name"],
                ) from error
            if version_key(version) < version_key(previous["version"]):
                raise UpdatePolicyError(
                    policy["id"],
                    "version",
                    f"Rolling artifact version moved backwards from {previous['version']} to {version}",
                    old=previous["version"],
                    new=version,
                )
            try:
                refreshed = refreshed_build(
                    previous,
                    target,
                    asset_policy["url"],
                    digest,
                    size,
                    previous["version"],
                    version,
                    policy["id"],
                )
            except DfpmError as error:
                raise UpdatePolicyError(
                    policy["id"],
                    "artifact-inspection",
                    str(error),
                    asset=asset_policy["name"],
                ) from error
            proposed_builds[current["builds"].index(previous)] = refreshed
            manifest_changed = True
            report["discovered"] = version

    if manifest_changed:
        proposed = dict(current)
        proposed["builds"] = proposed_builds
        with tempfile.TemporaryDirectory(prefix="dfpm-policy-check-") as temporary:
            candidate = Path(temporary) / manifest_path.name
            write_json(candidate, proposed)
            Tool.load(candidate)
        report["status"] = "updated" if apply else "available"
        if apply:
            write_json(manifest_path, proposed)
    if apply and policy_changed:
        if policy_path is None:
            raise UpdatePolicyError(policy["id"], "policy-state", "Cannot persist rolling URL state without a policy path")
        write_json(policy_path, policy)
        report["state_updated"] = True
    return report


def rolling_metadata(package_id: str, url: str) -> dict:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
        with urllib.request.urlopen(request, timeout=60) as response:
            etag = response.headers.get("ETag")
            if not etag:
                raise ValueError("response did not contain an ETag")
            result = {"etag": etag}
            if value := response.headers.get("Last-Modified"):
                result["last_modified"] = value
            return result
    except (OSError, ValueError, urllib.error.URLError) as error:
        raise UpdatePolicyError(
            package_id,
            "release-discovery",
            f"Could not read rolling artifact metadata: {error}",
            url=url,
        ) from error


def artifact_pe_version(policy: dict, artifact: Path, previous: dict) -> str:
    rule = policy["package_version"]
    position = rule.get("asset", 0)
    if position >= len(policy["assets"]):
        raise UpdatePolicyError(policy["id"], "version", f"package_version asset index {position} does not exist")
    install = previous["install"]
    if install["strategy"] != "portable-zip":
        raise UpdatePolicyError(policy["id"], "version", "PE file-version discovery currently requires a ZIP artifact")
    with tempfile.TemporaryDirectory(prefix="dfpm-version-") as temporary:
        destination = Path(temporary)
        extract_zip(
            artifact,
            destination,
            install.get("strip_components", 0),
            ArchiveLimits(free_space_margin=0),
        )
        binary_path = destination / rule["path"]
        try:
            binary = binary_path.read_bytes()
        except OSError as error:
            raise UpdatePolicyError(
                policy["id"],
                "version",
                f"Could not read version file {rule['path']}: {error}",
                path=rule["path"],
            ) from error
    version = file_version(binary)
    if version is None:
        raise UpdatePolicyError(policy["id"], "version", f"No Windows file version in {rule['path']}", path=rule["path"])
    return version


def file_version(binary: bytes) -> str | None:
    found = binary.find(VERSION_SIGNATURE)
    if found < 0 or len(binary) < found + 16:
        return None
    high, low = struct.unpack("<II", binary[found + 8 : found + 16])
    return f"{high >> 16}.{high & 0xFFFF}.{low >> 16}.{low & 0xFFFF}"


def release_version(policy: dict, release: dict) -> str:
    return release.get("tag_name", "").removeprefix(policy.get("tag_prefix", "v"))


def asset_pattern(asset_policy: dict, tag_version: str) -> str:
    # ``version`` remains an alias for policies written before release and
    # artifact versions were distinguished.
    return asset_policy["name"].format(version=tag_version, release_version=tag_version)


def select_assets(policy: dict, release: dict, tag_version: str) -> list[dict]:
    by_name = {asset.get("name", ""): asset for asset in release.get("assets", [])}
    selected = []
    for asset_policy in policy["assets"]:
        pattern = asset_pattern(asset_policy, tag_version)
        matches = [asset for name, asset in by_name.items() if fnmatch.fnmatchcase(name, pattern)]
        if len(matches) != 1:
            raise UpdatePolicyError(
                policy["id"],
                "asset-selection",
                f"{release.get('tag_name', '<untagged>')}: {pattern!r} matched {len(matches)} release assets",
                pattern=pattern,
                matched=[asset.get("name", "") for asset in matches],
                available=sorted(by_name),
            )
        selected.append(matches[0])
    return selected


def package_version(policy: dict, release: dict, selected_assets: list[dict]) -> str:
    rule = policy.get("package_version", {"source": "release-tag"})
    if rule.get("source") == "release-tag":
        return release_version(policy, release)
    position = rule["asset"]
    if position >= len(selected_assets):
        raise UpdatePolicyError(policy["id"], "version", f"package_version asset index {position} does not exist")
    name = selected_assets[position]["name"]
    match = re.fullmatch(rule["regex"], name)
    if not match:
        raise UpdatePolicyError(
            policy["id"],
            "version",
            f"Cannot extract a package version from {name!r}",
            asset=name,
            regex=rule["regex"],
        )
    return match.group("version")


def latest_applicable_release(policy: dict) -> dict:
    """Newest release that actually publishes every asset this policy needs.

    Projects sometimes publish source-only tags after their last binary build.
    Those are not package updates and must not make an otherwise current policy
    fail every scheduled run.
    """
    url = f"https://api.github.com/repos/{policy['repository']}/releases?per_page=30"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
            releases = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise UpdatePolicyError(
            policy["id"],
            "release-discovery",
            f"Could not read GitHub releases: {error}",
            api_url=url,
        ) from error
    observations = []
    for release in releases:
        tag = release.get("tag_name", "")
        if release.get("draft"):
            observations.append({"tag": tag, "accepted": False, "reason": "draft"})
            continue
        if release.get("prerelease"):
            if not policy.get("include_prereleases"):
                observations.append({"tag": tag, "accepted": False, "reason": "prerelease-disabled"})
                continue
            pattern = policy["prerelease_tag_pattern"]
            if not fnmatch.fnmatchcase(tag, pattern):
                observations.append({"tag": tag, "accepted": False, "reason": "prerelease-tag-mismatch"})
                continue
        version = release_version(policy, release)
        names = [asset.get("name", "") for asset in release.get("assets", [])]
        patterns = [asset_pattern(item, version) for item in policy["assets"]]
        counts = [sum(fnmatch.fnmatchcase(name, pattern) for name in names) for pattern in patterns]
        if version and all(count == 1 for count in counts):
            accepted = dict(release)
            observations.append({"tag": tag, "accepted": True, "reason": "asset-policy-matched"})
            accepted["_dfpm_observation"] = {"checked": observations}
            return accepted
        observations.append(
            {
                "tag": tag,
                "accepted": False,
                "reason": "asset-policy-mismatch",
                "patterns": [{"pattern": pattern, "matches": count} for pattern, count in zip(patterns, counts, strict=True)],
                "available_assets": names,
            }
        )
    raise UpdatePolicyError(
        policy["id"],
        "release-discovery",
        f"{policy['id']}: no recent GitHub release matches its asset policy",
        checked=observations,
    )


def download(url: str, target: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=120) as response:
        with target.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                output.write(chunk)
    return digest.hexdigest(), size


def matching_build(builds: list[dict], policy: dict, position: int) -> dict:
    platform = policy.get("platform")
    matches = [build for build in builds if build.get("platform") == platform]
    if len(matches) == 1:
        return matches[0]
    if platform is None and len(builds) == 1:
        return builds[0]
    if position < len(builds):
        return builds[position]
    raise SystemExit("Update policy does not identify exactly one existing build")


def refreshed_build(
    previous: dict,
    artifact: Path,
    url: str,
    digest: str,
    size: int,
    old: str,
    new: str,
    package_id: str = "unknown",
) -> dict:
    build = json.loads(json.dumps(previous))
    build["version"] = new
    package = build["package"]
    package.update({"url": url, "sha256": digest, "size": size})
    install = build["install"]
    if install["strategy"] == STANDALONE_FILE:
        installed_name = artifact.name
        install["entries"] = 1
        install["extracted_size"] = size
        install["entrypoints"][0]["path"] = installed_name
        return build
    if install["strategy"] != "portable-zip":
        raise SystemExit(f"Automation cannot inspect {install['strategy']}")
    with tempfile.TemporaryDirectory(prefix="dfpm-update-extract-") as temporary:
        files = extract_zip(
            artifact,
            Path(temporary),
            install.get("strip_components", 0),
            ArchiveLimits(free_space_margin=0),
        )
    installed = {str(item["path"]) for item in files}
    install["entries"] = len(files)
    install["extracted_size"] = sum(int(item["size"]) for item in files)
    for section in (install.get("entrypoints", []), build.get("verify", [])):
        for item in section:
            item["path"] = item["path"].replace(old, new)
            if item["path"] not in installed:
                raise UpdatePolicyError(
                    package_id,
                    "layout-validation",
                    f"Expected installed path disappeared in {artifact.name}: {item['path']}",
                    artifact=artifact.name,
                    missing_path=item["path"],
                )
    return build


if __name__ == "__main__":
    raise SystemExit(main())

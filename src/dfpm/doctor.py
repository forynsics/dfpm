from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import cache as download_cache
from . import runtimes, shims, sync
from .errors import DfpmError
from .inventory import forget_package, list_packages
from .manifest import Requirement
from .storage import Storage, remove_tree

STALE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class Finding:
    package: str
    version: str
    status: str
    detail: str


@dataclass(frozen=True)
class Repair:
    kind: str
    target: Path
    detail: str
    package: str | None = None


def inspect(storage: Storage, package_id: str | None = None) -> list[Finding]:
    """Report on installed packages, optionally narrowing to one.

    Four outcomes, and the distinctions matter. `failed` means something dfpm is
    responsible for is broken. `blocked` means the package is installed
    correctly but the machine is missing something it needs to run — nothing
    dfpm did wrong, and nothing it can fix by reinstalling. `unverified` means
    the install itself worked and the bytes were never the reviewed ones, which
    is a fact about where the package came from rather than about its condition,
    and which no amount of re-checking the files on disk would reveal.
    """
    findings: list[Finding] = []
    seen = False
    cache: dict[str, Any] = {}
    for package in list_packages(storage):
        version = package.get("version")
        if not version or (package_id is not None and package["id"] != package_id):
            continue
        seen = True
        broken = _file_problems(storage, package) + _shim_problems(storage, package)
        blocked, satisfied = _requirement_status(storage, package, cache)
        unverified = _provenance_problems(package)
        findings.extend(Finding(package["id"], version, "failed", detail) for detail in broken)
        findings.extend(Finding(package["id"], version, "blocked", detail) for detail in blocked)
        findings.extend(Finding(package["id"], version, "unverified", detail) for detail in unverified)
        if not broken and not blocked and not unverified:
            detail = "Installed files and command shortcuts are in place"
            if satisfied:
                detail += f". Ready to run with {', '.join(satisfied)}"
            findings.append(Finding(package["id"], version, "passing", detail))
    if package_id is not None and not seen:
        raise DfpmError(f"{package_id} is not installed")
    if package_id is None:
        findings.extend(_maintenance_findings(storage))
    return findings


def _provenance_problems(package: dict[str, Any]) -> list[str]:
    """Say so when what was installed was never the artifact the catalog described.

    Only an install that was explicitly allowed through can be in this state, so
    this is not detection — it is making sure a decision taken once, possibly
    weeks ago, is still visible afterwards.
    """
    if package.get("digest_verified", True):
        return []
    installed = package.get("package_sha256", "unknown")
    reviewed = package.get("catalog_sha256", "unknown")
    return [
        f"Installed from an artifact the catalog did not describe. "
        f"Installed {installed}, catalog recorded {reviewed}."
    ]


def _requirement_status(storage: Storage, package: dict[str, Any], cache: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Check the runtimes this package needs, live rather than from a record."""
    blocked: list[str] = []
    satisfied: list[str] = []
    for item in package.get("requires", []):
        requirement = Requirement(item["runtime"], item.get("version"), item.get("flavor"))
        try:
            met, _, detail = runtimes.check(requirement, storage, cache=cache)
        except DfpmError as exc:
            blocked.append(str(exc))
            continue
        if met:
            satisfied.append(detail)
        else:
            blocked.append(f"{detail}. {runtimes.describe(requirement.runtime).remediation}")
    return blocked, satisfied


def _file_problems(storage: Storage, package: dict[str, Any]) -> list[str]:
    """Check that the package is still where it was put and can still run.

    Only the files the manifest names are checked, and only for existence. The
    rest of a package's directory belongs to the package: a tool that updates
    its own rule set or downloads data on first run is behaving normally, and
    reporting that as drift would bury a real problem under thousands of
    findings. Nothing here re-hashes anything, so the cost does not grow with
    the size of a package.
    """
    root = storage.package_version(package["id"], package["version"])
    if not root.is_dir():
        return [f"Install directory is missing: {root}"]
    problems: list[str] = []
    for entrypoint in package.get("entrypoints", []):
        if not (root / entrypoint["path"]).is_file():
            problems.append(f"Missing entrypoint: {entrypoint['path']}")
    for check in package.get("verify", []):
        if check["type"] == "file" and not (root / check["path"]).is_file():
            problems.append(f"Health check failed: {check['path']}")
    return problems


def _shim_problems(storage: Storage, package: dict[str, Any]) -> list[str]:
    """Check the command shortcuts this package is entitled to own."""
    problems: list[str] = []
    try:
        expected = shims.planned(storage)
    except DfpmError as exc:
        return [f"Command shortcuts cannot be planned: {exc}"]
    for entrypoint in package.get("entrypoints", []):
        path = storage.bin / f"{entrypoint['name']}.cmd"
        if not path.is_file():
            problems.append(f"Missing command shortcut: {path.name}")
        elif not shims.owned(path):
            problems.append(f"Command shortcut was replaced by an unmanaged file: {path.name}")
        elif not shims.current(path, expected[entrypoint["name"]]):
            problems.append(f"Command shortcut is stale: {path.name}")
    return problems


def repair_plan(storage: Storage) -> list[Repair]:
    """Plan only repairs whose targets and intended state dfpm can prove."""
    actions: list[Repair] = []
    packages = list_packages(storage)
    forgotten = []
    for package in packages:
        version = package.get("version")
        if version and not storage.package_version(package["id"], version).is_dir():
            actions.append(
                Repair(
                    "forget-missing-package",
                    storage.package_state(package["id"]),
                    f"Remove the installed-state record for missing {package['id']} {version}",
                    package["id"],
                )
            )
            forgotten.append(package["id"])

    try:
        expected = shims.planned(storage)
    except DfpmError:
        expected = {}
    shim_changes = []
    for shim in expected.values():
        if shim.package in forgotten:
            continue
        path = storage.bin / f"{shim.name}.cmd"
        if not path.exists():
            shim_changes.append(f"recreate {path.name}")
        elif shims.owned(path) and not shims.current(path, shim):
            shim_changes.append(f"refresh {path.name}")
    if storage.bin.is_dir() and shims.state_records_readable(storage):
        for path in sorted(storage.bin.glob("*.cmd")):
            if path.stem not in expected and shims.owned(path):
                shim_changes.append(f"remove stale {path.name}")
    if shim_changes or forgotten:
        detail = "; ".join(shim_changes) if shim_changes else "Remove shortcuts left by missing installations"
        actions.append(Repair("reconcile-shims", storage.bin, detail))

    for path in _install_staging(storage):
        actions.append(Repair("remove-staging", path, f"Remove abandoned install staging directory {path.name}"))
    for path in sync.staging_directories(storage.catalog):
        if _stale(path):
            actions.append(Repair("remove-sync-staging", path, f"Remove abandoned catalog staging directory {path.name}"))

    backup = sync.backup_directory(storage.catalog)
    if backup.is_dir() and not storage.catalog.exists() and _catalog_valid(backup):
        actions.append(Repair("restore-catalog", backup, "Restore the previous catalog after an interrupted publish"))
    elif backup.is_dir() and _catalog_valid(storage.catalog):
        actions.append(Repair("remove-catalog-backup", backup, "Remove the previous catalog snapshot left after publication"))

    survey = download_cache.survey(storage, storage.catalog if storage.catalog.exists() else None)
    for path in survey.partials:
        if _stale(path):
            actions.append(Repair("remove-partial-download", path, f"Remove interrupted download {path.name}"))
    for entry, problem in download_cache.verify(storage, storage.catalog if storage.catalog.exists() else None):
        if problem is not None:
            actions.append(Repair("quarantine-cache", entry.path, f"Quarantine corrupt cached artifact {entry.digest}"))
    return actions


def apply_repairs(storage: Storage, actions: list[Repair]) -> list[Repair]:
    """Apply a previously displayed repair plan, rechecking ownership at each boundary."""
    applied: list[Repair] = []
    forgot_package = False
    for action in actions:
        if action.kind == "forget-missing-package":
            if action.package is None or action.target != storage.package_state(action.package):
                raise DfpmError(f"Refusing an invalid state repair target: {action.target}")
            record = next((item for item in list_packages(storage) if item["id"] == action.package), None)
            if record and record.get("version") and not storage.package_version(action.package, record["version"]).exists():
                forget_package(storage, action.package)
                forgot_package = True
        elif action.kind == "reconcile-shims":
            shims.repair(storage)
        elif action.kind == "remove-staging":
            _remove_owned_tree(action.target, storage.root / "staging")
        elif action.kind == "remove-sync-staging":
            if action.target not in sync.staging_directories(storage.catalog):
                raise DfpmError(f"Refusing an invalid catalog staging target: {action.target}")
            if _stale(action.target) and not remove_tree(action.target):
                raise DfpmError(f"Could not remove {action.target}")
        elif action.kind == "restore-catalog":
            backup = sync.backup_directory(storage.catalog)
            if action.target != backup or storage.catalog.exists() or not backup.is_dir():
                raise DfpmError("The interrupted catalog state changed; run doctor again.")
            try:
                os.replace(backup, storage.catalog)
            except OSError as exc:
                raise DfpmError(f"Could not restore {backup}: {exc}") from exc
        elif action.kind == "remove-catalog-backup":
            backup = sync.backup_directory(storage.catalog)
            if action.target != backup or not _catalog_valid(storage.catalog) or not remove_tree(backup):
                raise DfpmError(f"Could not safely remove catalog backup {backup}")
        elif action.kind == "remove-partial-download":
            if action.target.parent != storage.cache or not action.target.name.endswith(".partial") or not _stale(action.target):
                raise DfpmError(f"Refusing an invalid partial-download target: {action.target}")
            action.target.unlink(missing_ok=True)
        elif action.kind == "quarantine-cache":
            if action.target.parent != storage.cache or not download_cache.DIGEST_NAME.fullmatch(action.target.name):
                raise DfpmError(f"Refusing an invalid cache repair target: {action.target}")
            quarantine = storage.root / "quarantine" / "cache"
            try:
                if download_cache.file_digest(action.target) == action.target.name:
                    continue
            except OSError as exc:
                raise DfpmError(f"Could not recheck {action.target}: {exc}") from exc
            quarantine.mkdir(parents=True, exist_ok=True)
            destination = quarantine / f"{action.target.name}.corrupt"
            suffix = 1
            while destination.exists():
                destination = quarantine / f"{action.target.name}.corrupt.{suffix}"
                suffix += 1
            try:
                os.replace(action.target, destination)
            except OSError as exc:
                raise DfpmError(f"Could not quarantine {action.target}: {exc}") from exc
        else:
            raise DfpmError(f"Unknown doctor repair action: {action.kind}")
        applied.append(action)
    if forgot_package and not any(action.kind == "reconcile-shims" for action in actions):
        shims.repair(storage)
    return applied


def _maintenance_findings(storage: Storage) -> list[Finding]:
    findings: list[Finding] = []
    package_dir = storage.state / "packages"
    if package_dir.is_dir():
        for path in sorted(package_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
                    raise ValueError("record is not an object with a package id")
            except (OSError, ValueError) as exc:
                findings.append(Finding(path.stem, "-", "failed", f"Installed-state record is unreadable: {path}: {exc}"))

    recorded = {(item["id"], item.get("version")) for item in list_packages(storage)}
    if storage.tools.is_dir():
        for package_path in sorted(path for path in storage.tools.iterdir() if path.is_dir()):
            for version_path in sorted(path for path in package_path.iterdir() if path.is_dir()):
                if (package_path.name, version_path.name) not in recorded:
                    findings.append(
                        Finding(package_path.name, version_path.name, "failed", f"Unrecorded package directory left untouched: {version_path}")
                    )

    for path in _install_staging(storage):
        findings.append(Finding("dfpm", "-", "failed", f"Abandoned install staging directory: {path}"))
    for path in sync.staging_directories(storage.catalog):
        if _stale(path):
            findings.append(Finding("dfpm", "-", "failed", f"Abandoned catalog staging directory: {path}"))
    backup = sync.backup_directory(storage.catalog)
    if backup.is_dir():
        if not storage.catalog.exists() and _catalog_valid(backup):
            detail = "Interrupted catalog publish can be restored"
        elif not storage.catalog.exists():
            detail = "Interrupted catalog backup is unreadable and was left untouched"
        else:
            detail = "Previous catalog snapshot was not cleaned up"
        findings.append(Finding("dfpm", "-", "failed", f"{detail}: {backup}"))
    if storage.catalog.exists() and not _catalog_valid(storage.catalog):
        findings.append(Finding("dfpm", "-", "failed", f"Local catalog is unreadable: {storage.catalog}"))

    try:
        expected = shims.planned(storage)
    except DfpmError as exc:
        findings.append(Finding("dfpm", "-", "failed", f"Command shortcuts cannot be planned: {exc}"))
        expected = {}
    if storage.bin.is_dir() and shims.state_records_readable(storage):
        for path in sorted(storage.bin.glob("*.cmd")):
            if path.stem not in expected and shims.owned(path):
                findings.append(Finding("dfpm", "-", "failed", f"Stale command shortcut: {path.name}"))

    survey = download_cache.survey(storage, storage.catalog if storage.catalog.exists() else None)
    for path in survey.partials:
        if _stale(path):
            findings.append(Finding("dfpm", "-", "failed", f"Interrupted download: {path}"))
    for entry, problem in download_cache.verify(storage, storage.catalog if storage.catalog.exists() else None):
        if problem is not None:
            findings.append(Finding("dfpm", "-", "failed", f"Corrupt cached artifact {entry.digest}: {problem}"))
    return findings


def _install_staging(storage: Storage) -> list[Path]:
    directory = storage.root / "staging"
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_dir() and _stale(path))


def _stale(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime >= STALE_SECONDS
    except OSError:
        return False


def _catalog_valid(directory: Path) -> bool:
    try:
        sync.validate_snapshot(directory)
        return True
    except DfpmError:
        return False


def _remove_owned_tree(target: Path, parent: Path) -> None:
    try:
        valid = target.parent.resolve() == parent.resolve()
    except OSError:
        valid = False
    if not valid or not _stale(target):
        raise DfpmError(f"Refusing an invalid staging repair target: {target}")
    if not remove_tree(target):
        raise DfpmError(f"Could not remove {target}")

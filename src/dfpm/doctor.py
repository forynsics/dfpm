from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import runtimes
from .errors import DfpmError
from .inventory import list_packages
from .manifest import Requirement
from .shims import owned
from .storage import Storage


@dataclass(frozen=True)
class Finding:
    package: str
    version: str
    status: str
    detail: str


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
    for entrypoint in package.get("entrypoints", []):
        path = storage.bin / f"{entrypoint['name']}.cmd"
        if not path.is_file():
            problems.append(f"Missing command shortcut: {path.name}")
        elif not owned(path):
            problems.append(f"Command shortcut was replaced by an unmanaged file: {path.name}")
    return problems

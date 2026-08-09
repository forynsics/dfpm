from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .inventory import list_packages
from .shims import owned
from .storage import Storage


@dataclass(frozen=True)
class Finding:
    package: str
    version: str
    status: str
    detail: str


def inspect(storage: Storage) -> list[Finding]:
    findings: list[Finding] = []
    for package in list_packages(storage):
        version = package.get("version")
        if not version:
            continue
        problems = _file_problems(storage, package) + _shim_problems(storage, package)
        if problems:
            findings.extend(Finding(package["id"], version, "failed", detail) for detail in problems)
        else:
            findings.append(Finding(package["id"], version, "passing", "Installed files and command shortcuts are in place"))
    return findings


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
    for check in package.get("health_checks", []):
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

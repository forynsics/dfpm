from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .artifacts import file_digest
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
            findings.append(Finding(package["id"], version, "passing", "All managed files match their recorded digests"))
    return findings


def _file_problems(storage: Storage, package: dict[str, Any]) -> list[str]:
    root = storage.package_version(package["id"], package["version"])
    problems: list[str] = []
    for managed in package.get("files", []):
        path = root / managed["path"]
        if not path.is_file():
            problems.append(f"Missing managed file: {managed['path']}")
        elif file_digest(path) != managed["sha256"]:
            problems.append(f"Modified managed file: {managed['path']}")
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

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .inventory import list_packages
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
        for version, metadata in package["versions"].items():
            root = storage.package_version(package["id"], version)
            for managed in metadata["files"]:
                path = root / managed["path"]
                if not path.is_file():
                    findings.append(Finding(package["id"], version, "failed", f"Missing managed file: {managed['path']}"))
                    continue
                if _sha256(path) != managed["sha256"]:
                    findings.append(Finding(package["id"], version, "failed", f"Modified managed file: {managed['path']}"))
            for check in metadata.get("health_checks", []):
                if check["type"] == "file" and not (root / check["path"]).is_file():
                    findings.append(Finding(package["id"], version, "failed", f"Health check failed: {check['path']}"))
            if not any(item.package == package["id"] and item.version == version and item.status == "failed" for item in findings):
                findings.append(Finding(package["id"], version, "passing", "All managed files match their recorded digests"))
    return findings


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


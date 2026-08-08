from __future__ import annotations

from pathlib import Path

from .errors import ManifestError
from .manifest import Manifest


def load_catalog(directory: Path) -> list[Manifest]:
    if not directory.is_dir():
        raise ManifestError(f"Catalog directory does not exist: {directory}")
    return [Manifest.load(path) for path in sorted(directory.glob("*.json"))]


def resolve(directory: Path, package_id: str, version: str | None = None) -> Manifest:
    matches = [item for item in load_catalog(directory) if item.id == package_id and (version is None or item.version == version)]
    if not matches:
        requested = f" {version}" if version else ""
        raise ManifestError(f"Package not found in catalog: {package_id}{requested}")
    if version is None and len(matches) > 1:
        matches.sort(key=lambda item: item.version)
    return matches[-1]


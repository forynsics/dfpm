from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
        matches.sort(key=lambda item: version_key(item.version))
    return matches[-1]


def describe(manifest: Manifest) -> dict[str, Any]:
    """Summarize a manifest for listings, omitting optional sections that are absent."""
    entry: dict[str, Any] = {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "kind": manifest.kind,
        "description": manifest.description,
    }
    if manifest.platform is not None:
        entry["platform"] = {"os": manifest.platform.system, "arch": manifest.platform.architecture}
    if manifest.project is not None:
        recorded = {key: value for key, value in vars(manifest.project).items() if value is not None}
        if recorded:
            entry["project"] = recorded
    return entry


def version_key(version: str) -> tuple[tuple[int, ...], int, str]:
    """Order versions by their leading numeric components, ranking prereleases below releases."""
    parts = re.split(r"[._+-]", version)
    release: list[int] = []
    for part in parts:
        if not part.isdigit():
            break
        release.append(int(part))
    return tuple(release), 0 if len(release) < len(parts) else 1, version

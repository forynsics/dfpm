from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import platforms, shims
from .archive import DEFAULT_LIMITS, ArchiveLimits, check_path_lengths, extract_zip
from .artifacts import acquire
from .errors import InstallError
from .inventory import forget_package, read_package, write_package
from .manifest import Manifest
from .progress import Reporter
from .storage import Storage, remove_tree


def install(
    manifest: Manifest,
    storage: Storage,
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
    on_progress: Reporter | None = None,
) -> Path:
    """Install a package, replacing whatever version of it was installed before."""
    check_platform(manifest)
    previous = check_destination(manifest, storage)
    storage.initialize()
    destination = storage.package_version(manifest.id, manifest.version)
    artifact = acquire(manifest.artifact, manifest.artifact_source(), storage, on_progress)
    record = _stage(manifest, artifact, storage, destination, limits, on_progress)
    _publish(manifest, storage, destination, record, previous)
    return destination


def check_platform(manifest: Manifest) -> None:
    """Refuse a package built for a different operating system or architecture."""
    if manifest.platform is None:
        return
    system, architecture = platforms.current()
    if (manifest.platform.system, manifest.platform.architecture) != (system, architecture):
        raise InstallError(
            f"{manifest.id} {manifest.version} targets {manifest.platform}, but this machine is {system}/{architecture}"
        )


def check_destination(manifest: Manifest, storage: Storage) -> str | None:
    """Return the version being replaced, refusing when the new one is already in place."""
    installed = read_package(storage, manifest.id)
    current = installed.get("version") if installed else None
    if current == manifest.version:
        raise InstallError(f"{manifest.id} {manifest.version} is already installed")
    destination = storage.package_version(manifest.id, manifest.version)
    if destination.exists():
        raise InstallError(
            f"{destination} already exists, which means an earlier removal did not finish. "
            f"Run 'dfpm uninstall {manifest.id}' to clear it, then install again."
        )
    return current


def _stage(
    manifest: Manifest,
    artifact: Path,
    storage: Storage,
    destination: Path,
    limits: ArchiveLimits,
    on_progress: Reporter | None = None,
) -> dict[str, Any]:
    """Extract and validate into a staging directory, then move it into place atomically."""
    staging_parent = storage.root / "staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{manifest.id}-{manifest.version}-", dir=staging_parent))
    try:
        managed_files = extract_zip(
            artifact, staging, manifest.strip_components, limits, manifest.extracted_size, on_progress
        )
        check_path_lengths(destination, managed_files, limits)
        _check_recorded_extraction(manifest, managed_files)
        _validate_expected_paths(staging, manifest)
        record: dict[str, Any] = {
            "id": manifest.id,
            "name": manifest.name,
            "kind": manifest.kind,
            "version": manifest.version,
            "installed_at": datetime.now(UTC).isoformat(),
            "manifest_digest": manifest.digest,
            "artifact_sha256": manifest.artifact.sha256,
            "file_count": len(managed_files),
            "installed_size": sum(int(item["size"]) for item in managed_files),
            "entrypoints": [
                {"name": item.name, "path": item.path}
                | ({"working_directory": item.working_directory} if item.working_directory else {})
                for item in manifest.entrypoints
            ],
            # Declared, not observed. Whether a runtime is present can change
            # without dfpm doing anything, so it is checked live rather than
            # recorded here and allowed to go stale.
            "requires": [
                {"runtime": item.runtime}
                | ({"version": item.version} if item.version else {})
                | ({"flavor": item.flavor} if item.flavor else {})
                for item in manifest.requires
            ],
            "health_checks": [{"type": item.type, "path": item.path} for item in manifest.health_checks],
        }
        if manifest.platform is not None:
            record["platform"] = {"os": manifest.platform.system, "arch": manifest.platform.architecture}
        if manifest.project is not None:
            described = {key: value for key, value in vars(manifest.project).items() if value is not None}
            if described:
                record["project"] = described
        (staging / ".dfpm-install.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, destination)
        return record
    except Exception:
        # A successful install never reaches here: publishing moves the staging
        # directory rather than copying it, so there is nothing left to remove.
        remove_tree(staging)
        raise


def _publish(
    manifest: Manifest,
    storage: Storage,
    destination: Path,
    record: dict[str, Any],
    previous: str | None,
) -> None:
    """Record the new version, then retire the one it replaces once it is safely in place."""
    restore = read_package(storage, manifest.id)
    try:
        write_package(storage, manifest.id, record)
        shims.reconcile(storage)
    except Exception:
        remove_tree(destination)
        if restore is None:
            forget_package(storage, manifest.id)
        else:
            write_package(storage, manifest.id, restore)
        with contextlib.suppress(Exception):
            shims.reconcile(storage)
        raise
    if previous and previous != manifest.version:
        remove_tree(storage.package_version(manifest.id, previous))


def _check_recorded_extraction(manifest: Manifest, files: list[dict[str, Any]]) -> None:
    """Hold the install to the size and file count the manifest recorded.

    A matching artifact digest already proves the archive is the reviewed one,
    so a disagreement here does not mean the download was tampered with. It
    means the manifest's own figures came from somewhere else: a copy from
    another release, or an edit that never went back through review.
    """
    if manifest.entry_count is not None and len(files) != manifest.entry_count:
        raise InstallError(
            f"{manifest.id} {manifest.version} records {manifest.entry_count:,} installed files, "
            f"but the archive produced {len(files):,}. The manifest does not describe this artifact."
        )
    if manifest.extracted_size is not None:
        total = sum(int(item["size"]) for item in files)
        if total != manifest.extracted_size:
            raise InstallError(
                f"{manifest.id} {manifest.version} records an installed size of {manifest.extracted_size:,} bytes, "
                f"but the archive produced {total:,}. The manifest does not describe this artifact."
            )


def _validate_expected_paths(root: Path, manifest: Manifest) -> None:
    for item in (*manifest.entrypoints, *manifest.health_checks):
        if not (root / item.path).is_file():
            raise InstallError(f"Expected installed file is missing: {item.path}")

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
from .downloads import Acquired, Decision, acquire
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
    on_mismatch: Decision | None = None,
) -> Path:
    """Install a package, replacing whatever version of it was installed before."""
    check_platform(manifest)
    previous = check_destination(manifest, storage)
    storage.initialize()
    destination = storage.package_version(manifest.id, manifest.version)
    artifact = acquire(manifest.package, manifest.package_url(), storage, on_progress, on_mismatch)
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
    artifact: Acquired,
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
        # The recorded size is only usable as a target when this is the artifact
        # it was recorded from. For anything else it is a figure describing a
        # different file, so the archive's own totals are all there is to go on.
        expected_size = manifest.extracted_size if artifact.verified else None
        managed_files = extract_zip(
            artifact.path, staging, manifest.strip_components, limits, expected_size, on_progress
        )
        check_path_lengths(destination, managed_files, limits)
        if artifact.verified:
            _check_recorded_extraction(manifest, managed_files)
        _validate_expected_paths(staging, manifest)
        record: dict[str, Any] = {
            "id": manifest.id,
            "name": manifest.name,
            "kind": manifest.kind,
            # Recorded rather than looked up later, for the same reason the
            # platform and project are: what is installed should be able to
            # describe itself on a machine that has no catalog, or whose
            # catalog has since moved on to a different version.
            "description": manifest.description,
            # Classification travels with the install for the same reason. It
            # is what makes a tool findable by somebody who cannot name it, and
            # that is no less true of the tools already on the machine than of
            # the ones in the catalog.
            "disciplines": list(manifest.disciplines),
            "capabilities": list(manifest.capabilities),
            "use_cases": list(manifest.use_cases),
            "evidence": list(manifest.evidence),
            "version": manifest.version,
            "installed_at": datetime.now(UTC).isoformat(),
            "manifest_digest": manifest.digest,
            # Two facts, deliberately not collapsed into one. The catalog records
            # what a reviewer approved; this records what actually landed on the
            # machine. They are equal on every ordinary install, and the only
            # time they are not is exactly the time somebody needs both.
            "package_sha256": artifact.digest,
            "catalog_sha256": manifest.package.sha256,
            "digest_verified": artifact.verified,
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
            "verify": [{"type": item.type, "path": item.path} for item in manifest.verify],
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
    for item in (*manifest.entrypoints, *manifest.verify):
        if not (root / item.path).is_file():
            raise InstallError(f"Expected installed file is missing: {item.path}")

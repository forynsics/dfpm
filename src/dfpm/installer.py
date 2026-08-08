from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .artifacts import acquire
from .errors import InstallError
from .inventory import read_package, write_package
from .manifest import Manifest
from .storage import Storage


def install(manifest: Manifest, storage: Storage) -> Path:
    storage.initialize()
    destination = storage.package_version(manifest.id, manifest.version)
    if destination.exists():
        raise InstallError(f"{manifest.id} {manifest.version} is already installed")
    artifact = acquire(manifest.artifact, manifest.artifact_source(), storage)
    staging_parent = storage.root / "staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{manifest.id}-{manifest.version}-", dir=staging_parent))
    try:
        managed_files = _extract_zip(artifact, staging, manifest.strip_components)
        _validate_expected_paths(staging, manifest)
        metadata = {
            "manifest_digest": manifest.digest,
            "artifact_sha256": manifest.artifact.sha256,
            "installed_at": datetime.now(UTC).isoformat(),
            "files": managed_files,
            "entrypoints": [{"name": item.name, "path": item.path} for item in manifest.entrypoints],
            "health_checks": [{"type": item.type, "path": item.path} for item in manifest.health_checks],
        }
        (staging / ".dfpm-install.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, destination)
        state = read_package(storage, manifest.id) or {"id": manifest.id, "name": manifest.name, "kind": manifest.kind, "versions": {}}
        state["name"] = manifest.name
        state["kind"] = manifest.kind
        state["versions"][manifest.version] = metadata
        state["active_version"] = manifest.version
        write_package(storage, manifest.id, state)
        _write_shims(storage, manifest)
        return destination
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if destination.exists() and not read_package(storage, manifest.id):
            shutil.rmtree(destination, ignore_errors=True)
        raise


def _extract_zip(archive: Path, destination: Path, strip_components: int) -> list[dict[str, str | int]]:
    files: list[dict[str, str | int]] = []
    try:
        source = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        raise InstallError("Artifact is not a valid ZIP archive") from exc
    with source:
        for info in source.infolist():
            raw = info.filename.replace("\\", "/")
            parts = PurePosixPath(raw).parts
            if raw.startswith("/") or ".." in parts:
                raise InstallError(f"Archive contains an unsafe path: {info.filename}")
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise InstallError(f"Archive contains an unsupported symbolic link: {info.filename}")
            stripped = parts[strip_components:]
            if not stripped:
                continue
            relative = Path(*stripped)
            target = destination / relative
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with source.open(info) as input_file, target.open("wb") as output_file:
                while chunk := input_file.read(1024 * 1024):
                    size += len(chunk)
                    digest.update(chunk)
                    output_file.write(chunk)
            files.append({"path": relative.as_posix(), "size": size, "sha256": digest.hexdigest()})
    if not files:
        raise InstallError("Archive did not contain any installable files")
    return sorted(files, key=lambda item: str(item["path"]))


def _validate_expected_paths(root: Path, manifest: Manifest) -> None:
    for item in (*manifest.entrypoints, *manifest.health_checks):
        if not (root / item.path).is_file():
            raise InstallError(f"Expected installed file is missing: {item.path}")


def _write_shims(storage: Storage, manifest: Manifest) -> None:
    for entrypoint in manifest.entrypoints:
        command = storage.bin / f"{entrypoint.name}.cmd"
        target = storage.package_version(manifest.id, manifest.version) / entrypoint.path
        command.write_text(f'@echo off\r\n"{target}" %*\r\n', encoding="utf-8")


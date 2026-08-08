from __future__ import annotations

import hashlib
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import InstallError
from .names import unsafe_reason

CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ArchiveLimits:
    """Bounds applied to every archive dfpm extracts."""

    max_entries: int = 20000
    max_total_size: int = 4 * 1024**3
    max_file_size: int = 2 * 1024**3
    max_expansion_ratio: int = 200
    ratio_exemption: int = 8 * 1024 * 1024


DEFAULT_LIMITS = ArchiveLimits()


def extract_zip(
    archive: Path,
    destination: Path,
    strip_components: int,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> list[dict[str, str | int]]:
    """Extract *archive* into *destination*, returning a record of every file written."""
    try:
        source = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        raise InstallError("Artifact is not a valid ZIP archive") from exc
    with source:
        entries = source.infolist()
        _check_declared_totals(entries, limits)
        claimed: dict[str, tuple[str, bool]] = {}
        files: list[dict[str, str | int]] = []
        extracted = 0
        compressed = 0
        for info in entries:
            raw = info.filename.replace("\\", "/")
            is_directory = raw.endswith("/")
            relative = _safe_relative_path(info, raw)
            _claim(claimed, relative, info.filename, is_directory)
            stripped = relative.parts[strip_components:]
            if not stripped:
                continue
            target = destination / Path(*stripped)
            if is_directory:
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            digest, size = _write_entry(source, info, target, extracted, limits)
            extracted += size
            compressed += info.compress_size
            files.append({"path": str(PurePosixPath(*stripped)), "size": size, "sha256": digest})
    if not files:
        raise InstallError("Archive did not contain any installable files")
    _check_expansion(extracted, compressed, limits)
    return sorted(files, key=lambda item: str(item["path"]))


def _check_declared_totals(entries: list[zipfile.ZipInfo], limits: ArchiveLimits) -> None:
    """Reject obviously hostile archives before opening a single entry."""
    if len(entries) > limits.max_entries:
        raise InstallError(f"Archive declares {len(entries)} entries, above the limit of {limits.max_entries}")
    declared = sum(info.file_size for info in entries)
    if declared > limits.max_total_size:
        raise InstallError(f"Archive declares {declared} bytes, above the extraction limit of {limits.max_total_size}")
    _check_expansion(declared, sum(info.compress_size for info in entries), limits)


def _check_expansion(extracted: int, compressed: int, limits: ArchiveLimits) -> None:
    if extracted <= limits.ratio_exemption:
        return
    if compressed <= 0 or extracted > compressed * limits.max_expansion_ratio:
        raise InstallError(f"Archive expands more than {limits.max_expansion_ratio} times its compressed size")


def _safe_relative_path(info: zipfile.ZipInfo, raw: str) -> PurePosixPath:
    if info.flag_bits & 0x1:
        raise InstallError(f"Archive contains an encrypted entry: {info.filename}")
    mode = info.external_attr >> 16
    if stat.S_IFMT(mode):
        if stat.S_ISLNK(mode):
            raise InstallError(f"Archive contains an unsupported symbolic link: {info.filename}")
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise InstallError(f"Archive contains an unsupported special file: {info.filename}")
    if raw.startswith("/"):
        raise InstallError(f"Archive contains an absolute path: {info.filename}")
    parts = PurePosixPath(raw).parts
    if not parts:
        raise InstallError("Archive contains an entry with an empty path")
    for part in parts:
        reason = unsafe_reason(part)
        if reason is not None:
            raise InstallError(f"Archive contains a path component that {reason}: {info.filename}")
    return PurePosixPath(*parts)


def _claim(claimed: dict[str, tuple[str, bool]], relative: PurePosixPath, original: str, is_directory: bool) -> None:
    """Record a path so that duplicates and Windows case collisions are rejected."""
    key = str(relative).lower()
    existing = claimed.get(key)
    if existing is None:
        claimed[key] = (original, is_directory)
        return
    previous, previously_directory = existing
    if is_directory and previously_directory:
        return
    if is_directory != previously_directory:
        raise InstallError(f"Archive uses one path as both a file and a directory: {original}")
    if previous == original:
        raise InstallError(f"Archive contains a duplicate path: {original}")
    raise InstallError(f"Archive contains paths that collide on Windows: {previous} and {original}")


def _write_entry(
    source: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    target: Path,
    already_extracted: int,
    limits: ArchiveLimits,
) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open(info) as reader, target.open("wb") as writer:
            while chunk := reader.read(CHUNK_SIZE):
                size += len(chunk)
                if size > limits.max_file_size:
                    raise InstallError(f"Archive entry is above the {limits.max_file_size} byte file limit: {info.filename}")
                if already_extracted + size > limits.max_total_size:
                    raise InstallError(f"Archive expands beyond the {limits.max_total_size} byte extraction limit")
                digest.update(chunk)
                writer.write(chunk)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise InstallError(f"Could not extract archive entry: {info.filename}") from exc
    if size != info.file_size:
        raise InstallError(f"Archive entry does not match the size recorded in its header: {info.filename}")
    return digest.hexdigest(), size

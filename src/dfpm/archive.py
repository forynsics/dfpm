from __future__ import annotations

import os
import shutil
import stat
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import InstallError
from .names import unsafe_reason

CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ArchiveLimits:
    """Bounds applied to every archive dfpm extracts.

    None of these are integrity controls. The artifact's SHA-256 is verified
    before extraction begins, so the bytes are always exactly the ones a
    reviewer pinned. What is left is containment: keeping an archive inside the
    directory it was granted, and failing with a readable message rather than
    filling a disk or grinding for hours on something pathological.
    """

    # A runaway backstop, not a defence. Set well above any real tool: a bundled
    # Python runtime runs to 30-50k files and a Node one can exceed 100k.
    max_entries: int = 250_000
    max_path_length: int = 259
    # Never extract a volume down to nothing, even when the archive would fit.
    free_space_margin: int = 512 * 1024**2


DEFAULT_LIMITS = ArchiveLimits()


def human_size(size: float) -> str:
    for unit in ("bytes", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:,.0f} {unit}" if unit == "bytes" else f"{size:,.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def _space_budget(destination: Path, required: int, limits: ArchiveLimits) -> int:
    """Refuse up front if the result will not fit, and return the ceiling to enforce while writing.

    Free space is the thing that actually decides whether extraction hurts, so
    it is what dfpm measures. A fixed byte cap knows nothing about the volume it
    is protecting: the same number is needlessly strict on a machine with room
    to spare and useless on one without.
    """
    try:
        free = shutil.disk_usage(destination).free
    except OSError:
        # Unmeasurable volume: fall back to holding the archive to its own
        # declared size, which still catches a header that understates itself.
        return required
    budget = free - limits.free_space_margin
    if required > budget:
        raise InstallError(
            f"Extracting needs {human_size(required)}, but {destination} has {human_size(free)} free "
            f"and dfpm keeps {human_size(limits.free_space_margin)} in reserve"
        )
    return budget


def check_path_lengths(
    destination: Path,
    files: Iterable[dict[str, str | int]],
    limits: ArchiveLimits = DEFAULT_LIMITS,
    system: str | None = None,
) -> None:
    """Refuse an install whose files would not fit inside the platform's path limit.

    Extraction happens under a temporary staging name, so the length that decides
    whether an install works is the one the files take after they are moved into
    place. Windows refuses a path beyond 260 characters unless long paths are
    enabled machine-wide, and the error it raises part-way through extraction is
    an opaque FileNotFoundError that says nothing about what went wrong.
    """
    if (os.name if system is None else system) != "nt":
        return
    longest = max((str(destination / Path(str(item["path"]))) for item in files), key=len, default="")
    if len(longest) > limits.max_path_length:
        raise InstallError(
            f"Installing here would create a path {len(longest)} characters long, above the "
            f"{limits.max_path_length} character limit Windows applies: {longest}"
        )


def extract_zip(
    archive: Path,
    destination: Path,
    strip_components: int,
    limits: ArchiveLimits = DEFAULT_LIMITS,
    expected_size: int | None = None,
) -> list[dict[str, str | int]]:
    """Extract *archive* into *destination*, returning a record of every file written.

    When the manifest records the size the install takes, *expected_size* carries
    it, and the space check uses that instead of the archive's own declared
    totals, which are attacker-controlled metadata.
    """
    try:
        source = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        raise InstallError("Artifact is not a valid ZIP archive") from exc
    with source:
        entries = source.infolist()
        if len(entries) > limits.max_entries:
            raise InstallError(
                f"Archive holds {len(entries):,} entries, above the {limits.max_entries:,} dfpm will extract"
            )
        declared = sum(info.file_size for info in entries)
        budget = _space_budget(destination, declared if expected_size is None else expected_size, limits)
        claimed: dict[str, tuple[str, bool]] = {}
        files: list[dict[str, str | int]] = []
        extracted = 0
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
            size = _write_entry(source, info, target, extracted, budget)
            extracted += size
            files.append({"path": str(PurePosixPath(*stripped)), "size": size})
    if not files:
        raise InstallError(
            "Archive did not contain any installable files. Check whether install.strip_components is set too high."
        )
    return sorted(files, key=lambda item: str(item["path"]))


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
    """Record a path so duplicates and case-only collisions are rejected.

    Not a security rule. Two entries differing only by capitalization merge on a
    case-insensitive filesystem, which would leave dfpm holding a recorded digest
    for a file whose contents came from the other entry.
    """
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
    raise InstallError(
        f"Archive contains paths that differ only by capitalization, which a case-insensitive "
        f"filesystem would merge: {previous} and {original}"
    )


def _write_entry(
    source: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    target: Path,
    already_extracted: int,
    budget: int,
) -> int:
    size = 0
    try:
        with source.open(info) as reader, target.open("wb") as writer:
            while chunk := reader.read(CHUNK_SIZE):
                size += len(chunk)
                # The budget is re-checked against bytes actually written because
                # the sizes in the central directory are the archive's own claim.
                if already_extracted + size > budget:
                    raise InstallError(
                        f"Archive is expanding past the {human_size(budget)} there is room for, "
                        f"so its recorded sizes understate it: {info.filename}"
                    )
                writer.write(chunk)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise InstallError(f"Could not extract archive entry: {info.filename}") from exc
    if size != info.file_size:
        raise InstallError(f"Archive entry does not match the size recorded in its header: {info.filename}")
    return size

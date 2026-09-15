from __future__ import annotations

import os
import shutil
import stat
import tarfile
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO

from .errors import InstallError
from .names import unsafe_reason
from .progress import Reporter

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


@dataclass(frozen=True)
class _Entry:
    """One member of an archive, already checked, in terms every format shares."""

    name: str
    parts: tuple[str, ...]
    is_directory: bool
    size: int
    executable: bool
    open: Callable[[], IO[bytes]]


def human_size(size: float) -> str:
    for unit in ("bytes", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:,.0f} {unit}" if unit == "bytes" else f"{size:,.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def make_executable(path: Path) -> None:
    """Let whoever may read a file also run it, on a system where that is a permission.

    Execute is granted exactly where read already is, so the result follows the
    umask the file was created under instead of dfpm choosing who may run it.
    Nothing else about the mode changes, and setuid, setgid and sticky bits are
    never set: an archive gets to say a file is a program, not what authority it
    runs with. Windows has no execute bit, so there this does nothing.
    """
    if os.name == "nt":
        return
    mode = path.stat().st_mode
    path.chmod(stat.S_IMODE(mode) | ((mode & 0o444) >> 2))


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
    on_progress: Reporter | None = None,
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
        members = source.infolist()
        _check_entry_count(len(members), limits)
        entries = [_zip_entry(source, info) for info in members]
        return _extract(entries, destination, strip_components, limits, expected_size, on_progress)


def extract_tar(
    archive: Path,
    destination: Path,
    strip_components: int,
    limits: ArchiveLimits = DEFAULT_LIMITS,
    expected_size: int | None = None,
    on_progress: Reporter | None = None,
) -> list[dict[str, str | int]]:
    """Extract a tar archive, compressed or not, under exactly the rules a ZIP gets.

    Members are read one at a time and written by dfpm rather than handed to
    tarfile's own extraction, so what reaches the disk is decided here and does
    not depend on which filters a particular Python release applies by default.
    """
    try:
        source = tarfile.open(archive, "r:*")
    except (OSError, tarfile.TarError) as exc:
        raise InstallError("Artifact is not a valid tar archive") from exc
    with source:
        try:
            members = source.getmembers()
        except (OSError, EOFError, tarfile.TarError) as exc:
            raise InstallError("Artifact is not a valid tar archive") from exc
        _check_entry_count(len(members), limits)
        entries = [entry for member in members if (entry := _tar_entry(source, member)) is not None]
        return _extract(entries, destination, strip_components, limits, expected_size, on_progress)


def _check_entry_count(count: int, limits: ArchiveLimits) -> None:
    if count > limits.max_entries:
        raise InstallError(f"Archive holds {count:,} entries, above the {limits.max_entries:,} dfpm will extract")


def _zip_entry(source: zipfile.ZipFile, info: zipfile.ZipInfo) -> _Entry:
    raw = info.filename.replace("\\", "/")
    if info.flag_bits & 0x1:
        raise InstallError(f"Archive contains an encrypted entry: {info.filename}")
    # A ZIP made on a Unix system keeps the file's mode in the high bits of its
    # external attributes. One made elsewhere has no type bits there at all.
    mode = info.external_attr >> 16
    if stat.S_IFMT(mode):
        if stat.S_ISLNK(mode):
            raise InstallError(f"Archive contains an unsupported symbolic link: {info.filename}")
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise InstallError(f"Archive contains an unsupported special file: {info.filename}")
    return _Entry(
        name=info.filename,
        parts=_safe_parts(raw, info.filename),
        is_directory=raw.endswith("/"),
        size=info.file_size,
        executable=stat.S_ISREG(mode) and bool(mode & 0o111),
        open=lambda: source.open(info),
    )


def _tar_entry(source: tarfile.TarFile, member: tarfile.TarInfo) -> _Entry | None:
    if member.issym() or member.islnk():
        # Links are refused for the same reason in both formats: one resolving
        # outside the package would let a later write land somewhere dfpm never
        # granted, and following them safely is more than a package needs.
        raise InstallError(f"Archive contains an unsupported link: {member.name}")
    if not (member.isfile() or member.isdir()):
        raise InstallError(f"Archive contains an unsupported special file: {member.name}")
    raw = member.name.replace("\\", "/")
    if member.isdir() and not PurePosixPath(raw).parts:
        # Tools that archive "." record the archive's own root as a member.
        return None
    return _Entry(
        name=member.name,
        parts=_safe_parts(raw, member.name),
        is_directory=member.isdir(),
        size=member.size,
        executable=member.isfile() and bool(member.mode & 0o111),
        open=lambda: _tar_reader(source, member),
    )


def _tar_reader(source: tarfile.TarFile, member: tarfile.TarInfo) -> IO[bytes]:
    reader = source.extractfile(member)
    if reader is None:
        raise InstallError(f"Could not read archive entry: {member.name}")
    return reader


def _safe_parts(raw: str, name: str) -> tuple[str, ...]:
    if raw.startswith("/"):
        raise InstallError(f"Archive contains an absolute path: {name}")
    parts = PurePosixPath(raw).parts
    if not parts:
        raise InstallError("Archive contains an entry with an empty path")
    for part in parts:
        reason = unsafe_reason(part)
        if reason is not None:
            raise InstallError(f"Archive contains a path component that {reason}: {name}")
    return parts


def _extract(
    entries: list[_Entry],
    destination: Path,
    strip_components: int,
    limits: ArchiveLimits,
    expected_size: int | None,
    on_progress: Reporter | None,
) -> list[dict[str, str | int]]:
    """Write checked entries into *destination*, whatever format they were read from.

    Every entry is validated before anything is written, so an archive with one
    bad member at the end leaves nothing behind but an empty staging directory.
    """
    declared = sum(entry.size for entry in entries)
    budget = _space_budget(destination, declared if expected_size is None else expected_size, limits)
    expected_files = sum(1 for entry in entries if not entry.is_directory)
    claimed: dict[str, tuple[str, bool, str]] = {}
    files: list[dict[str, str | int]] = []
    extracted = 0
    for entry in entries:
        stripped = entry.parts[strip_components:]
        if not stripped:
            continue
        installed = PurePosixPath(*stripped)
        # Collision checks apply to the path that will actually be written.
        # Different archive paths can become the same installed path after
        # their leading components are removed.
        _claim(claimed, installed, entry.name, entry.is_directory)
        target = destination / Path(*stripped)
        if entry.is_directory:
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        size = _write_entry(entry, target, extracted, budget)
        if entry.executable:
            try:
                make_executable(target)
            except OSError as exc:
                raise InstallError(f"Could not make archive entry executable: {entry.name}") from exc
        extracted += size
        files.append({"path": str(installed), "size": size})
        if on_progress is not None:
            on_progress("extract", len(files), expected_files)
    if not files:
        raise InstallError(
            "Archive did not contain any installable files. Check whether install.strip_components is set too high."
        )
    return sorted(files, key=lambda item: str(item["path"]))


def _claim(
    claimed: dict[str, tuple[str, bool, str]],
    relative: PurePosixPath,
    original: str,
    is_directory: bool,
) -> None:
    """Record a path so duplicates and case-only collisions are rejected.

    Not a security rule. Two entries differing only by capitalization merge on a
    case-insensitive filesystem, which would leave dfpm holding a recorded digest
    for a file whose contents came from the other entry.
    """
    key = str(relative).lower()
    existing = claimed.get(key)
    if existing is None:
        claimed[key] = (original, is_directory, str(relative))
        return
    previous, previously_directory, previous_relative = existing
    if is_directory and previously_directory:
        return
    if is_directory != previously_directory:
        raise InstallError(f"Archive uses one path as both a file and a directory: {original}")
    if previous_relative == str(relative):
        raise InstallError(f"Archive contains paths that install to the same location: {previous} and {original}")
    raise InstallError(
        f"Archive contains paths that differ only by capitalization, which a case-insensitive "
        f"filesystem would merge: {previous} and {original}"
    )


def _write_entry(entry: _Entry, target: Path, already_extracted: int, budget: int) -> int:
    size = 0
    try:
        with entry.open() as reader, target.open("wb") as writer:
            while chunk := reader.read(CHUNK_SIZE):
                size += len(chunk)
                # The budget is re-checked against bytes actually written because
                # the sizes in an archive's headers are the archive's own claim.
                if already_extracted + size > budget:
                    raise InstallError(
                        f"Archive is expanding past the {human_size(budget)} there is room for, "
                        f"so its recorded sizes understate it: {entry.name}"
                    )
                writer.write(chunk)
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile, tarfile.TarError) as exc:
        raise InstallError(f"Could not extract archive entry: {entry.name}") from exc
    if size != entry.size:
        raise InstallError(f"Archive entry does not match the size recorded in its header: {entry.name}")
    return size

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import InstallError
from .inventory import list_packages
from .storage import Storage

# Every shim names itself near the top, which is what lets dfpm tell its own
# files from anything else in the bin directory. Each platform recognises only
# its own marker: a Linux dfpm pointed at a directory a Windows dfpm also uses
# must never decide that the Windows shims are stale and sweep them away.
WINDOWS_MARKER = "@rem dfpm-shim"
POSIX_MARKER = "# dfpm-shim"
MARKER = WINDOWS_MARKER if os.name == "nt" else POSIX_MARKER

EXECUTABLE_MODE = 0o755
# Enough for any marker line; far short of reading a binary whole.
OWNERSHIP_READ_LIMIT = 256


@dataclass(frozen=True)
class Shim:
    name: str
    package: str
    version: str
    target: Path
    working_directory: Path


def _windows(system: str | None) -> bool:
    return (os.name if system is None else system) == "nt"


def filename(name: str, system: str | None = None) -> str:
    """The file a command's shim is written to.

    Windows finds a script through its extension, so the shim is a .cmd. A POSIX
    shell looks a command up by its exact name and runs it if it is executable,
    so there the shim has no extension and `yara` is simply `yara`.
    """
    return f"{name}.cmd" if _windows(system) else name


def path(storage: Storage, name: str) -> Path:
    """Where the shim for a command lives."""
    return storage.bin / filename(name)


def command_of(shim_path: Path) -> str:
    """The command a shim file stands for."""
    return shim_path.stem if _windows(None) else shim_path.name


def existing(storage: Storage) -> list[Path]:
    """Files in the bin directory that could be shims, owned or not.

    Hidden names are skipped because that is where an interrupted write leaves
    its temporary file, and a half-written shim is not a command.
    """
    if not storage.bin.is_dir():
        return []
    if _windows(None):
        return sorted(storage.bin.glob("*.cmd"))
    return sorted(item for item in storage.bin.iterdir() if item.is_file() and not item.name.startswith("."))


def working_directory(root: Path, entrypoint: dict) -> Path:
    """Where an entrypoint runs from.

    Defaults to the directory holding the executable, which is what a tool
    resolving its own rules or configuration against the working directory
    needs, and what someone opening a terminal beside the binary would get.
    A manifest overrides it relative to the package root, using "." for the
    root itself.
    """
    declared = entrypoint.get("working_directory")
    if declared is None:
        return (root / entrypoint["path"]).parent
    if declared == ".":
        return root
    return root / declared


def planned(storage: Storage) -> dict[str, Shim]:
    """Return the shims the installed packages ask for, keyed by command name."""
    shims: dict[str, Shim] = {}
    for package in list_packages(storage):
        version = package.get("version")
        if not version:
            continue
        root = storage.package_version(package["id"], version)
        for entrypoint in package.get("entrypoints", []):
            name = entrypoint["name"]
            claimed = shims.get(name)
            if claimed is not None and claimed.package != package["id"]:
                raise InstallError(f"Command name '{name}' is claimed by both {claimed.package} and {package['id']}")
            shims[name] = Shim(
                name,
                package["id"],
                version,
                root / entrypoint["path"],
                working_directory(root, entrypoint),
            )
    return shims


def reconcile(storage: Storage) -> list[str]:
    """Make the bin directory match the recorded state, returning the shims removed."""
    storage.bin.mkdir(parents=True, exist_ok=True)
    shims = planned(storage)
    for shim in shims.values():
        _write(path(storage, shim.name), shim)
    removed = []
    if state_records_readable(storage):
        for candidate in existing(storage):
            if command_of(candidate) in shims or not owned(candidate):
                continue
            candidate.unlink()
            removed.append(candidate.name)
    return removed


def repair(storage: Storage) -> list[str]:
    """Repair only missing or dfpm-owned shims, leaving unmanaged files untouched."""
    storage.bin.mkdir(parents=True, exist_ok=True)
    expected = planned(storage)
    changed: list[str] = []
    for shim in expected.values():
        target = path(storage, shim.name)
        if target.exists() and not owned(target):
            continue
        if not current(target, shim):
            _write(target, shim)
            changed.append(target.name)
    if state_records_readable(storage):
        for candidate in existing(storage):
            if command_of(candidate) not in expected and owned(candidate):
                candidate.unlink()
                changed.append(candidate.name)
    return changed


def state_records_readable(storage: Storage) -> bool:
    """Whether sweeping an apparently stale shim is safe despite skipped state records."""
    directory = storage.state / "packages"
    if not directory.is_dir():
        return True
    for record in directory.glob("*.json"):
        try:
            if not isinstance(json.loads(record.read_text(encoding="utf-8")), dict):
                return False
        except (OSError, ValueError):
            return False
    return True


def current(shim_path: Path, shim: Shim) -> bool:
    """Whether a managed shortcut contains exactly the command now planned for it.

    On POSIX a shim that has lost its executable bit is not current either: the
    shell will not run it, however correct its contents are.
    """
    try:
        if shim_path.read_bytes() != _content(shim).encode("utf-8"):
            return False
        return _windows(None) or bool(shim_path.stat().st_mode & stat.S_IXUSR)
    except OSError:
        return False


def owned(shim_path: Path) -> bool:
    """Report whether *shim_path* is a shim dfpm wrote, so unknown files are never touched.

    A POSIX shim has to start with its interpreter line, so the marker may be on
    the second line as well as the first. Each read is bounded: on POSIX every
    file in the bin directory is asked, and a program copied in there may have
    no line break for megabytes.
    """
    try:
        with shim_path.open("r", encoding="utf-8", errors="replace") as source:
            head = [source.readline(OWNERSHIP_READ_LIMIT), source.readline(OWNERSHIP_READ_LIMIT)]
    except OSError:
        return False
    return any(line.startswith(MARKER) for line in head)


def _write(shim_path: Path, shim: Shim) -> None:
    if shim_path.exists() and not owned(shim_path):
        raise InstallError(f"Refusing to replace a file dfpm does not manage: {shim_path}")
    content = _content(shim)
    handle, temporary = tempfile.mkstemp(prefix=f".{shim_path.name}.", suffix=".tmp", dir=shim_path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if not _windows(None):
            # mkstemp creates the file readable by its owner only, and a shell
            # will not run a file without the executable bit.
            os.chmod(temporary, EXECUTABLE_MODE)
        os.replace(temporary, shim_path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _content(shim: Shim, system: str | None = None) -> str:
    if _windows(system):
        # setlocal scopes the directory change to this script, so a shell that
        # runs the shim is left where it was. The tool's exit code still
        # propagates through the implicit endlocal.
        return (
            f"{WINDOWS_MARKER} package={shim.package} version={shim.version}\r\n"
            f"@echo off\r\n"
            f"setlocal\r\n"
            f'cd /d "{shim.working_directory}"\r\n'
            f'"{shim.target}" %*\r\n'
        )
    # The script runs in a process of its own, so changing directory never
    # affects the shell that called it. exec replaces that process with the
    # tool, which means the tool's exit code and signals reach the caller
    # directly. Failing to enter the directory exits 126, the shell's code for
    # a command that was found but could not be run.
    return (
        "#!/bin/sh\n"
        f"{POSIX_MARKER} package={shim.package} version={shim.version}\n"
        f"cd {_sh_quote(shim.working_directory)} || exit 126\n"
        f'exec {_sh_quote(shim.target)} "$@"\n'
    )


def _sh_quote(value: object) -> str:
    """Quote a value for a POSIX shell, where nothing inside single quotes is special but the quote itself."""
    return "'" + str(value).replace("'", "'\\''") + "'"

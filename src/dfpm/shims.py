from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import InstallError
from .inventory import list_packages
from .storage import Storage

MARKER = "@rem dfpm-shim"


@dataclass(frozen=True)
class Shim:
    name: str
    package: str
    version: str
    target: Path
    working_directory: Path


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
        _write(storage.bin / f"{shim.name}.cmd", shim)
    removed = []
    if state_records_readable(storage):
        for path in sorted(storage.bin.glob("*.cmd")):
            if path.stem in shims or not owned(path):
                continue
            path.unlink()
            removed.append(path.name)
    return removed


def repair(storage: Storage) -> list[str]:
    """Repair only missing or dfpm-owned shims, leaving unmanaged files untouched."""
    storage.bin.mkdir(parents=True, exist_ok=True)
    expected = planned(storage)
    changed: list[str] = []
    for shim in expected.values():
        path = storage.bin / f"{shim.name}.cmd"
        if path.exists() and not owned(path):
            continue
        if not current(path, shim):
            _write(path, shim)
            changed.append(path.name)
    if state_records_readable(storage):
        for path in sorted(storage.bin.glob("*.cmd")):
            if path.stem not in expected and owned(path):
                path.unlink()
                changed.append(path.name)
    return changed


def state_records_readable(storage: Storage) -> bool:
    """Whether sweeping an apparently stale shim is safe despite skipped state records."""
    directory = storage.state / "packages"
    if not directory.is_dir():
        return True
    for path in directory.glob("*.json"):
        try:
            if not isinstance(json.loads(path.read_text(encoding="utf-8")), dict):
                return False
        except (OSError, ValueError):
            return False
    return True


def current(path: Path, shim: Shim) -> bool:
    """Whether a managed shortcut contains exactly the command now planned for it."""
    try:
        return path.read_bytes() == _content(shim).encode("utf-8")
    except OSError:
        return False


def owned(path: Path) -> bool:
    """Report whether *path* is a shim dfpm wrote, so unknown files are never touched."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as source:
            return source.readline().startswith(MARKER)
    except OSError:
        return False


def _write(path: Path, shim: Shim) -> None:
    if path.exists() and not owned(path):
        raise InstallError(f"Refusing to replace a file dfpm does not manage: {path}")
    # setlocal scopes the directory change to this script, so a shell that runs
    # the shim is left where it was. The tool's exit code still propagates
    # through the implicit endlocal.
    content = _content(shim)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _content(shim: Shim) -> str:
    return (
        f"{MARKER} package={shim.package} version={shim.version}\r\n"
        f"@echo off\r\n"
        f"setlocal\r\n"
        f'cd /d "{shim.working_directory}"\r\n'
        f'"{shim.target}" %*\r\n'
    )

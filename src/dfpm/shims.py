from __future__ import annotations

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
            shims[name] = Shim(name, package["id"], version, root / entrypoint["path"])
    return shims


def reconcile(storage: Storage) -> list[str]:
    """Make the bin directory match the recorded state, returning the shims removed."""
    storage.bin.mkdir(parents=True, exist_ok=True)
    shims = planned(storage)
    for shim in shims.values():
        _write(storage.bin / f"{shim.name}.cmd", shim)
    removed = []
    for path in sorted(storage.bin.glob("*.cmd")):
        if path.stem in shims or not owned(path):
            continue
        path.unlink()
        removed.append(path.name)
    return removed


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
    content = f"{MARKER} package={shim.package} version={shim.version}\r\n@echo off\r\n\"{shim.target}\" %*\r\n"
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

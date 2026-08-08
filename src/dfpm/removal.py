from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

from . import shims
from .artifacts import file_digest
from .errors import InstallError
from .inventory import forget_package, read_package
from .storage import Storage

METADATA_NAME = ".dfpm-install.json"


@dataclass(frozen=True)
class RemovalPlan:
    """What removing a package would delete, and what it would leave behind."""

    package: str
    name: str
    version: str
    root: Path
    removable: tuple[str, ...]
    modified: tuple[str, ...]
    missing: tuple[str, ...]
    unknown: tuple[str, ...]
    blocked: tuple[str, ...]
    commands: tuple[str, ...]

    def preserved(self, force: bool) -> tuple[str, ...]:
        kept = self.unknown + self.blocked
        return kept if force else kept + self.modified


def plan(storage: Storage, package_id: str) -> RemovalPlan:
    """Describe exactly what dfpm owns for *package_id* before anything is deleted."""
    state = read_package(storage, package_id)
    if state is None:
        raise InstallError(f"{package_id} is not installed")
    version = state["version"]
    root = storage.package_version(package_id, version)
    recorded = {item["path"]: item["sha256"] for item in state.get("files", [])}

    removable: list[str] = []
    modified: list[str] = []
    missing: list[str] = []
    blocked: list[str] = []
    for relative, digest in sorted(recorded.items()):
        path = root / relative
        if path.is_symlink():
            blocked.append(relative)
        elif not path.is_file():
            missing.append(relative)
        elif file_digest(path) != digest:
            modified.append(relative)
        else:
            removable.append(relative)

    return RemovalPlan(
        package=package_id,
        name=state.get("name", package_id),
        version=version,
        root=root,
        removable=tuple(removable),
        modified=tuple(modified),
        missing=tuple(missing),
        unknown=_unknown(root, set(recorded)),
        blocked=tuple(blocked),
        commands=tuple(sorted(item["name"] for item in state.get("entrypoints", []))),
    )


def execute(storage: Storage, removal_plan: RemovalPlan, *, force: bool = False) -> None:
    """Carry out *removal_plan*, deleting only files dfpm recorded and still recognizes."""
    _delete(removal_plan, force)
    forget_package(storage, removal_plan.package)
    shims.reconcile(storage)
    with contextlib.suppress(OSError):
        (storage.tools / removal_plan.package).rmdir()


def _unknown(root: Path, recorded: set[str]) -> tuple[str, ...]:
    """Find files inside the version directory that dfpm never installed."""
    if not root.is_dir():
        return ()
    found = []
    for directory, _, names in os.walk(root):
        for name in names:
            relative = (Path(directory) / name).relative_to(root).as_posix()
            if relative != METADATA_NAME and relative not in recorded:
                found.append(relative)
    return tuple(sorted(found))


def _delete(removal_plan: RemovalPlan, force: bool) -> None:
    for relative in removal_plan.removable + (removal_plan.modified if force else ()):
        path = removal_plan.root / relative
        if path.is_symlink() or not path.is_file():
            continue
        path.unlink()
    metadata = removal_plan.root / METADATA_NAME
    if metadata.is_file() and not metadata.is_symlink():
        metadata.unlink()
    _prune_directories(removal_plan.root)


def _prune_directories(root: Path) -> None:
    """Remove directories that are now empty, leaving any that still hold files."""
    if not root.is_dir():
        return
    for directory, _, _ in os.walk(root, topdown=False):
        with contextlib.suppress(OSError):
            Path(directory).rmdir()

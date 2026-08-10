from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

from . import shims
from .errors import InstallError
from .inventory import forget_package, read_package
from .storage import Storage, first_unremovable_file, remove_tree

METADATA_NAME = ".dfpm-install.json"


@dataclass(frozen=True)
class RemovalPlan:
    """What removing a package would delete.

    dfpm creates the version directory and nothing else writes to it, so the
    directory is the package. There is no per-file inventory to consult, which
    is what lets a tool that maintains its own files — updating rule sets,
    downloading data on first run — be removed without ceremony.
    """

    package: str
    name: str
    version: str
    root: Path
    file_count: int
    total_size: int
    installed_count: int | None
    installed_size: int | None
    commands: tuple[str, ...]

    @property
    def grew(self) -> bool:
        """Whether the directory holds more files now than the install put there."""
        return self.installed_count is not None and self.file_count > self.installed_count


def plan(storage: Storage, package_id: str) -> RemovalPlan:
    """Describe what removing *package_id* would delete, before anything is touched."""
    state = read_package(storage, package_id)
    if state is None:
        raise InstallError(f"{package_id} is not installed")
    version = state["version"]
    root = storage.package_version(package_id, version)
    file_count, total_size = _measure(root)
    return RemovalPlan(
        package=package_id,
        name=state.get("name", package_id),
        version=version,
        root=root,
        file_count=file_count,
        total_size=total_size,
        installed_count=state.get("file_count"),
        installed_size=state.get("installed_size"),
        commands=tuple(sorted(item["name"] for item in state.get("entrypoints", []))),
    )


def execute(storage: Storage, removal_plan: RemovalPlan, *, reconcile: bool = True) -> None:
    """Remove the version directory, then the command shortcuts it owned.

    The order matters. Files go first and the record is forgotten only once they
    are gone, so a removal that fails half way leaves dfpm still knowing about
    the package rather than believing it removed something it did not.

    Reconciling shims rebuilds every command from every remaining record, so a
    caller removing several packages should pass `reconcile=False` and do it
    once at the end. Doing it per package is the same answer computed N times.
    """
    if removal_plan.root.exists():
        if not storage.contains_package(removal_plan.root):
            raise InstallError(
                f"Refusing to remove {removal_plan.root}: it is not a package directory inside {storage.tools}"
            )
        if not remove_tree(removal_plan.root):
            stuck = first_unremovable_file(removal_plan.root)
            detail = f"\n  {stuck}" if stuck else ""
            raise InstallError(
                f"Could not remove {removal_plan.root}. A file there is in use by another program:{detail}\n"
                "Close whatever is reading it and run the removal again. Everything already deleted stays "
                "deleted, so a second run picks up where this one stopped."
            )
    forget_package(storage, removal_plan.package)
    if reconcile:
        shims.reconcile(storage)
    with contextlib.suppress(OSError):
        (storage.tools / removal_plan.package).rmdir()


def _measure(root: Path) -> tuple[int, int]:
    """Count the files in the version directory and add up their sizes.

    dfpm's own install record is skipped, so the count can be compared against
    what the install put there without being permanently one out.
    """
    if not root.is_dir():
        return 0, 0
    count = 0
    total = 0
    for directory, _, names in os.walk(root):
        for name in names:
            path = Path(directory) / name
            if path.parent == root and name == METADATA_NAME:
                continue
            count += 1
            with contextlib.suppress(OSError):
                total += path.lstat().st_size
    return count, total

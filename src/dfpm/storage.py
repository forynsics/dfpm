from __future__ import annotations

import os
import shutil
import stat
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .names import checked_package_id, checked_version

TREE_REMOVAL_DELAYS = (0, 0.1, 0.3, 1.0)


def _make_writable(action, path: str, exception: BaseException) -> None:
    """Clear a read-only flag and try the delete again.

    Read-only files are common inside real packages — version control marks its
    pack files that way because they are immutable, so any tool shipping a
    checkout brings some along. On Windows a read-only file cannot be deleted at
    all, and no amount of waiting changes that, so the flag has to be cleared
    rather than retried around.

    Only that one condition is handled. Anything else is raised on unchanged: a
    delete failing for a reason nobody predicted should stop and be reported,
    not be forced past. A handler that swallows every error is how a package
    manager ends up deleting something it should not have.
    """
    if not isinstance(exception, PermissionError):
        raise exception
    try:
        # Add write permission rather than replacing the mode, so nothing else
        # about the file is changed on the way to removing it.
        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
    except OSError:
        raise exception from None
    action(path)


def first_unremovable_file(root: Path) -> Path | None:
    """Find a file under *root* that cannot be opened for writing.

    Only ever called after a removal has already failed, so walking the whole
    tree costs nothing that matters, and naming the file saves the user hunting
    for it.
    """
    for directory, _, names in os.walk(root):
        for name in names:
            path = Path(directory) / name
            try:
                handle = os.open(path, os.O_RDWR)
            except OSError:
                return path
            os.close(handle)
    return None


def _rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_make_writable)
    else:  # pragma: no cover - onexc replaced onerror in 3.12
        shutil.rmtree(path, onerror=lambda action, name, info: _make_writable(action, name, info[1]))


def remove_tree(path: Path) -> bool:
    """Delete a directory tree, clearing read-only flags and retrying briefly.

    Two different things stop a delete on Windows and they need different
    answers. A read-only file never becomes deletable on its own, so the flag is
    cleared. A file being read by antivirus or the search indexer becomes
    deletable a moment later, so that one is worth waiting out. Reports whether
    the directory actually went rather than swallowing the failure.
    """
    for delay in TREE_REMOVAL_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            _rmtree(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            continue
    return False


@dataclass(frozen=True)
class Storage:
    root: Path

    @classmethod
    def default(cls, environ: Mapping[str, str] | None = None, system: str | None = None) -> "Storage":
        """Locate the dfpm root for this operating system.

        The choice follows the OS, never the presence of an environment variable.
        WSL inherits Windows variables through WSLENV, so keying on LOCALAPPDATA
        would put a Linux root on /mnt/c, where the executable bit does not stick
        and the filesystem is case-insensitive.
        """
        environ = os.environ if environ is None else environ
        system = os.name if system is None else system
        if system == "nt":
            local_app_data = environ.get("LOCALAPPDATA")
            base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        else:
            data_home = environ.get("XDG_DATA_HOME")
            base = Path(data_home) if data_home else Path.home() / ".local" / "share"
        return cls(base / "dfpm")

    @property
    def tools(self) -> Path:
        return self.root / "tools"

    @property
    def cache(self) -> Path:
        return self.root / "cache" / "sha256"

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def bin(self) -> Path:
        return self.root / "bin"

    def package_version(self, package_id: str, version: str) -> Path:
        return self.tools / checked_package_id(package_id) / checked_version(version)

    def package_state(self, package_id: str) -> Path:
        return self.state / "packages" / f"{checked_package_id(package_id)}.json"

    def contains_package(self, path: Path) -> bool:
        """Whether *path* is a package directory this store owns.

        The check is the positive one — resolved, strictly beneath the tools
        directory, and exactly two levels down at <id>/<version>. Listing paths
        that must not be deleted would be an endless list that still missed the
        case nobody thought of.
        """
        try:
            target = path.resolve()
            store = self.tools.resolve()
        except OSError:
            return False
        if target == store or store not in target.parents:
            return False
        return len(target.relative_to(store).parts) == 2

    def initialize(self) -> None:
        for directory in (self.tools, self.cache, self.state / "packages", self.bin):
            directory.mkdir(parents=True, exist_ok=True)


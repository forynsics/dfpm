from __future__ import annotations

import os
import shutil
import stat
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

TREE_REMOVAL_DELAYS = (0, 0.1, 0.3, 1.0)


def _make_writable(action, path: str, _exception) -> None:
    """Clear a read-only flag and try the delete again.

    Read-only files are common inside real packages — git marks its pack files
    that way because they are immutable, so any tool shipping a checkout brings
    some along. On Windows a read-only file cannot be deleted at all, and no
    amount of waiting changes that, so the flag has to be cleared rather than
    retried around.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        return
    action(path)


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
        return self.tools / package_id / version

    def package_state(self, package_id: str) -> Path:
        return self.state / "packages" / f"{package_id}.json"

    def initialize(self) -> None:
        for directory in (self.tools, self.cache, self.state / "packages", self.bin):
            directory.mkdir(parents=True, exist_ok=True)


from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


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


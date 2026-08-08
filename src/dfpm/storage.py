from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Storage:
    root: Path

    @classmethod
    def default(cls) -> "Storage":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
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


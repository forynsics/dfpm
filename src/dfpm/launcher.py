from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import shims
from .errors import DfpmError
from .storage import Storage


@dataclass(frozen=True)
class Resolution:
    """Which file a command name runs, and how the shell would find it today."""

    name: str
    package: str
    version: str
    target: Path
    shim: Path

    @property
    def shim_exists(self) -> bool:
        return self.shim.is_file()


def resolve(storage: Storage, name: str) -> Resolution:
    """Find the file a command name runs, using the active version of each package."""
    planned = shims.planned(storage)
    shim = planned.get(name)
    if shim is None:
        available = ", ".join(sorted(planned)) if planned else "none"
        raise DfpmError(f"No installed package provides the command '{name}'. Available commands: {available}")
    return Resolution(name, shim.package, shim.version, shim.target, storage.bin / f"{name}.cmd")


def run(storage: Storage, name: str, arguments: list[str]) -> int:
    """Run a command from an installed package and return its exit code."""
    resolution = resolve(storage, name)
    if not resolution.target.is_file():
        raise DfpmError(
            f"{resolution.package} {resolution.version} records the command '{name}', "
            f"but the file it points to is missing: {resolution.target}. Run 'dfpm doctor'."
        )
    try:
        # The recorded target is run directly rather than through the shim, so arguments
        # reach the tool as a real argument list instead of being re-parsed by cmd.
        return subprocess.run([str(resolution.target), *arguments], check=False).returncode
    except OSError as exc:
        raise DfpmError(f"Could not run {resolution.target}: {exc}") from exc


def path_status(storage: Storage, name: str) -> tuple[str, str | None]:
    """Report how a bare command name would resolve on this shell's PATH right now."""
    found = shutil.which(name)
    if found is None:
        return "unreachable", None
    shim = storage.bin / f"{name}.cmd"
    try:
        same = Path(found).resolve() == shim.resolve()
    except OSError:
        same = False
    return ("dfpm", found) if same else ("shadowed", found)

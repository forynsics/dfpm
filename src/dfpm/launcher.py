from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import shims
from .errors import CommandNotFound, CommandNotRunnable
from .storage import Storage

BATCH_SUFFIXES = frozenset({".cmd", ".bat"})

# Characters cmd.exe acts on rather than passes through. Verified against a real
# batch target: '&' and '|' execute the text after them, '^' is consumed, '(' and
# ')' break the surrounding block, '"' shifts the argument boundaries, '>' and '<'
# redirect, and '%' expands an environment variable. Quoting does not save any of
# them, because the script's own expansion of %1 re-parses the value.
CMD_METACHARACTERS = frozenset('&|<>^()"%\r\n')


@dataclass(frozen=True)
class Resolution:
    """Which file a command name runs, and how the shell would find it today."""

    name: str
    package: str
    version: str
    target: Path
    shim: Path
    working_directory: Path

    @property
    def shim_exists(self) -> bool:
        return self.shim.is_file()


def resolve(storage: Storage, name: str) -> Resolution:
    """Find the file a command name runs, and the directory it should run from."""
    planned = shims.planned(storage)
    shim = planned.get(name)
    if shim is None:
        available = ", ".join(sorted(planned)) if planned else "none"
        raise CommandNotFound(f"No installed package provides the command '{name}'. Available commands: {available}")
    return Resolution(
        name, shim.package, shim.version, shim.target, storage.bin / f"{name}.cmd", shim.working_directory
    )


def run(storage: Storage, name: str, arguments: list[str]) -> int:
    """Run a command from an installed package and return its exit code.

    The command is launched from the directory the package expects rather than
    from wherever the caller happens to be, so a tool that resolves its own
    rules or configuration relative to the working directory finds them.
    """
    resolution = resolve(storage, name)
    _preflight(resolution, arguments)
    try:
        # The recorded target is run directly rather than through the shim, so there is
        # one less layer between dfpm and the tool. Windows still routes a batch target
        # through cmd, which is why _preflight guards that case.
        completed = subprocess.run(
            [str(resolution.target), *arguments],
            check=False,
            cwd=str(resolution.working_directory),
        )
    except OSError as exc:
        raise CommandNotRunnable(f"Could not run {resolution.target}: {exc}") from exc
    return completed.returncode


def _preflight(resolution: Resolution, arguments: list[str]) -> None:
    """Everything that has to hold before a command can be launched."""
    if not resolution.target.is_file():
        raise CommandNotRunnable(
            f"{resolution.package} {resolution.version} records the command '{resolution.name}', "
            f"but the file it points to is missing: {resolution.target}. Run 'dfpm doctor'."
        )
    if not resolution.working_directory.is_dir():
        raise CommandNotRunnable(
            f"'{resolution.name}' expects to run from {resolution.working_directory}, "
            "which is missing. Run 'dfpm doctor'."
        )
    _check_deliverable(resolution, arguments)


def _check_deliverable(resolution: Resolution, arguments: list[str]) -> None:
    """Refuse arguments cmd would re-parse on the way into a batch entrypoint.

    Windows runs a .cmd or .bat through cmd.exe, which parses the command line
    before the script sees it, and parses it again each time the script expands
    an argument. Nothing dfpm can do at this end makes that round-trip safe, so
    an argument that would not arrive intact is refused rather than mangled.
    """
    if resolution.target.suffix.lower() not in BATCH_SUFFIXES:
        return
    for argument in arguments:
        found = sorted({character for character in argument if character in CMD_METACHARACTERS})
        if not found:
            continue
        display = " ".join(repr(character) for character in found)
        raise CommandNotRunnable(
            f"'{resolution.name}' is a {resolution.target.suffix} script, and Windows runs it through cmd, "
            f"which would re-interpret {display} in the argument {argument!r} instead of passing it to the tool. "
            f"Run it directly to keep the argument intact: {resolution.target}"
        )


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

"""Detection of the platform runtimes packaged tools need.

dfpm does not install runtimes. It knows how to find one, read its version and
say what is missing, which is what lets a package declare `requires` without
every manifest author inventing its own detection. There is one entry here per
runtime, never one per package: knowing that Java reports its version on stderr
is knowledge about Java, not about any tool that happens to need it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .errors import DfpmError

PROBE_TIMEOUT_SECONDS = 15

# dotnet reports its frameworks separately, and they are separate installs. A
# tool needing the desktop framework is not satisfied by the base runtime.
DOTNET_FRAMEWORKS = {
    "base": "Microsoft.NETCore.App",
    "desktop": "Microsoft.WindowsDesktop.App",
    "aspnet": "Microsoft.AspNetCore.App",
}


@dataclass(frozen=True)
class Runtime:
    name: str
    display: str
    commands: tuple[str, ...]
    probe: tuple[str, ...]
    remediation: str
    flavors: frozenset[str] = frozenset()
    default_flavor: str | None = None
    # Where this runtime installs itself. Being on PATH and being installed are
    # different things, and for some runtimes a package does not need the first.
    # An entry may begin with an environment variable and is skipped when it is
    # unset, so one list covers every platform without branching on the system.
    install_roots: tuple[str, ...] = ()


KNOWN: dict[str, Runtime] = {
    "dotnet": Runtime(
        name="dotnet",
        display=".NET",
        commands=("dotnet",),
        probe=("--list-runtimes",),
        remediation="Install the .NET runtime from https://dotnet.microsoft.com/download",
        flavors=frozenset(DOTNET_FRAMEWORKS),
        default_flavor="base",
        install_roots=(
            "$DOTNET_ROOT",
            "$ProgramFiles/dotnet",
            "$ProgramW6432/dotnet",
            "$ProgramFiles(x86)/dotnet",
            "/usr/local/share/dotnet",
            "/usr/share/dotnet",
            "~/.dotnet",
        ),
    ),
    "java": Runtime(
        name="java",
        display="Java",
        commands=("java",),
        probe=("-version",),
        remediation="Install a Java runtime and make sure 'java' is on PATH",
    ),
    "python": Runtime(
        name="python",
        display="Python",
        commands=("python3", "python"),
        probe=("--version",),
        remediation="Install Python and make sure it is on PATH",
    ),
    "perl": Runtime(
        name="perl",
        display="Perl",
        commands=("perl",),
        probe=("-v",),
        remediation="Install Perl and make sure it is on PATH",
    ),
    "powershell": Runtime(
        name="powershell",
        display="PowerShell",
        commands=("pwsh", "powershell"),
        probe=("-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"),
        remediation="PowerShell ships with Windows; install PowerShell 7 from https://aka.ms/powershell",
    ),
}


@dataclass(frozen=True)
class Detection:
    """What was found on this machine for one runtime."""

    runtime: str
    path: Path | None = None
    version: tuple[int, ...] | None = None
    source: str = "path"
    detail: str = ""
    versions_by_flavor: dict[str, tuple[int, ...]] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return self.path is not None

    def version_text(self) -> str:
        return ".".join(str(part) for part in self.version) if self.version else "unknown"


def describe(name: str) -> Runtime:
    runtime = KNOWN.get(name)
    if runtime is None:
        raise DfpmError(f"Unknown runtime '{name}'. Known runtimes: {', '.join(sorted(KNOWN))}")
    return runtime


def parse_minimum(constraint: str) -> tuple[int, ...]:
    """Read a `>=N.N.N` constraint. Only `>=` is supported, deliberately."""
    text = constraint.strip()
    if not text.startswith(">="):
        raise DfpmError(f"Version constraint must start with '>=': {constraint!r}")
    digits = text[2:].strip()
    if not re.fullmatch(r"\d+(\.\d+)*", digits):
        raise DfpmError(f"Version constraint must be a dotted number after '>=': {constraint!r}")
    return tuple(int(part) for part in digits.split("."))


def satisfies(detected: tuple[int, ...] | None, minimum: tuple[int, ...] | None) -> bool:
    """Whether a detected version meets a minimum.

    An unreadable version does not satisfy a stated minimum. Treating it as a
    pass would let banner noise stand in for a real check, which is worse than
    reporting that the version could not be determined.
    """
    if minimum is None:
        return True
    if detected is None:
        return False
    return detected >= minimum


def detect(name: str, storage=None, *, cache: dict | None = None) -> Detection:
    """Find a runtime, preferring one dfpm installed over one on PATH."""
    if cache is not None and name in cache:
        return cache[name]
    result = _detect(describe(name), storage)
    if cache is not None:
        cache[name] = result
    return result


def _detect(runtime: Runtime, storage) -> Detection:
    """Probe every candidate and keep the best answer.

    A runtime can go by more than one name, and which name is the real one
    differs by platform: `python3` is the safe choice where `python` might be a
    much older release, and on Windows it is usually a stub that offers to
    install Python rather than being one. Asking each candidate what version it
    is and taking the highest answers that without dfpm having to encode which
    platform prefers which name.
    """
    packaged = _from_packages(runtime, storage)
    if packaged is not None:
        return _probe(runtime, *packaged)
    on_path = _candidates_on_path(runtime)
    candidates = [(path, "path") for path in on_path]
    candidates += [(path, "install") for path in _installed_locations(runtime) if path not in on_path]
    found = [_probe(runtime, path, source) for path, source in candidates]
    usable = [item for item in found if item.version is not None]
    if usable:
        # Ties keep the earlier candidate, so a runtime the user put on PATH
        # still wins over one merely found where its installer left it.
        return max(usable, key=lambda item: item.version or ())
    # Found but unreadable is a different report from not found at all.
    return found[0] if found else Detection(runtime.name, detail="not found")


def _from_packages(runtime: Runtime, storage) -> tuple[Path, str] | None:
    """A runtime dfpm installed wins, so a catalogued runtime is used when present."""
    if storage is None:
        return None
    from . import shims

    try:
        planned = shims.planned(storage)
    except Exception:
        return None
    for command in runtime.commands:
        shim = planned.get(command)
        if shim is not None and shim.target.is_file():
            return shim.target, f"dfpm:{shim.package}"
    return None


def _candidates_on_path(runtime: Runtime) -> list[Path]:
    candidates: list[Path] = []
    for command in runtime.commands:
        found = _safe_which(command)
        if found is not None and found not in candidates:
            candidates.append(found)
    return candidates


def _installed_locations(runtime: Runtime) -> list[Path]:
    """Find a runtime where its installer puts it, for a machine where it is not on PATH.

    A framework-dependent .NET application resolves its runtime through the
    platform's own install location, so such a package runs perfectly well on a
    machine where `dotnet` is not a command at all. Looking only on PATH reports
    that machine as missing the runtime and refuses to launch something that
    works — and PATH is inherited when a process starts, so a shell opened
    before the runtime was installed will not see it however long it stays open.

    This is not a relaxation of the check. What is found here is still run and
    still asked its version; it is only searched for in one more place.
    """
    found: list[Path] = []
    for template in runtime.install_roots:
        root = _expand(template)
        if root is None or not root.is_dir():
            continue
        for command in runtime.commands:
            for name in (command, f"{command}.exe"):
                candidate = root / name
                if candidate.is_file() and candidate not in found:
                    found.append(candidate)
    return found


def _expand(template: str) -> Path | None:
    """Resolve an install root, which may begin with an environment variable or a home directory."""
    head, _, tail = template.partition("/")
    if head.startswith("$"):
        base = os.environ.get(head[1:])
        if not base:
            return None
        head = base
    try:
        root = Path(head).expanduser()
    except (OSError, RuntimeError):
        return None
    return root / tail if tail else root


def _safe_which(command: str) -> Path | None:
    """Find a command on PATH without ever returning dfpm's own interpreter.

    dfpm runs on Python, and when it is installed into a virtual environment of
    its own that environment's scripts directory sits at the front of PATH. An
    unguarded lookup for `python` therefore answers with the interpreter dfpm
    happens to be running on, which describes how dfpm was installed rather than
    anything about this machine.

    Only that environment is excluded, and only when there is one. The Python it
    was built from is the machine's own and a perfectly good answer. So is a
    virtual environment the user activated, which is what `python` means in
    their shell right now — excluding it would override a choice they made
    deliberately. This is the only place in dfpm that names sys.executable.
    """
    blocked: set[Path] = set()
    if sys.prefix != sys.base_prefix:
        for candidate in (sys.prefix, str(Path(sys.executable).parent)):
            try:
                blocked.add(Path(candidate).resolve())
            except OSError:
                continue
    entries = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            resolved = Path(entry).resolve()
        except OSError:
            continue
        if resolved in blocked or any(parent in blocked for parent in resolved.parents):
            continue
        entries.append(entry)
    found = shutil.which(command, path=os.pathsep.join(entries))
    if found is None:
        return None
    path = Path(found)
    if blocked:
        # Catches an interpreter reached through a link from outside the
        # environment, which the directory filter above would not see.
        try:
            if path.resolve() == Path(sys.executable).resolve():
                return None
        except OSError:
            pass
    return path


def _probe(runtime: Runtime, path: Path, source: str) -> Detection:
    try:
        completed = subprocess.run(
            [str(path), *runtime.probe],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Detection(runtime.name, path=path, source=source, detail=f"could not be run: {exc}")
    # Java writes its version to stderr, so both streams are always considered.
    output = f"{completed.stdout}\n{completed.stderr}"
    if runtime.name == "dotnet":
        by_flavor = _dotnet_frameworks(output)
        newest = max(by_flavor.values(), default=None)
        return Detection(runtime.name, path=path, version=newest, source=source, versions_by_flavor=by_flavor)
    return Detection(runtime.name, path=path, version=_version_from(runtime.name, output), source=source)


def _dotnet_frameworks(output: str) -> dict[str, tuple[int, ...]]:
    """Read the newest version of each installed framework.

    Lines look like `Microsoft.NETCore.App 8.0.19 [C:\\Program Files\\dotnet\\...]`.
    """
    newest: dict[str, tuple[int, ...]] = {}
    for line in output.splitlines():
        match = re.match(r"\s*(\S+)\s+(\d+(?:\.\d+)*)", line)
        if match is None:
            continue
        framework, digits = match.group(1), match.group(2)
        for flavor, expected in DOTNET_FRAMEWORKS.items():
            if framework == expected:
                version = tuple(int(part) for part in digits.split("."))
                if version > newest.get(flavor, ()):
                    newest[flavor] = version
    return newest


_VERSION_PATTERNS = {
    "java": (r'version "([\d._]+)"',),
    "python": (r"Python (\d+(?:\.\d+)*)",),
    "perl": (r"v(\d+\.\d+\.\d+)", r"perl 5, version (\d+), subversion (\d+)"),
    "powershell": (r"(\d+(?:\.\d+)+)",),
}


def _version_from(name: str, output: str) -> tuple[int, ...] | None:
    for pattern in _VERSION_PATTERNS.get(name, ()):
        match = re.search(pattern, output)
        if match is None:
            continue
        if name == "perl" and match.re.pattern.startswith("perl 5"):
            return (5, int(match.group(1)), int(match.group(2)))
        parts = re.split(r"[._]", match.group(1))
        version = tuple(int(part) for part in parts if part.isdigit())
        return _normalise(name, version)
    return None


def _normalise(name: str, version: tuple[int, ...]) -> tuple[int, ...]:
    """Java before 9 reports 1.8.0 for what everyone calls 8."""
    if name == "java" and len(version) > 1 and version[0] == 1:
        return version[1:]
    return version


def check(requirement, storage=None, *, cache: dict | None = None) -> tuple[bool, Detection, str]:
    """Test one requirement, returning whether it holds and how to say so."""
    runtime = describe(requirement.runtime)
    detection = detect(requirement.runtime, storage, cache=cache)
    minimum = parse_minimum(requirement.version) if requirement.version else None
    flavor = requirement.flavor or runtime.default_flavor

    if not detection.found:
        return False, detection, f"{runtime.display} was not found"

    if requirement.runtime == "dotnet":
        available = detection.versions_by_flavor.get(flavor or "base")
        label = f"{runtime.display} {flavor}" if flavor and flavor != "base" else runtime.display
        if available is None:
            return False, detection, f"{label} runtime is not installed"
        if not satisfies(available, minimum):
            return False, detection, f"{label} {_text(available)} is installed, below the required {_text(minimum)}"
        return True, detection, f"{label} {_text(available)}"

    if not satisfies(detection.version, minimum):
        if detection.version is None:
            return False, detection, f"{runtime.display} was found but did not report a version dfpm could read"
        return False, detection, f"{runtime.display} {detection.version_text()} is below the required {_text(minimum)}"
    return True, detection, f"{runtime.display} {detection.version_text()}"


def _text(version: tuple[int, ...] | None) -> str:
    return ".".join(str(part) for part in version) if version else "unknown"

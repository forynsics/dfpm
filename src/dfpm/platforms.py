from __future__ import annotations

import platform

SUPPORTED_SYSTEMS = frozenset({"windows", "linux", "macos"})
SUPPORTED_ARCHITECTURES = frozenset({"x86", "x64", "arm64"})

_SYSTEMS = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}
_ARCHITECTURES = {
    "AMD64": "x64",
    "x86_64": "x64",
    "ARM64": "arm64",
    "aarch64": "arm64",
    "x86": "x86",
    "i386": "x86",
    "i686": "x86",
}


def current() -> tuple[str, str]:
    """Report this machine as a (system, architecture) pair using dfpm's vocabulary."""
    system = _SYSTEMS.get(platform.system(), platform.system().lower())
    architecture = _ARCHITECTURES.get(platform.machine(), platform.machine().lower())
    return system, architecture

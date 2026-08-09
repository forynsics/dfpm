from __future__ import annotations

import re

from .errors import DfpmError

# A package identity and a version both become directory names, so both are
# checked wherever a path is built from them rather than only where a manifest
# is read. A removal takes its package name straight from a command line or an
# API request, and neither has been anywhere near a manifest.
PACKAGE_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")

INVALID_CHARACTERS = frozenset('<>:"|?*/\\')
RESERVED_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)


def checked_package_id(value: str) -> str:
    """Return *value* if it can safely become a directory name, or raise."""
    if not isinstance(value, str) or not PACKAGE_ID.fullmatch(value) or unsafe_reason(value):
        raise DfpmError(f"Not a usable package name: {value!r}")
    return value


def checked_version(value: str) -> str:
    if not isinstance(value, str) or not VERSION.fullmatch(value) or unsafe_reason(value):
        raise DfpmError(f"Not a usable version: {value!r}")
    return value


def unsafe_reason(name: str) -> str | None:
    """Explain why *name* cannot be used as one Windows path component, or return None."""
    if not name:
        return "is empty"
    if name in {".", ".."}:
        return "is a parent or self reference"
    if any(character in INVALID_CHARACTERS for character in name):
        return "contains a character that is not allowed in a file name"
    if any(ord(character) < 32 for character in name):
        return "contains a control character"
    if name != name.rstrip(" ."):
        return "ends with a space or a dot"
    if name.split(".")[0].lower() in RESERVED_DEVICE_NAMES:
        return "is a reserved Windows device name"
    return None

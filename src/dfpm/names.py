from __future__ import annotations

INVALID_CHARACTERS = frozenset('<>:"|?*/\\')
RESERVED_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)


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

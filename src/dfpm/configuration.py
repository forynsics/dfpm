from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import DfpmError

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RootChoice:
    path: Path
    source: str
    configuration: Path


def file(environ: Mapping[str, str] | None = None, system: str | None = None) -> Path:
    """Return the fixed bootstrap file used to locate dfpm's movable data root."""
    environ = os.environ if environ is None else environ
    system = os.name if system is None else system
    if system == "nt":
        local_app_data = environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    else:
        config_home = environ.get("XDG_CONFIG_HOME")
        base = Path(config_home) if config_home else Path.home() / ".config"
    return base / "dfpm" / "config.json"


def configured_root(environ: Mapping[str, str] | None = None, system: str | None = None) -> Path | None:
    path = file(environ, system)
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DfpmError(f"Could not read dfpm configuration {path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise DfpmError(f"dfpm configuration has an unsupported format: {path}")
    root = document.get("root")
    if not isinstance(root, str) or not root.strip():
        raise DfpmError(f"dfpm configuration does not contain a usable root: {path}")
    chosen = Path(root)
    if not chosen.is_absolute():
        raise DfpmError(f"The configured dfpm root is not absolute: {chosen}")
    return chosen


def choose_root(
    override: Path | None,
    default: Path,
    environ: Mapping[str, str] | None = None,
    system: str | None = None,
) -> RootChoice:
    configuration = file(environ, system)
    if override is not None:
        return RootChoice(override.resolve(), "command line", configuration)
    saved = configured_root(environ, system)
    if saved is not None:
        return RootChoice(saved, "saved configuration", configuration)
    return RootChoice(default, "platform default", configuration)


def set_root(root: Path, environ: Mapping[str, str] | None = None, system: str | None = None) -> Path:
    """Persist an absolute root with an atomic same-directory replacement."""
    chosen = root.resolve()
    if chosen.exists() and not chosen.is_dir():
        raise DfpmError(f"The dfpm root must be a directory, not a file: {chosen}")
    destination = file(environ, system)
    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        temporary = Path(temporary_name)
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            json.dump({"schema_version": SCHEMA_VERSION, "root": str(chosen)}, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    except OSError as exc:
        try:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise DfpmError(f"Could not save dfpm configuration {destination}: {exc}") from exc
    return chosen


def unset_root(environ: Mapping[str, str] | None = None, system: str | None = None) -> bool:
    destination = file(environ, system)
    try:
        existed = destination.exists()
        destination.unlink(missing_ok=True)
        return existed
    except OSError as exc:
        raise DfpmError(f"Could not remove dfpm configuration {destination}: {exc}") from exc

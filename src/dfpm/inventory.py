from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .storage import Storage


def read_package(storage: Storage, package_id: str) -> dict[str, Any] | None:
    path = storage.package_state(package_id)
    if not path.exists():
        return None
    return _normalize(json.loads(path.read_text(encoding="utf-8")))


def write_package(storage: Storage, package_id: str, state: dict[str, Any]) -> None:
    _atomic_json(storage.package_state(package_id), state)


def forget_package(storage: Storage, package_id: str) -> None:
    storage.package_state(package_id).unlink(missing_ok=True)


def list_packages(storage: Storage) -> list[dict[str, Any]]:
    package_dir = storage.state / "packages"
    if not package_dir.exists():
        return []
    return [_normalize(json.loads(path.read_text(encoding="utf-8"))) for path in sorted(package_dir.glob("*.json"))]


def _normalize(record: dict[str, Any]) -> dict[str, Any]:
    """Read records written by earlier versions of dfpm.

    Records written before "artifact" became "package" throughout the schema are
    read under the new names. Both matter: without the first, an existing install
    would stop being checked; without the second, the cache would think the file
    that package needs is unused and offer to delete it.

    Older ones again held a map of versions plus an active one, from before dfpm
    settled on one installed version per package. Flattening them here keeps an
    existing install working, and the record is rewritten in the current shape the next
    time the package is installed or removed.
    """
    if "artifact_sha256" in record and "package_sha256" not in record:
        record = dict(record)
        record["package_sha256"] = record.pop("artifact_sha256")
    if "health_checks" in record:
        record = dict(record)
        record.setdefault("verify", record.pop("health_checks"))
        record.pop("health_checks", None)
    if "version" in record or "versions" not in record:
        return record
    versions = record.get("versions") or {}
    chosen = record.get("active_version") or (sorted(versions)[-1] if versions else None)
    if chosen is None:
        return record
    flattened = {key: value for key, value in record.items() if key not in {"versions", "active_version", "activation_history"}}
    flattened.update(versions.get(chosen, {}))
    flattened["version"] = chosen
    return flattened


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            json.dump(data, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise

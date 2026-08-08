from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .storage import Storage


def read_package(storage: Storage, package_id: str) -> dict[str, Any] | None:
    path = storage.package_state(package_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_package(storage: Storage, package_id: str, state: dict[str, Any]) -> None:
    _atomic_json(storage.package_state(package_id), state)


def list_packages(storage: Storage) -> list[dict[str, Any]]:
    package_dir = storage.state / "packages"
    if not package_dir.exists():
        return []
    packages = []
    for path in sorted(package_dir.glob("*.json")):
        packages.append(json.loads(path.read_text(encoding="utf-8")))
    return packages


def export_lock(storage: Storage, destination: Path) -> dict[str, Any]:
    packages = list_packages(storage)
    lock = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "reproducibility": "hermetic",
        "packages": [
            {
                "id": package["id"],
                "active_version": package["active_version"],
                "versions": package["versions"],
            }
            for package in packages
        ],
        "system_prerequisites": [],
    }
    _atomic_json(destination, lock)
    return lock


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


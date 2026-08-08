from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ManifestError

PACKAGE_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
SUPPORTED_KINDS = {"tool", "runtime", "ruleset", "artifact-pack", "parser-pack", "integration", "config-pack"}


@dataclass(frozen=True)
class Artifact:
    source: str
    sha256: str
    size: int | None = None


@dataclass(frozen=True)
class Entrypoint:
    name: str
    path: str


@dataclass(frozen=True)
class HealthCheck:
    type: str
    path: str


@dataclass(frozen=True)
class Manifest:
    schema_version: int
    id: str
    name: str
    version: str
    kind: str
    description: str
    artifact: Artifact
    strip_components: int
    entrypoints: tuple[Entrypoint, ...]
    health_checks: tuple[HealthCheck, ...]
    source_path: Path
    digest: str

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        try:
            raw_bytes = path.read_bytes()
            data = json.loads(raw_bytes)
        except OSError as exc:
            raise ManifestError(f"Could not read manifest: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ManifestError(f"Manifest is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ManifestError("Manifest root must be an object")
        return cls._from_dict(data, path.resolve(), hashlib.sha256(raw_bytes).hexdigest())

    @classmethod
    def _from_dict(cls, data: dict[str, Any], path: Path, digest: str) -> "Manifest":
        required = ("schema_version", "id", "name", "version", "kind", "description", "artifact", "install")
        missing = [key for key in required if key not in data]
        if missing:
            raise ManifestError(f"Missing required fields: {', '.join(missing)}")
        if data["schema_version"] != 1:
            raise ManifestError("Only manifest schema_version 1 is supported")
        package_id = _text(data["id"], "id")
        if not PACKAGE_ID.fullmatch(package_id):
            raise ManifestError("id must contain lowercase letters, numbers, dots, underscores, or hyphens")
        kind = _text(data["kind"], "kind")
        if kind not in SUPPORTED_KINDS:
            raise ManifestError(f"Unsupported package kind: {kind}")

        artifact_data = _object(data["artifact"], "artifact")
        artifact_source = _text(artifact_data.get("source"), "artifact.source")
        artifact_hash = _text(artifact_data.get("sha256"), "artifact.sha256").lower()
        if not SHA256.fullmatch(artifact_hash):
            raise ManifestError("artifact.sha256 must be exactly 64 hexadecimal characters")
        size = artifact_data.get("size")
        if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
            raise ManifestError("artifact.size must be a non-negative integer")

        install = _object(data["install"], "install")
        if install.get("strategy") != "portable-zip":
            raise ManifestError("Only the portable-zip install strategy is currently supported")
        strip_components = install.get("strip_components", 0)
        if not isinstance(strip_components, int) or isinstance(strip_components, bool) or strip_components < 0:
            raise ManifestError("install.strip_components must be a non-negative integer")

        entrypoints = tuple(
            Entrypoint(_text(item.get("name"), "entrypoint.name"), _relative_path(item.get("path"), "entrypoint.path"))
            for item in _object_list(install.get("entrypoints", []), "install.entrypoints")
        )
        names = [item.name for item in entrypoints]
        if len(names) != len(set(names)):
            raise ManifestError("Entrypoint names must be unique")

        health_checks = tuple(
            HealthCheck(_text(item.get("type"), "health_check.type"), _relative_path(item.get("path"), "health_check.path"))
            for item in _object_list(data.get("health_checks", []), "health_checks")
        )
        if any(check.type != "file" for check in health_checks):
            raise ManifestError("Only file health checks are currently supported")

        return cls(
            schema_version=1,
            id=package_id,
            name=_text(data["name"], "name"),
            version=_text(data["version"], "version"),
            kind=kind,
            description=_text(data["description"], "description"),
            artifact=Artifact(artifact_source, artifact_hash, size),
            strip_components=strip_components,
            entrypoints=entrypoints,
            health_checks=health_checks,
            source_path=path,
            digest=digest,
        )

    def artifact_source(self) -> str:
        if "://" in self.artifact.source:
            return self.artifact.source
        return str((self.source_path.parent / self.artifact.source).resolve())


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{field} must be a non-empty string")
    return value.strip()


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{field} must be an object")
    return value


def _object_list(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ManifestError(f"{field} must be a list of objects")
    return value


def _relative_path(value: Any, field: str) -> str:
    text = _text(value, field).replace("\\", "/")
    candidate = Path(text)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ManifestError(f"{field} must stay within the package directory")
    return text


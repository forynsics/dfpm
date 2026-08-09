from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Sequence
from pathlib import Path


README_TEXT = "Synthetic dfpm test package\n"


def create_package(
    base: Path,
    *,
    package_id: str = "example.tool",
    version: str = "1.0.0",
    commands: Sequence[str] = ("example-tool",),
    body: str | None = None,
    extracted_size: int | None = None,
    entries: int | None = None,
    terms_url: str | None = None,
    working_directory: str | None = None,
    requires: list[dict] | None = None,
) -> tuple[Path, Path]:
    """Write a synthetic catalog entry and its artifact, returning (catalog, manifest path)."""
    catalog = base / "catalog"
    artifacts = catalog / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    archive = artifacts / f"{package_id}-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for command in commands:
            script = body if body is not None else f"@echo {command} {version}\r\n"
            output.writestr(f"example-tool/bin/{command}.cmd", script)
        output.writestr("example-tool/data/readme.txt", README_TEXT)
    artifact_bytes = archive.read_bytes()
    manifest = {
        "schema_version": 1,
        "id": package_id,
        "name": "Example Tool",
        "version": version,
        "kind": "tool",
        "description": "A synthetic package used to verify dfpm safely.",
        "artifact": {
            "source": f"artifacts/{archive.name}",
            "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            "size": len(artifact_bytes),
        },
        "install": {
            "strategy": "portable-zip",
            "strip_components": 1,
            "entrypoints": [
                {"name": command, "path": f"bin/{command}.cmd"}
                | ({"working_directory": working_directory} if working_directory else {})
                for command in commands
            ],
        },
        "health_checks": [{"type": "file", "path": "data/readme.txt"}],
    }
    if requires is not None:
        manifest["requires"] = requires
    if terms_url is not None:
        manifest["project"] = {"license": "LicenseRef-Example-EULA", "terms_url": terms_url}
    if extracted_size is not None:
        manifest["install"]["extracted_size"] = extracted_size
    if entries is not None:
        manifest["install"]["entries"] = entries
    manifest_path = catalog / f"{package_id}-{version}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return catalog, manifest_path

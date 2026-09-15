from __future__ import annotations

import hashlib
import json
import os
import zipfile
from collections.abc import Sequence
from pathlib import Path

README_TEXT = "Synthetic dfpm test package\n"

# Synthetic commands are scripts in whatever language this system runs natively,
# so the same tests exercise real launching on Windows and on POSIX.
WINDOWS = os.name == "nt"
SCRIPT_SUFFIX = ".cmd" if WINDOWS else ".sh"


def script_name(command: str) -> str:
    """The file a synthetic command is packaged as."""
    return f"{command}{SCRIPT_SUFFIX}"


def echo_script(text: str) -> str:
    return f"@echo {text}\r\n" if WINDOWS else f"#!/bin/sh\necho '{text}'\n"


def exit_script(code: int) -> str:
    return f"@exit /b {code}\r\n" if WINDOWS else f"#!/bin/sh\nexit {code}\n"


def record_arguments_script() -> str:
    """A command that writes the arguments it received to args.txt beside itself."""
    if WINDOWS:
        return '@echo %* > "%~dp0args.txt"\r\n'
    return '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$(dirname "$0")/args.txt"\n'


def report_directory_script(exit_code: int) -> str:
    """A command that writes the directory it was started in to where.txt in the package root."""
    if WINDOWS:
        return f'@echo off\r\n@echo %CD% > "%~dp0..\\where.txt"\r\nexit /b {exit_code}\r\n'
    return f'#!/bin/sh\npwd -P > "$(dirname "$0")/../where.txt"\nexit {exit_code}\n'


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
    platform: dict | None = None,
    stability: str | None = None,
    extra_builds: list[dict] | None = None,
) -> tuple[Path, Path]:
    """Write a synthetic catalog entry and its artifact, returning (catalog, manifest path).

    One tool with one build, which is what nearly every test wants. A test
    exercising selection passes extra_builds to add more.
    """
    catalog = base / "catalog"
    artifacts = catalog / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    archive = artifacts / f"{package_id}-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for command in commands:
            script = body if body is not None else echo_script(f"{command} {version}")
            output.writestr(f"example-tool/bin/{script_name(command)}", script)
        output.writestr("example-tool/data/readme.txt", README_TEXT)
    artifact_bytes = archive.read_bytes()

    install: dict = {
        "strategy": "portable-zip",
        "strip_components": 1,
        "entrypoints": [
            {"name": command, "path": f"bin/{script_name(command)}"}
            | ({"working_directory": working_directory} if working_directory else {})
            for command in commands
        ],
    }
    if extracted_size is not None:
        install["extracted_size"] = extracted_size
    if entries is not None:
        install["entries"] = entries

    build: dict = {
        "version": version,
        "package": {
            "url": f"artifacts/{archive.name}",
            "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            "size": len(artifact_bytes),
        },
        "install": install,
        "verify": [{"type": "file", "path": "data/readme.txt"}],
    }
    if stability is not None:
        build["package"]["stability"] = stability
    if platform is not None:
        build["platform"] = platform
    if requires is not None:
        build["requires"] = requires

    manifest: dict = {
        "schema_version": 1,
        "id": package_id,
        "name": "Example Tool",
        "kind": "tool",
        "description": "A synthetic package used to verify dfpm safely.",
        "builds": [build] + list(extra_builds or []),
    }
    if terms_url is not None:
        manifest["project"] = {"license": "LicenseRef-Example-EULA", "terms_url": terms_url}
    manifest_path = catalog / f"{package_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return catalog, manifest_path

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import classification, platforms
from .errors import ManifestError
from .manifest import Build, Manifest, Platform, Tool


# The entries reviewed at the time this version of dfpm was released. They are
# what a machine reads before anyone has curated a catalog of its own, so
# installing dfpm is enough to have something to install. Upgrading dfpm brings
# whatever had been reviewed by then; a catalog in the dfpm root takes over
# entirely once one exists.
SHIPPED = Path(__file__).resolve().parent / "entries"


def load_catalog(directory: Path) -> list[Tool]:
    """Every tool in the catalog, in the order a listing should show them."""
    if not directory.is_dir():
        # A machine with no catalog is the ordinary state of a fresh install
        # rather than a fault, so say what would fix it. Nothing is fetched
        # automatically: where entries come from is the operator's choice.
        raise ManifestError(
            f"No catalog on this machine: {directory}\n"
            f"Put reviewed package entries there, or point dfpm at a directory of them "
            f"with --catalog or the DFPM_CATALOG environment variable."
        )
    return [Tool.load(path) for path in sorted(directory.glob("*.json"))]


def resolve(directory: Path, package_id: str, version: str | None = None, platform: str | None = None) -> Manifest:
    """Choose one build of one tool: this machine's platform, newest version.

    Selection is explicit rather than incidental. Filtering by platform first
    matters because two builds of one version differ only in what they run on,
    and taking whichever happened to sort last would put a Linux binary on a
    Windows machine without ever saying so.
    """
    tools = [tool for tool in load_catalog(directory) if tool.id == package_id]
    if not tools:
        raise ManifestError(f"Package not found in catalog: {package_id}")
    tool = tools[0]

    wanted = _requested_platform(platform) if platform else platforms.current()
    builds = list(tool.builds)
    if version is not None:
        builds = [build for build in builds if build.version == version]
        if not builds:
            available = ", ".join(tool.versions())
            raise ManifestError(f"{package_id} has no version {version} in the catalog. It has: {available}")

    usable = [build for build in builds if build.platform is None or _matches(build.platform, wanted)]
    if not usable:
        offered = ", ".join(str(item) for item in tool.platforms()) or "none"
        raise ManifestError(
            f"{package_id} has no build for {wanted[0]}/{wanted[1]}. It ships builds for: {offered}"
        )
    usable.sort(key=lambda build: version_key(build.version))
    return tool.release(usable[-1])


def _matches(platform: Platform, wanted: tuple[str, str]) -> bool:
    return (platform.system, platform.architecture) == wanted


def _requested_platform(text: str) -> tuple[str, str]:
    """Read an explicitly requested platform, for staging a machine you are not sitting at."""
    parts = text.replace("\\", "/").split("/")
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise ManifestError(f"Platform must be written as os/arch, for example windows/x64: {text!r}")
    return parts[0].strip().lower(), parts[1].strip().lower()


def newer_than_installed(directory: Path, packages: list[dict[str, Any]]) -> dict[str, str]:
    """Which installed packages the catalog now offers a newer version of.

    This is a comparison and never a merge. The catalog says what is available
    and moves as projects publish releases; a record says what is installed and
    does not move at all. Reporting the difference is the whole point of
    keeping them apart.

    Selection runs through resolve, so a release that only ships for other
    platforms is not offered as an update to a machine that could not run it.
    A catalog that cannot be read yields nothing rather than failing: not
    knowing about an update is a smaller problem than being unable to list what
    is installed.
    """
    updates: dict[str, str] = {}
    for package in packages:
        installed = package.get("version")
        if not installed:
            continue
        try:
            candidate = resolve(directory, package["id"])
        except ManifestError:
            continue
        if version_key(candidate.version) > version_key(installed):
            updates[package["id"]] = candidate.version
    return updates


def newest(tool: Tool) -> Build:
    """The newest build of a tool regardless of platform, for listings."""
    return sorted(tool.builds, key=lambda build: version_key(build.version))[-1]


def describe(tool: Tool) -> dict[str, Any]:
    """Summarize a tool for listings, omitting optional sections that are absent.

    This is the one shape both interfaces read, so a tool reads the same way
    wherever it is shown. Classification carries its human labels alongside the
    keys, because a page should not have to know the vocabulary to display it,
    and platforms are listed because that is a property of the tool rather than
    of any one file.
    """
    entry: dict[str, Any] = {
        "id": tool.id,
        "name": tool.name,
        "kind": tool.kind,
        "description": tool.description,
        "version": newest(tool).version,
        "versions": list(tool.versions()),
        "platforms": [{"os": item.system, "arch": item.architecture} for item in tool.platforms()],
    }
    if tool.about:
        entry["about"] = tool.about
    for field in ("disciplines", "capabilities", "use_cases", "evidence"):
        keys = getattr(tool, field)
        if keys:
            entry[field] = [{"key": key, "label": classification.label(field, key)} for key in keys]
    commands: list[str] = []
    for build in tool.builds:
        for entrypoint in build.entrypoints:
            if entrypoint.name not in commands:
                commands.append(entrypoint.name)
    if commands:
        entry["commands"] = commands
    if tool.project is not None:
        recorded = {key: value for key, value in vars(tool.project).items() if value is not None}
        if recorded:
            entry["project"] = recorded
    return entry


def version_key(version: str) -> tuple[tuple[int, ...], int, str]:
    """Order versions by their leading numeric components, ranking prereleases below releases."""
    parts = re.split(r"[._+-]", version)
    release: list[int] = []
    for part in parts:
        if not part.isdigit():
            break
        release.append(int(part))
    return tuple(release), 0 if len(release) < len(parts) else 1, version

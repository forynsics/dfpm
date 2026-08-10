from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
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

# Names a catalog directory reserves for itself. The index lists what the
# directory holds, so that a published catalog can be read over HTTPS, where
# there is no way to list a directory.
INDEX_NAME = "index.json"
INDEX_SCHEMA_VERSION = 1


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
    return [Tool.load(path) for path in entry_files(directory)]


def entry_files(directory: Path) -> list[Path]:
    """The entry files in a catalog directory, in listing order.

    The index is skipped because it describes the directory rather than being
    a package in it. Keeping it inside the directory is deliberate: a catalog
    is then one folder that can be published, copied to a machine with no
    network, or mirrored, and still say what it contains.
    """
    return [path for path in sorted(directory.glob("*.json")) if path.name != INDEX_NAME]


def resolve(directory: Path, package_id: str, version: str | None = None, platform: str | None = None) -> Manifest:
    """Choose one build of one tool: this machine's platform, newest version.

    Selection is explicit rather than incidental. Filtering by platform first
    matters because two builds of one version differ only in what they run on,
    and taking whichever happened to sort last would put a Linux binary on a
    Windows machine without ever saying so.
    """
    return select(load_catalog(directory), package_id, version, platform)


def select(tools: list[Tool], package_id: str, version: str | None = None, platform: str | None = None) -> Manifest:
    """The same choice, made against a catalog that is already loaded.

    Resolving one package at a time reads and parses every entry in the
    directory each time, which is invisible for one package and quadratic-ish
    for a set of them. Asking for several is the ordinary case now, so the
    reading and the choosing are separable.
    """
    matches = [tool for tool in tools if tool.id == package_id]
    if not matches:
        raise ManifestError(f"Package not found in catalog: {package_id}")
    tool = matches[0]

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


def build_index(directory: Path) -> dict[str, Any]:
    """Describe what a catalog directory holds, so it can be published.

    Each entry carries its digest, which does two jobs. It says whether a copy
    arrived intact, and it says whether a copy is already current: a machine
    syncing this catalog compares digests and downloads only what differs, so
    an unchanged entry is never fetched twice. The newest version travels too,
    purely so a sync can describe what it is about to do without downloading
    anything first.
    """
    entries = []
    for path in entry_files(directory):
        tool = Tool.load(path)
        entries.append({
            "file": path.name,
            "id": tool.id,
            "version": newest(tool).version,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    index: dict[str, Any] = {"schema_version": INDEX_SCHEMA_VERSION, "entries": entries}
    # Collections travel with the entries or they exist only where they were
    # written. The key is optional and additive, so a reader that predates it
    # sees a catalog it already understands rather than one it must refuse.
    groups = []
    for path in sorted(collections_directory(directory).glob("*.json")) if collections_directory(directory).is_dir() else []:
        collection = Collection.load(path)
        groups.append({
            # Named relative to the catalog root, since this is both where to
            # fetch it from and where to put it.
            "file": f"{COLLECTIONS_DIRNAME}/{path.name}",
            "id": collection.id,
            "packages": len(collection.packages),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    if groups:
        index["collections"] = groups
    return index


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
    # A page saying an entry pins an exact artifact is telling the truth about
    # every build, and telling only half of it about one whose publisher replaces
    # the file at that address. The pin is what makes such a change visible, and
    # it is also what stops holding the day it happens.
    if any(build.package.rolling for build in tool.builds):
        entry["stability"] = "rolling"
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


# Collections live in a subdirectory of the catalog rather than beside the
# entries. The entry loader globs the top level only, so a collection can never
# be mistaken for a package, and a package manifest never has to grow a field
# describing which groups it happens to belong to.
COLLECTIONS_DIRNAME = "collections"

# A collection id must contain a hyphen. That looks arbitrary until you write
# one at a shell prompt: collections are requested as @name, and a shell that
# expands @word when word names a variable would silently pass something else
# entirely, or nothing at all. A name with a hyphen cannot be a variable, so the
# hazard stops being something a person has to remember.
COLLECTION_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")


@dataclass(frozen=True)
class Collection:
    """A named set of packages to request together.

    It holds ids and nothing else. A collection is never installed, never
    recorded, and never versioned: it says what to ask for, not what a machine
    promises to keep. That is what makes removing one of its members an
    ordinary removal rather than a question about whether the collection is
    still intact.
    """

    id: str
    name: str
    description: str
    packages: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> Collection:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"{path.name} could not be read: {exc}") from exc
        if not isinstance(data, dict):
            raise ManifestError(f"{path.name} must hold a JSON object")

        identifier = data.get("id")
        if not isinstance(identifier, str) or not COLLECTION_ID.fullmatch(identifier):
            raise ManifestError(
                f"{path.name}: collection id must be lowercase and contain a hyphen, so that "
                f"'@{identifier}' cannot be read as a variable by a shell. Got {identifier!r}."
            )
        packages = data.get("packages")
        if not isinstance(packages, list) or not packages or not all(isinstance(item, str) for item in packages):
            raise ManifestError(f"{path.name}: packages must be a non-empty list of package ids")
        seen: set[str] = set()
        for package_id in packages:
            if package_id in seen:
                raise ManifestError(f"{path.name}: lists {package_id!r} twice")
            seen.add(package_id)
        name = data.get("name")
        description = data.get("description")
        return cls(
            id=identifier,
            name=name if isinstance(name, str) and name.strip() else identifier,
            description=description if isinstance(description, str) else "",
            packages=tuple(packages),
        )


def collections_directory(directory: Path) -> Path:
    return directory / COLLECTIONS_DIRNAME


def load_collections(directory: Path) -> list[Collection]:
    """Every collection in a catalog, in listing order.

    A catalog with none is the ordinary case rather than a fault, so a missing
    directory reads as an empty list.
    """
    folder = collections_directory(directory)
    if not folder.is_dir():
        return []
    return [Collection.load(path) for path in sorted(folder.glob("*.json"))]


def check_collections(directory: Path) -> None:
    """Fail if any collection names a package the catalog does not have.

    Checked where the catalog is validated rather than when somebody installs,
    so a renamed entry breaks the catalog loudly instead of breaking one
    person's request quietly.
    """
    known = {tool.id for tool in load_catalog(directory)}
    for collection in load_collections(directory):
        missing = [package_id for package_id in collection.packages if package_id not in known]
        if missing:
            raise ManifestError(
                f"Collection {collection.id} names packages that are not in this catalog: {', '.join(missing)}"
            )

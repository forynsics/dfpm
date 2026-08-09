from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .downloads import file_digest
from .catalog import load_catalog
from .errors import DfpmError
from .inventory import list_packages
from .storage import Storage

DIGEST_NAME = re.compile(r"^[a-f0-9]{64}$")
SHORT_LENGTH = 16


@dataclass(frozen=True)
class Entry:
    """One verified download, and what still refers to it."""

    digest: str
    path: Path
    size: int
    installed_by: tuple[str, ...]
    listed_by: tuple[str, ...]

    @property
    def status(self) -> str:
        if self.installed_by:
            return "installed"
        if self.listed_by:
            return "catalog"
        return "orphan"

    @property
    def referenced_by(self) -> tuple[str, ...]:
        """Who still needs this, with a package that is both installed and listed named once."""
        return tuple(dict.fromkeys(self.installed_by + self.listed_by))


@dataclass(frozen=True)
class Survey:
    entries: tuple[Entry, ...] = ()
    partials: tuple[Path, ...] = ()
    unrecognized: tuple[Path, ...] = ()
    catalog_readable: bool = True
    catalog_error: str | None = None

    @property
    def total_size(self) -> int:
        return sum(entry.size for entry in self.entries)

    def with_status(self, status: str) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.status == status)


def survey(storage: Storage, catalog: Path | None = None) -> Survey:
    """Describe everything in the cache and what each artifact is still needed for."""
    installed = _installed_references(storage)
    listed, readable, error = _catalog_references(catalog)

    entries: list[Entry] = []
    partials: list[Path] = []
    unrecognized: list[Path] = []
    if storage.cache.is_dir():
        for path in sorted(storage.cache.iterdir()):
            if path.is_dir():
                unrecognized.append(path)
            elif path.name.endswith(".partial"):
                partials.append(path)
            elif DIGEST_NAME.fullmatch(path.name):
                entries.append(
                    Entry(
                        digest=path.name,
                        path=path,
                        size=path.stat().st_size,
                        installed_by=tuple(installed.get(path.name, ())),
                        listed_by=tuple(listed.get(path.name, ())),
                    )
                )
            else:
                unrecognized.append(path)
    return Survey(tuple(entries), tuple(partials), tuple(unrecognized), readable, error)


def verify(storage: Storage, catalog: Path | None = None) -> list[tuple[Entry, str | None]]:
    """Re-hash every artifact; the name is the digest, so a mismatch means corruption."""
    results = []
    for entry in survey(storage, catalog).entries:
        try:
            actual = file_digest(entry.path)
        except OSError as exc:
            results.append((entry, f"could not be read: {exc}"))
            continue
        results.append((entry, None if actual == entry.digest else "content does not match its digest"))
    return results


def removable(current: Survey, *, keep_catalog: bool = False) -> tuple[Entry, ...]:
    """Entries a prune would delete: anything no installed package needs."""
    if keep_catalog:
        return current.with_status("orphan")
    return tuple(entry for entry in current.entries if not entry.installed_by)


def delete(entries: tuple[Entry, ...], partials: tuple[Path, ...] = ()) -> int:
    """Delete the given artifacts, returning the bytes reclaimed."""
    reclaimed = 0
    for entry in entries:
        try:
            size = entry.path.stat().st_size
            entry.path.unlink()
        except OSError as exc:
            raise DfpmError(f"Could not remove {entry.path}: {exc}") from exc
        reclaimed += size
    for path in partials:
        try:
            reclaimed += path.stat().st_size
            path.unlink()
        except OSError:
            continue
    return reclaimed


def short(digest: str) -> str:
    """Shorten a digest for display, without adding characters that break a copy and paste."""
    return digest[:SHORT_LENGTH]


def find(current: Survey, digest: str) -> Entry:
    """Look up an artifact by its digest, or by enough leading characters to be unambiguous."""
    wanted = digest.strip().strip("….").lower()
    if not wanted or not re.fullmatch(r"[a-f0-9]+", wanted):
        raise DfpmError(f"'{digest}' is not a digest. Use a value shown by 'dfpm cache list'.")
    matches = [entry for entry in current.entries if entry.digest.startswith(wanted)]
    if not matches:
        raise DfpmError(f"No cached artifact starts with '{wanted}'")
    if len(matches) > 1:
        raise DfpmError(f"'{wanted}' matches {len(matches)} cached artifacts; use more characters")
    return matches[0]


def human(size: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def _installed_references(storage: Storage) -> dict[str, list[str]]:
    references: dict[str, list[str]] = defaultdict(list)
    for package in list_packages(storage):
        digest = package.get("package_sha256")
        if digest:
            references[digest].append(f"{package['id']} {package.get('version', '')}".strip())
    return references


def _catalog_references(catalog: Path | None) -> tuple[dict[str, list[str]], bool, str | None]:
    """Read the catalog, reporting failure rather than silently treating artifacts as unused."""
    if catalog is None:
        return {}, True, None
    try:
        manifests = load_catalog(catalog)
    except DfpmError as exc:
        return {}, False, str(exc)
    references: dict[str, list[str]] = defaultdict(list)
    for manifest in manifests:
        references[manifest.package.sha256].append(f"{manifest.id} {manifest.version}")
    return references, True, None

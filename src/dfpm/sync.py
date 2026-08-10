"""Bringing a machine's catalog into line with a published one.

A catalog is a directory of reviewed entries and an index describing them. That
is deliberately dull: it can be served by any static host, mirrored inside an
organisation, or carried to an isolated machine on removable media, and it says
what it contains without anything needing to list a directory for it.

Syncing writes the files that decide what software gets installed, so it is a
command somebody runs rather than something that happens quietly, it shows what
it would change before changing anything, and every entry has to parse as a
manifest before it is allowed to land.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import INDEX_NAME, INDEX_SCHEMA_VERSION, entry_files
from .errors import DfpmError
from .manifest import Tool
from .storage import remove_tree

# Where entries come from when nobody says otherwise: the project's own
# published catalog. A commit there is visible to every machine that syncs,
# without waiting for a release of dfpm itself.
DEFAULT_SOURCE = "https://raw.githubusercontent.com/forynsics/dfpm/main/catalog/"

# Collections are published inside the catalog rather than beside it, so their
# names carry the subdirectory and one comparison covers both kinds of file.
COLLECTION_PREFIX = "collections/"

MAX_FILE_BYTES = 1024 * 1024

ADDED, UPDATED, UNCHANGED, REMOVED, EDITED = "added", "updated", "unchanged", "removed", "edited"


@dataclass(frozen=True)
class Change:
    """One entry's fate in a sync."""

    file: str
    id: str
    version: str | None
    sha256: str | None
    kind: str


@dataclass
class Plan:
    """What syncing would do, worked out before a single entry is downloaded."""

    source: str
    directory: Path
    changes: list[Change] = field(default_factory=list)

    def of(self, *kinds: str) -> list[Change]:
        return [change for change in self.changes if change.kind in kinds]

    @property
    def fetches(self) -> list[Change]:
        """The entries whose bytes have to be downloaded, which is only what differs."""
        return self.of(ADDED, UPDATED, EDITED)

    @property
    def changes_anything(self) -> bool:
        return bool(self.fetches or self.of(REMOVED))


def plan(source: str, directory: Path) -> Plan:
    """Compare a published catalog against a local one, downloading only the index.

    The digest in the index is what makes this cheap: an entry already matching
    is never fetched again. The index this machine last wrote is kept too, which
    is what separates "the publisher changed it" from "somebody here changed
    it" — the second is worth saying out loud before it is overwritten.
    """
    published, published_collections = _read_index(source)
    local = {path.name: path for path in entry_files(directory)} if directory.is_dir() else {}
    last_synced = _local_index(directory)

    result = Plan(source=source, directory=directory)
    for entry in published:
        name = entry["file"]
        path = local.pop(name, None)
        if path is None:
            kind = ADDED
        else:
            here = hashlib.sha256(path.read_bytes()).hexdigest()
            if here == entry["sha256"]:
                kind = UNCHANGED
            elif name in last_synced and last_synced[name] != here:
                kind = EDITED
            else:
                kind = UPDATED
        result.changes.append(Change(name, entry["id"], entry.get("version"), entry["sha256"], kind))

    for entry in published_collections:
        name = entry["file"]
        path = local.pop(name, None)
        if path is None:
            path = directory / name
            path = path if path.is_file() else None
        if path is None:
            kind = ADDED
        elif hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]:
            kind = UNCHANGED
        else:
            kind = UPDATED
        result.changes.append(Change(name, entry["id"], None, entry["sha256"], kind))

    # Anything left is here and not there. It was withdrawn upstream, which
    # usually means something, so it goes rather than lingering as an offer
    # nobody stands behind. An installed package is unaffected: its record does
    # not depend on the catalog.
    for name in sorted(local):
        result.changes.append(Change(name, Path(name).stem, None, None, REMOVED))
    return result


def _must_be_a_collection(name: str, body: bytes) -> None:
    """Refuse a collection that will not load, before it reaches the catalog.

    A collection naming packages this catalog does not have is a real
    possibility across a sync, since entries and collections are published
    together but arrive as separate files. That is checked when the catalog is
    read rather than here, so a partial view never blocks a valid update.
    """
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise DfpmError(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("packages"), list):
        raise DfpmError(f"{name} does not describe a collection.")


def apply(current: Plan) -> list[Change]:
    """Fetch what differs and put it in place, having refused anything unreadable."""
    staged: dict[str, bytes] = {}
    for change in current.fetches:
        body = _read(_locate(current.source, change.file))
        actual = hashlib.sha256(body).hexdigest()
        if actual != change.sha256:
            # A published catalog is usually served through a cache, and an
            # index updated moments ago can arrive alongside files that have
            # not caught up. That looks exactly like tampering from here, so
            # the refusal stands -- but it is worth saying which is likelier.
            stale = ""
            if urllib.parse.urlparse(current.source).scheme in {"https", "http"}:
                stale = (
                    "\nA catalog updated in the last few minutes can serve an index newer than "
                    "the files it describes. If it was just published, try again shortly."
                )
            raise DfpmError(
                f"{change.file} does not match the digest its index recorded.\n"
                f"  expected {change.sha256}\n  found    {actual}{stale}"
            )
        if change.file.startswith(COLLECTION_PREFIX):
            _must_be_a_collection(change.file, body)
        else:
            _must_be_an_entry(change.file, body)
        staged[change.file] = body

    # Nothing is written until every entry has been fetched and read, so a
    # source that fails halfway leaves the catalog as it was rather than
    # half-updated.
    current.directory.mkdir(parents=True, exist_ok=True)
    for name, body in staged.items():
        target = current.directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    for change in current.of(REMOVED):
        (current.directory / change.file).unlink(missing_ok=True)

    kept = [change for change in current.changes if change.kind != REMOVED]
    index: dict = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "entries": [
            {"file": item.file, "id": item.id, "version": item.version, "sha256": item.sha256}
            for item in kept if not item.file.startswith(COLLECTION_PREFIX)
        ],
    }
    groups = [
        {"file": item.file, "id": item.id, "sha256": item.sha256}
        for item in kept if item.file.startswith(COLLECTION_PREFIX)
    ]
    if groups:
        index["collections"] = groups
    (current.directory / INDEX_NAME).write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return current.fetches + current.of(REMOVED)


def _must_be_an_entry(name: str, body: bytes) -> None:
    """Refuse anything that is not a manifest, rather than storing it and finding out later."""
    staging = Path(tempfile.mkdtemp(prefix="dfpm-sync-"))
    try:
        candidate = staging / Path(name).name
        candidate.write_bytes(body)
        Tool.load(candidate)
    except DfpmError as exc:
        raise DfpmError(f"{name} from the published catalog is not a usable entry: {exc}") from exc
    finally:
        remove_tree(staging)


def _local_index(directory: Path) -> dict[str, str]:
    """What this machine recorded the last time it synced, if it ever has."""
    path = directory / INDEX_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {entry["file"]: entry["sha256"] for entry in data["entries"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _published_collections(document: dict, source: str) -> list[dict]:
    """The collections a published index names, validated as paths before use.

    Optional by design: a catalog offering none, and an older published index
    that has never heard of them, are the same thing here. The names are read
    as untrusted text, exactly as entry names are, because they too decide
    where bytes get written. A collection may live in one place and nowhere
    else.
    """
    groups = document.get("collections") or []
    if not isinstance(groups, list):
        raise DfpmError(f"The catalog index at {source} does not list collections as an array.")
    for group in groups:
        if not isinstance(group, dict) or not {"file", "id", "sha256"} <= set(group):
            raise DfpmError(f"The catalog index at {source} has a collection missing file, id or sha256.")
        name = group["file"]
        stem = name[len(COLLECTION_PREFIX):] if name.startswith(COLLECTION_PREFIX) else ""
        if not stem or stem != Path(stem).name or stem.startswith(".") or not stem.endswith(".json"):
            raise DfpmError(f"The catalog index names a collection dfpm will not write: {name!r}")
    return groups


def _read_index(source: str) -> tuple[list[dict], list[dict]]:
    """The entries and collections a published catalog declares."""
    raw = _read(_locate(source, INDEX_NAME))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DfpmError(f"The catalog index at {source} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != INDEX_SCHEMA_VERSION:
        declared = data.get("schema_version") if isinstance(data, dict) else "nothing"
        raise DfpmError(
            f"The catalog index at {source} declares schema_version {declared}, which this dfpm cannot read."
        )
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise DfpmError(f"The catalog index at {source} does not list any entries.")
    for entry in entries:
        if not isinstance(entry, dict) or not {"file", "id", "sha256"} <= set(entry):
            raise DfpmError(f"The catalog index at {source} has an entry missing file, id or sha256.")
        name = entry["file"]
        # The index names files that will be written into a directory, so it is
        # read as untrusted text rather than as a path.
        if name != Path(name).name or name.startswith(".") or not name.endswith(".json"):
            raise DfpmError(f"The catalog index names a file dfpm will not write: {name!r}")
        if name == INDEX_NAME:
            raise DfpmError("The catalog index lists itself as an entry.")
    return entries, _published_collections(data, source)


def _locate(source: str, name: str) -> str:
    """Address one file within a catalog source.

    A URL is joined as a URL and a directory as a path. They cannot share one
    rule: joining a Windows path as a URL reads the drive letter as a scheme
    and throws the rest away.
    """
    if urllib.parse.urlparse(source).scheme in {"https", "http", "file", "ftp"}:
        return urllib.parse.urljoin(source, name)
    return str(Path(source) / name)


def _read(location: str) -> bytes:
    """Read a published file, over HTTPS or from a directory on disk."""
    parsed = urllib.parse.urlparse(location)
    if parsed.scheme == "https":
        request = urllib.request.Request(location, headers={"User-Agent": "dfpm/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if urllib.parse.urlparse(response.geturl()).scheme != "https":
                    raise DfpmError("The catalog source redirected to an insecure address.")
                body = response.read(MAX_FILE_BYTES + 1)
        except OSError as exc:
            raise DfpmError(f"Could not read {location}: {exc}") from exc
    elif parsed.scheme == "file":
        body = _read_file(Path(urllib.request.url2pathname(parsed.path)))
    elif not parsed.scheme or len(parsed.scheme) == 1:  # a bare path, or a Windows drive letter
        body = _read_file(Path(location))
    else:
        raise DfpmError(f"A catalog source must be an HTTPS address or a directory: {location}")
    if len(body) > MAX_FILE_BYTES:
        raise DfpmError(f"{location} is larger than dfpm will read for a catalog file.")
    return body


def _read_file(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise DfpmError(f"Could not read {path}: {exc}") from exc

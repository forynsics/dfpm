"""What a request means, and what it would cost, worked out before anything happens.

Installing one package could decide as it went: resolve it, check it, fetch it,
and fail wherever it failed. Installing several cannot. A set that stops halfway
has already written some of itself to disk, and the person who approved it
approved something other than what they got.

So the deciding is separated from the doing. Everything here reads: it resolves
names, works out what would be installed and what would be replaced, adds up
what that costs, and reports what stands in the way. Nothing here writes. The
result is one object a caller can render, put in front of a person, and then act
on -- which is what lets the command line and the local interface ask the same
question and get the same answer, instead of each working it out separately and
drifting apart.

Three outcomes per package, and the distinction between them is the whole point:
something to do, nothing to do, and something in the way. Only the third stops
the operation.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from . import catalog as catalogs
from . import installer, removal, runtimes
from .errors import DfpmError
from .manifest import Manifest
from .storage import Storage

# Why a package cannot proceed. These are compared by callers deciding how to
# report and what flag would clear them, so they are values rather than prose.
NOT_IN_CATALOG = "not-in-catalog"
NO_BUILD = "no-build"
WRONG_PLATFORM = "wrong-platform"
TERMS_NOT_ACCEPTED = "terms-not-accepted"
DESTINATION_IN_THE_WAY = "destination-in-the-way"
NOT_INSTALLED = "not-installed"
UNREADABLE = "unreadable"


@dataclass(frozen=True)
class Blocked:
    """A package that will not be acted on, and the reason a person needs."""

    package: str
    reason: str
    detail: str


@dataclass(frozen=True)
class Skipped:
    """A package that needs no work, which is not the same as one that failed."""

    package: str
    version: str
    detail: str


@dataclass(frozen=True)
class Incoming:
    """One package that would be installed, and what it would displace."""

    manifest: Manifest
    destination: Path
    previous: str | None = None
    outgoing: removal.RemovalPlan | None = None

    @property
    def package(self) -> str:
        return self.manifest.id

    @property
    def download_size(self) -> int:
        return self.manifest.package.size or 0

    @property
    def extracted_size(self) -> int:
        return self.manifest.extracted_size or 0

    @property
    def entry_count(self) -> int:
        return self.manifest.entry_count or 0


@dataclass(frozen=True)
class Requirement:
    """A runtime some packages need, and whether this machine has it."""

    runtime: str
    flavor: str | None
    version: str | None
    met: bool
    detail: str
    remediation: str
    wanted_by: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    """One answer for a whole request, whatever its size."""

    incoming: tuple[Incoming, ...] = ()
    outgoing: tuple[removal.RemovalPlan, ...] = ()
    skipped: tuple[Skipped, ...] = ()
    blocked: tuple[Blocked, ...] = ()
    requirements: tuple[Requirement, ...] = ()
    free_space: int | None = None

    @property
    def actionable(self) -> bool:
        """Whether anything would actually happen."""
        return bool(self.incoming or self.outgoing)

    @property
    def download_size(self) -> int:
        return sum(item.download_size for item in self.incoming)

    @property
    def extracted_size(self) -> int:
        return sum(item.extracted_size for item in self.incoming)

    @property
    def entry_count(self) -> int:
        return sum(item.entry_count for item in self.incoming)

    @property
    def reclaimed_size(self) -> int:
        return sum(item.total_size for item in self.outgoing)

    @property
    def reclaimed_files(self) -> int:
        return sum(item.file_count for item in self.outgoing)

    @property
    def terms(self) -> tuple[tuple[str, str], ...]:
        """Every package in the set whose terms have to be accepted, named.

        Collected rather than met one at a time, because a single confirmation
        covering a list nobody was shown is not acceptance of anything.
        """
        found = []
        for item in self.incoming:
            project = item.manifest.project
            if project is not None and project.terms_url:
                found.append((item.manifest.name, project.terms_url))
        return tuple(found)

    @property
    def rolling(self) -> tuple[str, ...]:
        """Packages whose publisher replaces the file at the URL being fetched."""
        return tuple(item.manifest.name for item in self.incoming if item.manifest.package.rolling)

    @property
    def unmet(self) -> tuple[Requirement, ...]:
        return tuple(item for item in self.requirements if not item.met)

    @property
    def fits(self) -> bool | None:
        """Whether the volume has room, or None when free space is unknown.

        Compared against the extracted size rather than the download, since the
        download is transient and what stays is what has to fit.
        """
        if self.free_space is None:
            return None
        return self.free_space >= self.extracted_size


def resolve(directory: Path, requested: list[str], version: str | None = None,
            platform: str | None = None) -> tuple[list[Manifest], list[Blocked]]:
    """Turn requested names into manifests, reading the catalog once.

    A name that cannot be resolved is reported rather than raised, because one
    unknown name in a list of twenty should not decide the fate of the other
    nineteen. Deciding what to do about it belongs to the caller.
    """
    tools = catalogs.load_catalog(directory)
    found: list[Manifest] = []
    blocked: list[Blocked] = []
    for package_id in _deduplicate(requested):
        try:
            found.append(catalogs.select(tools, package_id, version, platform))
        except DfpmError as exc:
            reason = NOT_IN_CATALOG if "not found" in str(exc) else NO_BUILD
            blocked.append(Blocked(package_id, reason, str(exc)))
    return found, blocked


def _deduplicate(requested: list[str]) -> list[str]:
    """The same names, each once, in the order they were first asked for.

    Order is kept because it is the order a person will read the plan in, and
    seeing their own list back is how they check it is the list they meant.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for name in requested:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def for_install(storage: Storage, directory: Path, requested: list[str], *,
                version: str | None = None, accept_terms: bool = False) -> Plan:
    """What installing these packages would do."""
    manifests, blocked = resolve(directory, requested, version)
    incoming: list[Incoming] = []
    skipped: list[Skipped] = []

    for manifest in manifests:
        try:
            installer.check_platform(manifest)
        except DfpmError as exc:
            blocked.append(Blocked(manifest.id, WRONG_PLATFORM, str(exc)))
            continue

        record = _installed_version(storage, manifest.id)
        if record == manifest.version:
            # Nothing to do is a fine outcome. Treating it as a failure would
            # make 'install these twenty' unusable the moment one is present.
            skipped.append(Skipped(manifest.id, manifest.version, "already at this version"))
            continue

        destination = storage.package_version(manifest.id, manifest.version)
        if destination.exists():
            blocked.append(Blocked(
                manifest.id,
                DESTINATION_IN_THE_WAY,
                f"{destination} already exists, left by an interrupted install. Remove it and try again.",
            ))
            continue

        outgoing = None
        if record is not None:
            try:
                outgoing = removal.plan(storage, manifest.id)
            except DfpmError:
                # A record without a readable directory still replaces cleanly;
                # what is lost is only the description of what goes.
                outgoing = None
        incoming.append(Incoming(manifest, destination, record, outgoing))

    if not accept_terms:
        blocked.extend(_terms_blockers(incoming))

    return Plan(
        incoming=tuple(incoming),
        skipped=tuple(skipped),
        blocked=tuple(blocked),
        requirements=_requirements(storage, incoming),
        free_space=_free_space(storage.root),
    )


def _terms_blockers(incoming: list[Incoming]) -> list[Blocked]:
    blockers = []
    for item in incoming:
        project = item.manifest.project
        if project is not None and project.terms_url:
            blockers.append(Blocked(
                item.manifest.id,
                TERMS_NOT_ACCEPTED,
                f"{item.manifest.name} {item.manifest.version} is distributed under terms restricting "
                f"who may use it. Review {project.terms_url} and confirm they permit your use.",
            ))
    return blockers


def for_uninstall(storage: Storage, requested: list[str]) -> Plan:
    """What removing these packages would do."""
    outgoing: list[removal.RemovalPlan] = []
    blocked: list[Blocked] = []
    for package_id in _deduplicate(requested):
        try:
            outgoing.append(removal.plan(storage, package_id))
        except DfpmError as exc:
            # Not installed is a skip in spirit, but reporting it as a blocker
            # keeps 'uninstall a b c' from silently doing less than it was asked.
            blocked.append(Blocked(package_id, NOT_INSTALLED, str(exc)))
    return Plan(outgoing=tuple(outgoing), blocked=tuple(blocked))


def _installed_version(storage: Storage, package_id: str) -> str | None:
    from .inventory import read_package

    record = read_package(storage, package_id)
    return record.get("version") if record else None


def _requirements(storage: Storage, incoming: list[Incoming]) -> tuple[Requirement, ...]:
    """Which runtimes the whole set needs, detected once each rather than once per package.

    Answered before installing rather than after, so a set needing something
    this machine does not have says so while that is still useful to know.
    """
    cache: dict = {}
    gathered: dict[tuple[str, str | None, str | None], list[str]] = {}
    for item in incoming:
        for requirement in item.manifest.requires:
            key = (requirement.runtime, requirement.flavor, requirement.version)
            gathered.setdefault(key, []).append(item.manifest.name)

    results = []
    for (runtime, flavor, wanted), names in gathered.items():
        sample = _requirement_for(runtime, flavor, wanted, incoming)
        if sample is None:
            continue
        met, _, detail = runtimes.check(sample, storage, cache=cache)
        results.append(Requirement(
            runtime=runtime,
            flavor=flavor,
            version=wanted,
            met=met,
            detail=detail,
            remediation=runtimes.describe(runtime).remediation,
            wanted_by=tuple(names),
        ))
    return tuple(results)


def _requirement_for(runtime: str, flavor: str | None, wanted: str | None, incoming: list[Incoming]):
    """The manifest's own requirement object, since runtimes.check reads more than three fields."""
    for item in incoming:
        for requirement in item.manifest.requires:
            if (requirement.runtime, requirement.flavor, requirement.version) == (runtime, flavor, wanted):
                return requirement
    return None


def _free_space(root: Path) -> int | None:
    """Room on the volume the dfpm root lives on, or None when it cannot be read.

    Walks up to the nearest parent that exists, since the root itself may not
    have been created yet on a first install.
    """
    candidate = root
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    try:
        return shutil.disk_usage(candidate).free
    except OSError:
        return None

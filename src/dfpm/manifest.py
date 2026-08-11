from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import classification, runtimes
from .errors import DfpmError, ManifestError
from .names import PACKAGE_ID, VERSION, unsafe_reason
from .platforms import SUPPORTED_ARCHITECTURES, SUPPORTED_SYSTEMS

ENTRYPOINT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
SUPPORTED_KINDS = {"tool", "runtime", "ruleset", "artifact-pack", "parser-pack", "integration", "config-pack"}

# How an artifact becomes a package directory. Three things vary -- unpacking a
# zip, unpacking a tarball, copying a file into place -- and only the last step
# differs between them, so they are named for what the artifact IS rather than
# for a procedure.
PORTABLE_ZIP = "portable-zip"
STANDALONE_FILE = "standalone-file"
STRATEGIES = (PORTABLE_ZIP, STANDALONE_FILE)

IMMUTABLE, ROLLING = "immutable", "rolling"
STABILITIES = (IMMUTABLE, ROLLING)


def published_filename(url: str) -> str:
    """The name a project published a file under, made safe to join to a directory.

    Used both when saving a download and when installing an artifact that is
    itself the payload, so the two cannot disagree about what upstream called
    something.
    """
    tail = url.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", tail).lstrip(".")


@dataclass(frozen=True)
class Package:
    """The file dfpm downloads.

    Named for what it is, not for what it holds: an artifact in this catalog is
    a forensic artifact.
    """

    url: str
    sha256: str
    size: int | None = None
    stability: str = IMMUTABLE

    @property
    def rolling(self) -> bool:
        """Whether the publisher replaces the file at this URL rather than adding a new one.

        A fact about the address, not about the tool. Most projects publish an
        asset per release under a URL carrying the version, and those bytes never
        change again; some publish one URL per tool and overwrite it. A digest
        that stops matching means something different in each case, and dfpm
        cannot tell them apart by looking.
        """
        return self.stability == ROLLING


@dataclass(frozen=True)
class Entrypoint:
    name: str
    path: str
    working_directory: str | None = None


@dataclass(frozen=True)
class Check:
    """One thing that must be true for an install to count as successful."""

    type: str
    path: str


@dataclass(frozen=True)
class Requirement:
    """A platform runtime the package needs, which dfpm detects but never installs."""

    runtime: str
    version: str | None = None
    flavor: str | None = None

    def __str__(self) -> str:
        parts = [runtimes.describe(self.runtime).display]
        if self.flavor:
            parts.append(self.flavor)
        if self.version:
            parts.append(self.version)
        return " ".join(parts)


@dataclass(frozen=True)
class Platform:
    system: str
    architecture: str

    def __str__(self) -> str:
        return f"{self.system}/{self.architecture}"


@dataclass(frozen=True)
class Project:
    homepage: str | None
    repository: str | None
    license: str | None
    terms_url: str | None = None


@dataclass(frozen=True)
class Build:
    """One concrete distributable: a single file, for one platform, at one version."""

    version: str
    platform: Platform | None
    package: Package
    strategy: str
    strip_components: int
    extracted_size: int | None
    entry_count: int | None
    entrypoints: tuple[Entrypoint, ...]
    verify: tuple[Check, ...]
    requires: tuple[Requirement, ...]

    def __str__(self) -> str:
        return f"{self.version} ({self.platform})" if self.platform else self.version

    @property
    def installable(self) -> bool:
        """Whether this dfpm knows how to turn this artifact into a package.

        A catalog describes what a project publishes. What this version can
        install is a smaller and separately changing thing, and conflating them
        would mean either omitting builds that exist or refusing entries that
        are perfectly correct.
        """
        return self.strategy in STRATEGIES


@dataclass(frozen=True)
class Manifest:
    """One build of one tool, flattened into everything an install needs.

    A catalog entry describes a tool and holds several of these. This is the
    view the rest of dfpm works with, so nothing downstream has to know that a
    tool ships more than one file.
    """

    schema_version: int
    id: str
    name: str
    version: str
    kind: str
    description: str
    about: str | None
    disciplines: tuple[str, ...]
    capabilities: tuple[str, ...]
    use_cases: tuple[str, ...]
    evidence: tuple[str, ...]
    package: Package
    strategy: str
    strip_components: int
    extracted_size: int | None
    entry_count: int | None
    requires: tuple[Requirement, ...]
    entrypoints: tuple[Entrypoint, ...]
    verify: tuple[Check, ...]
    platform: Platform | None
    project: Project | None
    source_path: Path
    digest: str

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        """Load a catalog entry that describes exactly one build.

        Anything with a choice to make goes through the catalog instead, which
        knows this machine's platform and can say why it picked what it picked.
        """
        tool = Tool.load(path)
        if len(tool.builds) != 1:
            raise ManifestError(
                f"{tool.id} has {len(tool.builds)} builds, so one has to be chosen rather than assumed"
            )
        return tool.release(tool.builds[0])

    def package_url(self) -> str:
        if "://" in self.package.url:
            return self.package.url
        return str((self.source_path.parent / self.package.url).resolve())


@dataclass(frozen=True)
class Tool:
    """A catalog entry: one tool, and every build of it dfpm can install.

    Tools are what a person browses; builds are what dfpm downloads. Holding
    both in one file means the description, classification and provenance are
    written once rather than repeated for every platform, and moving to a new
    release edits the builds instead of accumulating a file for every version
    that ever shipped. What those files would have preserved, version control
    already holds.
    """

    schema_version: int
    id: str
    name: str
    kind: str
    description: str
    about: str | None
    disciplines: tuple[str, ...]
    capabilities: tuple[str, ...]
    use_cases: tuple[str, ...]
    evidence: tuple[str, ...]
    project: Project | None
    builds: tuple[Build, ...]
    source_path: Path
    digest: str

    @classmethod
    def load(cls, path: Path) -> "Tool":
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
    def _from_dict(cls, data: dict[str, Any], path: Path, digest: str) -> "Tool":
        required = ("schema_version", "id", "name", "kind", "description", "builds")
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

        builds = tuple(_build(item) for item in _object_list(data["builds"], "builds"))
        if not builds:
            raise ManifestError("builds must describe at least one build")
        identities = [(item.version, str(item.platform)) for item in builds]
        if len(identities) != len(set(identities)):
            raise ManifestError("Two builds describe the same version and platform")

        return cls(
            schema_version=1,
            id=package_id,
            name=_text(data["name"], "name"),
            kind=kind,
            description=_text(data["description"], "description"),
            about=None if data.get("about") is None else _text(data["about"], "about"),
            disciplines=classification.checked(data.get("disciplines"), "disciplines"),
            capabilities=classification.checked(data.get("capabilities"), "capabilities"),
            use_cases=classification.checked(data.get("use_cases"), "use_cases"),
            evidence=classification.checked(data.get("evidence"), "evidence"),
            project=_project(data.get("project")),
            builds=builds,
            source_path=path,
            digest=digest,
        )

    def release(self, build: Build) -> Manifest:
        """Flatten this tool and one of its builds into an installable manifest."""
        return Manifest(
            schema_version=self.schema_version,
            id=self.id,
            name=self.name,
            version=build.version,
            kind=self.kind,
            description=self.description,
            about=self.about,
            disciplines=self.disciplines,
            capabilities=self.capabilities,
            use_cases=self.use_cases,
            evidence=self.evidence,
            package=build.package,
            strategy=build.strategy,
            strip_components=build.strip_components,
            extracted_size=build.extracted_size,
            entry_count=build.entry_count,
            requires=build.requires,
            entrypoints=build.entrypoints,
            verify=build.verify,
            platform=build.platform,
            project=self.project,
            source_path=self.source_path,
            digest=self.digest,
        )

    def platforms(self) -> tuple[Platform, ...]:
        """Every platform this tool has a build for, derived rather than declared.

        A tool runs on whatever it ships builds for. Stating that separately
        would be a second copy of the same fact, free to disagree with the first.
        """
        found: list[Platform] = []
        for build in self.builds:
            if build.platform is not None and build.platform not in found:
                found.append(build.platform)
        return tuple(found)

    def versions(self) -> tuple[str, ...]:
        seen: list[str] = []
        for build in self.builds:
            if build.version not in seen:
                seen.append(build.version)
        return tuple(seen)


def _build(data: dict[str, Any]) -> Build:
    package_data = _object(data.get("package"), "build.package")
    package_url = _text(package_data.get("url"), "package.url")
    package_hash = _text(package_data.get("sha256"), "package.sha256").lower()
    if not SHA256.fullmatch(package_hash):
        raise ManifestError("package.sha256 must be exactly 64 hexadecimal characters")
    size = package_data.get("size")
    if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
        raise ManifestError("package.size must be a non-negative integer")
    stability = package_data.get("stability", IMMUTABLE)
    if not isinstance(stability, str) or stability.strip().lower() not in STABILITIES:
        raise ManifestError(f"package.stability must be one of: {', '.join(STABILITIES)}")
    stability = stability.strip().lower()

    install = _object(data.get("install"), "build.install")
    strategy = install.get("strategy")
    if not isinstance(strategy, str) or not strategy.strip():
        raise ManifestError("install.strategy is required")
    strategy = strategy.strip()
    # An unknown strategy describes an artifact this version cannot materialize,
    # not a broken entry. It is kept so the catalog can say what a project
    # publishes, and refused where it would actually be acted on.
    strip_components = install.get("strip_components", 0)
    if not isinstance(strip_components, int) or isinstance(strip_components, bool) or strip_components < 0:
        raise ManifestError("install.strip_components must be a non-negative integer")

    entrypoints = tuple(
        Entrypoint(
            _command_name(item.get("name")),
            _relative_path(item.get("path"), "entrypoint.path"),
            _working_directory(item.get("working_directory")),
        )
        for item in _object_list(install.get("entrypoints", []), "install.entrypoints")
    )
    names = [item.name for item in entrypoints]
    if len(names) != len(set(names)):
        raise ManifestError("Entrypoint names must be unique")

    verify = tuple(
        Check(_text(item.get("type"), "verify.type"), _relative_path(item.get("path"), "verify.path"))
        for item in _object_list(data.get("verify", []), "verify")
    )
    if any(check.type != "file" for check in verify):
        raise ManifestError("Only file checks are currently supported in verify")
    # Every entrypoint is already required to exist, at install and by doctor.
    # Repeating one here adds nothing and suggests verify has been read as "the
    # list of important files" rather than "what else has to be there".
    duplicated = {check.path for check in verify} & {item.path for item in entrypoints}
    if duplicated:
        raise ManifestError(
            f"verify repeats an entrypoint, which is already checked: {', '.join(sorted(duplicated))}"
        )

    if strategy == STANDALONE_FILE:
        # The artifact is the payload, so there is exactly one thing to name and
        # nothing to unpack. Saying otherwise in the manifest would describe a
        # shape this strategy cannot produce.
        if len(entrypoints) != 1:
            raise ManifestError(f"{STANDALONE_FILE} needs exactly one entrypoint, which is the file itself")
        if strip_components:
            raise ManifestError(f"{STANDALONE_FILE} has nothing to strip, so install.strip_components must be 0")
        if "/" in entrypoints[0].path or "\\" in entrypoints[0].path:
            raise ManifestError(f"{STANDALONE_FILE} places the file at the package root, so its path cannot be nested")
        # Installed under the name its project published it under. An archive
        # decides its own contents' names, but here dfpm chooses, and choosing
        # anything else would put a file on disk that cannot be matched against
        # the release it came from without consulting dfpm's own records.
        published = published_filename(package_url)
        if entrypoints[0].path != published:
            raise ManifestError(
                f"{STANDALONE_FILE} installs the published file under its own name, so this entrypoint's "
                f"path must be {published!r} rather than {entrypoints[0].path!r}"
            )

    return Build(
        version=_version(data.get("version")),
        platform=_platform(data.get("platform")),
        package=Package(package_url, package_hash, size, stability),
        strategy=strategy,
        strip_components=strip_components,
        extracted_size=_optional_count(install.get("extracted_size"), "install.extracted_size"),
        entry_count=_optional_count(install.get("entries"), "install.entries"),
        entrypoints=entrypoints,
        verify=verify,
        requires=_requirements(data.get("requires")),
    )


def _optional_count(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ManifestError(f"{field} must be a non-negative integer")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{field} must be a non-empty string")
    return value.strip()


def _version(value: Any) -> str:
    """Validate a version string, which also becomes an installation directory name."""
    text = _text(value, "version")
    if not VERSION.fullmatch(text):
        raise ManifestError("version must start with a letter or number and use only letters, numbers, dots, plus, underscores, or hyphens")
    reason = unsafe_reason(text)
    if reason is not None:
        raise ManifestError(f"version {reason}")
    return text


def _command_name(value: Any) -> str:
    """Validate an entrypoint name, which also becomes a command shim file name."""
    text = _text(value, "entrypoint.name")
    if not ENTRYPOINT_NAME.fullmatch(text):
        raise ManifestError("entrypoint.name must start with a letter or number and use only letters, numbers, dots, underscores, or hyphens")
    reason = unsafe_reason(text)
    if reason is not None:
        raise ManifestError(f"entrypoint.name {reason}")
    return text


def _requirements(value: Any) -> tuple[Requirement, ...]:
    """Read the platform runtimes a package needs to run.

    A requirement never blocks installation. It decides whether the package can
    be run once installed, which is a separate question and one that can change
    without dfpm doing anything.
    """
    if value is None:
        return ()
    requirements = []
    for item in _object_list(value, "requires"):
        name = _text(item.get("runtime"), "requires.runtime").lower()
        if name not in runtimes.KNOWN:
            raise ManifestError(f"requires.runtime must be one of: {', '.join(sorted(runtimes.KNOWN))}")
        runtime = runtimes.KNOWN[name]
        version = item.get("version")
        if version is not None:
            version = _text(version, "requires.version")
            try:
                runtimes.parse_minimum(version)
            except DfpmError as exc:
                raise ManifestError(f"requires.version is not usable: {exc}") from exc
        flavor = item.get("flavor")
        if flavor is not None:
            flavor = _text(flavor, "requires.flavor").lower()
            if flavor not in runtime.flavors:
                known = ", ".join(sorted(runtime.flavors)) if runtime.flavors else "none"
                raise ManifestError(f"requires.flavor for {name} must be one of: {known}")
        requirements.append(Requirement(name, version, flavor))
    names = [item.runtime for item in requirements]
    if len(names) != len(set(names)):
        raise ManifestError("Each runtime may only be required once")
    return tuple(requirements)


def _working_directory(value: Any) -> str | None:
    """Where an entrypoint expects to be run from, relative to the package root.

    Omitted means the directory holding the executable, which is what a tool
    resolving its own rules or configuration against the working directory
    needs. A tool whose binary sits in a subdirectory but which expects the
    package root says so with ".".
    """
    if value is None:
        return None
    text = _text(value, "entrypoint.working_directory").replace("\\", "/")
    if text == ".":
        return text
    return _relative_path(text, "entrypoint.working_directory")


def _platform(value: Any) -> Platform | None:
    """Read the platform one build was made for.

    Singular, because a build is one compiled file. A tool that ships for
    several systems lists several builds, and its platforms follow from those.
    """
    if value is None:
        return None
    fields = _object(value, "platform")
    system = _text(fields.get("os"), "platform.os").lower()
    architecture = _text(fields.get("arch"), "platform.arch").lower()
    if system not in SUPPORTED_SYSTEMS:
        raise ManifestError(f"platform.os must be one of: {', '.join(sorted(SUPPORTED_SYSTEMS))}")
    if architecture not in SUPPORTED_ARCHITECTURES:
        raise ManifestError(f"platform.arch must be one of: {', '.join(sorted(SUPPORTED_ARCHITECTURES))}")
    return Platform(system, architecture)


def _project(value: Any) -> Project | None:
    """Read the optional upstream project information recorded for provenance."""
    if value is None:
        return None
    fields = _object(value, "project")
    return Project(
        homepage=_optional_url(fields.get("homepage"), "project.homepage"),
        repository=_optional_url(fields.get("repository"), "project.repository"),
        license=None if fields.get("license") is None else _text(fields.get("license"), "project.license"),
        terms_url=_optional_url(fields.get("terms_url"), "project.terms_url"),
    )


def _optional_url(value: Any, field: str) -> str | None:
    if value is None:
        return None
    text = _text(value, field)
    if not text.startswith("https://"):
        raise ManifestError(f"{field} must be an HTTPS URL")
    return text


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

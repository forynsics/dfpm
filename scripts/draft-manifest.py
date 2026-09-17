#!/usr/bin/env python
"""Draft a catalog entry from a published artifact.

Half of a catalog entry is mechanical: a digest, a size, the depth the archive
unpacks at, where the executable ended up, what the binary says its version is.
Working those out by hand is slow and every one of them fails an install if it
is off, so this reads them from the file itself.

The other half is judgement — what the tool is for, who would reach for it, what
evidence it reads, and whether the URL it came from is one the publisher
replaces. This leaves all of that blank. A draft with a hole in it is honest; a
draft with a plausible wrong value in it is not, and would be reviewed by
somebody reading past a field that looks already decided.

Nothing here knows about any particular publisher. Everything it derives is a
property of the artifact — a ZIP, a tar archive, or a bare executable — so it
works on whatever the catalog needs next.

    python scripts/draft-manifest.py <url-or-path> [--id ID] [--name NAME]
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import struct
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Generator
from pathlib import Path, PurePosixPath
from typing import NamedTuple

CHUNK = 1024 * 1024

PORTABLE_ZIP = "portable-zip"
PORTABLE_TAR = "portable-tar"
STANDALONE_FILE = "standalone-file"

# Two of these are separate installs rather than versions of one thing, so a
# tool needing the desktop framework is not satisfied by the base runtime.
FRAMEWORKS = {
    "Microsoft.NETCore.App": "base",
    "Microsoft.WindowsDesktop.App": "desktop",
    "Microsoft.AspNetCore.App": "aspnet",
}
# Most specific wins: a package listing both frameworks needs the one that
# implies the other, and dfpm accepts a runtime only once.
FLAVOR_ORDER = ("base", "aspnet", "desktop")

# Enough of a file to identify it and read its architecture. A PE header sits
# behind a DOS stub whose length varies, so this is generous.
HEADER_BYTES = 4096

MACHINES = {0x8664: "x64", 0x014C: "x86", 0xAA64: "arm64"}
ELF_MACHINES = {0x3E: "x64", 0x03: "x86", 0xB7: "arm64"}
MACHO_CPUS = {0x01000007: "x64", 0x00000007: "x86", 0x0100000C: "arm64"}
MACHO_MAGICS = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"}
MACHO_EXECUTE = 2
VERSION_SIGNATURE = b"\xbd\x04\xef\xfe"  # VS_FIXEDFILEINFO

# A shared library is as much an ELF file as the program that loads it, and is
# often marked executable too, so the name is what tells them apart.
SHARED_LIBRARY = re.compile(r"\.so(\.\d+)*$")
# What a release file name carries after the tool's own name: a version, or the
# system and architecture it was built for.
RELEASE_SUFFIX = re.compile(
    r"[-_. ](v?\d|(linux|lin|windows|win|win64|win32|darwin|macos|mac|osx|amd64|x86_64|x64|x86|arm64|aarch64)(?=[-_. ]|$))",
    re.IGNORECASE,
)


class Member(NamedTuple):
    """One file in an artifact, whatever the artifact is."""

    name: str
    size: int
    # None when the artifact recorded no permissions, which a ZIP made on
    # Windows and a bare download both do.
    executable: bool | None
    read: Callable[[int], bytes]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source", help="HTTPS URL or path to the published artifact.")
    parser.add_argument("--id", help="Package id. Left blank when not given.")
    parser.add_argument("--name", help="Display name. Left blank when not given.")
    parser.add_argument("--keep", type=Path, help="Directory to save the downloaded artifact into.")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="dfpm-draft-") as workspace:
        artifact = Path(workspace) / "artifact"
        note(f"Reading {args.source}")
        digest, size = fetch(args.source, artifact)
        draft, unknowns = describe(artifact, digest, size, args.source, args.id, args.name)
        if args.keep:
            args.keep.mkdir(parents=True, exist_ok=True)
            kept = args.keep / released_name(args.source)
            kept.write_bytes(artifact.read_bytes())
            note(f"Saved {kept}")

    print(json.dumps(draft, indent=2))
    report(unknowns)
    return 0


def fetch(source: str, target: Path) -> tuple[str, int]:
    """Copy the artifact somewhere it can be read repeatedly, hashing as it goes."""
    digest = hashlib.sha256()
    size = 0
    with open_source(source) as stream, target.open("wb") as out:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
            out.write(chunk)
    return digest.hexdigest(), size


def open_source(source: str):
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return urllib.request.urlopen(
            urllib.request.Request(source, headers={"User-Agent": "dfpm-draft/1"}), timeout=60
        )
    path = Path(urllib.request.url2pathname(parsed.path)) if parsed.scheme == "file" else Path(source)
    return path.open("rb")


def describe(
    artifact: Path, digest: str, size: int, source: str, package_id: str | None, name: str | None
) -> tuple[dict, list[str]]:
    """Read everything about a build that the artifact itself can settle."""
    unknowns: list[str] = []
    with opened(artifact, released_name(source)) as (strategy, members):
        if not members:
            raise SystemExit("The archive holds no files.")
        strip = common_depth([member.name for member in members])
        rooted = {strip_prefix(member.name, strip): member for member in members}

        programs = find_programs(strategy, rooted, unknowns)
        system = programs[0][1] if programs else None
        architecture = programs[0][2] if programs else None
        if len({found[1] for found in programs}) > 1:
            unknowns.append(f"install.entrypoints - programs for more than one system; kept the {system} ones")
        entrypoints = [path for path, found_system, _ in programs if found_system == system]
        if not entrypoints:
            unknowns.append("install.entrypoints - no executable found in the archive; name it by hand")
        elif architecture is None:
            unknowns.append("platform - could not read the executable's architecture")

        version = None
        if system == "windows":
            # The version resource can sit anywhere in the file, so this one is read whole.
            version = file_version(rooted[entrypoints[0]].read(-1))
            if version is None:
                unknowns.append("version - no version resource in the executable; take it from the release")
        else:
            unknowns.append("version - not stated in the executable; take it from the release")
        requires = runtime_requirements(rooted)

    build: dict = {
        "version": version or "",
        "package": {"url": source, "sha256": digest, "size": size},
        "install": {
            "strategy": strategy,
            "strip_components": strip,
            "extracted_size": sum(member.size for member in members),
            "entries": len(members),
            "entrypoints": [{"name": command_name(path), "path": path} for path in entrypoints],
        },
    }
    if system and architecture:
        build["platform"] = {"os": system, "arch": architecture}
    if requires:
        build["requires"] = requires

    unknowns.append("package.stability - immutable, or rolling if the publisher overwrites this URL")
    unknowns.append("description, about - what it does, and what an investigator gets from it")
    unknowns.append("disciplines, capabilities, use_cases, evidence - from src/dfpm/classification.py")
    unknowns.append("project - homepage, repository and licence")
    if strategy != STANDALONE_FILE:
        unknowns.append("verify - a supporting file proving the archive unpacked at the right depth")

    return {
        "schema_version": 1,
        "id": package_id or "",
        "name": name or "",
        "kind": "tool",
        "description": "",
        "builds": [build],
    }, unknowns


@contextlib.contextmanager
def opened(artifact: Path, released: str) -> Generator[tuple[str, list[Member]], None, None]:
    """Identify the artifact and list its files, as the strategy that would install it sees them.

    An executable is recognised before either archive format: a self-extracting
    program carries a ZIP inside it, and is still published as a program.
    """
    with artifact.open("rb") as stream:
        head = stream.read(HEADER_BYTES)
    if binary_platform(head) is not None:
        size = artifact.stat().st_size

        def read(limit: int) -> bytes:
            with artifact.open("rb") as stream:
                return stream.read(limit)

        yield STANDALONE_FILE, [Member(released, size, None, read)]
    elif zipfile.is_zipfile(artifact):
        with zipfile.ZipFile(artifact) as bundle:
            yield PORTABLE_ZIP, [zip_member(bundle, item) for item in bundle.infolist() if not item.is_dir()]
    elif tarfile.is_tarfile(artifact):
        with tarfile.open(artifact, "r:*") as bundle:
            yield PORTABLE_TAR, [tar_member(bundle, item) for item in bundle.getmembers() if not item.isdir()]
    else:
        raise SystemExit("The artifact is not a ZIP, a tar archive, or an executable this can read.")


def zip_member(bundle: zipfile.ZipFile, item: zipfile.ZipInfo) -> Member:
    mode = item.external_attr >> 16
    # Only an archive made on a Unix-like system records permissions at all.
    executable = bool(mode & 0o111) if item.create_system == 3 and mode else None

    def read(limit: int) -> bytes:
        with bundle.open(item) as stream:
            return stream.read(limit)

    return Member(item.filename, item.file_size, executable, read)


def tar_member(bundle: tarfile.TarFile, item: tarfile.TarInfo) -> Member:
    if not item.isfile():
        # dfpm refuses these on install, so a draft for this archive could never be used.
        raise SystemExit(f"The archive holds a link or special file, which dfpm refuses: {item.name}")

    def read(limit: int) -> bytes:
        stream = bundle.extractfile(item)
        return stream.read(limit) if stream is not None else b""

    return Member(item.name, item.size, bool(item.mode & 0o111), read)


def find_programs(strategy: str, rooted: dict[str, Member], unknowns: list[str]) -> list[tuple[str, str, str | None]]:
    """The files that are programs, as (path, system, architecture), in path order.

    What decides is the header and, for Linux, a name that is not a shared
    library's. Where the archive marks some of those executable, only the marked
    ones are taken. Many archives mark none, including ones that record
    permissions for every file, and dfpm makes entrypoints executable on install
    regardless, so then every program is taken and the reviewer is told why.
    """
    if strategy == STANDALONE_FILE:
        path, member = next(iter(rooted.items()))
        system, architecture = binary_platform(member.read(HEADER_BYTES))
        return [(path, system, architecture)]

    programs = []
    marked = []
    for path, member in sorted(rooted.items()):
        head = member.read(HEADER_BYTES)
        found = binary_platform(head)
        if found is None or not is_program(path, head, found[0]):
            continue
        programs.append((path, *found))
        # Windows has no execute permission, so its programs always count as marked.
        if found[0] == "windows" or member.executable:
            marked.append((path, *found))
    if any(system != "windows" for _, system, _ in marked):
        return marked
    if any(system != "windows" for _, system, _ in programs):
        unknowns.append(
            "install.entrypoints - the archive marks no program executable, so these are every"
            " executable not named as a library; remove any that are not commands"
        )
    return programs


def binary_platform(head: bytes) -> tuple[str, str | None] | None:
    """The system and architecture an executable was built for, from its header.

    None means this is not an executable at all; an architecture of None means
    it is one, for a machine dfpm has no name for.
    """
    if head[:2] == b"MZ":
        machine = machine_type(head)
        return ("windows", MACHINES.get(machine)) if machine is not None else None
    if head[:4] == b"\x7fELF" and len(head) >= 20:
        order = "<" if head[5] == 1 else ">"
        return "linux", ELF_MACHINES.get(struct.unpack(order + "H", head[18:20])[0])
    if head[:4] in MACHO_MAGICS and len(head) >= 16:
        return "macos", MACHO_CPUS.get(struct.unpack("<I", head[4:8])[0])
    return None


def is_program(path: str, head: bytes, system: str) -> bool:
    """Whether an executable file is a command rather than a library."""
    if system == "windows":
        return path.lower().endswith(".exe")
    if system == "macos":
        return struct.unpack("<I", head[12:16])[0] == MACHO_EXECUTE
    return not SHARED_LIBRARY.search(path.rsplit("/", 1)[-1])


def _parts(name: str) -> tuple[str, ...]:
    # Tar archives often prefix every entry with "./", which is no directory at all.
    return PurePosixPath(name.replace("\\", "/")).parts


def common_depth(names: list[str]) -> int:
    """How many leading directories every entry shares, which is what to strip.

    One wrapping folder is the common case and the reason strip_components
    exists. Two would be unusual enough that a person should look at it, so this
    reports at most one and leaves the rest visible in the draft.
    """
    split = [_parts(name) for name in names]
    if len({parts[0] for parts in split if parts}) != 1:
        return 0
    return 1 if all(len(parts) > 1 for parts in split) else 0


def strip_prefix(name: str, depth: int) -> str:
    return "/".join(_parts(name)[depth:])


def command_name(path: str) -> str:
    """A shim name derived from the executable, held to what dfpm will accept.

    A release file name often carries the version and platform after the tool's
    own name; those are dropped, since a command keeps its name across releases.
    """
    base = path.rsplit("/", 1)[-1]
    suffix = RELEASE_SUFFIX.search(base)
    stem = base[: suffix.start()] if suffix else base.rsplit(".", 1)[0]
    cleaned = re.sub(r"[^a-z0-9._-]", "-", stem.lower()).strip("-.")
    return cleaned or "tool"


def file_version(binary: bytes) -> str | None:
    """The version a Windows executable reports about itself.

    Read from the file rather than from a URL or a filename because that is
    where it is actually stated, and because a publisher who versions by
    overwriting one address states it nowhere else.
    """
    found = binary.find(VERSION_SIGNATURE)
    if found < 0 or len(binary) < found + 16:
        return None
    high, low = struct.unpack("<II", binary[found + 8 : found + 16])
    return f"{high >> 16}.{high & 0xFFFF}.{low >> 16}.{low & 0xFFFF}"


def machine_type(binary: bytes) -> int | None:
    """The architecture in the PE header, which is what platform.arch has to agree with."""
    if len(binary) < 0x40 or binary[:2] != b"MZ":
        return None
    start = struct.unpack("<I", binary[0x3C:0x40])[0]
    if len(binary) < start + 6 or binary[start : start + 4] != b"PE\0\0":
        return None
    return struct.unpack("<H", binary[start + 4 : start + 6])[0]


def runtime_requirements(rooted: dict[str, Member]) -> list[dict]:
    """Read the platform runtime a .NET package needs from what it ships beside itself."""
    configs = [member for path, member in rooted.items() if path.endswith(".runtimeconfig.json")]
    flavors: set[str] = set()
    minimum = None
    for config in configs:
        try:
            options = json.loads(config.read(-1)).get("runtimeOptions", {})
        except (ValueError, KeyError):
            continue
        declared = options.get("frameworks") or ([options["framework"]] if "framework" in options else [])
        for framework in declared:
            flavor = FRAMEWORKS.get(framework.get("name", ""))
            if flavor is None:
                continue
            flavors.add(flavor)
            major = str(framework.get("version", "")).split(".")[0]
            if major.isdigit() and (minimum is None or int(major) > minimum):
                minimum = int(major)
    if not flavors:
        return []
    chosen = max(flavors, key=FLAVOR_ORDER.index)
    requirement = {"runtime": "dotnet", "flavor": chosen}
    if minimum is not None:
        requirement["version"] = f">={minimum}"
    return [requirement]


def released_name(source: str) -> str:
    tail = urllib.parse.urlparse(source).path if "://" in source else source
    tail = tail.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", tail).lstrip(".") or "artifact"


def note(message: str) -> None:
    print(message, file=sys.stderr)


def report(unknowns: list[str]) -> None:
    note("\nStill to decide, none of which the artifact can answer:")
    for item in unknowns:
        note(f"  - {item}")


if __name__ == "__main__":
    raise SystemExit(main())

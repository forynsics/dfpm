#!/usr/bin/env python
"""Draft a catalog entry from a published archive.

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
property of a portable ZIP, so it works on whatever the catalog needs next.

    python scripts/draft-manifest.py <url-or-path> [--id ID] [--name NAME]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

CHUNK = 1024 * 1024

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

MACHINES = {0x8664: "x64", 0x014C: "x86", 0xAA64: "arm64"}
VERSION_SIGNATURE = b"\xbd\x04\xef\xfe"  # VS_FIXEDFILEINFO


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source", help="HTTPS URL or path to the published archive.")
    parser.add_argument("--id", help="Package id. Left blank when not given.")
    parser.add_argument("--name", help="Display name. Left blank when not given.")
    parser.add_argument("--keep", type=Path, help="Directory to save the downloaded archive into.")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="dfpm-draft-") as workspace:
        archive = Path(workspace) / "artifact.zip"
        note(f"Reading {args.source}")
        digest, size = fetch(args.source, archive)
        draft, unknowns = describe(archive, digest, size, args.source, args.id, args.name)
        if args.keep:
            args.keep.mkdir(parents=True, exist_ok=True)
            kept = args.keep / released_name(args.source)
            kept.write_bytes(archive.read_bytes())
            note(f"Saved {kept}")

    print(json.dumps(draft, indent=2))
    report(unknowns)
    return 0


def fetch(source: str, target: Path) -> tuple[str, int]:
    """Copy the archive somewhere it can be read repeatedly, hashing as it goes."""
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
    archive: Path, digest: str, size: int, source: str, package_id: str | None, name: str | None
) -> tuple[dict, list[str]]:
    """Read everything about a build that the archive itself can settle."""
    unknowns: list[str] = []
    with zipfile.ZipFile(archive) as bundle:
        members = [item for item in bundle.infolist() if not item.filename.endswith("/")]
        if not members:
            raise SystemExit("The archive holds no files.")
        strip = common_depth([item.filename for item in members])
        rooted = {strip_prefix(item.filename, strip): item for item in members}

        entrypoints = [path for path in sorted(rooted) if path.lower().endswith(".exe")]
        if not entrypoints:
            # Nothing that names itself executable on Windows. Rather than guess
            # from a file mode that may not have survived zipping, say so.
            unknowns.append("install.entrypoints - no .exe at the archive root; name the executable by hand")
        leader = rooted[entrypoints[0]] if entrypoints else None
        header = bundle.read(leader) if leader is not None else b""

        version = file_version(header)
        if version is None:
            unknowns.append("version - no version resource in the executable; take it from the release")
        architecture = MACHINES.get(machine_type(header))
        if architecture is None and entrypoints:
            unknowns.append("platform - could not read the executable's architecture")
        requires = runtime_requirements(bundle, rooted)

    build: dict = {
        "version": version or "",
        "package": {"url": source, "sha256": digest, "size": size},
        "install": {
            "strategy": "portable-zip",
            "strip_components": strip,
            "extracted_size": sum(item.file_size for item in members),
            "entries": len(members),
            "entrypoints": [{"name": command_name(path), "path": path} for path in entrypoints],
        },
    }
    if architecture:
        build["platform"] = {"os": "windows", "arch": architecture}
    if requires:
        build["requires"] = requires

    unknowns.append("package.stability - immutable, or rolling if the publisher overwrites this URL")
    unknowns.append("description, about - what it does, and what an investigator gets from it")
    unknowns.append("disciplines, capabilities, use_cases, evidence - from src/dfpm/classification.py")
    unknowns.append("project - homepage, repository and licence")
    unknowns.append("verify - a supporting file proving the archive unpacked at the right depth")

    return {
        "schema_version": 1,
        "id": package_id or "",
        "name": name or "",
        "kind": "tool",
        "description": "",
        "builds": [build],
    }, unknowns


def common_depth(names: list[str]) -> int:
    """How many leading directories every entry shares, which is what to strip.

    One wrapping folder is the common case and the reason strip_components
    exists. Two would be unusual enough that a person should look at it, so this
    reports at most one and leaves the rest visible in the draft.
    """
    leaders = {name.replace("\\", "/").split("/")[0] for name in names}
    if len(leaders) != 1:
        return 0
    return 1 if all("/" in name.replace("\\", "/") for name in names) else 0


def strip_prefix(name: str, depth: int) -> str:
    return "/".join(name.replace("\\", "/").split("/")[depth:])


def command_name(path: str) -> str:
    """A shim name derived from the executable, held to what dfpm will accept."""
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    cleaned = re.sub(r"[^a-z0-9._-]", "-", stem).strip("-.")
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


def runtime_requirements(bundle: zipfile.ZipFile, rooted: dict) -> list[dict]:
    """Read the platform runtime a .NET package needs from what it ships beside itself."""
    configs = [item for path, item in rooted.items() if path.endswith(".runtimeconfig.json")]
    flavors: set[str] = set()
    minimum = None
    for config in configs:
        try:
            options = json.loads(bundle.read(config)).get("runtimeOptions", {})
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
    tail = source.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", tail).lstrip(".") or "artifact.zip"


def note(message: str) -> None:
    print(message, file=sys.stderr)


def report(unknowns: list[str]) -> None:
    note("\nStill to decide, none of which the archive can answer:")
    for item in unknowns:
        note(f"  - {item}")


if __name__ == "__main__":
    raise SystemExit(main())

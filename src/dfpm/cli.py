from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .catalog import load_catalog, resolve
from .doctor import inspect
from .errors import DfpmError
from .installer import install
from .inventory import export_lock, list_packages
from .manifest import Manifest
from .storage import Storage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dfpm", description="Find and manage digital forensics tools.")
    parser.add_argument("--version", action="version", version=f"DFPM {__version__}")
    parser.add_argument("--root", type=Path, help="Override the DFPM data directory.")
    parser.add_argument("--catalog", type=Path, default=Path("catalog"), help="Directory containing package manifests.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("paths", help="Show where DFPM stores files.")
    catalog = commands.add_parser("catalog", help="List available packages.")
    catalog.add_argument("--json", action="store_true")
    validate = commands.add_parser("validate", help="Validate a package manifest.")
    validate.add_argument("manifest", type=Path)
    install_command = commands.add_parser("install", help="Install a package from the catalog.")
    install_command.add_argument("package")
    install_command.add_argument("--package-version", dest="package_version")
    install_command.add_argument("--yes", action="store_true", help="Confirm the displayed plan.")
    list_command = commands.add_parser("list", help="List installed packages.")
    list_command.add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor", help="Check managed files without changing them.")
    doctor.add_argument("--json", action="store_true")
    environment = commands.add_parser("environment", help="Export exact installed state.")
    environment_commands = environment.add_subparsers(dest="environment_command", required=True)
    export = environment_commands.add_parser("export", help="Write an environment lockfile.")
    export.add_argument("output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    storage = Storage(args.root.resolve()) if args.root else Storage.default()
    try:
        return _run(args, storage)
    except DfpmError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


def _run(args: argparse.Namespace, storage: Storage) -> int:
    if args.command == "paths":
        print(f"Tools:            {storage.tools}")
        print(f"Verified downloads: {storage.cache}")
        print(f"Command shortcuts:  {storage.bin}")
        print(f"Package records:    {storage.state / 'packages'}")
        return 0
    if args.command == "catalog":
        packages = load_catalog(args.catalog)
        if args.json:
            print(json.dumps([{"id": p.id, "name": p.name, "version": p.version, "kind": p.kind, "description": p.description} for p in packages], indent=2))
        else:
            for package in packages:
                print(f"{package.id:<28} {package.version:<14} {package.name}")
        return 0
    if args.command == "validate":
        manifest = Manifest.load(args.manifest)
        print(f"Valid manifest: {manifest.id} {manifest.version}")
        print(f"Manifest SHA-256: {manifest.digest}")
        return 0
    if args.command == "install":
        manifest = resolve(args.catalog, args.package, args.package_version)
        print("Install plan")
        print(f"  Package:     {manifest.name} {manifest.version}")
        print(f"  Source:      {manifest.artifact_source()}")
        print(f"  SHA-256:     {manifest.artifact.sha256}")
        print(f"  Destination: {storage.package_version(manifest.id, manifest.version)}")
        print("  System-wide changes: none")
        if not args.yes:
            answer = input("Continue? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("No changes made.")
                return 2
        destination = install(manifest, storage)
        print(f"Installed to {destination}")
        return 0
    if args.command == "list":
        packages = list_packages(storage)
        if args.json:
            print(json.dumps(packages, indent=2, sort_keys=True))
        elif not packages:
            print("No packages are installed.")
        else:
            for package in packages:
                print(f"{package['id']:<28} {package['active_version']:<14} {package['name']}")
        return 0
    if args.command == "doctor":
        findings = inspect(storage)
        if args.json:
            print(json.dumps([item.__dict__ for item in findings], indent=2))
        elif not findings:
            print("No managed packages to check.")
        else:
            for finding in findings:
                marker = "PASS" if finding.status == "passing" else "FAIL"
                print(f"{marker:<4} {finding.package} {finding.version}: {finding.detail}")
        return 1 if any(item.status == "failed" for item in findings) else 0
    if args.command == "environment" and args.environment_command == "export":
        lock = export_lock(storage, args.output)
        print(f"Wrote {len(lock['packages'])} package(s) to {args.output.resolve()}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

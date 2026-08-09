from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__, cache, launcher, removal
from .archive import human_size
from .catalog import describe, load_catalog, resolve
from .doctor import inspect
from .errors import DfpmError
from .gui import serve
from .installer import check_destination, check_platform, install
from .inventory import list_packages
from .storage import Storage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dfpm", description="A package manager for digital forensics tools.")
    parser.add_argument("--version", action="version", version=f"dfpm {__version__}")
    parser.add_argument("--root", type=Path, help="Override the dfpm data directory.")
    parser.add_argument("--catalog", type=Path, default=Path("catalog"), help="Directory containing package manifests.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("paths", help="Show where dfpm stores files.")
    catalog = commands.add_parser("catalog", help="List available packages.")
    catalog.add_argument("--json", action="store_true")

    install_command = commands.add_parser("install", help="Install a package, replacing any version already installed.")
    install_command.add_argument("package")
    install_command.add_argument("--package-version", dest="package_version", help="Install this version instead of the newest.")
    install_command.add_argument("--yes", action="store_true", help="Confirm the displayed plan.")

    uninstall_command = commands.add_parser("uninstall", help="Remove installed files dfpm recorded.")
    uninstall_command.add_argument("package")
    uninstall_command.add_argument("--force", action="store_true", help="Also remove managed files that changed since installation.")
    uninstall_command.add_argument("--yes", action="store_true", help="Confirm the displayed plan.")

    cache_command = commands.add_parser("cache", help="Inspect and clean the verified download cache.")
    cache_commands = cache_command.add_subparsers(dest="cache_command", required=True)
    cache_list = cache_commands.add_parser("list", help="Show cached artifacts and what still needs them.")
    cache_list.add_argument("--json", action="store_true")
    cache_verify = cache_commands.add_parser("verify", help="Re-hash cached artifacts to detect corruption.")
    cache_verify.add_argument("--json", action="store_true")
    cache_prune = cache_commands.add_parser("prune", help="Remove cached artifacts no installed package needs.")
    cache_prune.add_argument("--keep-catalog", action="store_true", help="Keep artifacts the catalog lists, for offline installs.")
    cache_prune.add_argument("--ignore-catalog", action="store_true", help="Prune even though the catalog cannot be read.")
    cache_prune.add_argument("--yes", action="store_true", help="Confirm the displayed plan.")
    cache_remove = cache_commands.add_parser("remove", help="Remove one cached artifact by digest.")
    cache_remove.add_argument("digest", help="Full digest, or enough leading characters to be unambiguous.")
    cache_remove.add_argument("--force", action="store_true", help="Remove even though an installed package needs it.")
    cache_remove.add_argument("--yes", action="store_true", help="Confirm the displayed plan.")

    run_command = commands.add_parser("run", help="Run a command from an installed package.")
    run_command.add_argument("name", help="Command name, as listed by 'dfpm which'.")
    run_command.add_argument("arguments", nargs=argparse.REMAINDER, help="Arguments passed straight to the tool.")
    which = commands.add_parser("which", help="Show which file a command runs.")
    which.add_argument("name")
    which.add_argument("--json", action="store_true")

    gui = commands.add_parser("gui", help="Open a local interface for managing installed packages.")
    gui.add_argument("--host", default="127.0.0.1", help="Loopback address to bind (127.0.0.1, localhost, or ::1).")
    gui.add_argument("--port", type=int, default=8765, help="Port to listen on. Use 0 to pick any free port.")
    gui.add_argument("--no-browser", action="store_true", help="Do not open a browser window.")

    list_command = commands.add_parser("list", help="List installed packages.")
    list_command.add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor", help="Check managed files without changing them.")
    doctor.add_argument("--json", action="store_true")
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
        print(f"Tools:              {storage.tools}")
        print(f"Verified downloads: {storage.cache}")
        print(f"Command shortcuts:  {storage.bin}")
        print(f"Package records:    {storage.state / 'packages'}")
        return 0
    if args.command == "catalog":
        packages = load_catalog(args.catalog)
        if args.json:
            print(json.dumps([describe(package) for package in packages], indent=2))
        else:
            for package in packages:
                print(f"{package.id:<28} {package.version:<14} {package.name}")
                print(f"{'':<28} {package.description}")
        return 0
    if args.command == "install":
        return _install(args, storage)
    if args.command == "uninstall":
        return _uninstall(args, storage)
    if args.command == "cache":
        return _cache(args, storage)
    if args.command == "run":
        return launcher.run(storage, args.name, args.arguments)
    if args.command == "which":
        return _which(args, storage)
    if args.command == "gui":
        return serve(storage, args.catalog, host=args.host, port=args.port, open_browser=not args.no_browser)
    if args.command == "list":
        return _list(args, storage)
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
    return 1


def _free_space(root: Path) -> int | None:
    """Free bytes on the volume dfpm installs to, measured at the nearest existing parent."""
    for candidate in (root, *root.parents):
        try:
            return shutil.disk_usage(candidate).free
        except OSError:
            continue
    return None


def _install(args: argparse.Namespace, storage: Storage) -> int:
    manifest = resolve(args.catalog, args.package, args.package_version)
    check_platform(manifest)
    previous = check_destination(manifest, storage)

    print("Install plan")
    print(f"  Package:     {manifest.name} {manifest.version}")
    if previous:
        print(f"  Replaces:    {previous}, which is removed once {manifest.version} is installed and working")
    if manifest.platform is not None:
        print(f"  Platform:    {manifest.platform}")
    if manifest.project is not None:
        if manifest.project.license:
            print(f"  License:     {manifest.project.license}")
        if manifest.project.source:
            print(f"  Project:     {manifest.project.source}")
    print(f"  Source:      {manifest.artifact_source()}")
    print(f"  SHA-256:     {manifest.artifact.sha256}")
    if manifest.artifact.size is not None:
        print(f"  Download:    {human_size(manifest.artifact.size)}")
    if manifest.extracted_size is not None:
        installed = human_size(manifest.extracted_size)
        if manifest.entry_count is not None:
            installed += f" across {manifest.entry_count:,} files"
        print(f"  Installed:   {installed}")
    print(f"  Destination: {storage.package_version(manifest.id, manifest.version)}")
    free = _free_space(storage.root)
    if free is not None:
        print(f"  Disk:        {human_size(free)} free on that volume")
    print("  System-wide changes: none")
    if not args.yes:
        answer = input("Continue? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("No changes made.")
            return 2
    destination = install(manifest, storage)
    print(f"Installed to {destination}")
    if previous:
        print(f"Removed the previous version, {previous}.")
    return 0


def _uninstall(args: argparse.Namespace, storage: Storage) -> int:
    plan = removal.plan(storage, args.package)
    preserved = plan.preserved(args.force)

    print("Removal plan")
    print(f"  Package:     {plan.name} {plan.version} ({plan.package})")
    print(f"  Removes:     {len(plan.removable) + (len(plan.modified) if args.force else 0)} file(s) dfpm installed")
    if plan.modified:
        changed = "removed because --force was given" if args.force else "kept, because dfpm did not write their current contents"
        print(f"  Changed:     {len(plan.modified)} managed file(s) {changed}")
    if plan.unknown:
        print(f"  Preserves:   {len(plan.unknown)} file(s) dfpm did not install")
    if plan.blocked:
        print(f"  Links:       {len(plan.blocked)} recorded path(s) are now links and will not be touched")
    if plan.commands:
        print(f"  Commands:    {', '.join(plan.commands)} removed")
    print("  Verified downloads stay in the cache; 'dfpm cache prune' clears them.")
    if not args.yes:
        answer = input("Continue? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("No changes made.")
            return 2

    removal.execute(storage, plan, force=args.force)
    print(f"Removed {plan.package} {plan.version}")
    if preserved:
        print(f"Kept {len(preserved)} file(s) in {plan.root}:")
        for relative in preserved:
            print(f"  {relative}")
    return 0


def _cache(args: argparse.Namespace, storage: Storage) -> int:
    if args.cache_command == "list":
        return _cache_list(args, storage)
    if args.cache_command == "verify":
        return _cache_verify(args, storage)
    if args.cache_command == "prune":
        return _cache_prune(args, storage)
    return _cache_remove(args, storage)


def _cache_list(args: argparse.Namespace, storage: Storage) -> int:
    current = cache.survey(storage, args.catalog)
    if args.json:
        print(json.dumps({
            "artifacts": [
                {"digest": entry.digest, "size": entry.size, "status": entry.status, "referenced_by": list(entry.referenced_by)}
                for entry in current.entries
            ],
            "partial_downloads": [str(path) for path in current.partials],
            "unrecognized": [str(path) for path in current.unrecognized],
            "catalog_readable": current.catalog_readable,
        }, indent=2))
        return 0

    if not current.entries and not current.partials and not current.unrecognized:
        print(f"The cache is empty: {storage.cache}")
        return 0
    if current.entries:
        print(f"{'DIGEST':<{cache.SHORT_LENGTH}}  {'STATUS':<9}  {'SIZE':>9}  NEEDED BY")
    for entry in current.entries:
        referenced = ", ".join(entry.referenced_by) or "nothing"
        print(f"{cache.short(entry.digest)}  {entry.status:<9}  {cache.human(entry.size):>9}  {referenced}")
    reclaimable = cache.removable(current)
    print(f"\n{len(current.entries)} artifact(s), {cache.human(current.total_size)} total")
    if reclaimable:
        print(f"{len(reclaimable)} not needed by any installed package, "
              f"{cache.human(sum(item.size for item in reclaimable))} reclaimable with 'dfpm cache prune'")
    if current.partials:
        print(f"{len(current.partials)} interrupted download(s) left behind; 'dfpm cache prune' clears them")
    for path in current.unrecognized:
        print(f"unrecognized file kept as-is: {path}")
    if current.entries:
        print("Digests are shortened. 'dfpm cache remove' accepts any digest shown above, and --json prints them in full.")
    if not current.catalog_readable:
        print(f"warning: the catalog could not be read ({current.catalog_error})")
    return 0


def _cache_verify(args: argparse.Namespace, storage: Storage) -> int:
    results = cache.verify(storage, args.catalog)
    if args.json:
        print(json.dumps([{"digest": entry.digest, "problem": problem} for entry, problem in results], indent=2))
    elif not results:
        print("No cached artifacts to check.")
    else:
        for entry, problem in results:
            marker = "OK" if problem is None else "FAIL"
            print(f"{marker:<4} {cache.short(entry.digest)}  {cache.human(entry.size) if problem is None else problem}")
    return 1 if any(problem for _, problem in results) else 0


def _cache_prune(args: argparse.Namespace, storage: Storage) -> int:
    current = cache.survey(storage, args.catalog)
    if not current.catalog_readable and args.keep_catalog and not args.ignore_catalog:
        raise DfpmError(
            f"The catalog could not be read ({current.catalog_error}), so artifacts it needs would look unused. "
            "Point --catalog at the right directory, or pass --ignore-catalog to prune anyway."
        )
    doomed = cache.removable(current, keep_catalog=args.keep_catalog)
    if not doomed and not current.partials:
        print("Nothing to prune.")
        return 0

    reclaimable = sum(entry.size for entry in doomed) + sum(path.stat().st_size for path in current.partials)
    print("Cache prune plan")
    print(f"  Removes: {len(doomed)} artifact(s) and {len(current.partials)} interrupted download(s), {cache.human(reclaimable)}")
    print(f"  Keeps:   {len(current.with_status('installed'))} in use by installed packages")
    for entry in doomed:
        print(f"    {cache.short(entry.digest)}  {cache.human(entry.size)}  {', '.join(entry.referenced_by) or 'nothing needs this'}")
    if not args.yes:
        answer = input("Continue? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("No changes made.")
            return 2
    print(f"Reclaimed {cache.human(cache.delete(doomed, current.partials))}. "
          "Anything removed is downloaded again when it is next needed.")
    return 0


def _cache_remove(args: argparse.Namespace, storage: Storage) -> int:
    current = cache.survey(storage, args.catalog)
    entry = cache.find(current, args.digest)
    if entry.installed_by and not args.force:
        raise DfpmError(
            f"{cache.short(entry.digest)} is still used by {', '.join(entry.installed_by)}. "
            "Removing it would prevent an offline repair or reinstall. Pass --force to remove it anyway."
        )
    print(f"Removes {entry.digest}  {cache.human(entry.size)}")
    print(f"  Needed by: {', '.join(entry.referenced_by) or 'nothing'}")
    if not args.yes:
        answer = input("Continue? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("No changes made.")
            return 2
    print(f"Reclaimed {cache.human(cache.delete((entry,)))}.")
    return 0


def _which(args: argparse.Namespace, storage: Storage) -> int:
    resolution = launcher.resolve(storage, args.name)
    status, found = launcher.path_status(storage, args.name)
    if args.json:
        print(json.dumps({
            "name": resolution.name,
            "package": resolution.package,
            "version": resolution.version,
            "target": str(resolution.target),
            "shim": str(resolution.shim),
            "path_status": status,
            "path_resolves_to": found,
        }, indent=2))
        return 0

    print(f"{resolution.name} -> {resolution.target}")
    print(f"  Package:  {resolution.package} {resolution.version}")
    print(f"  Shortcut: {resolution.shim}{'' if resolution.shim_exists else ' (missing, run dfpm doctor)'}")
    if status == "dfpm":
        print("  On PATH:  resolves to this package's command shortcut")
    elif status == "shadowed":
        print(f"  On PATH:  '{resolution.name}' currently runs {found} instead")
        print(f"            Use 'dfpm run {resolution.name}' to be certain which one you get.")
    else:
        print(f"  On PATH:  not reachable. Use 'dfpm run {resolution.name}', the full path above,")
        print(f"            or add {storage.bin} to your PATH yourself.")
    return 0


def _list(args: argparse.Namespace, storage: Storage) -> int:
    packages = list_packages(storage)
    if args.json:
        print(json.dumps(packages, indent=2, sort_keys=True))
        return 0
    if not packages:
        print("No packages are installed.")
        return 0
    for package in packages:
        print(f"{package['id']:<28} {package.get('version', '-'):<14} {package.get('name', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import shutil
import sys
import textwrap
from pathlib import Path

from . import __version__, cache, classification, launcher, progress, removal, runtimes
from .archive import human_size
from . import platforms
from .catalog import describe, load_catalog, resolve
from .catalog import newest as catalog_newest
from .catalog import version_key as catalog_version_key
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
    catalog = commands.add_parser("catalog", help="List available packages, or show one in detail.")
    catalog.add_argument("package", nargs="?", help="Show everything known about this package.")
    catalog.add_argument("--json", action="store_true")

    install_command = commands.add_parser("install", help="Install a package, replacing any version already installed.")
    install_command.add_argument("package")
    install_command.add_argument("--package-version", dest="package_version", help="Install this version instead of the newest.")
    install_command.add_argument("--yes", action="store_true", help="Confirm the displayed plan.")
    install_command.add_argument(
        "--accept-terms",
        action="store_true",
        dest="accept_terms",
        help="Assert that the package's usage terms permit your use. Never implied by --yes.",
    )

    uninstall_command = commands.add_parser("uninstall", help="Remove installed files dfpm recorded.")
    uninstall_command.add_argument("package")
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
    doctor = commands.add_parser("doctor", help="Check installed packages without changing them.")
    doctor.add_argument("package", nargs="?", help="Check only this package.")
    doctor.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    storage = Storage(args.root.resolve()) if args.root else Storage.default()
    try:
        return _run(args, storage)
    except DfpmError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
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
        return _catalog(args)
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
        findings = inspect(storage, args.package)
        if args.json:
            print(json.dumps([item.__dict__ for item in findings], indent=2))
        elif not findings:
            print("No installed packages to check.")
        else:
            markers = {"passing": "PASS", "blocked": "WAIT", "failed": "FAIL"}
            for finding in findings:
                marker = markers.get(finding.status, "FAIL")
                print(f"{marker:<4} {finding.package} {finding.version}: {finding.detail}")
        # A machine missing a runtime is not a broken install, so it gets its
        # own code: a script can tell "dfpm is wrong" from "this box is not ready".
        if any(item.status == "failed" for item in findings):
            return 1
        return 2 if any(item.status == "blocked" for item in findings) else 0
    return 1


def _other_builds(catalog: Path, manifest) -> int:
    """How many builds of this tool were not chosen, for the install plan."""
    try:
        tools = [tool for tool in load_catalog(catalog) if tool.id == manifest.id]
    except DfpmError:
        return 0
    return len(tools[0].builds) - 1 if tools else 0


def _catalog(args: argparse.Namespace) -> int:
    tools = load_catalog(args.catalog)
    if args.package:
        matches = [tool for tool in tools if tool.id == args.package]
        if not matches:
            raise DfpmError(f"Package not found in catalog: {args.package}")
        tools = matches

    if args.json:
        # The vocabulary travels with the packages so an interface can offer
        # every discipline as a filter, including the ones nothing is
        # catalogued under yet. Hard-coding that list somewhere else is how
        # the two drift apart.
        print(json.dumps({
            "packages": [describe(tool) for tool in tools],
            "vocabulary": classification.vocabulary(),
        }, indent=2))
        return 0

    if args.package:
        _show_tool(tools[0])
        return 0

    for tool in tools:
        platforms = ", ".join(str(item) for item in tool.platforms()) or "any platform"
        print(f"{tool.id:<24} {catalog_newest(tool).version:<12} {tool.name}")
        print(f"{'':<24} {tool.description}")
        print(f"{'':<24} {platforms}")
    print("\nRun 'dfpm catalog <package>' to see everything known about one of them.")
    return 0


def _show_tool(tool) -> None:
    """Everything known about one tool, including builds this machine cannot use.

    Somebody deciding whether a tool is worth installing needs more than a line,
    and somebody wondering what else it ships needs to be able to see it. The
    install plan only ever shows the one build it chose.
    """
    here = platforms.current()
    print(f"{tool.name}  {catalog_newest(tool).version}")
    print(f"  {tool.description}")
    print()
    if tool.about:
        for line in textwrap.wrap(tool.about, width=76):
            print(f"  {line}")
        print()

    labelled = [
        ("Discipline", "disciplines"),
        ("Does", "capabilities"),
        ("Use for", "use_cases"),
        ("Reads", "evidence"),
    ]
    for heading, field in labelled:
        keys = getattr(tool, field)
        if keys:
            print(f"  {heading + ':':<12} {', '.join(classification.label(field, key) for key in keys)}")

    commands = [name for build in tool.builds for name in (item.name for item in build.entrypoints)]
    if commands:
        print(f"  {'Commands:':<12} {', '.join(dict.fromkeys(commands))}")
    if tool.project:
        if tool.project.license:
            print(f"  {'License:':<12} {tool.project.license}")
        if tool.project.repository:
            print(f"  {'Project:':<12} {tool.project.repository}")

    print("\n  Builds")
    for build in sorted(tool.builds, key=lambda item: catalog_version_key(item.version), reverse=True):
        platform = str(build.platform) if build.platform else "any platform"
        size = human_size(build.package.size) if build.package.size else ""
        usable = build.platform is None or (build.platform.system, build.platform.architecture) == here
        marker = "  <- installs on this machine" if usable else ""
        print(f"    {build.version:<10} {platform:<16} {size:>10}{marker}")
    if not any(
        build.platform is None or (build.platform.system, build.platform.architecture) == here
        for build in tool.builds
    ):
        print(f"\n  None of these run on {here[0]}/{here[1]}.")


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
        # Replacing a version deletes its whole folder, so show what is in there
        # now rather than letting a tool's downloaded rules vanish unannounced.
        outgoing = removal.plan(storage, manifest.id)
        print(f"  Replaces:    {previous}, whose folder is deleted once {manifest.version} is installed and working")
        print(f"               {outgoing.root}")
        print(f"               {outgoing.file_count:,} file(s), {human_size(outgoing.total_size)}")
        if outgoing.grew:
            print(f"               Installed with {outgoing.installed_count:,}; anything added since goes too.")
    if manifest.platform is not None:
        # Say that a choice was made. Otherwise a tool shipping for three
        # systems looks like it only exists for this one.
        others = _other_builds(args.catalog, manifest)
        note = f"  (1 of {others + 1} builds; 'dfpm catalog {manifest.id}' shows the rest)" if others else ""
        print(f"  Platform:    {manifest.platform}{note}")
    if manifest.project is not None:
        if manifest.project.license:
            print(f"  License:     {manifest.project.license}")
        if manifest.project.repository:
            print(f"  Project:     {manifest.project.repository}")
        if manifest.project.terms_url:
            print(f"  Terms:       {manifest.project.terms_url}")
            print("               Acceptance required. dfpm cannot judge whether they permit your use.")
    print(f"  Source:      {manifest.package_url()}")
    print(f"  SHA-256:     {manifest.package.sha256}")
    if manifest.package.size is not None:
        print(f"  Download:    {human_size(manifest.package.size)}")
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
    terms = manifest.project.terms_url if manifest.project else None
    if terms and args.yes and not args.accept_terms:
        # --yes says the plan was reviewed. Whether restricted terms permit this
        # particular user is a separate claim, and only they can make it.
        print(
            f"\n{manifest.name} {manifest.version} is distributed under terms restricting who may use it.\n"
            f"Review {terms} and pass --accept-terms if they permit your use.",
            file=sys.stderr,
        )
        return 1
    if not args.yes:
        answer = input("Continue? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("No changes made.")
            return 2
    reporter = progress.reporter()
    try:
        destination = install(manifest, storage, on_progress=reporter)
    finally:
        if reporter is not None:
            reporter.close()
    print(f"Installed to {destination}")
    if previous:
        print(f"Removed the previous version, {previous}.")
    _report_readiness(storage, manifest)
    return 0


def _report_readiness(storage: Storage, manifest) -> None:
    """Say whether the package can actually be run, without failing the install.

    Installing and being runnable are separate. dfpm does not install platform
    runtimes, so a package can land correctly on a machine that cannot yet run
    it, and saying nothing would leave that to be discovered later.
    """
    if not manifest.requires:
        return
    cache: dict = {}
    unmet = []
    for requirement in manifest.requires:
        met, _, detail = runtimes.check(requirement, storage, cache=cache)
        if not met:
            unmet.append((requirement, detail))
    if not unmet:
        return
    # Console output stays ASCII: a Windows console defaults to a legacy code
    # page, where anything else is mangled or raises on the way out.
    print("\nRuntime requirement:")
    for requirement, detail in unmet:
        print(f"  {requirement}: {detail}")
        print(f"    {runtimes.describe(requirement.runtime).remediation}")
    print(f"\nThe package is installed but cannot be run yet. Run 'dfpm doctor {manifest.id}' for details.")


def _uninstall(args: argparse.Namespace, storage: Storage) -> int:
    plan = removal.plan(storage, args.package)

    print("Removal plan")
    print(f"  Package:     {plan.name} {plan.version} ({plan.package})")
    print(f"  Removes:     {plan.root}")
    print(f"               {plan.file_count:,} file(s), {human_size(plan.total_size)}")
    if plan.grew:
        # The tool may maintain its own files, or someone may have added their
        # own. Either way the whole directory goes, so say so before it does.
        print(f"  Note:        the install put {plan.installed_count:,} file(s) here; everything present now is removed")
    if plan.commands:
        print(f"  Commands:    {', '.join(plan.commands)} removed")
    print("  Downloads stay in the cache; 'dfpm cache prune' clears them.")
    if not args.yes:
        answer = input("Continue? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("No changes made.")
            return 2

    removal.execute(storage, plan)
    print(f"Removed {plan.package} {plan.version}")
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
            "working_directory": str(resolution.working_directory),
            "path_status": status,
            "path_resolves_to": found,
        }, indent=2))
        return 0

    print(f"{resolution.name} -> {resolution.target}")
    print(f"  Package:  {resolution.package} {resolution.version}")
    print(f"  Runs in:  {resolution.working_directory}")
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

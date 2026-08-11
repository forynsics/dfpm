from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import textwrap
from collections.abc import Mapping
from pathlib import Path

from . import __version__, cache, classification, configuration, launcher, plan, progress, removal, runtimes, shims, sync
from .archive import human_size
from . import platforms
from .catalog import SHIPPED, build_index, check_collections, describe, load_catalog, load_collections, resolve
from .catalog import newer_than_installed as catalog_updates
from .catalog import newest as catalog_newest
from .catalog import version_key as catalog_version_key
from .doctor import apply_repairs, inspect, repair_plan
from . import downloads
from .downloads import retrieve
from .errors import DfpmError
from .gui import serve
from .installer import check_destination, check_platform, install
from .inventory import list_packages
from .manifest import published_filename
from .storage import Storage
from .sync import DEFAULT_SOURCE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dfpm", description="A package manager for digital forensics tools.")
    parser.add_argument("--version", action="version", version=f"dfpm {__version__}")
    parser.add_argument("--root", type=Path, help="Override the dfpm data directory.")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Directory containing package manifests. Defaults to DFPM_CATALOG, then the catalog in the dfpm root.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("paths", help="Show where dfpm stores files.")
    config = commands.add_parser("config", help="Save or inspect persistent dfpm settings.")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_set = config_commands.add_parser("set", help="Save a setting for future dfpm commands.")
    config_set.add_argument("setting", choices=["root"])
    config_set.add_argument("value", type=Path)
    config_unset = config_commands.add_parser("unset", help="Return a setting to its platform default.")
    config_unset.add_argument("setting", choices=["root"])
    config_commands.add_parser("show", help="Show the saved root setting and configuration file.")
    catalog = commands.add_parser("catalog", help="List available packages, or show one in detail.")
    catalog.add_argument("package", nargs="?", help="Show everything known about this package.")
    catalog.add_argument("--json", action="store_true")
    catalog.add_argument(
        "--index",
        action="store_true",
        help="Print the index that describes this catalog, for publishing it.",
    )
    search = commands.add_parser("search", help="Find packages by name, purpose, capability, or evidence.")
    search.add_argument("query", nargs="+", help="Words describing the tool or forensic task to find.")
    search.add_argument("--json", action="store_true")

    outdated = commands.add_parser("outdated", help="Show installed packages with a newer catalog version.")
    outdated.add_argument("--json", action="store_true")

    upgrade = commands.add_parser("upgrade", help="Upgrade installed packages to newer catalog versions.")
    upgrade.add_argument("package", nargs="*", help="Installed package IDs to upgrade.")
    upgrade.add_argument("--all", action="store_true", help="Upgrade every installed package with an available update.")
    upgrade.add_argument("--yes", action="store_true", help="Confirm the displayed plan.")
    upgrade.add_argument(
        "--accept-terms",
        action="store_true",
        dest="accept_terms",
        help="Assert that updated packages' usage terms permit your use. Never implied by --yes.",
    )
    upgrade.add_argument(
        "--accept-digest-mismatch",
        action="store_true",
        dest="accept_digest_mismatch",
        help="Upgrade a rolling package whose bytes no longer match the catalog. Never implied by --yes.",
    )
    # Upgrade always selects the newest version. Giving it the same internal
    # shape as install lets both commands use one planner and executor.
    upgrade.set_defaults(package_version=None)

    install_command = commands.add_parser("install", help="Install a package, replacing any version already installed.")
    install_command.add_argument("package", nargs="+")
    install_command.add_argument("--package-version", dest="package_version", help="Install this version instead of the newest.")
    install_command.add_argument("--yes", action="store_true", help="Confirm the displayed plan.")
    install_command.add_argument(
        "--accept-terms",
        action="store_true",
        dest="accept_terms",
        help="Assert that the package's usage terms permit your use. Never implied by --yes.",
    )
    install_command.add_argument(
        "--accept-digest-mismatch",
        action="store_true",
        dest="accept_digest_mismatch",
        help="Install a rolling package whose bytes no longer match the catalog. Never implied by --yes.",
    )

    download_command = commands.add_parser(
        "download",
        help="Download a package's release file without installing it, for a machine that is not this one.",
    )
    download_command.add_argument("package", nargs="+")
    download_command.add_argument("--package-version", dest="package_version", help="Download this version instead of the newest.")
    download_command.add_argument("--platform", help="Download the build for this os/arch, written as os/arch.")
    download_command.add_argument("--to", dest="destination", type=Path, help="Directory to save into. Defaults to the current one.")
    download_command.add_argument(
        "--accept-digest-mismatch",
        action="store_true",
        dest="accept_digest_mismatch",
        help="Save the file even when its digest has changed, so it can be examined.",
    )

    uninstall_command = commands.add_parser("uninstall", help="Remove installed files dfpm recorded.")
    uninstall_command.add_argument("package", nargs="*")
    uninstall_command.add_argument("--all", action="store_true", help="Remove every installed package.")
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

    sync_command = commands.add_parser(
        "sync",
        help="Update this machine's catalog from the published one.",
    )
    sync_command.add_argument("--source", help=f"Where to read entries from. Defaults to {DEFAULT_SOURCE}")
    sync_command.add_argument("--yes", action="store_true", help="Confirm the displayed plan.")

    # Both spellings, because listing them reads as plural and showing one
    # reads as singular, and nobody should have to remember which was chosen.
    collection = commands.add_parser(
        "collection",
        aliases=["collections"],
        help="Show the named sets of packages this catalog offers.",
    )
    collection.add_argument("name", nargs="?", help="Show what one collection contains.")

    list_command = commands.add_parser("list", help="List installed packages.")
    list_command.add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor", help="Check installed packages without changing them.")
    doctor.add_argument("package", nargs="?", help="Check only this package.")
    doctor_mode = doctor.add_mutually_exclusive_group()
    doctor_mode.add_argument("--json", action="store_true")
    doctor_mode.add_argument("--repair", action="store_true", help="Plan and repair safe dfpm-owned inconsistencies.")
    doctor.add_argument("--yes", action="store_true", help="Confirm the displayed repair plan.")
    return parser


def catalog_directory(chosen: Path | None, storage: Storage, environ: Mapping[str, str] | None = None) -> Path:
    """Where to read package entries from, most explicit choice first.

    The flag beats the environment, which beats this machine's own catalog,
    which beats the entries dfpm shipped with. The environment variable exists
    because working on dfpm itself means reading the catalog in the source tree
    rather than the installed one, and saying so once is better than repeating
    it on every command.

    Falling back to the shipped entries is what makes a fresh install usable:
    otherwise dfpm arrives with an empty directory and no way to fill it.
    Nothing is copied anywhere — an empty catalog directory is read straight
    past, so a machine that has curated one is never second-guessed, and one
    that has not is never written to without being asked.
    """
    if chosen is not None:
        return chosen
    environ = os.environ if environ is None else environ
    configured = environ.get("DFPM_CATALOG")
    if configured:
        return Path(configured)
    curated = storage.catalog.is_dir() and any(storage.catalog.glob("*.json"))
    return storage.catalog if curated else SHIPPED


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "config":
            return _config(args)
        choice = configuration.choose_root(args.root, Storage.default().root)
        storage = Storage(choice.path)
        args.root_source = choice.source
        args.configuration = choice.configuration
        args.catalog = catalog_directory(args.catalog, storage)
        return _run(args, storage)
    except DfpmError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


def _run(args: argparse.Namespace, storage: Storage) -> int:
    if args.command == "paths":
        print(f"Root:               {storage.root} ({args.root_source})")
        print(f"Tools:              {storage.tools}")
        print(f"Verified downloads: {storage.cache}")
        print(f"Command shortcuts:  {storage.bin}")
        # Resolved, because a relative path answers the question with the
        # question. Where the catalog came from is worth saying too: reading a
        # different one than you expect is the quiet way every later command
        # goes wrong.
        print(f"Catalog:            {args.catalog.resolve()}")
        if args.catalog == SHIPPED:
            print("                    The entries dfpm shipped with. 'dfpm sync' fetches the published catalog.")
        elif args.catalog != storage.catalog:
            print("                    Not this machine's catalog, which is:")
            print(f"                    {storage.catalog}")
        print(f"Package records:    {storage.state / 'packages'}")
        print(f"Configuration:      {args.configuration}")
        return 0
    if args.command == "catalog":
        return _catalog(args)
    if args.command == "search":
        return _search(args)
    if args.command == "outdated":
        return _outdated(args, storage)
    if args.command == "upgrade":
        return _upgrade(args, storage)
    if args.command in ("collection", "collections"):
        return _collection(args)
    if args.command == "install":
        return _install(args, storage)
    if args.command == "sync":
        return _sync(args, storage)
    if args.command == "download":
        return _download(args)
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
        return _doctor(args, storage)
    return 1


def _config(args: argparse.Namespace) -> int:
    path = configuration.file()
    default = Storage.default().root
    if args.config_command == "set":
        try:
            previous = configuration.configured_root() or default
        except DfpmError:
            # Setting the root is also the recovery path for a damaged
            # configuration file; overwriting it must not require reading it.
            previous = None
        chosen = configuration.set_root(args.value)
        print(f"Saved dfpm root:    {chosen}")
        print(f"Configuration:      {path}")
        if previous is None:
            print("The unreadable previous setting was replaced.")
            print("Existing files were not moved. Future commands will use the saved root.")
        elif previous != chosen:
            print(f"Previous root:      {previous}")
            print("Existing files were not moved. Future commands will use the saved root.")
        return 0
    if args.config_command == "unset":
        removed = configuration.unset_root()
        print(f"Using default root: {default}")
        print(f"Configuration:      {path}")
        if not removed:
            print("No saved root setting was present.")
        print("Existing files were not moved.")
        return 0
    saved = configuration.configured_root()
    if saved is None:
        print(f"Root:               {default} (platform default)")
    else:
        print(f"Root:               {saved} (saved configuration)")
    print(f"Configuration:      {path}")
    return 0


def _other_builds(catalog: Path, manifest) -> int:
    """How many builds of this tool were not chosen, for the install plan."""
    try:
        tools = [tool for tool in load_catalog(catalog) if tool.id == manifest.id]
    except DfpmError:
        return 0
    return len(tools[0].builds) - 1 if tools else 0


def _collection(args: argparse.Namespace) -> int:
    """What can be asked for by one name, and what it stands for.

    A collection is a way of requesting packages, not a thing that gets
    installed, so there is nothing here about what is on this machine.
    """
    collections = load_collections(args.catalog)
    if not collections:
        print("This catalog offers no collections.")
        return 0
    if args.name:
        wanted = args.name.lstrip("@")
        matches = [item for item in collections if item.id == wanted]
        if not matches:
            offered = ", ".join(f"@{item.id}" for item in collections)
            raise DfpmError(f"No collection called @{wanted} in this catalog. It has: {offered}")
        chosen = matches[0]
        print(f"@{chosen.id}  {chosen.name}")
        if chosen.description:
            print(textwrap.fill(chosen.description, width=88, initial_indent="  ", subsequent_indent="  "))
        print(f"\n  {len(chosen.packages)} packages:")
        for package_id in chosen.packages:
            print(f"    {package_id}")
        print(f"\nInstall them all with 'dfpm install @{chosen.id}'.")
        return 0
    for item in collections:
        print(f"@{item.id:<22} {len(item.packages):>3} packages  {item.name}")
    print("\nRun 'dfpm collection <name>' to see what one contains.")
    return 0


def _catalog(args: argparse.Namespace) -> int:
    if args.index:
        # What a published catalog needs beside its entries, so a machine
        # syncing it can tell what is there without listing a directory.
        print(json.dumps(build_index(args.catalog), indent=2))
        return 0
    tools = load_catalog(args.catalog)
    check_collections(args.catalog)
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


def _search(args: argparse.Namespace) -> int:
    """Find tools by ordinary words, including vocabulary aliases."""
    query = " ".join(args.query).strip().lower()
    matches = []
    for tool in load_catalog(args.catalog):
        text = " ".join((tool.id, tool.name, tool.description, tool.about or "")).lower()
        direct = query in text
        classified = any(
            set(getattr(tool, field)) & classification.matching_keys(field, query)
            for field in classification.VOCABULARIES
        )
        commands = any(query in entrypoint.name.lower() for build in tool.builds for entrypoint in build.entrypoints)
        if direct or classified or commands:
            matches.append(tool)

    if args.json:
        print(json.dumps({"query": query, "packages": [describe(tool) for tool in matches]}, indent=2))
        return 0
    if not matches:
        print(f"No catalog packages match: {query}")
        return 0
    for tool in matches:
        print(f"{tool.id:<24} {catalog_newest(tool).version:<12} {tool.name}")
        print(f"{'':<24} {tool.description}")
    print("\nRun 'dfpm catalog <package>' to see everything known about one of them.")
    return 0


def _available_updates(catalog: Path, packages: list[dict]) -> list[dict]:
    """Installed and available versions in a stable, machine-readable shape."""
    updates = catalog_updates(catalog, packages)
    return [
        {
            "id": package["id"],
            "name": package.get("name") or package["id"],
            "installed_version": package.get("version"),
            "available_version": updates[package["id"]],
        }
        for package in packages
        if package["id"] in updates
    ]


def _outdated(args: argparse.Namespace, storage: Storage) -> int:
    """Report upgrades without changing the machine."""
    packages = list_packages(storage)
    updates = _available_updates(args.catalog, packages)
    if args.json:
        print(json.dumps(updates, indent=2, sort_keys=True))
        return 0
    if not packages:
        print("No packages are installed.")
        return 0
    if not updates:
        print("All installed packages are up to date.")
        return 0

    print(f"{'PACKAGE':<28} {'INSTALLED':<14} {'AVAILABLE':<14} NAME")
    for item in updates:
        print(
            f"{item['id']:<28} {item['installed_version'] or '-':<14} "
            f"{item['available_version']:<14} {item['name']}"
        )
    print("\nUpgrade selected packages with 'dfpm upgrade <package-id>', or all of them with 'dfpm upgrade --all'.")
    return 0


def _upgrade(args: argparse.Namespace, storage: Storage) -> int:
    """Upgrade only installed packages for which the catalog is newer.

    The install planner deliberately permits replacing a version with any
    explicitly selected version. Upgrade has the narrower promise its name
    implies, so it filters first and can never turn an installed package back
    to an older catalog version.
    """
    if args.all and args.package:
        raise DfpmError("Name packages or pass --all, not both.")
    if not args.all and not args.package:
        raise DfpmError("Name installed packages to upgrade, or pass --all.")

    packages = list_packages(storage)
    installed = {package["id"]: package for package in packages}
    if args.all:
        requested = [item["id"] for item in _available_updates(args.catalog, packages)]
        if not packages:
            print("Nothing is installed.")
            return 0
        if not requested:
            print("All installed packages are up to date.")
            return 0
    else:
        # Preserve the order typed while treating an accidental duplicate as
        # one request, matching the install planner's behavior.
        requested = list(dict.fromkeys(args.package))
        missing = [package_id for package_id in requested if package_id not in installed]
        if missing:
            print("\nCannot upgrade the requested set:", file=sys.stderr)
            for package_id in missing:
                print(f"  {package_id:<24} is not installed.", file=sys.stderr)
            print("\nNo changes were made.", file=sys.stderr)
            return 1

        candidates: list[str] = []
        blocked: list[tuple[str, str]] = []
        current: list[str] = []
        for package_id in requested:
            try:
                candidate = resolve(args.catalog, package_id)
            except DfpmError as exc:
                blocked.append((package_id, str(exc)))
                continue
            installed_version = installed[package_id].get("version")
            if installed_version and catalog_version_key(candidate.version) > catalog_version_key(installed_version):
                candidates.append(package_id)
            else:
                current.append(package_id)

        if blocked:
            print("\nCannot upgrade the requested set:", file=sys.stderr)
            for package_id, detail in blocked:
                print(f"  {package_id:<24} {detail}", file=sys.stderr)
            print("\nNo changes were made.", file=sys.stderr)
            return 1
        for package_id in current:
            version = installed[package_id].get("version") or "unknown version"
            print(f"{package_id} {version} is already the newest version available.")
        requested = candidates
        if not requested:
            return 0

    if len(requested) > 1:
        print(
            "Upgrade behavior: after approval, packages are installed independently; "
            "a failure does not roll back upgrades that succeeded."
        )
    args.package = requested
    return _install(args, storage)


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
    requested = args.package if isinstance(args.package, list) else [args.package]
    # Terms are settled by the prompt when there is going to be one. Asking a
    # person to confirm a plan that names the terms, and then asking again for a
    # flag, would be the same question twice.
    current = plan.for_install(
        storage,
        args.catalog,
        requested,
        version=args.package_version,
        accept_terms=args.accept_terms or not args.yes,
    )

    if len(requested) == 1 and len(current.incoming) == 1:
        _describe_install(args, storage, current.incoming[0])
    elif current.incoming:
        _summarize_install(current)

    for skip in current.skipped:
        print(f"{skip.package} {skip.version} is already installed.")
    if current.blocked:
        _report_blocked(current.blocked)
        return 1
    if not current.incoming:
        return 0
    if _declined(args.yes):
        return 2
    return _perform_installs(args, storage, current)


def _describe_install(args: argparse.Namespace, storage: Storage, item: plan.Incoming) -> None:
    """The whole story for one package, which is what one package deserves."""
    manifest = item.manifest
    previous = item.previous
    print("Install plan")
    print(f"  Package:     {manifest.name} {manifest.version}")
    if previous:
        # Replacing a version deletes its whole folder, so show what is in there
        # now rather than letting a tool's downloaded rules vanish unannounced.
        outgoing = item.outgoing or removal.plan(storage, manifest.id)
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
    # Which catalog made this claim. The digest proves the bytes match what the
    # entry said; it says nothing about whether that entry should be believed,
    # and the entry is what names the URL. So the plan says where it came from.
    if args.catalog not in (storage.catalog, SHIPPED):
        print(f"  Entry from:  {args.catalog}")
        print("               Not this machine's catalog. Install only from entries you trust.")
    print(f"  Source:      {manifest.package_url()}")
    if manifest.package.rolling:
        # Worth saying before the install rather than only when it goes wrong: a
        # pinned digest against a URL like this describes a moment, not a release.
        print("               Rolling: the publisher replaces this file rather than adding a new one.")
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


def _summarize_install(current: plan.Plan) -> None:
    """What a set costs, said once. Repeating the single-package block per
    package would put hundreds of lines between the request and the question."""
    print(f"Install plan: {len(current.incoming)} packages")
    for item in current.incoming:
        manifest = item.manifest
        size = f", {human_size(item.download_size)}" if manifest.package.size is not None else ""
        replaces = f", replacing {item.previous}" if item.previous else ""
        print(f"  {manifest.name} {manifest.version} ({manifest.id}){replaces}{size}")
    if current.download_size:
        print(f"  Download:    {human_size(current.download_size)}")
    if current.extracted_size:
        installed = human_size(current.extracted_size)
        if current.entry_count:
            installed += f" across {current.entry_count:,} files"
        print(f"  Installed:   {installed}")
    if current.free_space is not None:
        print(f"  Disk:        {human_size(current.free_space)} free on that volume")
        if current.fits is False:
            print("               That is less than this would install.")
    if current.rolling:
        print(f"  Rolling:     {len(current.rolling)} of these have URLs the publisher replaces")
    if current.terms:
        named = ", ".join(name for name, _ in current.terms)
        count = len(current.terms)
        print(f"  Terms:       {count} package{'' if count == 1 else 's'} need{'s' if count == 1 else ''} acceptance ({named})")
    for requirement in current.unmet:
        print(f"  Runtime:     {requirement.detail}, needed by {len(requirement.wanted_by)}")
    print("  System-wide changes: none")


def _report_blocked(blocked: list[plan.Blocked]) -> None:
    """Why nothing happened. Reported together so one run names every problem."""
    print("\nCannot install the requested set:", file=sys.stderr)
    for item in blocked:
        print(f"  {item.package:<24} {item.detail}", file=sys.stderr)
        if item.reason == plan.TERMS_NOT_ACCEPTED:
            print(f"  {'':<24} Pass --accept-terms if they permit your use.", file=sys.stderr)
    print("\nNo changes were made.", file=sys.stderr)


def _perform_installs(args: argparse.Namespace, storage: Storage, current: plan.Plan) -> int:
    """Install what the plan approved, reporting rather than stopping on a failure.

    Atomicity ended when the plan was approved. Letting one download failure
    abandon the packages after it would turn a recoverable problem into a
    half-finished machine nobody asked for.
    """
    reporter = progress.reporter()
    installed: list[plan.Incoming] = []
    failed: list[tuple[str, str]] = []
    total = len(current.incoming)
    try:
        for position, item in enumerate(current.incoming, start=1):
            if total > 1:
                # One progress bar serves the whole set and restarts per stage,
                # so without this a long batch reads as one download that keeps
                # going back to nothing.
                print(f"[{position}/{total}] {item.manifest.name} {item.manifest.version}")
            try:
                destination = install(
                    item.manifest,
                    storage,
                    on_progress=reporter,
                    on_mismatch=_digest_decision(item.manifest.package, args.accept_digest_mismatch),
                )
            except DfpmError as exc:
                if len(current.incoming) == 1:
                    raise
                failed.append((item.manifest.id, str(exc)))
                continue
            installed.append(item)
            if len(current.incoming) == 1:
                print(f"Installed to {destination}")
                if item.previous:
                    print(f"Removed the previous version, {item.previous}.")
    finally:
        if reporter is not None:
            reporter.close()

    if len(current.incoming) > 1:
        print(f"\nInstalled {len(installed)} of {len(current.incoming)} packages.")
        if failed:
            print("\nFailed:", file=sys.stderr)
            for package_id, detail in failed:
                print(f"  {package_id:<24} {detail}", file=sys.stderr)
    for item in installed:
        _report_readiness(storage, item.manifest)
    return 1 if failed else 0


def _declined(assume_yes: bool) -> bool:
    """Whether the plan just printed was not agreed to.

    A plan nobody answered is a plan nobody agreed to, so silence is a no. It has
    to be said rather than raised: a scheduled job or a piped command reaches
    this with nothing on standard input, and a stack trace would tell whoever
    finds it nothing about whether dfpm had already changed something.
    """
    if assume_yes:
        return False
    try:
        if input("Continue? [y/N] ").strip().lower() in {"y", "yes"}:
            return False
        print("No changes made.")
    except EOFError:
        print("\nNo answer given, so nothing was changed. Pass --yes to confirm without being asked.")
    return True


def _digest_decision(package, accepted: bool):
    """How this run answers an artifact that is not the one the catalog described.

    Only reached for a package whose URL the publisher replaces; an immutable one
    never gets this far. The flag is deliberately not implied by --yes, for the
    same reason --accept-terms is not: confirming a plan and accepting bytes
    nobody reviewed are different claims, and the plan was drawn up before the
    file was fetched.
    """
    def decide(expected: str, actual: str) -> bool:
        if accepted:
            return True
        if not sys.stdin.isatty():
            return False
        print(f"\n{downloads.mismatch_report(package, actual, remedy=False)}", file=sys.stderr)
        try:
            answer = input("Continue? [y/N] ")
        except EOFError:
            # Nothing is there to answer. Falling through to the full report is
            # better than treating silence as either yes or a bare refusal.
            return False
        if answer.strip().lower() in {"y", "yes"}:
            return True
        raise DfpmError("No changes made.")

    return decide


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


def _sync(args: argparse.Namespace, storage: Storage) -> int:
    """Bring this machine's catalog into line with a published one.

    Entries decide what gets installed, so this is a thing somebody asks for
    rather than something that happens in the background, and it says what it
    would change before changing it.
    """
    source = args.source or DEFAULT_SOURCE
    current = sync.plan(source, storage.catalog)

    print("Catalog sync plan")
    print(f"  Source:      {source}")
    print(f"  Into:        {storage.catalog}")
    for kind, label in ((sync.ADDED, "Add"), (sync.UPDATED, "Update"), (sync.EDITED, "Replace"), (sync.REMOVED, "Remove")):
        for change in current.of(kind):
            version = f"  {change.version}" if change.version else ""
            print(f"  {label + ':':<12} {change.id}{version}")
    unchanged = current.of(sync.UNCHANGED)
    if unchanged:
        print(f"  Unchanged:   {len(unchanged)}, which will not be downloaded again")
    if current.of(sync.EDITED):
        print("  Some entries were changed on this machine since the last sync. Replacing them discards those edits.")
    if not current.changes_anything:
        print("Already up to date.")
        return 0
    print(f"  Downloads:   {len(current.fetches)} entr{'y' if len(current.fetches) == 1 else 'ies'}")
    print("  Nothing is installed or removed. This only changes what is available to install.")

    if _declined(args.yes):
        return 2

    applied = sync.apply(current)
    print(f"Catalog updated: {len(applied)} entr{'y' if len(applied) == 1 else 'ies'} changed")
    print(f"  {storage.catalog}")
    return 0

def _download(args: argparse.Namespace) -> int:
    """Save a package's release file, for a machine dfpm is not running on.

    Installing a build this machine cannot run would be meaningless, but there
    is nothing wrong with wanting the file itself. This is that and nothing
    more: the release, under the name its project gave it, in a directory of
    your choosing. Whatever the other machine does with it is its own business.
    """
    requested = args.package if isinstance(args.package, list) else [args.package]
    directory = args.destination or Path.cwd()
    if not directory.is_dir():
        raise DfpmError(f"Not a directory: {directory}")

    manifests, blocked = plan.resolve(args.catalog, requested, args.package_version, args.platform)
    if blocked:
        for item in blocked:
            print(f"error: {item.detail}", file=sys.stderr)
        return 1

    # Two packages can publish assets with the same filename, and retrieve
    # refuses to overwrite. Finding that out after the first download is a worse
    # way to learn it than being told before any of them start.
    targets = {}
    for manifest in manifests:
        target = directory / _released_filename(manifest)
        if target in targets:
            raise DfpmError(
                f"{manifest.id} and {targets[target]} would both be saved as {target.name}. "
                "Download them separately, or into different directories."
            )
        targets[target] = manifest.id

    failed = False
    for manifest in manifests:
        if not _download_one(args, manifest, directory / _released_filename(manifest)):
            failed = True
    return 1 if failed else 0


def _download_one(args: argparse.Namespace, manifest, target: Path) -> bool:
    size = f", {human_size(manifest.package.size)}" if manifest.package.size else ""
    print(f"Downloading {manifest.name} {manifest.version} for {manifest.platform or 'any platform'}{size}")
    print(f"  from {manifest.package_url()}")
    print(f"  to   {target}")

    reporter = progress.reporter()
    try:
        saved = retrieve(
            manifest.package,
            manifest.package_url(),
            target,
            reporter,
            _digest_decision(manifest.package, args.accept_digest_mismatch),
        )
    except DfpmError as exc:
        print(f"error: {manifest.id}: {exc}", file=sys.stderr)
        return False
    finally:
        if reporter is not None:
            reporter.close()
    print(f"Saved {target}")
    if saved.verified:
        print(f"  sha256 {saved.digest}, which is what the catalog pinned")
    else:
        # Saying only what it hashes to would leave the reader to notice for
        # themselves that it is not the file the catalog describes.
        print(f"  sha256 {saved.digest}")
        print(f"  The catalog pinned {manifest.package.sha256}, so this is not the reviewed file.")
    return True


def _released_filename(manifest) -> str:
    """What to call a saved download, falling back when the URL names nothing usable."""
    return published_filename(manifest.package.url) or f"{manifest.id}-{manifest.version}"


def _uninstall(args: argparse.Namespace, storage: Storage) -> int:
    requested = args.package if isinstance(args.package, list) else [args.package]
    if args.all:
        if requested:
            raise DfpmError("Name packages or pass --all, not both.")
        requested = [record["id"] for record in list_packages(storage)]
        if not requested:
            print("Nothing is installed.")
            return 0

    current = plan.for_uninstall(storage, requested, args.catalog)
    if current.blocked:
        for item in current.blocked:
            print(f"error: {item.detail}", file=sys.stderr)
        return 1
    if len(current.outgoing) == 1:
        _describe_uninstall(current.outgoing[0])
    else:
        _summarize_uninstall(current)
    if _declined(args.yes):
        return 2

    # Shim reconciliation rebuilds every command from every remaining record,
    # so doing it once at the end rather than once per package is the whole
    # difference between linear and quadratic work on a large set.
    removed = []
    for item in current.outgoing:
        removal.execute(storage, item, reconcile=False)
        removed.append(item)
    shims.reconcile(storage)
    for item in removed:
        print(f"Removed {item.package} {item.version}")
    return 0


def _describe_uninstall(item) -> None:
    print("Removal plan")
    print(f"  Package:     {item.name} {item.version} ({item.package})")
    print(f"  Removes:     {item.root}")
    print(f"               {item.file_count:,} file(s), {human_size(item.total_size)}")
    if item.grew:
        # The tool may maintain its own files, or someone may have added their
        # own. Either way the whole directory goes, so say so before it does.
        print(f"  Note:        the install put {item.installed_count:,} file(s) here; everything present now is removed")
    if item.commands:
        print(f"  Commands:    {', '.join(item.commands)} removed")
    print("  Downloads stay in the cache; 'dfpm cache prune' clears them.")


def _summarize_uninstall(current: plan.Plan) -> None:
    print(f"Removal plan: {len(current.outgoing)} packages")
    for item in current.outgoing:
        print(f"  {item.name} {item.version} ({item.package}), {item.file_count:,} file(s), {human_size(item.total_size)}")
    print(f"  Removes:     {current.reclaimed_files:,} file(s), {human_size(current.reclaimed_size)}")
    print("  Downloads stay in the cache; 'dfpm cache prune' clears them.")


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
    if _declined(args.yes):
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
    if _declined(args.yes):
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
    updates = catalog_updates(args.catalog, packages)
    if args.json:
        print(json.dumps(
            [package | {"update_available": updates[package["id"]]} if package["id"] in updates else package
             for package in packages],
            indent=2,
            sort_keys=True,
        ))
        return 0
    if not packages:
        print("No packages are installed.")
        return 0
    for package in packages:
        newer = updates.get(package["id"])
        note = f"  ({newer} available)" if newer else ""
        print(f"{package['id']:<28} {package.get('version', '-'):<14} {package.get('name', '')}{note}")
    if updates:
        names = ", ".join(sorted(updates))
        print(f"\nThe catalog has a newer version of: {names}")
        print("Installing one replaces the version you have: dfpm install <package-id>")
    return 0


def _doctor(args: argparse.Namespace, storage: Storage) -> int:
    if args.yes and not args.repair:
        raise DfpmError("--yes is only meaningful with doctor --repair")
    if args.repair:
        if args.package:
            raise DfpmError("doctor --repair checks the whole dfpm root; it cannot be narrowed to one package")
        actions = repair_plan(storage)
        print("Doctor repair plan")
        print("------------------")
        if not actions:
            print("No safe automatic repairs are available.")
        else:
            for action in actions:
                print(f"  {action.detail}")
                print(f"    Target: {action.target}")
            if _declined(args.yes):
                return 0
            applied = apply_repairs(storage, actions)
            print(f"Applied {len(applied)} repair(s).")
        findings = inspect(storage)
        remaining = [item for item in findings if item.status != "passing"]
        if remaining:
            print("\nProblems that still need attention:")
            _print_doctor_findings(remaining)
        return _doctor_exit(findings)

    findings = inspect(storage, args.package)
    if args.json:
        print(json.dumps([item.__dict__ for item in findings], indent=2))
    elif not findings:
        print("No installed packages or dfpm maintenance problems to check.")
    else:
        _print_doctor_findings(findings)
    return _doctor_exit(findings)


def _print_doctor_findings(findings) -> None:
    markers = {"passing": "PASS", "blocked": "WAIT", "failed": "FAIL", "unverified": "WARN"}
    for finding in findings:
        marker = markers.get(finding.status, "FAIL")
        print(f"{marker:<4} {finding.package} {finding.version}: {finding.detail}")


def _doctor_exit(findings) -> int:
    # A machine missing a runtime is not a broken install, so it gets its own
    # code: a script can tell "dfpm is wrong" from "this box is not ready".
    if any(item.status == "failed" for item in findings):
        return 1
    return 2 if any(item.status == "blocked" for item in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())

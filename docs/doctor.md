# Checking and repairing a dfpm installation

`dfpm doctor` is a read-only inspection. It checks installed entrypoints and declared verification files, command shortcuts, runtime readiness, state records, package directories, catalog transaction leftovers, old staging directories, interrupted downloads and cached artifact digests.

```powershell
dfpm doctor
dfpm doctor <package-id>
dfpm doctor --json
```

The exit code is `1` when dfpm-owned state is broken, `2` when installed tools are intact but a required runtime is unavailable, and `0` otherwise.

## Safe repairs

`dfpm doctor --repair` first prints a plan and asks before changing anything. `--yes` confirms that displayed plan noninteractively.

```powershell
dfpm doctor --repair
dfpm doctor --repair --yes
```

Repairs are deliberately narrow:

- missing, stale and obsolete dfpm-owned command shortcuts are reconciled;
- a state record is forgotten when its recorded installation directory no longer exists;
- install and catalog staging directories untouched for at least 24 hours are removed;
- a previous catalog snapshot is restored when an interrupted directory swap left no active catalog;
- an obsolete catalog backup is removed only when the active catalog validates;
- old partial downloads are removed; and
- a cache file whose contents do not match its digest filename is moved under `quarantine\cache\` rather than deleted.

Doctor does not replace unmanaged shortcut files, remove unrecorded package directories, reconstruct missing package files, install runtimes, redownload artifacts or guess how to repair unreadable state. It reports those conditions for manual handling.

Package-specific inspection is read-only. Repairs operate on the complete dfpm root because shortcut and transaction consistency crosses package boundaries.

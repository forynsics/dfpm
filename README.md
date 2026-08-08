# dfpm

dfpm is a package manager for digital forensics tools. It exists to build, freeze, repair, and reproduce known-good forensic environments.

It is designed around one core principle: forensic tools and forensic content should be managed directly, with their exact artifacts, versions, configuration, validation results, and provenance kept under explicit control. General-purpose package managers may satisfy approved machine-level prerequisites, but they are not dfpm package sources.

> Build a trusted forensic toolchain without surrendering its lifecycle to a general-purpose package manager.

## What dfpm is building

dfpm brings three connected capabilities together:

- A searchable registry organized around forensic evidence, artifacts, formats, and operations.
- Reproducible environments with profiles, exact lockfiles, side-by-side versions, and stable entrypoints.
- A trusted distribution layer with digest verification, provenance, health checks, repair, and rollback.

Packages can represent tools, isolated runtimes, rulesets, parser packs, artifact packs, integrations, and configuration packs. dfpm does not acquire or interpret evidence, manage cases, or execute investigation workflows.

## Lifecycle ownership

Forensic packages are downloaded into content-addressed storage, verified, staged in isolated version directories, validated against bounded synthetic fixtures, and only then activated. Previous working versions remain available for rollback.

Machine-level prerequisites such as shared runtimes and Windows features are handled separately. dfpm detects them first, requires an explicit provider and authorization for changes, validates the resulting capability independently, and records the observed state in the environment lockfile.

This distinction supports three honest reproducibility grades:

- **Hermetic:** all relevant bytes are managed by dfpm.
- **Pinned external:** external prerequisites are constrained and recorded.
- **Observed external:** required system state is detected but cannot be reproduced exactly.

## Product preview

This repository contains an interactive public catalog and the first working version of the local package-management core. The public experience helps practitioners discover and understand tools without requiring prior knowledge of the DFIR ecosystem.

The current prototype covers:

- Plain-language, artifact-first tool discovery.
- Curated starter kits for common investigation tasks.
- Introductory guides organized by evidence type.
- Explicit install, cache, command, and configuration locations.
- Installed versions and health status in local mode.
- Update planning with validation and rollback safeguards.
- A compact, accessible interface designed for clear reading on the web.

The browser preview models reviewed lifecycle operations but is not connected to the Python core yet. It does not install software or modify system prerequisites.

## Current scope

The initial target is Windows 11 x64, with portable tools prioritized for strong isolation and rollback. Planned package sources include reviewed GitHub releases, fixed HTTPS and local artifacts, ZIP/7z archives, MSI packages, and conventional EXE installers.

Longer-term plans include Linux and macOS support, private and offline registries, signed repository snapshots, organization policy, validation infrastructure, and stable catalog and inventory APIs.

## Project status

dfpm is in an early implementation phase. The Python core supports manifest validation, verified local and HTTPS artifacts, bounded portable ZIP installation, replacing installs, conservative removal, a manageable download cache, owned command shims, and read-only health checks. Interfaces, manifests, and behavior remain subject to change.

Lockfile export, repair, release discovery, executable health checks, and interpreter-backed packages are planned but not built. The command line ships only what is actually implemented.

The `catalog/` directory holds reviewed manifests. It currently contains one package, YARA 4.5.5 for Windows x64, pinned to its official release artifact and digest. See [catalog/README.md](catalog/README.md) for how a package is reviewed before it is added.

## Current command-line interface

dfpm requires Python 3.11 or newer. Install the current development version in an isolated environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --editable .
```

The initial commands are:

```text
dfpm paths
dfpm catalog
dfpm install <package-id> [--package-version <version>]
dfpm uninstall <package-id>
dfpm run <command> [arguments...]
dfpm which <command>
dfpm cache list | verify | prune | remove <digest>
dfpm gui
dfpm list
dfpm doctor
```

**One version of a package is installed at a time.** Installing replaces whatever was there before, the way `apt` and `pip` behave, so a tools directory never fills up with old copies you have to think about. The previous version is removed only after the new one is installed and working, so a failed install leaves the old one untouched.

Going back to an older release is the same command with a version: `dfpm install yara --package-version 4.5.4`. That is usually instant and needs no network, because the artifact is already in the verified cache.

Installation always displays the package, the version being replaced, platform, license, upstream project, source, digest, destination, and system-wide impact before making changes. A package that declares a platform is refused outright on a machine that does not match it. Use `--yes` only when the plan has already been reviewed.

Every archive is extracted under fixed size, entry-count, and expansion limits, and unsafe entries are rejected outright. See the [manifest format](docs/manifest-v1.md) for the full list.

Removal is equally explicit. `dfpm uninstall` previews everything dfpm owns, then deletes only the files it recorded at install time and can still recognize. Files it did not install, and managed files whose contents have changed since installation, are preserved and reported rather than deleted.

## The verified download cache

Every artifact dfpm downloads is verified and then kept in a content-addressed cache, named by its own SHA-256. Keeping it is not about the uninstall-then-reinstall case, which is rare. It earns its disk for four reasons that matter to forensic work:

- **Offline and air-gapped installs.** Populate the cache on a connected machine, copy the directory to an isolated one, and install with no network at all.
- **Upstream is not permanent.** Release assets get deleted and versions get yanked. A pinned digest is worthless without the bytes, and re-running an analysis years later needs the exact version that was used at the time.
- **Repair without a download.** A damaged install can be rebuilt from the artifact already proven to match its digest.
- **Provenance.** The cached file is literally the bytes that were verified and installed.

`dfpm cache` keeps that from growing without bound:

```powershell
dfpm cache list      # every artifact, its size, and what still needs it
dfpm cache verify    # re-hash each one; the name is the digest, so a mismatch means corruption
dfpm cache prune     # remove everything no installed package needs, and interrupted downloads
dfpm cache remove <digest>
```

`prune` clears everything no installed package needs, which is the behaviour `apt clean` gives you and needs no flags for the common case. If you are seeding a cache for offline installs, `--keep-catalog` narrows it to artifacts no manifest lists either, and in that mode a catalog that cannot be read makes `prune` refuse rather than treat everything as unused. `remove` refuses a digest an installed package still depends on unless you pass `--force`, and files dfpm does not recognize are reported and left alone, exactly as they are during uninstall.

## Running installed tools

**dfpm never modifies your PATH.** Changing a system-wide setting on your behalf is exactly the kind of surprise a forensic toolchain should not spring on you, so the decision stays yours. There are three ways to reach an installed tool.

The recommended one is `dfpm run`, which needs no setup and removes all ambiguity about which binary executed:

```powershell
dfpm run yara --version
dfpm run yara rules.yar C:\evidence\collected
```

It looks up the command in the active version of each installed package, runs that exact file, and passes your arguments through as a real argument list. Its exit code is the tool's exit code, so it composes normally in scripts. `dfpm which` shows what a command resolves to before you run it:

```text
yara -> C:\Users\you\AppData\Local\dfpm\tools\yara\4.5.5\yara64.exe
  Package:  yara 4.5.5
  Shortcut: C:\Users\you\AppData\Local\dfpm\bin\yara.cmd
  On PATH:  not reachable. Use 'dfpm run yara', the full path above,
            or add C:\Users\you\AppData\Local\dfpm\bin to your PATH yourself.
```

The second option is to add the command-shortcut directory to your PATH yourself. In PowerShell, for the current user only:

```powershell
$bin  = "$env:LOCALAPPDATA\dfpm\bin"
$user = [Environment]::GetEnvironmentVariable("Path", "User")
$new  = if ([string]::IsNullOrEmpty($user)) { $bin } else { "$bin;$user" }
[Environment]::SetEnvironmentVariable("Path", $new, "User")
```

Two cautions if you do. Do not use `setx` for this: it silently truncates PATH at 1024 characters and has destroyed many people's environments. And if your user PATH already contains `%VARIABLE%` references, edit it through the Windows *Environment Variables* dialog instead, because the API above rewrites the value as literal text and those references would stop expanding. Either way the change only affects newly opened terminals.

Putting the directory first, as above, means dfpm's tools win. That is usually what you want from a toolchain manager, but it does mean a `yara` installed by something else is shadowed. Windows resolves a bare command by scanning PATH left to right, and within one directory it tries extensions in `PATHEXT` order — where `.EXE` comes before `.CMD` — so another tool's `yara.exe` earlier on PATH would win over dfpm's `yara.cmd`. `dfpm which` reports when that is happening.

The third option is simply to invoke the full path shown by `dfpm which`, which is what the command shortcut does internally.

## Local interface

`dfpm gui` serves a management interface backed by the same core the command line uses, then opens it in a browser. It lists installed packages, browses the reviewed catalog, shows health results, and performs installs, updates, and removal. Every change shows the same plan the command line prints and waits for confirmation.

The interface is built for a single local operator, not for shared or remote use:

- It binds loopback only, and refuses to bind any other address.
- Each run mints a session token that is delivered in the served page and required on every API request.
- Requests carrying an unexpected `Host` or a foreign `Origin` are rejected, which blocks DNS rebinding and cross-site requests.
- Changes must arrive as `application/json`, so a cross-origin form cannot reach them, and only one change runs at a time.

```powershell
dfpm gui --port 8765          # default; use --port 0 to take any free port
dfpm gui --no-browser         # start the server without opening a browser
```

The interface shares the public site's visual system: `src/dfpm/web/styles.css` and `refinements.css` are byte-identical copies of the root stylesheets, and interface-only rules live in `local.css`. A test fails if the copies drift, so the two surfaces cannot quietly diverge. The root `index.html` remains a public catalog preview with illustrative data and is not connected to the Python core.

The default Windows data locations are rooted in `%LOCALAPPDATA%\dfpm`:

```text
tools\<package-id>\<version>\  Installed package versions
cache\sha256\                 Verified downloaded artifacts
bin\                          Stable command shortcuts
state\packages\               Managed-file and version records
```

See the [manifest format](docs/manifest-v1.md) for the currently supported package definition.

## Security and privacy

Telemetry is disabled by default. dfpm is not intended to receive evidence, case information, or forensic results. Security reporting guidance will be published before the first distributable release.

## License

Licensing terms have not yet been selected. Until a license is added, the repository remains all rights reserved.

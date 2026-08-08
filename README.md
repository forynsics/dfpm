<p align="center">
  <img src="assets/brix-hero.png" alt="Brix, the dfpm mascot, holding a wrench" width="120">
</p>

<h1 align="center">dfpm</h1>

<p align="center"><strong>A package manager for digital forensics tools</strong></p>

<p align="center">
  <img src="assets/divider-dam.png" alt="" width="440">
</p>

Forensic tooling is scattered across project pages, release feeds, personal sites and word of mouth — and you have to already know a tool exists before you can go looking for it. dfpm gathers them into one catalog you can browse and install from, then keeps track of what you installed, where it went, and exactly which version is running.

It installs tools straight from the releases their projects publish, pins the exact artifact and its digest, shows you the plan before it touches anything, and keeps every file in a folder it has told you about.

> Build a trusted forensic toolchain without surrendering its lifecycle to a general-purpose package manager.

dfpm does not acquire or interpret evidence, manage cases, or run investigation workflows. It manages the tools you use to do those things, and nothing more.

## Why it exists

<img align="right" width="96" src="assets/brix-magnifier.png" alt="">

**It will not install anything it cannot verify.** Every package pins a SHA-256. The download is refused unless the bytes match exactly, and refused again if an HTTPS source quietly redirects to plain HTTP. A digest you cannot check is not provenance.

**It will not leave you guessing which version ran.** One version of a package is installed at a time. Installing replaces what was there, and the old version is removed only once the new one is in place and working. No stack of folders to reason about mid-case.

**It will not change your system behind your back.** dfpm never edits your PATH, never writes outside the folders it shows you, and deletes only files it installed and can still recognise. Anything it did not put there is preserved and reported.

**And one thing it always does.** It prints the plan first — package, version, platform, licence, source, digest, destination, and what will be replaced — every time, before anything changes.

## How it works

Every install follows the same five steps. If any of them fails, the step before it is left exactly as it was.

1. **The package points at an official release.** An entry names the artifact the project itself published and pins its SHA-256 and size, alongside the licence and the platform it was built for. dfpm never repackages, rebuilds or mirrors anything.
2. **The artifact is fetched and verified.** Downloaded over HTTPS into a content-addressed cache and checked against the pinned digest and size. A redirect that drops out of HTTPS is refused outright.
3. **The archive is opened under limits.** Extraction is bounded by entry count, total size, per-file size and expansion ratio. Path traversal, drive letters, symlinks, encrypted entries, reserved device names and case collisions are all rejected.
4. **The result is checked before it counts.** Files land in a staging directory first. The expected entrypoints and health-check files must be present, or the whole install is discarded and nothing becomes active.
5. **Only then does it take over.** The staged version moves into place atomically, command shortcuts are rewritten, and the version it replaces is removed.

<p align="center">
  <img src="assets/divider-dam.png" alt="" width="440">
</p>

## Get started

<img align="right" width="110" src="assets/brix-laptop.png" alt="">

dfpm requires Python 3.11 or newer and currently targets Windows 11 x64.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --editable .
```

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

Installation always displays the package, the version being replaced, platform, licence, upstream project, source, digest, destination, and system-wide impact before making changes. A package that declares a platform is refused outright on a machine that does not match it. Use `--yes` only when the plan has already been reviewed.

Removal is equally explicit. `dfpm uninstall` previews everything dfpm owns, then deletes only the files it recorded at install time and can still recognise. Files it did not install, and managed files whose contents have changed since installation, are preserved and reported rather than deleted.

## The catalog

<img align="right" width="100" src="assets/brix-box.png" alt="">

The `catalog/` directory holds the manifests dfpm can install from. Each one names the release artifact its project published, pins that artifact's SHA-256 and size, and records the upstream project, its licence and the platform it was built for.

It currently contains one package, **YARA 4.5.5 for Windows x64**. dfpm is in early development, so the catalog is still being built out. See [catalog/README.md](catalog/README.md) for what goes into an entry.

Every archive is extracted under fixed size, entry-count and expansion limits, and unsafe entries are rejected outright. See the [manifest format](docs/manifest-v1.md) for the full list.

## Running installed tools

**dfpm never modifies your PATH.** Changing a system-wide setting on your behalf is exactly the kind of surprise a forensic toolchain should not spring on you, so the decision stays yours. There are three ways to reach an installed tool.

The recommended one is `dfpm run`, which needs no setup and removes all ambiguity about which binary executed:

```powershell
dfpm run yara --version
dfpm run yara rules.yar C:\evidence\collected
```

It looks up the command among the installed packages, runs that exact file, and passes your arguments through as a real argument list. Its exit code is the tool's exit code, so it composes normally in scripts. `dfpm which` shows what a command resolves to before you run it:

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

Putting the directory first means dfpm's tools win. That is usually what you want from a toolchain manager, but it does mean a `yara` installed by something else is shadowed. Windows resolves a bare command by scanning PATH left to right, and within one directory it tries extensions in `PATHEXT` order — where `.EXE` comes before `.CMD` — so another tool's `yara.exe` earlier on PATH would win over dfpm's `yara.cmd`. `dfpm which` reports when that is happening.

The third option is simply to invoke the full path shown by `dfpm which`, which is what the command shortcut does internally.

## The verified download cache

Every artifact dfpm downloads is verified and then kept in a content-addressed cache, named by its own SHA-256. Keeping it is not about the uninstall-then-reinstall case, which is rare. It earns its disk for four reasons that matter to forensic work:

- **Offline and air-gapped installs.** Populate the cache on a connected machine, copy the directory to an isolated one, and install with no network at all.
- **Upstream is not permanent.** Release assets get deleted and versions get yanked. A pinned digest is worthless without the bytes, and re-running an analysis years later needs the exact version that was used at the time.
- **Repair without a download.** A damaged install can be rebuilt from the artifact already proven to match its digest.
- **Provenance.** The cached file is literally the bytes that were verified and installed.

```powershell
dfpm cache list      # every artifact, its size, and what still needs it
dfpm cache verify    # re-hash each one; the name is the digest, so a mismatch means corruption
dfpm cache prune     # remove everything no installed package needs, and interrupted downloads
dfpm cache remove <digest>
```

`prune` clears everything no installed package needs, which is the behaviour `apt clean` gives you and needs no flags for the common case. If you are seeding a cache for offline installs, `--keep-catalog` narrows it to artifacts no manifest lists either, and in that mode a catalog that cannot be read makes `prune` refuse rather than treat everything as unused. `remove` refuses a digest an installed package still depends on unless you pass `--force`, and files dfpm does not recognise are reported and left alone, exactly as they are during uninstall.

## Local interface

`dfpm gui` serves a management interface backed by the same core the command line uses, then opens it in a browser. It lists installed packages, browses the catalog, shows health results, and performs installs, updates and removal. Every change shows the same plan the command line prints and waits for confirmation.

The interface is built for a single local operator, not for shared or remote use:

- It binds loopback only, and refuses to bind any other address.
- Each run mints a session token that is delivered in the served page and required on every API request.
- Requests carrying an unexpected `Host` or a foreign `Origin` are rejected, which blocks DNS rebinding and cross-site requests.
- Changes must arrive as `application/json`, so a cross-origin form cannot reach them, and only one change runs at a time.

```powershell
dfpm gui --port 8765          # default; use --port 0 to take any free port
dfpm gui --no-browser         # start the server without opening a browser
```

There are two web surfaces and they share one visual system. `src/dfpm/web/` is the local interface above; `index.html` at the repository root is the public site, which explains dfpm and browses the catalog but installs nothing. `styles.css` and `refinements.css` are byte-identical in both, and a test fails if the copies drift.

The default Windows data locations are rooted in `%LOCALAPPDATA%\dfpm`:

```text
tools\<package-id>\<version>\  The installed version
cache\sha256\                 Verified downloaded artifacts
bin\                          Command shortcuts
state\packages\               Managed-file records
```

## Project status

<img align="right" width="96" src="assets/brix-sleeping.png" alt="">

dfpm is in early development. Interfaces, manifests and behaviour remain subject to change, and the command line ships only what is actually implemented.

**Working today:** manifest validation, verified local and HTTPS artifacts, bounded portable ZIP installation, replacing installs, conservative removal, a manageable download cache, command shortcuts and `dfpm run`, a loopback management interface, and read-only health checks.

**Not built yet:** lockfile export, repair, release discovery, executable health checks, a `dfpm search` command, and packages that need an interpreter such as Python, Perl or Java. Linux and macOS support, private and offline registries, signed repository snapshots and organisation policy are longer-term.

Packages may eventually represent tools, isolated runtimes, rulesets, parser packs, artifact packs, integrations and configuration packs. Today only portable ZIP tools are supported.

## Security and privacy

Telemetry is disabled by default. dfpm is not intended to receive evidence, case information, or forensic results. Security reporting guidance will be published before the first distributable release.

## License

Licensing terms have not yet been selected. Until a license is added, the repository remains all rights reserved.

<p align="center">
  <img src="assets/divider-dam.png" alt="" width="440">
</p>

<p align="center">
  <sub><strong>Brix</strong> · Chief Package Officer</sub>
</p>

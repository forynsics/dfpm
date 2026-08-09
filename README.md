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

## What it is responsible for

**dfpm installs forensic tools and provides the environment needed to invoke them. Platform requirements are detected and reported, not installed.**

| | |
| --- | --- |
| Download a tool, verify its digest, install it | yes |
| Know its entrypoints and run them from the right directory | yes |
| Pass your arguments through unchanged | yes |
| Detect a required runtime and check its version | yes |
| Explain precisely why a tool will not run | yes |
| Set environment for one invocation | yes |
| Install .NET, Java, Python or any other runtime | no |
| Change your PATH, your `JAVA_HOME`, or any other global setting | no |
| Manage operating system components | no |

That boundary buys a stronger promise than guaranteeing every dependency on a machine: **dfpm either launches a tool in the environment it expects, or tells you exactly why it cannot.** A package installs whether or not the machine can run it yet, and says which it is.

## Why it exists

<img align="right" width="96" src="assets/brix-magnifier.png" alt="">

**It will not install anything it cannot verify.** Every package pins a SHA-256. The download is refused unless the bytes match exactly, and refused again if an HTTPS source quietly redirects to plain HTTP. Cached artifacts are re-hashed every time they are used, not only when first downloaded. A digest you cannot check is not provenance.

**It will not leave you guessing which version ran.** One version of a package is installed at a time. Installing replaces what was there, and the old version is removed only once the new one is in place and working. No stack of folders to pick through mid-case.

**It will not change your system behind your back.** dfpm never edits your PATH, never writes outside the folders it shows you, and deletes only the directories it created. Removing a package removes its own folder and its command shortcuts — nothing else on your machine is touched.

**And one thing it always does.** It prints the plan first — package, version, platform, license, source, digest, download size, what the install costs on disk, free space, destination, and what will be replaced — every time, before anything changes.

## How it works

Every install follows the same five steps. If any of them fails, the step before it is left exactly as it was.

1. **The package points at an official release.** An entry names the file the project itself published and records its SHA-256, alongside the license and the platform it was built for. dfpm never repackages, rebuilds or mirrors anything.
2. **The artifact is fetched and checked.** Downloaded over HTTPS into a content-addressed cache and re-hashed against the digest the entry recorded. Anything else is refused, as is a redirect that drops out of HTTPS.
3. **The archive stays inside the directory it was given.** Path traversal, absolute paths, drive letters, symlinks, encrypted entries, reserved device names and case collisions are all rejected outright. Extraction is refused if the result would not fit the volume, with a reserve kept back so a successful install never leaves you at zero bytes free.
4. **The result is checked before it counts.** Files land in a staging directory first. The expected entrypoints and health-check files must be present, and the size and file count must match what the manifest recorded, or the whole install is discarded and nothing is installed.
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
dfpm catalog [<package-id>]
dfpm install <package-id> [--package-version <version>]
dfpm download <package-id> [--platform <os/arch>] [--to <dir>]
dfpm uninstall <package-id>
dfpm run <command> [arguments...]
dfpm which <command>
dfpm cache list | verify | prune | remove <digest>
dfpm gui
dfpm list
dfpm doctor
```

**One version of a package is installed at a time.** Installing replaces whatever was there before, so a tools directory never fills up with old copies you have to think about. The previous version is removed only after the new one is installed and working, so a failed install leaves the old one untouched.

Going back to an older release is the same command with a version: `dfpm install yara --package-version 4.5.4`. That is usually instant and needs no network, because the artifact is already in the verified cache.

Installation always displays the plan before making changes:

```text
Install plan
  Package:     YARA 4.5.5
  Platform:    windows/x64
  License:     BSD-3-Clause
  Source:      https://github.com/VirusTotal/yara/releases/download/v4.5.5/...
  SHA-256:     352396c8a3d9b31b157a4820abd3b9347fc934a2314cdda8a4f566a5570163e4
  Download:    2.1 MiB
  Installed:   4.6 MiB across 2 files
  Destination: C:\Users\you\AppData\Local\dfpm\tools\yara\4.5.5
  Disk:        412.8 GiB free on that volume
  System-wide changes: none
Continue? [y/N]
```

A package that declares a platform is refused outright on a machine that does not match it. Use `--yes` only when the plan has already been reviewed.

**Getting a build for a different machine.** Installing one here would be meaningless — a Linux binary behind a Windows command shortcut is a broken tool — but wanting the file is perfectly reasonable. `dfpm download` saves the release itself and does nothing else with it:

```powershell
dfpm download hayabusa --platform macos/arm64 --to D:\staging
```

```text
Downloading Hayabusa 4.0.0 for macos/arm64, 43.3 MiB
  from https://github.com/Yamato-Security/hayabusa/releases/download/v4.0.0/hayabusa-4.0.0-mac-aarch64.zip
  to   D:\staging\hayabusa-4.0.0-mac-aarch64.zip
Saved D:\staging\hayabusa-4.0.0-mac-aarch64.zip
```

The file keeps the name its project published it under, and lands where you asked. It is checked against the digest the catalog pinned, and discarded if it does not match, but beyond that dfpm does not get involved: nothing is cached, unpacked, recorded or installed. Whatever the machine it is meant for does with it is that machine's business.

A few tools carry terms restricting who may use them, or for what purpose. Those packages record the terms URL, dfpm shows it in the plan, and `--yes` on its own will not install them — confirming a plan and asserting that restricted terms permit your use are different claims, and only you can make the second one. Answering the prompt covers it interactively; a scripted install needs `--accept-terms`.

Removal is equally explicit. Each version lives in a directory dfpm created and nothing else writes to, so `dfpm uninstall` removes that directory and the command shortcuts pointing at it. Installing a different version does the same thing to the one it replaces.

Both plans show the path, the file count and the size before anything happens, and say so when the folder holds more than the install put there — which is what you see after a tool has updated its own rules or downloaded data on first run. Those extras go with it, so a tool that fetches its own data will fetch it again after an upgrade.

## The catalog

<img align="right" width="100" src="assets/brix-box.png" alt="">

The `catalog/` directory holds the manifests dfpm can install from. Each one names the release file its project published, records its SHA-256, and records the upstream project, its license and the platform it was built for. The download size and the size on disk are recorded too — not as a second integrity check, since the digest already settles what the bytes are, but so the plan can tell you the cost before you agree to it.

It currently contains **YARA 4.5.5** for Windows x64 and **Hayabusa 4.0.0** for Windows, Linux and macOS. dfpm is in early development, so the catalog is still being built out. See [catalog/README.md](catalog/README.md) for what goes into an entry, and the review notes recorded for each package.

Recording a digest per release is a job for a script, not a person — reading a project's release feed, fetching the asset and computing the hash is exactly the work a machine should do. What a person does is approve the change. That tooling does not exist yet, so entries are currently written by hand; until it does, the catalog will grow slowly and deliberately.

Each entry describes one tool and every build of it dfpm can install, so a tool shipping for several systems is one entry rather than one per platform. `dfpm catalog` lists what is available; `dfpm catalog <package-id>` shows everything known about one of them, including the builds this machine cannot use:

```text
  Builds
    4.0.0      windows/x64        42.1 MiB  <- installs on this machine
    4.0.0      linux/x64          44.1 MiB
    4.0.0      macos/arm64        43.3 MiB
```

Installing picks the newest version with a build for your machine, and the plan says so rather than leaving it implied. A manifest also records what the package costs on disk once unpacked, so the plan shows the size and file count before anything is downloaded. See the [manifest format](docs/manifest-v1.md) for the full list of rules extraction applies, and for what those rules are and are not defending against.

## Running installed tools

**dfpm never modifies your PATH.** Changing a system-wide setting on your behalf is exactly the kind of surprise a forensic toolchain should not spring on you, so the decision stays yours. There are three ways to reach an installed tool.

The recommended one is `dfpm run`, which needs no setup and removes all ambiguity about which binary executed:

```powershell
dfpm run yara --version
dfpm run yara rules.yar C:\evidence\collected
```

It looks up the command among the installed packages, runs that exact file from the directory the package expects, and passes your arguments through as a real argument list.

Its exit code is the tool's exit code, so it composes normally in scripts. dfpm's own refusals use the shell's conventions instead — **`127`** when no installed package provides the command, **`126`** when it resolved but could not be launched — so a script can tell them apart from anything the tool itself returns.

`dfpm doctor` follows the same idea: **`0`** when everything is ready, **`1`** when something dfpm is responsible for is broken, **`2`** when a package is installed correctly but the machine is missing a runtime it needs. The last is not a fault dfpm can fix, and it should not read like one.

**dfpm never adds arguments of its own.** What you type is what runs.

What it does decide is *where* the tool runs. A command launches from the directory holding its executable rather than from wherever you happen to be, so a tool that keeps its rules or configuration beside itself finds them from any working directory. A package can name a different directory if it expects one. `dfpm which` shows it before you run anything.

One exception, because Windows leaves no honest alternative: when a package's entrypoint is a `.cmd` or `.bat`, Windows runs it through `cmd`, which re-reads the command line before the script ever sees it. An argument containing `&`, `|`, `<`, `>`, `^`, `(`, `)`, `"` or `%` would not arrive intact, so dfpm refuses it and points you at the file to run directly rather than passing something the tool would misread.

`dfpm which` shows what a command resolves to before you run it:

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
- **Reinstalling never needs the network.** Going back to an earlier release, or putting a version back after removing it, uses bytes already proven to match their digest.
- **Provenance.** The cached file is literally the bytes that were verified and installed.

```powershell
dfpm cache list      # every artifact, its size, and what still needs it
dfpm cache verify    # re-hash each one; the name is the digest, so a mismatch means corruption
dfpm cache prune     # remove everything no installed package needs, and interrupted downloads
dfpm cache remove <digest>
```

`prune` clears everything no installed package needs, and needs no flags for the common case. If you are seeding a cache for offline installs, `--keep-catalog` narrows it to artifacts no manifest lists either, and in that mode a catalog that cannot be read makes `prune` refuse rather than treat everything as unused. `remove` refuses a digest an installed package still depends on unless you pass `--force`, and files in the cache directory that are not named after their own digest are reported and left alone rather than deleted.

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

**Working today:** manifest validation, verified local and HTTPS artifacts, contained portable ZIP installation with a free-space check, an install plan that shows what a package costs before it is fetched, replacing installs, directory-scoped removal, a manageable download cache, plain downloads of builds for other machines, command shortcuts and `dfpm run`, a loopback management interface, and read-only health checks.

**Not built yet:** lockfile export, repair, release discovery, executable health checks, a `dfpm search` command, and packages that need an interpreter such as Python, Perl or Java. Linux and macOS support, private and offline registries, signed repository snapshots and organisation policy are longer-term.

Packages may eventually represent tools, isolated runtimes, rulesets, parser packs, artifact packs, integrations and configuration packs. Today only portable ZIP tools are supported.

## Security and privacy

Telemetry is disabled by default. dfpm is not intended to receive evidence, case information, or forensic results. Security reporting guidance will be published before the first distributable release.

## License

dfpm is released under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE).

dfpm distributes no third-party software. Every catalogued package is downloaded from the upstream project's own release URL and stays under its own license, which the manifest records and `dfpm install` prints before anything is fetched. Some tools carry terms restricting who may use them, or for what purpose; reviewing those terms is yours to do.

<p align="center">
  <img src="assets/divider-dam.png" alt="" width="440">
</p>

<p align="center">
  <sub><strong>Brix</strong> · Chief Package Officer</sub>
</p>

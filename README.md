<p align="center">
  <img src="docs/assets/brix-hero.png" alt="Brix, the dfpm mascot, holding a wrench" width="120">
</p>

<h1 align="center">dfpm</h1>

<p align="center"><strong>A package manager for digital forensics tools</strong></p>

<p align="center">
  <img src="docs/assets/divider-dam.png" alt="" width="440">
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

**dfpm either launches a tool in the environment it expects, or tells you exactly why it cannot.** A package installs whether or not the machine can run it yet, and says which it is.

## Why it exists

<img align="right" width="96" src="docs/assets/brix-magnifier.png" alt="">

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
  <img src="docs/assets/divider-dam.png" alt="" width="440">
</p>

## Get started

<img align="right" width="110" src="docs/assets/brix-laptop.png" alt="">

You need Python 3.11 or newer. dfpm currently runs on Windows.

```powershell
pipx install git+https://github.com/forynsics/dfpm.git
```

`pipx` keeps dfpm in its own environment and puts the `dfpm` command on your PATH, which is what you want for a command-line tool. If you would rather manage that yourself, `pip install git+https://github.com/forynsics/dfpm.git` works the same way. dfpm has no dependencies — it is about 400 KB and pulls in nothing else.

Then install something:

```powershell
dfpm catalog            # what's available
dfpm install mftecmd    # shows the plan, asks before doing anything
dfpm run mftecmd -f C:\evidence\$MFT --csv C:\out
```

That is the whole loop. There is nothing to configure and no repository to clone — dfpm ships with a catalog, so it has something to install from the moment it is installed.

### The commands

```text
dfpm catalog [<package-id>]    what's available, or everything about one package
dfpm install <package-id>      install it, after showing you the plan
dfpm list                      what's installed, and what has a newer version
dfpm run <command> [args...]   run an installed tool
dfpm which <command>           show exactly which file a command resolves to
dfpm uninstall <package-id>    remove it
dfpm doctor                    check installed packages are intact and runnable
dfpm sync                      update the catalog from where it is published
dfpm download <package-id>     save a release file without installing it
dfpm cache list | verify | prune | remove <digest>
dfpm paths                     where everything lives
dfpm gui                       manage all of this in a browser instead
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

<img align="right" width="100" src="docs/assets/brix-box.png" alt="">

The `catalog/` directory holds the manifests dfpm can install from. Each one names the release file its project published, records its SHA-256, and records the upstream project, its license and the platform it was built for. The download size and the size on disk are recorded too — not as a second integrity check, since the digest already settles what the bytes are, but so the plan can tell you the cost before you agree to it.

It currently holds seven packages: **Hayabusa** and **YARA**, and five of Eric Zimmerman's command-line tools — **MFTECmd**, **PECmd**, **EvtxECmd**, **RECmd** and **SQLECmd**. dfpm is in early development, so the catalog is still small. Every entry is reviewed by a person before it lands, and the notes from that review are kept in [catalog/README.md](catalog/README.md).

Each entry describes one tool and every build of it dfpm can install, so a tool shipping for several systems is one entry rather than one per platform. `dfpm catalog` lists what is available; `dfpm catalog <package-id>` shows everything known about one of them, including the builds this machine cannot use:

```text
  Builds
    4.0.0      windows/x64        42.1 MiB  <- installs on this machine
    4.0.0      linux/x64          44.1 MiB
    4.0.0      macos/arm64        43.3 MiB
```

Installing picks the newest version with a build for your machine, and the plan tells you which one it picked. An entry also records what the package costs on disk once unpacked, so the plan shows the size and file count before anything is downloaded. The [manifest format](docs/manifest-v1.md) lists every rule extraction applies.

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

One exception. When a package's entrypoint is a `.cmd` or `.bat`, Windows runs it through `cmd`, which re-reads the command line before the script ever sees it. An argument containing `&`, `|`, `<`, `>`, `^`, `(`, `)`, `"` or `%` would not arrive intact, so dfpm refuses it and points you at the file to run directly.

`dfpm which` shows what a command resolves to before you run it:

```text
yara -> C:\Users\you\AppData\Local\dfpm\tools\yara\4.5.5\yara64.exe
  Package:  yara 4.5.5
  Shortcut: C:\Users\you\AppData\Local\dfpm\bin\yara.cmd
  On PATH:  not reachable. Use 'dfpm run yara', the full path above,
            or add C:\Users\you\AppData\Local\dfpm\bin to your PATH yourself.
```

The second is to add dfpm's `bin` directory to your PATH yourself — `dfpm paths` shows where it is. Use the Windows *Environment Variables* dialog rather than `setx`, which silently truncates PATH at 1024 characters and has wrecked a lot of environments. Putting it first means dfpm's copy of a tool wins over any other copy on the machine, which is usually what you want from a toolchain manager but does mean a `yara` installed by something else is shadowed. `dfpm which` tells you when something else would win instead.

The third is to run the full path `dfpm which` prints, which is what the command shortcut does anyway.

## The verified download cache

Every artifact dfpm downloads is verified and then kept in a content-addressed cache, named by its own SHA-256. That is worth the disk for four reasons:

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

There is also a public site, which explains dfpm and browses the catalog but installs nothing.

The default Windows data locations are rooted in `%LOCALAPPDATA%\dfpm`:

```text
catalog\                      Entries this machine can install from
tools\<package-id>\<version>\  The installed version
cache\sha256\                 Verified downloaded artifacts
bin\                          Command shortcuts
state\packages\               Records of what was installed
```

`catalog\` holds what is **available**; `state\packages\` records what is **installed**. They move independently, so when a project publishes a new release the catalog can show you 4.1.0 while still correctly reporting that 4.0.0 is the version you are running.

dfpm reads entries from `catalog\` rather than from wherever you happen to be standing. `--catalog <dir>` overrides it for one command, and `DFPM_CATALOG` for a session.

**A fresh install is not empty.** dfpm carries the entries that had been reviewed when that version was released, and reads those until `catalog\` has something in it — so installing dfpm is enough to have something to install. Nothing is copied into `catalog\` behind your back: put entries there and they take over completely.

**`dfpm sync` keeps it current without waiting for a dfpm release.** The catalog is published as a plain directory of entries plus an index describing them, so a reviewed change reaches every machine that syncs, whenever they sync:

```powershell
dfpm sync                          # from the published catalog
dfpm sync --source D:\mirror\      # or from a copy you carry
```

```text
Catalog sync plan
  Source:      https://raw.githubusercontent.com/forynsics/dfpm/main/catalog/
  Into:        C:\Users\you\AppData\Local\dfpm\catalog
  Update:      mftecmd  2026.5.0.0
  Unchanged:   6, which will not be downloaded again
  Downloads:   1 entry
  Nothing is installed or removed. This only changes what is available to install.
```

The version there has not moved, which is normal. Some projects publish each release at its own address, and some replace the file at a fixed one whenever they rebuild, so an entry can change without the version changing. dfpm knows which kind a package is and tells you in the install plan.

An unchanged entry is never downloaded twice. An entry you have edited yourself is reported before it is replaced rather than overwritten in silence, and entries withdrawn upstream are removed — nothing you have installed is affected either way.

Syncing only happens when you ask for it. It reads over HTTPS or from a directory, refuses a redirect that drops out of HTTPS, checks every entry is a valid manifest before it lands, and writes nothing at all unless all of them passed.

**When a project publishes a new release,** the entry is updated to describe it and nothing you have installed changes. `dfpm list` says so:

```text
yara                         4.5.5          YARA  (4.5.6 available)

The catalog has a newer version of: yara
Installing one replaces the version you have: dfpm install <package-id>
```

A release that only ships for other systems is never offered to a machine that could not run it, and the check needs no network.

## Project status

<img align="right" width="96" src="docs/assets/brix-sleeping.png" alt="">

dfpm is in early development, and interfaces, manifests and behaviour may still change.

**Working today:** installing, replacing and removing packages from verified artifacts; an install plan that shows the cost before anything is fetched; contained extraction with a free-space check; `dfpm run` and `dfpm which`; a verified download cache; catalog sync from a published directory; runtime detection that says why a tool cannot run yet; downloads of builds meant for other machines; a loopback management interface; and read-only health checks.

**Not built yet:** a `dfpm search` command, health checks that actually execute a tool rather than checking its files are present, and telling you when a catalogued project has published something newer upstream. Packages are portable ZIPs only, so anything shipped as a tarball or as scripts needing an interpreter cannot be catalogued yet.

Linux and macOS support are longer-term.

## Security and Privacy

dfpm is not intended to receive evidence, case information, or forensic results.

## License

dfpm is released under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE).

dfpm distributes no third-party software. Every catalogued package is downloaded from the upstream project's own release URL and stays under its own license, which the manifest records and `dfpm install` prints before anything is fetched. Some tools carry terms restricting who may use them, or for what purpose; reviewing those terms is yours to do.

<p align="center">
  <img src="docs/assets/divider-dam.png" alt="" width="440">
</p>

<p align="center">
  <sub><strong>Brix</strong> · Chief Package Officer</sub>
</p>

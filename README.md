<p align="center">
  <img src="docs/assets/brix-hero.png" alt="Brix, the dfpm mascot, holding a wrench" width="120">
</p>

<h1 align="center">dfpm</h1>

<p align="center"><strong>A package manager for digital forensics tools</strong></p>

<p align="center">
  <img src="docs/assets/divider-dam.png" alt="" width="440">
</p>

Forensic tooling is scattered across project pages, release feeds, personal sites and word of mouth — and you have to already know a tool exists before you can go looking for it. dfpm gathers them into one catalog you can browse and install from, then keeps track of what you installed, where it went, and exactly which version is running.

> Build a trusted forensic toolchain without surrendering its lifecycle to a general-purpose package manager.

dfpm does not acquire or interpret evidence, manage cases, or run investigation workflows. It manages the tools you use to do those things, and nothing more.

## Get started

<img align="right" width="110" src="docs/assets/brix-laptop.png" alt="">

You need Python 3.11 or newer. dfpm currently runs on Windows.

```powershell
pipx install git+https://github.com/forynsics/dfpm.git
```

`pipx` keeps dfpm in its own environment and puts the command on your PATH. dfpm has no dependencies — about 400 KB, and it pulls in nothing else.

```powershell
dfpm catalog            # what's available
dfpm install mftecmd    # shows the plan, asks before doing anything
dfpm run mftecmd -f C:\evidence\$MFT --csv C:\out
```

That is the whole loop. There is nothing to configure and no repository to clone — dfpm ships with a catalog, so it has something to install the moment it is installed.

Every install shows you this first, and waits:

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

<p align="center">
  <img src="docs/assets/divider-dam.png" alt="" width="440">
</p>

## Why dfpm

<img align="right" width="96" src="docs/assets/brix-magnifier.png" alt="">

**Every artifact is the one a reviewer pinned.** Packages install straight from the releases their projects publish. Each entry records a SHA-256, and the download is refused unless the bytes match exactly. dfpm never repackages, rebuilds or mirrors anything.

**You see the change before it happens.** Package, version, platform, license, source, digest, sizes, destination and free space — every time, before anything is fetched.

**You always know which version ran.** One version of a package is installed at a time, and `dfpm which` tells you the exact file a command resolves to. Going back to an earlier release is one command, usually with no network at all.

**It will not change your system behind your back.** dfpm never edits your PATH, never writes outside the folders it shows you, and deletes only the directories it created.

### What it is responsible for

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

## What you can install

<img align="right" width="100" src="docs/assets/brix-box.png" alt="">

The catalog includes **Hayabusa**, **YARA**, Eric Zimmerman's command-line parsers and graphical viewers, and a growing set of acquisition, memory-analysis, malware-analysis and threat-hunting tools. Run `dfpm catalog` for the current list; it is generated from the reviewed manifests rather than maintained separately here.

dfpm is early, so the catalog is small and every entry is reviewed by a person before it lands. `dfpm sync` picks up new and updated entries without waiting for a dfpm release.

See [the catalog](docs/catalog.md) for how entries work, or [catalog/README.md](catalog/README.md) for what a review requires.
Routine releases can be maintained by [policy-constrained catalog automation](docs/catalog-updates.md) after a package's initial admission.

## Commands

```text
dfpm catalog [<package-id>]    what's available, or everything about one package
dfpm search <words>            find tools by purpose, capability, or evidence
dfpm install <package-id>      install it, after showing you the plan
dfpm list                      what's installed, and what has a newer version
dfpm outdated                  show installed packages with available updates
dfpm upgrade <id> | --all      upgrade through the same reviewed install plan
dfpm run <command> [args...]   run an installed tool
dfpm which <command>           show exactly which file a command resolves to
dfpm uninstall <package-id>    remove it
dfpm doctor                    check installed packages are intact and runnable
dfpm sync                      update the catalog from where it is published
dfpm download <package-id>     save a release file without installing it
dfpm collection [<name>]       list curated package sets, or show one set
dfpm cache list | verify | prune | remove <digest>
dfpm paths                     where everything lives
dfpm gui                       manage all of this in a browser instead
```

dfpm does not modify PATH. Use `dfpm run <command>`, or add the directory `dfpm paths` shows you to PATH yourself — see [running tools](docs/running-tools.md).

## How an install stays safe

<p align="center">
  <img src="docs/assets/divider-dam.png" alt="" width="440">
</p>

Five steps. If any of them fails, the one before it is left exactly as it was.

1. **The entry points at an official release**, names the file the project published, and records its SHA-256 alongside the license and the platform it was built for.
2. **The artifact is fetched and checked**, over HTTPS into a content-addressed cache, and re-hashed against that digest. A redirect that drops out of HTTPS is refused.
3. **Extraction stays inside the directory it was given**, and is refused if the result would not fit the volume.
4. **The result is checked before it counts.** Files land in staging, and the expected entrypoints, supporting files, size and file count must all match or the whole install is discarded.
5. **Only then does it take over.** The staged version moves into place, command shortcuts are rewritten, and the version it replaces is removed.

The full set of rules, and what they do and do not defend against, is in the [security model](docs/security.md).

## Documentation

| | |
| --- | --- |
| [Installing and removing](docs/installing.md) | plans, versions, platforms, restricted terms, uninstalling |
| [Running tools](docs/running-tools.md) | `dfpm run`, PATH options, exit codes, runtimes |
| [The catalog](docs/catalog.md) | where entries come from, `dfpm sync`, upstream changes |
| [The verified cache](docs/cache.md) | offline installs, pruning, seeding an isolated machine |
| [Local interface](docs/gui.md) | `dfpm gui`, its security controls, where files live |
| [Security model](docs/security.md) | what dfpm guarantees, and what it does not |
| [Manifest format](docs/manifest-v1.md) | how a catalog entry is written |

## Project status

<img align="right" width="96" src="docs/assets/brix-sleeping.png" alt="">

dfpm is in early development, and interfaces, manifests and behaviour may still change.

**Working today:** installing, replacing and removing packages from verified artifacts; install plans; contained extraction; `dfpm run` and `dfpm which`; a verified download cache; catalog sync; runtime detection; downloads of builds meant for other machines; a local management interface; and read-only health checks.

**Not built yet:** health checks that actually execute a tool rather than checking its files are present. Installable artifacts currently include portable ZIP archives and standalone files; other published formats can be described in the catalog but are not selected for installation. Policy-enabled catalog entries can be checked against upstream releases by the catalog-maintenance workflow.

Windows is supported today. Linux and macOS are longer-term.

## Data handling

dfpm manages forensic tooling, not forensic evidence. It does not receive, process, upload or store case evidence or forensic results. Its only network requests are for catalog entries and the release artifacts an entry names, and only when a command asks for them.

## License

dfpm is released under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE).

dfpm distributes no third-party software. Every catalogued package is downloaded from the upstream project's own release URL and stays under its own license, which the entry records and `dfpm install` prints before anything is fetched. Some tools carry terms restricting who may use them, or for what purpose; reviewing those terms is yours to do.

<p align="center">
  <img src="docs/assets/divider-dam.png" alt="" width="440">
</p>

<p align="center">
  <sub><strong>Brix</strong> · Chief Package Officer</sub>
</p>

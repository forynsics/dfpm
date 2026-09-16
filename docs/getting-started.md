# Getting started

This walks through installing dfpm, where it keeps everything, and installing and running a first tool — on Windows, and on Linux including WSL. dfpm itself never needs administrator rights.

## What you need

- Python 3.11 or newer
- Git
- pipx

## Install dfpm

The same on every system:

```sh
pipx install git+https://github.com/forynsics/dfpm.git
dfpm --version
```

That is all the setup there is. dfpm has no dependencies, needs no configuration, and ships with a catalog of tools, so it has something to install straight away.

**WSL is Linux.** Install dfpm inside WSL exactly as above. A dfpm in WSL and a dfpm on Windows are separate installations with separate tools: install a tool in each place you want to use it.

## Where dfpm keeps things

Everything dfpm downloads, installs and records lives under one folder, its **root**:

| | Windows | Linux and WSL |
| --- | --- | --- |
| Root | `%LOCALAPPDATA%\dfpm`, usually `C:\Users\you\AppData\Local\dfpm` | `~/.local/share/dfpm` |
| Settings file | `%LOCALAPPDATA%\dfpm\config.json` | `~/.config/dfpm/config.json` |

Inside the root:

| Folder | What is in it |
| --- | --- |
| `tools/<package>/<version>/` | The installed tool, unpacked exactly as its project published it |
| `cache/sha256/` | Verified downloads, kept so reinstalling or going back a version needs no network |
| `bin/` | One short command for each installed tool |
| `state/packages/` | A record of what is installed, from where, and with which digest |
| `catalog/` | The tool list `dfpm sync` downloads. Until you sync, dfpm uses the list it shipped with |
| `staging/` | Working space for an install in progress |

Folders appear the first time they are needed. `dfpm paths` prints the real locations on your machine:

```text
Root:               /home/you/.local/share/dfpm (platform default)
Tools:              /home/you/.local/share/dfpm/tools
Verified downloads: /home/you/.local/share/dfpm/cache/sha256
Command shortcuts:  /home/you/.local/share/dfpm/bin
Catalog:            /home/you/.local/share/pipx/venvs/dfpm/lib/python3.12/site-packages/dfpm/entries
                    The entries dfpm shipped with. 'dfpm sync' fetches the published catalog.
Package records:    /home/you/.local/share/dfpm/state/packages
Configuration:      /home/you/.config/dfpm/config.json
```

dfpm writes nowhere else. It does not change PATH, install anything system-wide, or touch the registry. The one exception is a file you ask `dfpm download` to save, which goes where you tell it.

To keep the root somewhere else — a larger drive, or an encrypted volume — see [storage configuration](configuration.md). In WSL, keep it on the Linux filesystem rather than under `/mnt/c`.

## Find a tool

```sh
dfpm catalog                 # tools with a build for this machine
dfpm search event logs       # find tools by what they do or read
dfpm catalog hayabusa        # everything about one tool
```

Both listings show only tools that install on your machine. Add `--all` to see every platform, or `--platform linux/x64` to see another machine's.

The detail view ends with the builds a tool ships, and marks the one that fits your machine:

```text
  Builds
    4.1.0      windows/x64        42.7 MiB
    4.1.0      linux/x64          44.7 MiB  <- installs on this machine
    4.1.0      macos/arm64        43.8 MiB
```

Most of the catalog is Windows builds so far. A tool with no build for your machine is refused with the platforms it does ship for.

## Install it

```sh
dfpm install hayabusa
```

dfpm shows what it is about to do, and waits:

```text
Install plan
  Package:     Hayabusa 4.1.0
  Platform:    linux/x64  (1 of 3 builds; 'dfpm catalog hayabusa' shows the rest)
  License:     AGPL-3.0-only AND LicenseRef-DRL-1.1
  Project:     https://github.com/Yamato-Security/hayabusa
  Source:      https://github.com/Yamato-Security/hayabusa/releases/download/v4.1.0/hayabusa-4.1.0-lin-x64-musl.zip
  SHA-256:     2348a889c1d5dc07880f170e131c61ef68af1c1e1d3cebd5bed8af2d17d42bed
  Download:    44.7 MiB
  Installed:   58.7 MiB across 5,092 files
  Destination: /home/you/.local/share/dfpm/tools/hayabusa/4.1.0
  Disk:        412.8 GiB free on that volume
  System-wide changes: none
Continue? [y/N]
```

The download comes from the project's own release, and is refused unless its SHA-256 matches the one in the plan. Some tools restrict who may use them; the plan shows their terms, and reviewing them is yours to do.

## Run it

```sh
dfpm run hayabusa help
```

`dfpm run` needs no setup: it finds the installed command, runs it, passes your arguments through unchanged, and returns the tool's exit code. `dfpm which` shows exactly which file that is and where it runs:

```text
hayabusa -> /home/you/.local/share/dfpm/tools/hayabusa/4.1.0/hayabusa-4.1.0-lin-x64-musl
  Package:  hayabusa 4.1.0
  Runs in:  /home/you/.local/share/dfpm/tools/hayabusa/4.1.0
  Shortcut: /home/you/.local/share/dfpm/bin/hayabusa
  On PATH:  not reachable. Use 'dfpm run hayabusa', the full path above,
            or add /home/you/.local/share/dfpm/bin to your PATH yourself.
```

### Use full paths for evidence and output

A tool runs from its own folder under dfpm's root, not from wherever you typed the command. That is what lets a tool find the rules and configuration it ships with — but it also means **a relative path is resolved inside the tool's folder**. An output file named `timeline.csv` would land in `tools/hayabusa/4.1.0/`, and that folder is deleted when the tool is upgraded or uninstalled.

Keep evidence and results in a case folder of your own, and name it in full:

```sh
dfpm run capa ~/cases/case-01/suspicious.bin
```

```powershell
dfpm run capa D:\cases\case-01\suspicious.bin
```

In PowerShell, quote a path containing `$`, such as `'D:\cases\case-01\$MFT'`, or PowerShell reads it as a variable.

### Typing the command on its own

To type `hayabusa` instead of `dfpm run hayabusa`, add the `bin` folder from `dfpm paths` to your PATH yourself. dfpm will not do it for you. [Running tools](running-tools.md#putting-dfpms-bin-directory-on-path) shows how on each system.

## Keep it current

```sh
dfpm sync               # fetch the latest reviewed catalog
dfpm outdated           # installed tools with a newer version available
dfpm upgrade --all      # upgrade them, through the same install plan
dfpm doctor             # check that everything installed is intact
```

Going back to an earlier release is `dfpm install <package> --package-version <version>`, and usually needs no network because the download is still in the cache.

To update dfpm itself:

```sh
pipx reinstall dfpm
```

## Remove things

```sh
dfpm uninstall hayabusa     # one tool, its commands and its record
dfpm uninstall --all        # every installed tool
```

Removing dfpm itself is `pipx uninstall dfpm`. That removes the program but not its root, so anything still installed and every cached download stays where it is. Delete the root and the settings file shown by `dfpm paths` to remove those too.

---

See also: [installing and removing](installing.md) · [running tools](running-tools.md) · [storage configuration](configuration.md)

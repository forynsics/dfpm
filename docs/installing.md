# Installing and removing packages

## Finding and updating packages

`dfpm search <words>` finds packages by name, description, command, capability and evidence vocabulary. `dfpm outdated` reports installed packages for which the current catalog has a newer version and supports `--json` for automation.

Upgrade selected packages with `dfpm upgrade <package-id>...`, or every outdated package with `dfpm upgrade --all`. Upgrades reuse the ordinary install plan, confirmation, terms and digest rules. In a multi-package upgrade, packages install independently: a later failure does not roll back packages that already upgraded successfully.

## The plan comes first

`dfpm install <package-id>` shows what it is about to do and waits:

```text
Install plan
  Package:     YARA 4.5.5
  Platform:    windows/x64
  License:     BSD-3-Clause
  Project:     https://github.com/VirusTotal/yara
  Source:      https://github.com/VirusTotal/yara/releases/download/v4.5.5/...
  SHA-256:     352396c8a3d9b31b157a4820abd3b9347fc934a2314cdda8a4f566a5570163e4
  Download:    2.1 MiB
  Installed:   4.6 MiB across 2 files
  Destination: C:\Users\you\AppData\Local\dfpm\tools\yara\4.5.5
  Disk:        412.8 GiB free on that volume
  System-wide changes: none
Continue? [y/N]
```

`--yes` confirms without asking, for a plan you have already reviewed. A prompt that cannot be answered — a scheduled job, a piped command — counts as no, and dfpm says so rather than assuming.

## One version at a time

Installing replaces whatever version was there before, so the tools directory never fills up with old copies. The previous version is removed only after the new one is in place and its command shortcuts work, so a failed install leaves what you had untouched.

Going back to an earlier release is the same command with a version:

```powershell
dfpm install yara --package-version 4.5.4
```

That is usually instant and needs no network, because the artifact is still in the [verified cache](cache.md).

## Platform matching

A package that declares a platform is refused on a machine that does not match it. Installing picks the newest version that has a build for your machine, and the plan says which one it picked.

`dfpm catalog <package-id>` shows every build, including the ones this machine cannot use:

```text
  Builds
    4.0.0      windows/x64        42.1 MiB  <- installs on this machine
    4.0.0      linux/x64          44.1 MiB
    4.0.0      macos/arm64        43.3 MiB
```

## Getting a build for another machine

Installing a Linux binary on Windows would put a broken tool behind a command shortcut, so it stays refused. Wanting the file is a different thing, and `dfpm download` does exactly that and nothing else:

```powershell
dfpm download hayabusa --platform macos/arm64 --to D:\staging
```

```text
Downloading Hayabusa 4.0.0 for macos/arm64, 43.3 MiB
  from https://github.com/Yamato-Security/hayabusa/releases/download/v4.0.0/hayabusa-4.0.0-mac-aarch64.zip
  to   D:\staging\hayabusa-4.0.0-mac-aarch64.zip
Saved D:\staging\hayabusa-4.0.0-mac-aarch64.zip
```

The file keeps the name its project published it under and lands where you asked. It is checked against the digest the catalog pinned and discarded if it does not match. Nothing is cached, unpacked, recorded or installed.

## Packages with restricted terms

Some tools restrict who may use them, or for what purpose. Those entries record a terms URL, dfpm prints it in the plan, and `--yes` alone will not install them: confirming a plan and asserting that restricted terms permit your use are separate claims, and only you can make the second. Answering the prompt covers it interactively; a scripted install needs `--accept-terms`.

## Removing

```powershell
dfpm uninstall <package-id>
```

Each version lives in a directory dfpm created and nothing else writes to, so removal takes that directory and the command shortcuts pointing at it. Installing a different version does the same to the one it replaces.

Both plans show the path, the file count and the size first, and say so when the folder holds more than the install put there — which is what you see once a tool has updated its own rules or downloaded data on first run. Those extras go with it, so a tool that fetches its own data will fetch it again after an upgrade.

## When an artifact no longer matches

Most projects publish each release at its own address, and those bytes never change again. Some publish one address per tool and replace the file whenever they rebuild. An entry records which kind it is, and the install plan says so.

If the bytes at a rolling address have changed, dfpm shows both digests and asks whether to continue, or takes `--accept-digest-mismatch`. If they have changed at an address that should never change, dfpm refuses and will not be talked out of it — use `dfpm download --accept-digest-mismatch` to fetch the file and examine it instead.

An install that went ahead with bytes the catalog did not describe is recorded as such, and `dfpm doctor` keeps reporting it afterwards.

---

See also: [the catalog](catalog.md) · [running tools](running-tools.md) · [security model](security.md)

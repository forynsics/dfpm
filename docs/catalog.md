# The catalog

Routine releases for suitable packages can be maintained through [policy-constrained automation](catalog-updates.md). Initial admission and changes to publisher, asset selection, layout, commands, licensing or terms remain explicit catalog decisions.

The catalog is the set of entries dfpm can install from. Each entry names the release file its project published, records its SHA-256, and records the upstream project, its license and the platform it was built for. It also records the download size and the size on disk, so the install plan can tell you the cost before you agree to it.

Each entry describes one tool and every build of it dfpm can install, so a tool shipping for three systems is one entry rather than three.

```powershell
dfpm catalog                 # everything available
dfpm catalog <package-id>    # everything known about one, including builds this machine cannot use
```

Every entry is reviewed by a person before it lands. What that review requires is in [catalog/README.md](../catalog/README.md). The format itself is in [manifest-v1.md](manifest-v1.md).

## Where entries come from

dfpm reads entries from `catalog\` under its own root, not from whatever directory you are standing in. Precedence, most explicit first:

1. `--catalog <dir>` for one command
2. `DFPM_CATALOG` for a session
3. `catalog\` in the dfpm root
4. The entries dfpm shipped with

**A fresh install is not empty.** dfpm carries the entries that had been reviewed when that version was released and reads those until `catalog\` has something in it, so installing dfpm is enough to have something to install. Nothing is copied into `catalog\` behind your back — put entries there and they take over completely.

## Keeping it current

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

The catalog is published as a plain directory of entries plus an index describing them, so a reviewed change reaches every machine that syncs, whenever it syncs — no dfpm release required.

Syncing only happens when you ask for it. It reads over HTTPS or from a directory, refuses a redirect that drops out of HTTPS, checks every entry parses as a manifest before it lands, and writes nothing at all unless all of them passed.

- An unchanged entry is never downloaded twice.
- An entry you edited yourself is reported before it is replaced, rather than overwritten in silence.
- Entries withdrawn upstream are removed. Nothing you have installed is affected — a package's record does not depend on the catalog.

## Available and installed move independently

`catalog\` holds what is **available**; `state\packages\` records what is **installed**. When a project publishes a new release, the entry changes and nothing under `state\` is touched, which is what lets dfpm show you 4.1.0 in the catalog while correctly reporting that 4.0.0 is what you are running:

```text
yara                         4.5.5          YARA  (4.5.6 available)

The catalog has a newer version of: yara
Installing one replaces the version you have: dfpm install <package-id>
```

A release that only ships for other systems is never offered to a machine that could not run it, and the check needs no network.

## Rolling and immutable sources

Most projects publish each release at its own address, and those bytes never change. Some publish one address per tool and replace the file whenever they rebuild. An entry records which kind it is, and the install plan says so:

```text
  Source:      https://download.ericzimmermanstools.com/net9/MFTECmd.zip
               Rolling: the publisher replaces this file rather than adding a new one.
```

That matters when a digest stops matching. On a rolling address it usually means a new build, so dfpm shows both digests and asks. On an address that should never change it means something is wrong, so dfpm refuses. See [installing](installing.md#when-an-artifact-no-longer-matches).

It also means an entry can change without its version changing, which is why a sync plan can show an update against a version you already have.

---

See also: [installing](installing.md) · [the cache](cache.md) · [manifest format](manifest-v1.md)

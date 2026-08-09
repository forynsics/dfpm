# Security model

What dfpm guarantees, and what it does not.

## What it guarantees

**The bytes are the ones a reviewer pinned.** Every entry records a SHA-256. The download is refused unless it matches, and refused again if an HTTPS source redirects to plain HTTP. Cached artifacts are re-hashed on every use, not only when first downloaded.

**Nothing changes without a plan.** Package, version, platform, license, source, digest, download size, size on disk, destination, free space, and what will be replaced — printed every time, before anything is fetched. `--yes` confirms a plan you have read; it never implies acceptance of a package's usage terms, and never accepts an artifact that failed verification.

**An install is all-or-nothing.** Files land in a staging directory. The expected entrypoints and supporting files must be present, and the size and file count must match what the entry recorded, or the whole thing is discarded. Only then does the staged version move into place, and only then is the version it replaces removed.

**dfpm owns its own directories and nothing else.** It never edits PATH or any other global setting, never writes outside the folders `dfpm paths` shows you, and deletes only directories it created.

## Containment during extraction

The digest already settles what the bytes are, so these rules are about keeping an archive inside the directory it was granted and failing readably instead of filling a disk. Any entry breaking one of them fails the whole install before anything is installed:

- No absolute paths, parent traversal, drive letters or alternate data streams. dfpm builds each destination path itself rather than delegating it, because the standard library silently rewrites a `..` component instead of refusing it.
- No symbolic links, device files or other non-regular entries.
- No encrypted entries, whose contents cannot be reviewed.
- No reserved Windows device names, and no path component ending in a space or a dot.
- No duplicate paths, and none differing only by capitalisation, which a case-insensitive filesystem would merge.
- Every extracted file must match the size recorded in its own header.
- The result must fit, checked against free space before extraction and against bytes actually written during it, with a reserve kept back so a successful install cannot leave a volume at zero.
- On Windows, no resulting path may exceed 260 characters, measured against the final destination rather than the staging name.
- At most 250,000 entries, as a backstop against something pathological.

The [manifest format](manifest-v1.md) documents these alongside the fields they apply to.

## What it does not guarantee

**A digest is not a review.** It proves everyone gets identical bytes and that an asset quietly replaced at the same URL is caught. It says nothing about whether the software is good or safe. What stands behind an entry is that a person looked at it and approved it — see [catalog/README.md](../catalog/README.md).

**dfpm holds no per-file digests.** Such a list would sit unsigned beside the files it vouched for, so anyone able to alter a binary could alter the list in the same breath. What is recorded is the digest of the file the project published. Real integrity checking for a binary comes from its own code signature.

**The catalog is not signed.** Syncing is protected by HTTPS and by the digests in the published index, which detect corruption and interception in transit. A signed catalog is a later step.

**Runtimes are detected, not vouched for.** dfpm checks whether the runtime a package needs is present and what version it reports. It does not install or verify it.

## Data handling

dfpm manages forensic tooling, not forensic evidence. It does not receive, process, upload or store case evidence or forensic results. It makes no network requests other than fetching catalog entries and the release artifacts an entry names, and only when a command asks it to.

## Reporting a problem

Open an issue on the repository. If the issue is sensitive, say so without details and a private channel will be arranged.

---

See also: [manifest format](manifest-v1.md) · [the catalog](catalog.md) · [local interface](gui.md)

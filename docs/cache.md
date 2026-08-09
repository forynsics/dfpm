# The verified download cache

Every artifact dfpm downloads is verified and then kept in a content-addressed cache, named by its own SHA-256. That is worth the disk for four reasons:

- **Offline and air-gapped installs.** Populate the cache on a connected machine, copy the directory to an isolated one, and install with no network at all.
- **Upstream is not permanent.** Release assets get deleted and versions get yanked. A pinned digest is worthless without the bytes, and re-running an analysis years later needs the exact version used at the time.
- **Reinstalling never needs the network.** Going back to an earlier release, or putting a version back after removing it, uses bytes already proven to match their digest.
- **Provenance.** The cached file is literally the bytes that were verified and installed.

A cached artifact is re-hashed every time it is used, not only when it was first downloaded, so a file that is corrupted or replaced on disk is caught before extraction.

## Commands

```powershell
dfpm cache list      # every artifact, its size, and what still needs it
dfpm cache verify    # re-hash each one; a mismatch means corruption
dfpm cache prune     # remove everything no installed package needs
dfpm cache remove <digest>
```

`prune` clears everything no installed package needs, plus interrupted downloads, and needs no flags for the common case.

`--keep-catalog` narrows it to artifacts no catalog entry lists either, which is what you want when seeding a cache for offline installs. In that mode a catalog that cannot be read makes `prune` refuse rather than treat everything as unused.

`remove` refuses a digest an installed package still depends on unless you pass `--force`. Files in the cache directory that are not named after their own digest are reported and left alone rather than deleted.

## Seeding a cache for an isolated machine

On a connected machine, install what you need — or install and then remove it, which leaves the artifacts behind. Copy `cache\` from the dfpm root to the same place on the isolated machine, along with `catalog\` if that machine needs the entries too. Installs there will find the bytes already present and verified.

---

See also: [installing](installing.md) · [the catalog](catalog.md)

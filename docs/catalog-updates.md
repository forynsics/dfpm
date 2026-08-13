# Automated catalog updates

A package needs judgement when it first enters the catalog. Routine releases after that can be maintained mechanically when the publisher and package layout keep following the policy approved at admission.

Update policies live in `catalog/update-policies/`. They are maintenance instructions, not install metadata, and are not shipped to dfpm users. Every catalog entry has a policy. A policy either identifies an upstream GitHub repository and expected release asset or describes a publisher-controlled rolling URL.

The `catalog updates` workflow runs daily and can also be started manually. It:

1. asks GitHub for the latest applicable published release and records why newer releases were skipped;
2. requires exactly one asset to match each declared pattern;
3. downloads and hashes the asset;
4. recomputes its size, installed size and file count;
5. requires every established entrypoint and verification path to remain present;
6. loads the proposed manifest through dfpm's normal validation;
7. regenerates the catalog index;
8. runs the complete test suite;
9. commits the validated changes and pushes them to `main`; and
10. uploads the proposed catalog and evidence as a workflow artifact.

It does not rewrite descriptions, classification, licensing, terms, commands or project provenance. A renamed or missing asset, ambiguous match, changed archive layout, disappeared entrypoint, unsupported artifact format, invalid manifest, or failing test stops the job rather than being guessed through. The evidence report includes the failed stage, patterns, available assets and inspected release tags where applicable. A failed multi-package apply restores manifests already changed during that invocation and does not regenerate the index.

Routine changes land without a human when every policy succeeds, the established archive layout remains intact, manifest validation succeeds, and the complete test suite passes. The commit is the audit record: it carries only what the policy recomputed, and the run that produced it holds the evidence report. The workflow then explicitly starts the normal test matrix and site deployment because events created by GitHub's workflow token do not recursively start other workflows.

New packages and changes to update policies still require normal review. An ambiguous asset, prerelease outside an explicit policy, changed archive layout, missing entrypoint or download failure leaves that package unchanged and records structured evidence, while unrelated valid updates may continue. The complete resulting catalog must still pass validation before anything is pushed. If validation or publication fails, nothing new lands.

The workflow maintains one `Catalog update automation failures` issue rather than opening a new issue every day. It updates that issue with the current failed packages and stages, and closes it automatically after a clean run. If every policy-managed package is already current, the run records its evidence and exits without committing anything.

## Adding a policy

Create `catalog/update-policies/<package-id>.json` after the package's initial review. For example:

```json
{
  "schema_version": 1,
  "id": "yara",
  "provider": "github-releases",
  "repository": "VirusTotal/yara",
  "tag_prefix": "v",
  "assets": [
    {
      "name": "yara-{version}-*-win64.zip",
      "platform": {"os": "windows", "arch": "x64"}
    }
  ]
}
```

`{release_version}` is replaced with the release tag after `tag_prefix` is removed. The older `{version}` spelling is retained as an alias. `*` may cover a publisher-controlled build number, but patterns should otherwise be narrow enough that exactly one release asset matches.

Some publishers put a more precise package version in an asset name than in the release tag. Keep release discovery and the installed version separate in that case:

```json
{
  "package_version": {
    "source": "asset-name",
    "asset": 0,
    "regex": "^example_v(?P<version>[0-9]+\\.[0-9]+\\.[0-9]+)_win64\\.zip$"
  }
}
```

The regular expression must match the entire selected asset name and contain a named `version` group. `asset` is the zero-based position in the policy's `assets` list.

GitHub prereleases are excluded by default. A package may opt in only with both an explicit switch and a narrow tag pattern:

```json
{
  "include_prereleases": true,
  "prerelease_tag_pattern": "v*-rc*"
}
```

This prevents an unrelated nightly or development release from becoming eligible merely because prereleases were enabled. A policy can explicitly set `include_prereleases` to `false` to document that production releases must be used, as WinPmem does because its newer 4.1 build is test-signed.

Run a policy locally without changing anything:

```powershell
.venv\Scripts\python.exe scripts\update-catalog.py --package yara
```

Apply a discovered update and write its evidence report:

```powershell
.venv\Scripts\python.exe scripts\update-catalog.py --package yara --apply --evidence catalog-update-evidence.json
```

The updater intentionally supports a small policy surface. Add another release provider or artifact strategy only when a real catalog entry needs it and its invariants can be checked without guessing.

## Rolling URLs

Some publishers overwrite a stable download URL instead of publishing immutable, versioned release assets. A rolling policy records that URL, the publisher's current HTTP ETag, and the installed executable whose embedded Windows file version is authoritative:

```json
{
  "schema_version": 1,
  "id": "mftecmd",
  "provider": "rolling-url",
  "package_version": {
    "source": "pe-file-version",
    "asset": 0,
    "path": "MFTECmd.exe"
  },
  "assets": [
    {
      "name": "MFTECmd.zip",
      "url": "https://download.ericzimmermanstools.com/net9/MFTECmd.zip",
      "etag": "publisher-provided-etag",
      "platform": {"os": "windows", "arch": "x64"}
    }
  ]
}
```

The scheduled job first makes a HEAD request. An unchanged ETag avoids downloading the ZIP. A new ETag causes the artifact to be downloaded and SHA-256 hashed. If its digest is unchanged, only the ETag cursor advances. If the bytes changed, the updater extracts the ZIP under dfpm's normal limits, reads the declared executable version, rejects version rollback, verifies every established path and recalculates the package facts before merging. The ETag is only a change detector; it is never treated as an integrity digest.

Local `--apply` remains all-or-nothing by default. `--continue-on-policy-error` is an explicit unattended-maintenance mode: it retains independently valid package updates and returns structured failures for the rest. The scheduled workflow uses this mode, validates the combined result, and reports failures before publication.

## Execution policy

The automated job treats a release as a package-layout update; it does not claim to audit or prove the behavior of a new executable. Initial admission still establishes what is being packaged. Projects whose routine updates require elevation, drivers, services, hardware, changing command lines or meaningful behavioral acceptance tests should not be granted an automatic policy until a suitable disposable-runner check exists.

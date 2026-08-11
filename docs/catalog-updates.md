# Automated catalog updates

A package needs judgement when it first enters the catalog. Routine releases after that can be maintained mechanically when the publisher and package layout keep following the policy approved at admission.

Update policies live in `catalog/update-policies/`. They are maintenance instructions, not install metadata, and are not shipped to dfpm users. A policy identifies the upstream GitHub repository and the expected release asset for each platform.

The `catalog updates` workflow currently runs only when manually dispatched, while its policies and evidence are being observed. It:

1. asks GitHub for the latest applicable published release and records why newer releases were skipped;
2. requires exactly one asset to match each declared pattern;
3. downloads and hashes the asset;
4. recomputes its size, installed size and file count;
5. requires every established entrypoint and verification path to remain present;
6. loads the proposed manifest through dfpm's normal validation;
7. regenerates the catalog index;
8. runs the complete test suite; and
9. uploads the proposed catalog and evidence as a workflow artifact only if every check succeeds.

It does not rewrite descriptions, classification, licensing, terms, commands or project provenance. A renamed or missing asset, ambiguous match, changed archive layout, disappeared entrypoint, unsupported artifact format, invalid manifest, or failing test stops the job rather than being guessed through. The evidence report includes the failed stage, patterns, available assets and inspected release tags where applicable. A failed multi-package apply restores manifests already changed during that invocation and does not regenerate the index.

During this observation phase the workflow has read-only repository permission and cannot push to `main`. After several real updates have produced correct proposals, scheduling and automatic publication can be enabled as a separate policy decision.

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

## Execution policy

The automated job treats a release as a package-layout update; it does not claim to audit or prove the behavior of a new executable. Initial admission still establishes what is being packaged. Projects whose routine updates require elevation, drivers, services, hardware, changing command lines or meaningful behavioral acceptance tests should not be granted an automatic policy until a suitable disposable-runner check exists.

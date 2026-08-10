# Package catalog

This directory contains the package manifests that make up the dfpm catalog. Each manifest describes one tool and the builds of that tool that dfpm can install.

Every change to this catalog must be reviewed and approved by a person before it is merged. Tooling may discover releases, download assets, calculate hashes, inspect archives, or generate manifests, but it must not add or update catalog entries on its own.

**Discovery proposes; a person merges.**

## What reviewing a package means

Reviewing a package does **not** mean auditing its source code or inspecting every byte of a compiled binary.

For each build, dfpm records the exact asset URL and its SHA-256 digest. This gives dfpm a known set of bytes for that version. Someone installing the same version later should receive exactly the same file, and dfpm can detect if an asset at an existing URL is silently replaced.

A manifest can therefore be generated partly or entirely by tooling. The important requirement is that a person reviews and approves the resulting catalog change before it is merged.

The process below describes doing that work manually.

## Before you start

The complete field reference is [docs/manifest-v1.md](../docs/manifest-v1.md). Read it once; you will not need to reread it for every entry.

The fastest way to begin is to copy an existing manifest with a similar shape and edit it. `yara.json` is a small tool with two entrypoints and no runtime dependency. `hayabusa.json` covers three platforms in one manifest. `mftecmd.json` is a single Windows build that needs the .NET runtime.

There is also a script that fills in the mechanical fields for you:

```powershell
python scripts\draft-manifest.py <url> --id <package-id> --name <DisplayName>
```

It downloads the archive and derives the digest, size, version, architecture, archive depth, entrypoints, installed size, entry count, and any runtime the package declares. It prints a manifest to standard output.

It deliberately leaves blank everything that requires judgement: `description`, `about`, the four classification axes, and `package.stability`. Those are yours to write. A draft is a starting point, not a finished entry.

## Reviewing a package

### 1. Choose the release and assets

Find the release you want to package and identify the correct asset for each platform you intend to support.

One tool gets one manifest. If a release provides Windows, Linux, and macOS builds, those are three builds in the same manifest, not three separate manifests.

Do not assume that:

* asset names are consistent between releases;
* every release contains compiled binaries; or
* the newest tag is necessarily the release you should package.

Verify the actual assets published by the upstream project.

### 2. Download and hash each asset

Download each asset over HTTPS from the project's official distribution location.

Record its:

* URL;
* SHA-256 digest; and
* download size.

Compute the SHA-256 locally from the file you actually downloaded.

Also determine `package.stability`.

Use `immutable` when the URL identifies a particular release or version, for example:

```text
.../releases/download/v4.0.0/tool-4.0.0.zip
```

Use `rolling` when the publisher reuses the same URL for changing builds, for example:

```text
.../latest/tool.zip
```

This distinction matters. A changed `immutable` asset is unexpected and should raise an alarm. A changed `rolling` asset may simply mean that upstream published a new build.

Getting this wrong in the cautious direction produces an alarming message about a routine event. Getting it wrong the other way describes a genuine problem as routine, which is worse.

### 3. Corroborate the digest when possible

If upstream provides an independent digest or signature, compare it with the SHA-256 you calculated.

Useful sources include:

* checksums published by the project;
* signatures published by the project; or
* the digest recorded by the hosting platform for that asset.

Not every release has one. For example, GitHub only records digests for assets uploaded after it introduced that feature. When no independent digest exists, use the locally computed SHA-256.

### 4. Inspect every archive

Inspect each platform's archive separately.

Do not assume that builds from the same release have identical layouts. Binary names, directories, and file counts can differ between Windows, Linux, and macOS packages.

Determine the correct:

* `install.strip_components` — how many leading directories to remove so the tool lands at the package root;
* `install.entrypoints` — the real path to each executable, and the command name it should be reachable as; and
* `build.verify` — files that must exist after extraction for the install to count as successful.

`verify` is worth using whenever a tool ships supporting files it cannot run without, such as a rules directory or a bundled database. Naming one of those files catches an archive that unpacked at the wrong depth while still leaving the executable reachable.

Do this for every build rather than copying values from another platform.

### 5. Record the installed contents

For each build, record:

* `install.extracted_size`; and
* `install.entries`.

These let `dfpm install` tell the user how much disk space the package requires before downloading it, and verify the resulting installation after extraction.

These values are per-build. If they are wrong, installation should fail rather than silently accepting an unexpected archive layout.

### 6. Describe and classify the tool

Write a short `description` and an `about` section.

Use them differently:

* `description` — what the tool is, in one line.
* `about` — what the tool does, what it works with, and what it produces.

Keep `about` factual. Avoid claims about how good, fast, popular, or useful a tool is; those age badly and are not claims the catalog needs to make.

Then classify the package using four separate axes:

* `disciplines` — the forensic domain the tool belongs to;
* `capabilities` — what the tool can do;
* `use_cases` — when an investigator would reach for it;
* `evidence` — what kinds of evidence the tool reads.

Classification should help someone discover a useful tool **without already knowing its name**.

`disciplines` describes the evidence domain, not the operating system the executable runs on. A Windows executable can analyze evidence from another platform.

If a tool genuinely does not belong to one particular discipline, leave `disciplines` empty rather than listing every discipline.

The allowed vocabulary lives in:

```text
src/dfpm/classification.py
```

Manifests cannot introduce arbitrary classification terms. If an existing term does not accurately describe the tool, add an appropriate term to `classification.py` in the same change rather than forcing the package into a near-match.

### 7. Record project and license information

Record upstream project information and licensing once at the tool level.

Platform information belongs to individual builds. Do not duplicate a list of supported platforms at the tool level; dfpm derives that from the builds in the manifest.

`license` uses an SPDX expression. If an artifact is subject to multiple licenses, express that directly, for example:

```text
AGPL-3.0-only AND LicenseRef-DRL-1.1
```

Record what you can actually establish. If a tool has no public source repository, omit `repository` and `license` rather than inferring them from a sibling project.

If upstream restricts who may use the tool or what it may be used for, record its terms in `project.terms_url`. This also applies when a package redistributes third-party data under its own terms, such as a bundled geolocation database.

Packages with a `terms_url` cannot be installed non-interactively unless the user explicitly supplies `--accept-terms`.

### 8. Document required invocation behaviour

Some tools require particular command-line arguments, or expect rules, configuration, or other files relative to their working directory.

If someone needs to know this to successfully run the installed tool, explain it in the entry's `about` section.

dfpm does not automatically supply arguments on behalf of installed tools. This information is documentation, not package configuration.

### 9. Validate and test the package

Point dfpm at the catalog:

```powershell
$env:DFPM_CATALOG = "catalog"
```

Then validate it:

```powershell
dfpm catalog
```

This loads and validates every manifest in the catalog. Fix any validation errors before continuing.

Install the package through dfpm and confirm that the installed tool actually runs. Running it is what catches a manifest that is valid but wrong, and it regularly corrects the `about` text written before anyone launched the tool.

If a tool cannot be verified — because it requires elevation, particular hardware, or evidence you do not have — say so in the pull request rather than implying it was tested.

### 10. Regenerate the catalog index

After adding or changing a manifest, regenerate the index:

```powershell
dfpm catalog --index > catalog\index.json
```

`index.json` tells remote dfpm clients which manifests exist and which ones have changed. A new manifest that is not included in the index is invisible to clients using `dfpm sync`.

The test suite checks that the committed index matches the catalog.

## Before you commit

At minimum, these commands should succeed:

```powershell
$env:DFPM_CATALOG = "catalog"

dfpm catalog
dfpm catalog --index > catalog\index.json
```

You should also have installed the package through dfpm and confirmed that its entrypoint runs.

## Source of truth

**This directory is the only place package manifests are edited.**

Do not copy manifests into another source directory after changing them here.

The catalog bundled with dfpm is staged from this directory when the package is built. The feed used by the public site is generated when the site is deployed. Neither generated copy is committed to the repository, so there is nothing else for a contributor to keep synchronized manually.

`catalog/index.json` is the exception. `dfpm sync` fetches the index directly from the repository over HTTPS, so the generated index must be committed alongside catalog changes.

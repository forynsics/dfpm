# Reviewed package catalog

Every file here describes one tool and every build of it dfpm can install. Each build names one exact file and records its SHA-256, and a person approved it being here.

That approval is the point, not the typing. A manifest may perfectly well be produced by a script that reads a project's release feed, downloads the asset and computes the digest — nobody is auditing eleven megabytes of compiled Rust by hand, and pretending otherwise would be dishonest about what the digest is for. What it actually buys is that everyone installing a given version gets identical bytes, now and in three years, and that an asset quietly replaced at the same URL is caught. What must not happen is a manifest reaching this directory without a person approving the change. Discovery proposes; a person merges.

The steps below describe doing it by hand, which is how it works until that tooling exists.

## Reviewing a package

1. Find the candidate release and the correct asset for each platform you intend to support. A tool shipping for Windows, Linux and macOS becomes three builds in one file, not three files. Asset naming is not stable across releases, and a project's newest release does not always publish binaries at all, so the newest tag is not automatically the right answer.
2. Download the asset over HTTPS from the project's official location and compute its SHA-256 and size locally. Decide `package.stability` while you are looking at the URL: does it name a version, or is it a fixed address the publisher overwrites on every build? A URL like `.../releases/download/v4.0.0/tool-4.0.0.zip` is `immutable` and needs nothing said; one like `.../latest/tool.zip` is `rolling`, and saying so is what lets dfpm tell a routine upstream release apart from an artifact that changed when it should not have. Getting this wrong in the safe direction costs an alarming message; getting it wrong the other way describes a genuine problem as routine.
3. Corroborate the digest against a second source where one exists, such as the digest the hosting platform recorded for the asset, or a checksum or signature the project publishes. GitHub only records digests for assets uploaded after it added the feature, so older releases have none and the locally computed digest is all you get.
4. Inspect **each** archive to determine `strip_components`, the real entrypoint paths, and the files worth checking. Builds of one release are not interchangeable: their binaries are named differently and their file counts differ, so every build needs its own inspection rather than the Windows numbers copied across. Record `install.extracted_size` and `install.entries` while you are there, so `dfpm install` can show what the package costs on disk before anything is downloaded. Both are verified after extraction, so a wrong figure fails the install rather than misleading someone. Record them per build.
5. Write `about`, and classify the package with `disciplines`, `capabilities`, `use_cases` and `evidence`. The one-line `description` says what the tool is; `about` describes what it does and produces, factually — not why it is good, which ages badly and is not the catalog's job to claim. Classification is what makes a package findable by someone who does not already know its name, which is most people most of the time. Keep the four axes honest: which discipline it belongs to, what it does, when you would reach for it, what it reads. `disciplines` is about whose evidence the tool examines, not which operating system the binary runs on — those differ often. Leave it empty for a tool that genuinely serves no single discipline rather than listing them all. The full vocabulary lives in `src/dfpm/classification.py`; a term that is not in it is refused, so a manifest cannot invent one. If no existing term fits, add one to `src/dfpm/classification.py` in the same change rather than forcing a near-miss.
6. Record the upstream project and its license once, at the tool level. The platform belongs to each build; the platforms a tool supports are read from its builds rather than stated again. `license` takes an SPDX expression, so an artifact under more than one license says so directly (`AGPL-3.0-only AND LicenseRef-DRL-1.1`). If the tool restricts who may use it or for what purpose, record `project.terms_url`; that alone makes dfpm refuse to install it from a script without `--accept-terms`.
7. If the tool needs particular arguments to work at all — some resolve their own rules or configuration relative to the working directory — say so in the entry's `about`, where whoever installs it will read it. dfpm does not supply arguments on a tool's behalf, so this is documentation rather than configuration.
8. Run `dfpm catalog`, which loads and validates every manifest in this directory and fails on a malformed one. Then install it and confirm the tool actually runs.
9. Regenerate the index with `dfpm catalog --index > catalog\index.json`. The index is how a published catalog says what it contains, since nothing can list a directory over HTTPS, and its digests are what let a machine sync only what changed. An entry added without regenerating the index is invisible to everyone syncing.

So the whole mechanical part is two commands:

```powershell
$env:DFPM_CATALOG = "catalog"
dfpm catalog                              # validates every entry
dfpm catalog --index > catalog\index.json
```

**Nothing else needs copying anywhere.** This directory is the only place entries are edited. The entries dfpm ships with are staged into the package when it is built, and the feed the public site reads is generated when the site is deployed — neither is committed, so neither can fall out of step with what is here.

The index is the one exception, because `dfpm sync` fetches it straight from the repository over HTTPS and so it has to exist there. The test suite fails when it is stale.

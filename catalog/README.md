# Reviewed package catalog

Every manifest here names one exact artifact and records its SHA-256, and a person approved it being here.

That approval is the point, not the typing. A manifest may perfectly well be produced by a script that reads a project's release feed, downloads the asset and computes the digest — nobody is auditing eleven megabytes of compiled Rust by hand, and pretending otherwise would be dishonest about what the digest is for. What it actually buys is that everyone installing a given version gets identical bytes, now and in three years, and that an asset quietly replaced at the same URL is caught. What must not happen is a manifest reaching this directory without a person approving the change. Discovery proposes; a person merges.

The steps below describe doing it by hand, which is how it works until that tooling exists.

## Reviewing a package

1. Find the candidate release and the correct asset for the target platform. Asset naming is not stable across releases, and a project's newest release does not always publish binaries at all, so the newest tag is not automatically the right answer.
2. Download the asset over HTTPS from the project's official location and compute its SHA-256 and size locally.
3. Corroborate the digest against a second source where one exists, such as the digest the hosting platform recorded for the asset, or a checksum or signature the project publishes. GitHub only records digests for assets uploaded after it added the feature, so older releases have none and the locally computed digest is all you get.
4. Inspect the archive to determine `strip_components`, the real entrypoint paths, and the files worth health checking. Record `install.extracted_size` and `install.entries` while you are there, so `dfpm install` can show what the package costs on disk before anything is downloaded. Both are verified after extraction, so a wrong figure fails the install rather than misleading someone.
5. Write `about`, and classify the package with `disciplines`, `capabilities`, `use_cases` and `evidence`. The one-line `description` says what the tool is; `about` describes what it does and produces, factually — not why it is good, which ages badly and is not the catalog's job to claim. Classification is what makes a package findable by someone who does not already know its name, which is most people most of the time. Keep the four axes honest: which discipline it belongs to, what it does, when you would reach for it, what it reads. `disciplines` is about whose evidence the tool examines, not which operating system the binary runs on — those differ often. Leave it empty for a tool that genuinely serves no single discipline rather than listing them all. The full vocabulary lives in `src/dfpm/classification.py`; a term that is not in it is refused, so a manifest cannot invent one. If no existing term fits, add one to `src/dfpm/classification.py` in the same change rather than forcing a near-miss.
6. Record the upstream project, its license, and the platform the artifact was built for. `license` takes an SPDX expression, so an artifact under more than one license says so directly (`AGPL-3.0-only AND LicenseRef-DRL-1.1`). If the tool restricts who may use it or for what purpose, record `project.terms_url`; that alone makes dfpm refuse to install it from a script without `--accept-terms`.
7. If the tool needs particular arguments to work at all — some resolve their own rules or configuration relative to the working directory — record the working invocation in the review notes below. dfpm does not supply arguments on a tool's behalf, so this is documentation for whoever installs it, not configuration.
8. Run `dfpm catalog`, which loads and validates every manifest in this directory and fails on a malformed one. Then install it and confirm the tool actually runs.

## Review notes

### hayabusa 4.0.0

- The digest was computed locally from the downloaded asset and matches the digest GitHub recorded for it.
- The archive holds `hayabusa-4.0.0-win-x64.exe`, `config/` and `rules/` at its root with no wrapping directory, so `strip_components` is `0`. 5,077 files expanding to 53.5 MiB.
- **The executable name carries the version and target triple**, so it changes with every release. The entrypoint is still named `hayabusa`, since the command name is stable even when the file it points at is not. Re-check `install.entrypoints[].path` when bumping the version; nothing validates that it matches.
- **It reads its rules from the working directory.** Run from anywhere else it fails with `[ERROR] The rules directory does not exist.` Verified: the same binary invoked directly from an unrelated folder exits 1, and through `dfpm run` exits 0. No `working_directory` is declared because the executable sits at the package root, so the default — the directory holding the executable — is already correct.
- The binary is Rust and statically linked, so there is no `requires` entry. Confirmed by running it on a machine with no Java or .NET present.
- Two licences in one artifact, stated by upstream: AGPLv3 for the binary and DRL 1.1 for the detection rules. Recorded as the SPDX expression `AGPL-3.0-only AND LicenseRef-DRL-1.1`. Upstream says "AGPLv3" without saying whether later versions apply, so `-only` is the conservative reading.
- **33.5 MiB of the 44 MiB download is `rules/.git`**, a complete git working copy of the rules repository, 69 files. It is installed along with everything else. Its config also references CI runner paths, which is harmless but worth knowing is on disk.
- `hayabusa update-rules` pulls into `rules/` inside the install. That is fine — the directory belongs to the package — but those updated rules are discarded when the package is replaced, so they need re-fetching after an upgrade.
- The longest path inside the archive is 171 characters. Under a default Windows root that lands around 223 of the 260 Windows allows, so a deeply nested dfpm root will be refused. That is the path-length check doing its job rather than a fault in the package.
- Upstream releases v4.5.6 and later were not checked; v4.0.0 was the newest release at review time.

### yara 4.5.5

- The three releases after v4.5.5 (v4.5.6, v4.5.7, and v4.5.8) publish no Windows assets at all, so v4.5.5 is the newest release that ships a usable win64 build.
- The asset name lost its `v` prefix between v4.5.4 (`yara-v4.5.4-2355-win64.zip`) and v4.5.5 (`yara-4.5.5-2368-win64.zip`).
- The digest was computed locally from the downloaded asset and matches the digest GitHub recorded for it.
- The archive holds `yara64.exe` and `yarac64.exe` at its root with no wrapping directory, so `strip_components` is `0`. Those two files are the whole install: 4,783,616 bytes across 2 entries.
- Upstream publishes no signature or checksum file alongside these assets, so HTTPS provenance and the pinned digest are the only integrity guarantees available.

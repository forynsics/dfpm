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
7. If the tool needs particular arguments to work at all — some resolve their own rules or configuration relative to the working directory — record the working invocation in the review notes below. dfpm does not supply arguments on a tool's behalf, so this is documentation for whoever installs it, not configuration.
8. Run `dfpm catalog`, which loads and validates every manifest in this directory and fails on a malformed one. Then install it and confirm the tool actually runs.
9. Regenerate the site's feed with `dfpm catalog --json > catalog.json` from the repository root. The public site is a static page and cannot run dfpm, so that file is how a reviewed package reaches it. The test suite fails if the two disagree, which is the reminder rather than the requirement.
10. Regenerate the index with `dfpm catalog --index > catalog/index.json`. The index is how a published catalog says what it contains, since nothing can list a directory over HTTPS, and its digests are what let a machine sync only what changed. An entry added without regenerating the index is invisible to everyone syncing.
11. Copy the entries and the index over `src/dfpm/entries/`, which is what dfpm ships with and what a machine reads before anyone has curated a catalog of its own. A reviewed entry that never reaches there is one a new install cannot see. The test suite fails if these drift too.

Steps 8 to 11 are mechanical and the test suite fails if any is skipped, so run them together:

```powershell
$env:DFPM_CATALOG = "catalog"
dfpm catalog                              # validates every entry
dfpm catalog --index > catalog\index.json
dfpm catalog --json  > catalog.json
Copy-Item catalog\*.json src\dfpm\entries\ -Force
```

## Review notes

### hayabusa

- Three builds at 4.0.0: `windows/x64`, `linux/x64` (the gnu variant) and `macos/arm64`. Every digest was computed locally from the downloaded asset and matches the digest GitHub recorded.
- Each holds its binary, `config/` and `rules/` at the archive root with no wrapping directory, so `strip_components` is `0` throughout.
- **The builds are not interchangeable.** Windows unpacks 5,077 files to 53.5 MiB, Linux 5,043 files to 58.0 MiB, macOS 5,077 files to 53.8 MiB, and each binary carries its own target triple in its name. Copying one build's figures to another would fail the install, which is the point of recording them.
- Only the Windows build has been installed and run. The Linux and macOS builds were downloaded, verified and inspected, but not executed.
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

### mftecmd, pecmd, evtxecmd, recmd, sqlecmd

These five come from one publisher and share everything below. They were drafted with `scripts/draft-manifest.py <url>`, which reads the mechanical fields out of the archive; the prose and classification were written by hand.

- **There is no versioned URL and no release to point at.** Each tool is published at one fixed address — `https://download.ericzimmermanstools.com/net9/<Tool>.zip` — which returns the file directly, with no redirect and no version anywhere in the path. A new build replaces what is there. The project's GitHub repositories publish no release assets at all, so this is the only distribution channel, and every one of these builds carries `package.stability: "rolling"`.
- **The consequence is worth stating plainly: these entries go stale on the publisher's schedule, not ours.** When a tool is rebuilt, its pinned digest stops matching and installing it fails until the entry is refreshed. That is the pin doing its job — it is the only thing that makes the change visible — but it means re-running the draft script is routine maintenance here rather than a once-a-release event.
- **The version comes from inside the binary.** Nothing else states it. The executables carry a calendar version in their PE resource, currently `2026.5.0.0`, which is what the entries record. It is month-granular, so two builds in the same month share a version and differ only by digest.
- Where an executable and its managed assembly disagree, the `.exe` is what the entries follow. SQLECmd's `.dll` reports `1.0.119.0` while its `.exe` reports `2026.5.0.0`, and the latter is what the product is stamped with and what the other four agree with.
- **Two archive shapes, and both occur here.** MFTECmd and PECmd unpack flat, three files each, `strip_components: 0`. EvtxECmd, RECmd and SQLECmd wrap everything in one folder, `strip_components: 1`, which lands `Maps/`, `Plugins/` and `BatchExamples/` beside the executable at the package root. That is where each tool looks for them, and it is the default working directory, so no `working_directory` is declared. The three wrapping builds carry a `verify` entry naming a file inside those directories, which is what would catch an archive that unpacked at the wrong depth while leaving the executable reachable.
- EvtxECmd's executable sits at `EvtxeCmd/EvtxECmd.exe` inside the archive — a lowercase `e` in the directory and an uppercase one in the file. It is invisible in a listing and would be easy to copy wrongly.
- **These tools update their own supporting files.** EvtxECmd, RECmd and SQLECmd fetch newer maps and plugins into their own install directory. That is normal and dfpm allows it, and those updates are discarded when the package is replaced, so they need fetching again after an upgrade.
- Every build is `windows/x64`, read from the PE machine type rather than assumed, and needs the .NET 9 runtime (`Microsoft.NETCore.App`, so the `base` flavor). dfpm detects that but never installs it. The GUI tools this publisher also ships would need the `desktop` flavor instead; none of them are catalogued here.
- `MIT` is taken from each tool's own source repository. EvtxECmd has no repository of its own: its source and its maps live under `EricZimmerman/evtx`, which is what the entry records and which carries the MIT licence file. The distributed binaries bundle third-party libraries, so this describes the tool's own source rather than everything inside the archive, and it should be confirmed per tool rather than copied across.
- **All five have been installed and run.** Each launches through `dfpm run` and reports its own version, matching the version its entry records.
- **They resolve their support files against the executable, not the working directory**, which is what makes `strip_components: 1` sufficient and `working_directory` unnecessary. Verified from an unrelated directory: EvtxECmd reports `Maps loaded: 383`, and SQLECmd names its map directory as the installed package folder. RECmd reads a batch file out of its own `BatchExamples` and reaches `Total hives found: 0`. Its plugins load only once a hive is processed, so they are present on disk and confirmed no further than that.
- Running them is also what corrected this catalog: SQLECmd's entry claimed databases were matched on structure rather than filename, and the tool says the opposite — a map's expected filename is the default, and header inspection is what `--hunt` turns on.

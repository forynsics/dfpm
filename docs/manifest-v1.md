# dfpm manifest format, version 1

The first implemented manifest format is intentionally narrow. It supports portable ZIP packages from local files or HTTPS sources. Broader package types and installation strategies will be added without weakening the validation rules around existing packages.

## Example

```json
{
  "schema_version": 1,
  "id": "example.tool",
  "name": "Example Tool",
  "version": "1.0.0",
  "kind": "tool",
  "description": "A short description of what the tool does.",
  "platform": {
    "os": "windows",
    "arch": "x64"
  },
  "project": {
    "homepage": "https://example.org/",
    "source": "https://github.com/example/example-tool",
    "license": "BSD-3-Clause"
  },
  "artifact": {
    "source": "https://example.org/example-tool-1.0.0.zip",
    "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "size": 1048576
  },
  "install": {
    "strategy": "portable-zip",
    "strip_components": 1,
    "entrypoints": [
      {
        "name": "example-tool",
        "path": "bin/example-tool.exe"
      }
    ]
  },
  "health_checks": [
    {
      "type": "file",
      "path": "bin/example-tool.exe"
    }
  ]
}
```

## Fields

- `schema_version` must be `1`.
- `id` is a stable lowercase package identity.
- `version` becomes an installation directory name, so it must begin with a letter or number and use only letters, numbers, dots, plus signs, underscores, and hyphens.
- `kind` may be `tool`, `runtime`, `ruleset`, `artifact-pack`, `parser-pack`, `integration`, or `config-pack`.
- `platform` is optional. When present, `platform.os` must be `windows`, `linux`, or `macos`, and `platform.arch` must be `x86`, `x64`, or `arm64`. dfpm refuses to install a package whose platform does not match the machine, which is what keeps a 32-bit or non-Windows build of the same tool from being installed by mistake.
- `project` is optional and records upstream provenance. `project.homepage`, `project.source` and `project.terms_url` must be HTTPS URLs.
- `project.license` is a single string holding an SPDX **expression**, so an artifact under more than one license needs no extra field: Hayabusa ships as `AGPL-3.0-only AND LicenseRef-DRL-1.1`, the binary being AGPL and the bundled rules DRL. Terms with no SPDX identifier use a `LicenseRef-` value. dfpm displays this string and does not parse it; validating an expression would mean carrying the SPDX license list to catch typos in a field whose only job is to be read.
- `project.terms_url` marks a package whose terms restrict *who* may use it, or for what purpose, beyond what a license identifier conveys. Its presence is the whole trigger: dfpm prints the URL in the install plan, and `--yes` alone will no longer install the package, because confirming a plan and asserting that restricted terms permit your use are different claims. An interactive install needs nothing extra — the existing confirmation already puts the terms in front of a person. A scripted one needs `--accept-terms`. The local interface applies the same rule.
- `platform` and `project` are both recorded in the package state, so what is installed says where it came from and under what license.
- `artifact.source` accepts an HTTPS URL, `file` URL, or path relative to the manifest.
- `artifact.sha256` is mandatory and must contain the expected SHA-256 digest.
- `artifact.size` is optional but recommended.
- `install.strategy` must currently be `portable-zip`.
- `strip_components` removes a fixed number of leading archive path components.
- `install.extracted_size` and `install.entries` are optional non-negative integers recording what the package costs on disk once unpacked, so `dfpm install` can show the cost before fetching anything. When present they are verified after extraction. A disagreement does not mean the download was tampered with — the digest already settles that — it means the manifest's own figures were taken from a different artifact.
- Entrypoint names become stable command shims in the dfpm `bin` directory, so they follow the same character rules as `version` and must be unique within a manifest.
- A manifest cannot supply arguments of its own, and this is deliberate. Some tools resolve their own data relative to the working directory — Hayabusa looks for `./rules` — so they fail when run from elsewhere unless told where to look. Having dfpm insert the missing arguments was tried and abandoned: the command you typed and the command that ran would differ, which is precisely what `dfpm which` exists to prevent; the injected option would collide with the same option passed by the user, and duplicate options resolve differently in every argument parser, including silently using both values; and the per-tool knowledge would not stop at arguments, extending next to environment variables, config file locations and working directories. dfpm installs the files and tells you where they are. How a tool is invoked is the tool's interface, and belongs in the catalog review notes rather than in dfpm.
- File health checks verify that required files remain present. Together with the entrypoints, they are the only paths `dfpm doctor` looks at: everything else inside a package's directory belongs to the package, and a tool that updates its own rule set or fetches data on first run is working normally rather than drifting.

All paths inside packages must be relative and stay within the package installation directory.

## Archive safety

The artifact's SHA-256 is verified before extraction begins, so the bytes are always exactly the ones a reviewer pinned. Nothing in this section is an integrity control — the digest is. What remains is containment: keeping an archive inside the directory it was granted, and failing with a readable message instead of filling a disk.

Any entry that breaks one of these rules fails the whole installation before anything is installed:

- No absolute paths, parent traversal, drive letters, or alternate data streams. This is the rule that carries the weight. dfpm builds each destination path itself rather than delegating to the standard library, so a `..` component would write outside the package directory. Python's own `extractall` silently rewrites such a path instead of refusing it, which is the worse outcome for a tool that records where every file went.
- No symbolic links, device files, or other non-regular entries.
- No encrypted entries, because their contents cannot be reviewed.
- No reserved Windows device names such as `nul` or `com1`, and no path component ending in a space or a dot.
- No duplicate paths, and no paths that differ only by capitalization, since a case-insensitive filesystem merges them and the digest dfpm recorded would stop describing what is on disk.
- Every extracted file must match the size recorded in its own header.
- The result must fit. Free space on the target volume is checked before extraction, against `install.extracted_size` where the manifest records it and the archive's declared totals otherwise, then enforced again against bytes actually written, because an archive's declared sizes are only its own claim. A reserve is kept back so a successful install cannot leave the volume at zero.
- On Windows, no resulting path may exceed 260 characters. The length is measured against the final destination rather than the staging directory, since staging uses a temporary name.
- At most 250,000 entries. This is a runaway backstop rather than a defence: its job is to fail quickly on something pathological instead of grinding for hours. It sits well above any real tool.

Fixed byte ceilings and a compression-ratio limit were removed deliberately. Against a digest-pinned artifact they defended nothing the review step did not already cover, while a fixed cap knows nothing about the volume it is protecting — the same number is needlessly strict on a machine with room to spare and useless on one without.

## Installation behavior

dfpm downloads into a content-addressed cache, verifies the artifact, extracts into a staging directory, validates expected files, and only then moves the version into its final directory and records it. An interrupted or invalid staged install never becomes the installed version. A cached artifact is re-hashed on every use, not only when it is first downloaded, so a cache entry that is corrupted or replaced on disk is caught before extraction.

Staging is cleaned up by the install that created it, and by nothing else. A successful install leaves nothing behind, because publishing moves the staging directory into place rather than copying it; a failed one deletes it, retrying briefly first, since Windows holds a short lock on a freshly written executable while antivirus or the search indexer reads it.

An install that is killed outright leaves its staging directory on disk, and dfpm does not go looking for it later. Deciding that a directory belongs to no one requires a lock dfpm does not take, and guessing from a timestamp would mean deleting a directory another dfpm might be writing to.

One version of a package is installed at a time. Installing a different version replaces the current one, and the version being replaced is removed only after the new one is in place and its command shortcuts are working, so a failed install leaves the previous version untouched. Returning to an earlier release is `dfpm install <package> --package-version <version>`, which normally needs no network because the artifact is still in the verified cache.

Command shims are derived from the installed version's recorded entrypoints and rewritten atomically on every change. Each shim carries a `@rem dfpm-shim` marker on its first line: dfpm only ever replaces or removes files carrying that marker, and refuses to install when a command name is already claimed by another package or by a file it does not own.

## Removal behavior

`dfpm uninstall <package>` removes the version directory and the command shortcuts pointing at it, then forgets the package. The plan prints the path, the file count and the total size first, and says so when the directory holds more than the install put there.

The directory is the unit of ownership. dfpm creates `tools/<id>/<version>/` and nothing else writes to it, so there is no per-file inventory to consult and no question of which files inside it are dfpm's. That is what lets a tool which maintains its own files be removed without ceremony: a rule set updated in place is still part of the package, and removing the package removes it.

Installing a different version does the same to the directory it replaces, and the install plan shows that folder and its contents before anything is fetched. So the consequence is the same in both cases and worth stating plainly: **everything in the directory goes, including whatever the tool put there after installation.** A tool that downloads its own rules will download them again after an upgrade.

Redirecting a tool's own writes somewhere durable would mean building it from source with different paths compiled in, or patching it afterwards. dfpm extracts binaries the project already published and changes nothing about them, so there is no such seam. In exchange for accepting that, uninstalling never strands a directory that blocks reinstalling the same version, and never leaves thousands of files for a person to review by hand.

dfpm holds no per-file digests, and this is deliberate. Such a list would sit unsigned beside the files it vouched for, so anyone able to alter a binary could alter the list in the same breath — it detects accidental corruption, not an adversary. What is recorded instead is `artifact_sha256`, the digest of the file the project published, which is the claim worth making about an installed tool. Real integrity checking for a binary comes from its own code signature.

Downloads stay in the content-addressed cache, so a package can be reinstalled without network access.

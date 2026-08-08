# DFPM

DFPM is a DFIR-native toolchain manager for building, freezing, repairing, and reproducing known-good forensic environments.

It is designed around one core principle: forensic tools and forensic content should be managed directly, with their exact artifacts, versions, configuration, validation results, and provenance kept under explicit control. Generic package managers may satisfy approved machine-level prerequisites, but they are not DFPM package sources.

> Build a trusted forensic toolchain without surrendering its lifecycle to a generic package manager.

## What DFPM is building

DFPM brings three connected capabilities together:

- A searchable registry organized around forensic evidence, artifacts, formats, and operations.
- Reproducible environments with profiles, exact lockfiles, side-by-side versions, and stable entrypoints.
- A trusted distribution layer with digest verification, provenance, health checks, repair, and rollback.

Packages can represent tools, isolated runtimes, rulesets, parser packs, artifact packs, integrations, and configuration packs. DFPM does not acquire or interpret evidence, manage cases, or execute investigation workflows.

## Lifecycle ownership

Forensic packages are downloaded into content-addressed storage, verified, staged in isolated version directories, validated against bounded synthetic fixtures, and only then activated. Previous working versions remain available for rollback.

Machine-level prerequisites such as shared runtimes and Windows features are handled separately. DFPM detects them first, requires an explicit provider and authorization for changes, validates the resulting capability independently, and records the observed state in the environment lockfile.

This distinction supports three honest reproducibility grades:

- **Hermetic:** all relevant bytes are managed by DFPM.
- **Pinned external:** external prerequisites are constrained and recorded.
- **Observed external:** required system state is detected but cannot be reproduced exactly.

## Product preview

This repository contains an interactive public catalog and the first working version of the local package-management core. The public experience helps practitioners discover and understand tools without requiring prior knowledge of the DFIR ecosystem.

The current prototype covers:

- Plain-language, artifact-first tool discovery.
- Curated starter kits for common investigation tasks.
- Introductory guides organized by evidence type.
- Explicit install, cache, command, and configuration locations.
- Installed versions and health status in local mode.
- Update planning with validation and rollback safeguards.
- A compact, accessible interface designed for clear reading on the web.

The browser preview models reviewed lifecycle operations but is not connected to the Python core yet. It does not install software or modify system prerequisites.

## Current scope

The initial target is Windows 11 x64, with portable tools prioritized for strong isolation and rollback. Planned package sources include reviewed GitHub releases, fixed HTTPS and local artifacts, ZIP/7z archives, MSI packages, and conventional EXE installers.

Longer-term plans include Linux and macOS support, private and offline registries, signed repository snapshots, organization policy, validation infrastructure, and stable catalog and inventory APIs.

## Project status

DFPM is in an early implementation phase. The Python core supports manifest validation, verified local and HTTPS artifacts, safe portable ZIP installation, isolated versions, managed-file inventory, command shims, read-only health checks, and environment lockfile export. Interfaces, manifests, and behavior remain subject to change.

## Current command-line interface

DFPM requires Python 3.11 or newer. Install the current development version in an isolated environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --editable .
```

The initial commands are:

```text
dfpm paths
dfpm catalog
dfpm validate <manifest.json>
dfpm install <package-id>
dfpm list
dfpm doctor
dfpm environment export <lockfile.json>
```

Installation always displays the package, source, digest, destination, and system-wide impact before making changes. Use `dfpm install <package-id> --yes` only when the plan has already been reviewed.

The default Windows data locations are rooted in `%LOCALAPPDATA%\DFPM`:

```text
tools\<package-id>\<version>\  Installed package versions
cache\sha256\                 Verified downloaded artifacts
bin\                          Stable command shortcuts
state\packages\               Managed-file and version records
```

See the [manifest format](docs/manifest-v1.md) for the currently supported package definition.

## Security and privacy

Telemetry is disabled by default. DFPM is not intended to receive evidence, case information, or forensic results. Security reporting guidance will be published before the first distributable release.

## License

Licensing terms have not yet been selected. Until a license is added, the repository remains all rights reserved.

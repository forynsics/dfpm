# Security policy

## Supported versions

dfpm is currently an alpha project. Security fixes are made on the `main` branch and included in the next published release. Until the first stable release, only the newest release is supported.

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, private catalog material or information that could put users at risk.

Use GitHub's private vulnerability reporting for this repository:

https://github.com/forynsics/dfpm/security/advisories/new

Include the affected command or component, expected and observed behavior, reproduction steps, and any relevant package manifest or archive layout. Do not attach forensic evidence or case data.

If private vulnerability reporting is unavailable, open a public issue containing no sensitive details and ask the maintainer to establish a private channel.

## Scope

Useful reports include unsafe extraction or deletion, catalog or artifact verification bypasses, command-invocation escaping, unauthorized local-interface actions, and publication-pipeline weaknesses.

Reports about the behavior of third-party forensic tools should normally go to that tool's publisher. dfpm records and verifies the artifact selected by its catalog; it does not audit the tool's source code or guarantee that the tool itself is safe.

# Reviewed package catalog

Every manifest here pins an exact artifact URL, SHA-256 digest, and size that a maintainer has reviewed. Nothing in this directory is generated automatically, and release discovery never writes to it: discovery can suggest a candidate release, but a person decides what dfpm is allowed to install.

## Reviewing a package

1. Find the candidate release and the correct asset for the target platform. Asset naming is not stable across releases, and a project's newest release does not always publish binaries at all, so the newest tag is not automatically the right answer.
2. Download the asset over HTTPS from the project's official location and compute its SHA-256 and size locally.
3. Corroborate the digest against a second source where one exists, such as the digest the hosting platform recorded for the asset, or a checksum or signature the project publishes. GitHub only records digests for assets uploaded after it added the feature, so older releases have none and the locally computed digest is all you get.
4. Inspect the archive to determine `strip_components`, the real entrypoint paths, and the files worth health checking. Record `install.extracted_size` and `install.entries` while you are there, so `dfpm install` can show what the package costs on disk before anything is downloaded. Both are verified after extraction, so a wrong figure fails the install rather than misleading someone.
5. Record the upstream project, its license, and the platform the artifact was built for.
6. Run `dfpm catalog`, which loads and validates every manifest in this directory and fails on a malformed one. Then install it and confirm the tool actually runs.

## Review notes

### yara 4.5.5

- The three releases after v4.5.5 (v4.5.6, v4.5.7, and v4.5.8) publish no Windows assets at all, so v4.5.5 is the newest release that ships a usable win64 build.
- The asset name lost its `v` prefix between v4.5.4 (`yara-v4.5.4-2355-win64.zip`) and v4.5.5 (`yara-4.5.5-2368-win64.zip`).
- The digest was computed locally from the downloaded asset and matches the digest GitHub recorded for it.
- The archive holds `yara64.exe` and `yarac64.exe` at its root with no wrapping directory, so `strip_components` is `0`. Those two files are the whole install: 4,783,616 bytes across 2 entries.
- Upstream publishes no signature or checksum file alongside these assets, so HTTPS provenance and the pinned digest are the only integrity guarantees available.

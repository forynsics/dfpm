# Releases

dfpm's release workflow builds release candidates; it does not currently publish them to PyPI or create a GitHub release.

The package version has one source of truth: `src/dfpm/__init__.py`. A release tag must use the same version with a `v` prefix, such as `v0.1.0`. A mismatched tag fails before artifacts are built.

For every version tag, the workflow:

1. runs the complete test suite on Windows;
2. builds both a wheel and a source distribution;
3. installs the wheel into a clean virtual environment and exercises the installed command and bundled catalog;
4. rebuilds a wheel from the source distribution, proving that the source archive contains the inputs required by the custom catalog build; and
5. records SHA-256 checksums and uploads all results as a GitHub Actions artifact.

The workflow can also be run manually to test the current branch without creating a tag. Manual runs produce temporary release-candidate artifacts only.

## Publishing a release

Until automated publishing is deliberately enabled, a maintainer should:

1. update `src/dfpm/__init__.py` to the intended version;
2. run `.venv\Scripts\python.exe -m unittest discover -s tests`;
3. merge the version change and create the matching `vX.Y.Z` tag;
4. inspect the completed `release candidate` workflow, its clean-install checks and `SHA256SUMS`; and
5. publish those exact verified artifacts through the chosen release channel.

Keeping publication separate from construction makes an accidental tag insufficient to publish a package while the release process is still maturing.

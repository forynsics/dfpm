class DfpmError(Exception):
    """A user-facing dfpm error."""


class ManifestError(DfpmError):
    """A package manifest is invalid."""


class VerificationError(DfpmError):
    """An artifact failed verification."""


class InstallError(DfpmError):
    """A package could not be installed safely."""


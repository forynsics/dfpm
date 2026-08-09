class DfpmError(Exception):
    """A user-facing dfpm error."""

    exit_code = 1


class ManifestError(DfpmError):
    """A package manifest is invalid."""


class VerificationError(DfpmError):
    """An artifact failed verification."""


class InstallError(DfpmError):
    """A package could not be installed safely."""


class CommandNotFound(DfpmError):
    """No installed package provides the requested command.

    Uses the shell's own convention so a script can tell dfpm's failure apart
    from the tool's. `dfpm run` returns the tool's exit code, and plenty of
    tools exit 1 to mean something ordinary, so dfpm must not also use 1 here.
    """

    exit_code = 127


class CommandNotRunnable(DfpmError):
    """The command resolved, but dfpm could not launch it."""

    exit_code = 126


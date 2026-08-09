from __future__ import annotations

import hashlib
import shutil
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .errors import VerificationError
from .manifest import Package
from .progress import Reporter
from .storage import Storage

CHUNK_SIZE = 1024 * 1024

# Asked when what arrived is not what the catalog described, and only for a
# package whose URL the publisher is known to replace. Answering it is a policy
# decision belonging to whoever is driving dfpm, so it is passed in rather than
# made here.
Decision = Callable[[str, str], bool]


@dataclass(frozen=True)
class Acquired:
    """A downloaded artifact, and the truth about it.

    `digest` is what the bytes actually hash to, which is not always what the
    catalog said. Keeping the two apart is the whole point: the catalog records
    what was reviewed and this records what arrived, and a caller that conflated
    them would write a digest into an install record for a file that does not
    have it.
    """

    path: Path
    digest: str
    verified: bool


def retrieve(
    package: Package,
    source: str,
    target: Path,
    on_progress: Reporter | None = None,
    on_mismatch: Decision | None = None,
) -> Acquired:
    """Download an artifact to a path the caller chose, and check it against its digest.

    This is a plain file download. Nothing is cached, extracted or installed:
    the file lands where it was asked to land, under the name its project
    published it with, for someone to carry to whichever machine needs it.

    Unlike installing, this will hand over an artifact that does not match, when
    asked to. Fetching a file to find out why it changed is the reasonable thing
    to do about an unexpected digest, not something to be prevented.
    """
    if target.exists():
        raise VerificationError(f"Refusing to overwrite an existing file: {target}")
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    try:
        _write(package, source, partial, on_progress)
        digest, verified = _settle(partial, package, on_mismatch, insist_on_immutable=False)
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return Acquired(target, digest, verified)


def acquire(
    package: Package,
    source: str,
    storage: Storage,
    on_progress: Reporter | None = None,
    on_mismatch: Decision | None = None,
) -> Acquired:
    """Fetch an artifact into the content-addressed cache and say what it turned out to be."""
    storage.cache.mkdir(parents=True, exist_ok=True)
    described = storage.cache / package.sha256
    if described.exists():
        verify(described, package)
        return Acquired(described, package.sha256, True)

    partial = described.with_suffix(".partial")
    partial.unlink(missing_ok=True)
    try:
        _write(package, source, partial, on_progress)
        digest, verified = _settle(partial, package, on_mismatch, insist_on_immutable=True)
        # Filed under what it is rather than what it was expected to be. A
        # content-addressed cache whose names are claims rather than facts is
        # worse than no cache: every lookup through it would be wrong.
        destination = storage.cache / digest
        partial.replace(destination)
    except VerificationError:
        partial.unlink(missing_ok=True)
        raise
    except (OSError, ValueError) as exc:
        partial.unlink(missing_ok=True)
        raise VerificationError(f"Could not download the package: {exc}") from exc
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return Acquired(destination, digest, verified)


def _settle(path: Path, package: Package, on_mismatch: Decision | None, insist_on_immutable: bool) -> tuple[str, bool]:
    """Hash what arrived and decide whether it may be used.

    A digest that stops matching means two very different things depending on
    how the artifact is published, and dfpm cannot tell which by looking at the
    bytes. For a URL the publisher replaces, it usually means a new release; for
    one that should never change, it means something is wrong. Only the first is
    a question worth putting to somebody.
    """
    try:
        digest, size = _digest_and_size(path)
    except OSError as exc:
        raise VerificationError(f"Could not read the downloaded file: {path}") from exc
    if digest == package.sha256:
        if package.size is not None and size != package.size:
            raise VerificationError(f"Artifact size mismatch: expected {package.size}, received {size}")
        return digest, True
    if insist_on_immutable and not package.rolling:
        raise VerificationError(mismatch_report(package, digest))
    if on_mismatch is None or not on_mismatch(package.sha256, digest):
        raise VerificationError(mismatch_report(package, digest))
    return digest, False


def mismatch_report(package: Package, actual: str, remedy: bool = True) -> str:
    """Say what changed, and what that means for this particular package.

    *remedy* is dropped when the caller is about to ask the question itself,
    since telling somebody which flag to re-run with and then prompting them
    reads as though the prompt were not the answer.
    """
    if package.rolling:
        report = (
            "Artifact digest changed.\n"
            "This package uses a rolling upstream URL, so the publisher may replace the file\n"
            "when a new version is released.\n"
            f"  Catalog digest:  {package.sha256}\n"
            f"  Downloaded:      {actual}\n"
            "The downloaded artifact has not been reviewed for the dfpm catalog."
        )
        action = "Run 'dfpm sync' for an updated entry, or use --accept-digest-mismatch to take these bytes."
    else:
        report = (
            "Artifact digest mismatch.\n"
            "This package is expected to be immutable, so its bytes should never change.\n"
            f"  Expected: {package.sha256}\n"
            f"  Received: {actual}\n"
            "That is not an upstream release doing what it normally does, so dfpm will not install it."
        )
        action = "'dfpm download --accept-digest-mismatch' saves the file for you to examine."
    return f"{report}\n{action}" if remedy else report


def _write(package: Package, source: str, partial: Path, on_progress: Reporter | None) -> None:
    """Put the bytes at `source` into `partial`, whatever kind of source it is."""
    source_path = Path(source)
    parsed = urllib.parse.urlparse(source)
    if source_path.is_absolute():
        shutil.copyfile(source_path, partial)
    elif parsed.scheme == "https":
        request = urllib.request.Request(source, headers={"User-Agent": "dfpm/0.1"})
        with urllib.request.urlopen(request, timeout=30) as response, partial.open("wb") as target:
            if urllib.parse.urlparse(response.geturl()).scheme != "https":
                raise VerificationError("An HTTPS download redirected to an insecure source")
            _stream(response, target, package.size or _declared_length(response), on_progress)
    elif parsed.scheme == "file":
        shutil.copyfile(urllib.request.url2pathname(parsed.path), partial)
    elif not parsed.scheme:
        shutil.copyfile(source_path, partial)
    else:
        raise VerificationError("Artifact sources must use HTTPS, file URLs, or local paths")


def _declared_length(response) -> int | None:
    """The size the server claims, used only to draw a bar against."""
    try:
        return int(response.headers.get("Content-Length"))
    except (TypeError, ValueError):
        return None


def _stream(response, target, total: int | None, on_progress: Reporter | None) -> None:
    """Copy the body across, reporting as it goes.

    The size here is only for drawing a bar. Whether the bytes are the right
    ones is settled afterwards by the digest, which is the only thing that
    decides a download is acceptable.
    """
    done = 0
    if on_progress is not None:
        on_progress("download", 0, total)
    while chunk := response.read(CHUNK_SIZE):
        target.write(chunk)
        done += len(chunk)
        if on_progress is not None:
            on_progress("download", done, total)


def verify(path: Path, package: Package) -> None:
    try:
        digest, size = _digest_and_size(path)
    except OSError as exc:
        raise VerificationError(f"Could not read the downloaded file: {path}") from exc
    if package.size is not None and size != package.size:
        raise VerificationError(f"Artifact size mismatch: expected {package.size}, received {size}")
    if digest != package.sha256:
        raise VerificationError(mismatch_report(package, digest))


def file_digest(path: Path) -> str:
    return _digest_and_size(path)[0]


def _digest_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size

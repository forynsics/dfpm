from __future__ import annotations

import hashlib
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from .errors import VerificationError
from .manifest import Package
from .progress import Reporter
from .storage import Storage

CHUNK_SIZE = 1024 * 1024


def retrieve(package: Package, source: str, target: Path, on_progress: Reporter | None = None) -> Path:
    """Download an artifact to a path the caller chose, and check it against its digest.

    This is a plain file download. Nothing is cached, extracted or installed:
    the file lands where it was asked to land, under the name its project
    published it with, for someone to carry to whichever machine needs it.
    """
    if target.exists():
        raise VerificationError(f"Refusing to overwrite an existing file: {target}")
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    try:
        _write(package, source, partial, on_progress)
        verify(partial, package)
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return target


def acquire(package: Package, source: str, storage: Storage, on_progress: Reporter | None = None) -> Path:
    storage.cache.mkdir(parents=True, exist_ok=True)
    destination = storage.cache / package.sha256
    if destination.exists():
        verify(destination, package)
        return destination

    partial = destination.with_suffix(".partial")
    partial.unlink(missing_ok=True)
    try:
        _write(package, source, partial, on_progress)
        verify(partial, package)
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
    return destination


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
        raise VerificationError("The download's SHA-256 does not match the one the manifest records")


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

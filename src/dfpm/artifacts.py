from __future__ import annotations

import hashlib
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from .errors import VerificationError
from .manifest import Artifact
from .storage import Storage

CHUNK_SIZE = 1024 * 1024


def acquire(artifact: Artifact, source: str, storage: Storage) -> Path:
    storage.cache.mkdir(parents=True, exist_ok=True)
    destination = storage.cache / artifact.sha256
    if destination.exists():
        verify(destination, artifact)
        return destination

    partial = destination.with_suffix(".partial")
    partial.unlink(missing_ok=True)
    try:
        source_path = Path(source)
        parsed = urllib.parse.urlparse(source)
        if source_path.is_absolute():
            shutil.copyfile(source_path, partial)
        elif parsed.scheme == "https":
            request = urllib.request.Request(source, headers={"User-Agent": "DFPM/0.1"})
            with urllib.request.urlopen(request, timeout=30) as response, partial.open("wb") as target:
                if urllib.parse.urlparse(response.geturl()).scheme != "https":
                    raise VerificationError("HTTPS artifact redirected to an insecure source")
                shutil.copyfileobj(response, target, CHUNK_SIZE)
        elif parsed.scheme == "file":
            shutil.copyfile(urllib.request.url2pathname(parsed.path), partial)
        elif not parsed.scheme:
            shutil.copyfile(source_path, partial)
        else:
            raise VerificationError("Artifact sources must use HTTPS, file URLs, or local paths")
        verify(partial, artifact)
        partial.replace(destination)
    except (OSError, ValueError) as exc:
        partial.unlink(missing_ok=True)
        if isinstance(exc, VerificationError):
            raise
        raise VerificationError(f"Could not acquire artifact: {exc}") from exc
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return destination


def verify(path: Path, artifact: Artifact) -> None:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(CHUNK_SIZE):
                size += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise VerificationError(f"Could not read artifact: {path}") from exc
    if artifact.size is not None and size != artifact.size:
        raise VerificationError(f"Artifact size mismatch: expected {artifact.size}, received {size}")
    if digest.hexdigest() != artifact.sha256:
        raise VerificationError("Artifact SHA-256 digest does not match the manifest")

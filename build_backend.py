"""Build backend that manufactures the entries dfpm ships with.

`catalog/` is the source of truth and the only place entries are edited. A wheel
still has to carry them, so that a fresh install has something to install from
before anyone has synced anything. Copying them by hand meant two directories
that had to be kept identical, and a test whose whole job was noticing when they
were not.

Building does the copy instead. The entries land in the package at build time,
including for an editable install, so `catalog/` stays the one thing a person
maintains.

This wraps setuptools rather than replacing it; everything not named here is
setuptools' own.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools.build_meta import *  # noqa: F403 - the rest of the backend, unchanged
from setuptools.build_meta import build_editable as _build_editable
from setuptools.build_meta import build_sdist as _build_sdist
from setuptools.build_meta import build_wheel as _build_wheel

ROOT = Path(__file__).parent
SOURCE = ROOT / "catalog"
SHIPPED = ROOT / "src" / "dfpm" / "entries"
BUILT = ROOT / "build" / "lib" / "dfpm" / "entries"
COLLECTIONS = "collections"


def _stage_entries() -> None:
    """Put the reviewed catalog where the package expects to find it."""
    if not SOURCE.is_dir():
        return
    # setuptools may reuse build/lib between local builds. Package data removed
    # from the source catalog must not survive there and leak into a later
    # wheel, especially when a draft has been moved out of publication.
    if BUILT.is_dir():
        shutil.rmtree(BUILT)
    SHIPPED.mkdir(parents=True, exist_ok=True)
    wanted = {path.name for path in SOURCE.glob("*.json")}
    for stale in SHIPPED.glob("*.json"):
        if stale.name not in wanted:
            stale.unlink()
    for entry in SOURCE.glob("*.json"):
        shutil.copyfile(entry, SHIPPED / entry.name)

    source_collections = SOURCE / COLLECTIONS
    shipped_collections = SHIPPED / COLLECTIONS
    if source_collections.is_dir():
        shipped_collections.mkdir(parents=True, exist_ok=True)
        wanted_collections = {path.name for path in source_collections.glob("*.json")}
        for stale in shipped_collections.glob("*.json"):
            if stale.name not in wanted_collections:
                stale.unlink()
        for collection in source_collections.glob("*.json"):
            shutil.copyfile(collection, shipped_collections / collection.name)


def build_wheel(*args, **kwargs):
    _stage_entries()
    return _build_wheel(*args, **kwargs)


def build_sdist(*args, **kwargs):
    _stage_entries()
    return _build_sdist(*args, **kwargs)


def build_editable(*args, **kwargs):
    _stage_entries()
    return _build_editable(*args, **kwargs)

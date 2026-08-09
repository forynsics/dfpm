"""Progress reporting for the slow parts of an install.

Downloading tens of megabytes and unpacking thousands of files both take long
enough that silence reads as a hang. This draws a bar when someone is watching
and stays quiet when nothing is, so piped output and logs are unchanged.
"""

from __future__ import annotations

import sys
from typing import Protocol, TextIO

BAR_WIDTH = 24


class Reporter(Protocol):
    def __call__(self, stage: str, done: int, total: int | None) -> None: ...


def human(size: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:,.0f} {unit}" if unit == "B" else f"{size:,.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


class TerminalProgress:
    """Draws a single line that rewrites itself, in ASCII only.

    A Windows console at its default code page mangles anything else, so the
    bar is drawn with plain hashes rather than block-drawing characters.
    """

    LABELS = {"download": "Downloading", "extract": " Extracting"}
    UNITS = {"download": "bytes", "extract": "files"}

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self._stage: str | None = None
        self._width = 0
        self._last: tuple[str, int] | None = None

    def __call__(self, stage: str, done: int, total: int | None) -> None:
        if stage != self._stage:
            self._finish_line()
            self._stage = stage
            self._last = None
        # Extraction reports every file, which for a large package is thousands
        # of calls. Only redraw when the line would actually look different.
        if total:
            mark = (stage, min(100, round(100 * done / total)))
            if mark == self._last and done != total:
                return
            self._last = mark
        label = self.LABELS.get(stage, stage.title())
        if self.UNITS.get(stage) == "bytes":
            amount = f"{human(done)} / {human(total)}" if total else human(done)
        else:
            amount = f"{done:,} / {total:,} files" if total else f"{done:,} files"
        if total:
            filled = min(BAR_WIDTH, round(BAR_WIDTH * done / total)) if total else 0
            bar = "#" * filled + "-" * (BAR_WIDTH - filled)
            percent = f"{min(100, round(100 * done / total)):>3}%"
            line = f"{label}  [{bar}] {percent}  {amount}"
        else:
            line = f"{label}  {amount}"
        self._write(line)

    def close(self) -> None:
        self._finish_line()
        self._stage = None

    def _write(self, line: str) -> None:
        padding = " " * max(0, self._width - len(line))
        self.stream.write(f"\r{line}{padding}")
        self.stream.flush()
        self._width = len(line)

    def _finish_line(self) -> None:
        if self._width:
            self.stream.write("\n")
            self.stream.flush()
            self._width = 0


def reporter(stream: TextIO | None = None) -> TerminalProgress | None:
    """A reporter when someone is watching, and nothing when output is piped."""
    stream = stream if stream is not None else sys.stderr
    try:
        interactive = stream.isatty()
    except (AttributeError, ValueError):
        interactive = False
    return TerminalProgress(stream) if interactive else None

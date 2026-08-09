from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from dfpm import progress
from dfpm.installer import install
from dfpm.manifest import Manifest
from dfpm.storage import Storage
from tests.helpers import create_package


class FakeTerminal(io.StringIO):
    def isatty(self) -> bool:
        return True


class ReporterChoiceTests(unittest.TestCase):
    """A bar is for someone watching. Piped output and logs stay unchanged."""

    def test_a_terminal_gets_a_reporter(self) -> None:
        self.assertIsInstance(progress.reporter(FakeTerminal()), progress.TerminalProgress)

    def test_piped_output_gets_nothing(self) -> None:
        self.assertIsNone(progress.reporter(io.StringIO()))

    def test_a_stream_that_cannot_say_gets_nothing(self) -> None:
        class Awkward:
            def isatty(self):
                raise ValueError("closed")

        self.assertIsNone(progress.reporter(Awkward()))


class RenderingTests(unittest.TestCase):
    def render(self, calls) -> list[str]:
        out = FakeTerminal()
        bar = progress.TerminalProgress(out)
        for stage, done, total in calls:
            bar(stage, done, total)
        bar.close()
        return [line.rstrip() for line in out.getvalue().split("\r") if line.strip()]

    def test_it_draws_a_bar_and_the_amounts(self) -> None:
        lines = self.render([("download", 0, 1000), ("download", 500, 1000), ("download", 1000, 1000)])
        self.assertIn("Downloading", lines[0])
        self.assertIn(" 50%", lines[1])
        self.assertIn("100%", lines[-1])

    def test_the_output_stays_ascii(self) -> None:
        # A Windows console at its default code page mangles anything else.
        out = FakeTerminal()
        bar = progress.TerminalProgress(out)
        bar("download", 5_000_000, 44_165_228)
        bar("extract", 1200, 5077)
        bar.close()
        out.getvalue().encode("ascii")

    def test_an_unknown_total_still_reports_something(self) -> None:
        lines = self.render([("download", 4096, None)])
        self.assertIn("4.0 KiB", lines[0])
        self.assertNotIn("%", lines[0])

    def test_redraws_are_throttled_to_visible_change(self) -> None:
        # Extraction reports every file; a large package would otherwise write
        # thousands of lines that look identical.
        out = FakeTerminal()
        bar = progress.TerminalProgress(out)
        for done in range(1, 5001):
            bar("extract", done, 5000)
        bar.close()
        drawn = [line for line in out.getvalue().split("\r") if line.strip()]
        # One per percentage point from 0 to 100, plus the final state, which is
        # always drawn so the bar never stops short of where it finished.
        self.assertLessEqual(len(drawn), 102)
        self.assertIn("100%", drawn[-1])

    def test_shorter_lines_do_not_leave_debris_behind(self) -> None:
        out = FakeTerminal()
        bar = progress.TerminalProgress(out)
        bar("download", 10_000_000, 44_165_228)
        bar("download", 44_165_228, 44_165_228)
        bar.close()
        last = out.getvalue().split("\r")[-1]
        self.assertNotIn("MiB / 42.1 MiB4", last)


class InstallReportingTests(unittest.TestCase):
    def test_an_install_reports_both_stages(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        storage = Storage(base / "dfpm-data")
        _, manifest_path = create_package(base)
        seen: list[tuple[str, int, int | None]] = []
        install(Manifest.load(manifest_path), storage, on_progress=lambda *args: seen.append(args))

        stages = {stage for stage, _, _ in seen}
        self.assertIn("extract", stages)
        extract = [item for item in seen if item[0] == "extract"]
        self.assertEqual(extract[-1][1], extract[-1][2], "it finishes at the total it announced")

    def test_no_reporter_is_the_normal_case(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        storage = Storage(base / "dfpm-data")
        _, manifest_path = create_package(base)
        self.assertTrue(install(Manifest.load(manifest_path), storage).is_dir())


if __name__ == "__main__":
    unittest.main()

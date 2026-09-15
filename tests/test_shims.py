from __future__ import annotations

import os
import subprocess
import tempfile
import tracemalloc
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath

from dfpm import launcher, shims
from dfpm.installer import install
from dfpm.manifest import Manifest
from dfpm.storage import Storage
from tests.helpers import create_package, report_directory_script


class ShimContentTests(unittest.TestCase):
    """What a shim says is a pure function of the install, so both forms are checked on every system."""

    def test_a_windows_shim_is_a_cmd_script(self) -> None:
        # Exact bytes on purpose: an existing shim is compared byte for byte,
        # so any change here reports every installed command as stale.
        shim = shims.Shim(
            "yara", "yara", "4.5.5",
            PureWindowsPath(r"C:\dfpm\tools\yara\4.5.5\yara64.exe"),
            PureWindowsPath(r"C:\dfpm\tools\yara\4.5.5"),
        )
        self.assertEqual(
            shims._content(shim, "nt"),
            "@rem dfpm-shim package=yara version=4.5.5\r\n"
            "@echo off\r\n"
            "setlocal\r\n"
            'cd /d "C:\\dfpm\\tools\\yara\\4.5.5"\r\n'
            '"C:\\dfpm\\tools\\yara\\4.5.5\\yara64.exe" %*\r\n',
        )

    def test_a_posix_shim_is_a_shell_script_that_hands_over_to_the_tool(self) -> None:
        shim = shims.Shim(
            "hayabusa", "hayabusa", "4.1.0",
            PurePosixPath("/home/analyst/.local/share/dfpm/tools/hayabusa/4.1.0/hayabusa"),
            PurePosixPath("/home/analyst/.local/share/dfpm/tools/hayabusa/4.1.0"),
        )
        self.assertEqual(
            shims._content(shim, "posix").splitlines(),
            [
                "#!/bin/sh",
                "# dfpm-shim package=hayabusa version=4.1.0",
                "cd '/home/analyst/.local/share/dfpm/tools/hayabusa/4.1.0' || exit 126",
                "exec '/home/analyst/.local/share/dfpm/tools/hayabusa/4.1.0/hayabusa' \"$@\"",
            ],
        )

    def test_a_quote_in_a_posix_path_cannot_end_the_quoting(self) -> None:
        shim = shims.Shim("x", "x", "1.0", PurePosixPath("/cases/it's $HOME/x"), PurePosixPath("/cases/it's $HOME"))
        self.assertIn("exec '/cases/it'\\''s $HOME/x' \"$@\"", shims._content(shim, "posix"))

    def test_the_shim_file_follows_the_platform(self) -> None:
        self.assertEqual(shims.filename("yara", "nt"), "yara.cmd")
        self.assertEqual(shims.filename("yara", "posix"), "yara")


class OwnershipCheckTests(unittest.TestCase):
    def test_a_large_file_in_the_bin_directory_is_not_read_whole(self) -> None:
        # On POSIX every file in bin is asked whether it is a shim, including a
        # program somebody copied there, which may have no line break for
        # megabytes. Answering must not mean reading it into memory.
        base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        program = base / "some-program"
        program.write_bytes(b"\x7fELF" + b"\x01" * (8 * 1024 * 1024))
        tracemalloc.start()
        try:
            self.assertFalse(shims.owned(program))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1024 * 1024)


@unittest.skipIf(os.name == "nt", "POSIX shims only")
class PosixShimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.storage = Storage(self.base / "dfpm-data")

    def install_package(self, base: Path | None = None, **kwargs) -> Path:
        _, manifest_path = create_package(base or self.base, **kwargs)
        return install(Manifest.load(manifest_path), self.storage)

    def test_the_shim_is_an_executable_file_named_exactly_like_the_command(self) -> None:
        self.install_package()
        shim = self.storage.bin / "example-tool"
        self.assertTrue(shim.is_file())
        self.assertTrue(os.access(shim, os.X_OK))
        self.assertTrue(shims.owned(shim))

    def test_the_shim_runs_from_a_path_with_characters_a_shell_would_act_on(self) -> None:
        awkward = self.base / "case 42 it's $HOME & more"
        awkward.mkdir()
        self.storage = Storage(awkward / "dfpm-data")
        destination = self.install_package(awkward, body=report_directory_script(5), working_directory=".")
        completed = subprocess.run([str(shims.path(self.storage, "example-tool"))], capture_output=True)
        self.assertEqual(completed.returncode, 5, completed.stderr)
        self.assertEqual(Path((destination / "where.txt").read_text(encoding="utf-8").strip()), destination)

    def test_a_windows_shim_in_the_same_directory_is_never_swept(self) -> None:
        # Only this platform's marker is ours to act on. A root shared with a
        # Windows dfpm must not lose that system's commands.
        self.install_package()
        foreign = self.storage.bin / "yara.cmd"
        foreign.write_text(f"{shims.WINDOWS_MARKER} package=yara version=4.5.5\r\n", encoding="utf-8")
        shims.reconcile(self.storage)
        self.assertTrue(foreign.exists())

    def test_an_unmanaged_program_in_the_bin_directory_is_left_alone(self) -> None:
        self.install_package()
        other = self.storage.bin / "somebody-elses-tool"
        other.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
        other.chmod(0o755)
        shims.reconcile(self.storage)
        self.assertEqual(other.read_text(encoding="utf-8"), "#!/bin/sh\necho mine\n")

    def test_an_interrupted_write_is_not_mistaken_for_a_command(self) -> None:
        self.install_package()
        leftover = self.storage.bin / ".example-tool.abc123.tmp"
        leftover.write_text(f"#!/bin/sh\n{shims.POSIX_MARKER} package=x version=1\n", encoding="utf-8")
        self.assertNotIn(leftover, shims.existing(self.storage))

    def test_which_reports_the_extensionless_shortcut(self) -> None:
        self.install_package()
        self.assertEqual(launcher.resolve(self.storage, "example-tool").shim, self.storage.bin / "example-tool")


if __name__ == "__main__":
    unittest.main()

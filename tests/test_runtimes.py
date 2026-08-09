from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dfpm import runtimes
from dfpm.cli import main
from dfpm.doctor import inspect
from dfpm.errors import CommandNotRunnable, DfpmError, ManifestError
from dfpm.installer import install
from dfpm.manifest import Manifest, Requirement
from dfpm.storage import Storage
from tests.helpers import create_package

JAVA = [{"runtime": "java", "version": ">=21"}]


class VersionReadingTests(unittest.TestCase):
    """Every runtime reports its version differently, and some of them lie about it."""

    def test_java_before_nine_reports_one_point_eight(self) -> None:
        # Java 8 calls itself 1.8.0, so a >=8 requirement has to understand that.
        self.assertEqual(runtimes._version_from("java", 'openjdk version "1.8.0_402"'), (8, 0, 402))

    def test_modern_java_is_read_as_written(self) -> None:
        self.assertEqual(runtimes._version_from("java", 'openjdk version "21.0.1" 2023-10-17'), (21, 0, 1))

    def test_java_reports_on_stderr(self) -> None:
        # Both streams are merged before parsing precisely because of this.
        self.assertEqual(runtimes._version_from("java", "\nopenjdk version \"17.0.9\""), (17, 0, 9))

    def test_the_perl_banner_is_understood(self) -> None:
        banner = "This is perl 5, version 38, subversion 2 (v5.38.2) built for x86_64"
        self.assertEqual(runtimes._version_from("perl", banner), (5, 38, 2))

    def test_unreadable_output_yields_nothing(self) -> None:
        self.assertIsNone(runtimes._version_from("java", "some unrelated banner"))

    def test_an_unreadable_version_never_satisfies_a_minimum(self) -> None:
        # Passing here would let banner noise stand in for a real check.
        self.assertFalse(runtimes.satisfies(None, runtimes.parse_minimum(">=8")))

    def test_an_unreadable_version_is_fine_with_no_minimum(self) -> None:
        self.assertTrue(runtimes.satisfies(None, None))

    def test_a_constraint_must_use_at_least(self) -> None:
        with self.assertRaises(DfpmError):
            runtimes.parse_minimum("8")
        with self.assertRaises(DfpmError):
            runtimes.parse_minimum(">=eight")


class DotnetFlavorTests(unittest.TestCase):
    """Desktop, ASP.NET and the base runtime are separate installs."""

    LISTING = "\n".join([
        r"Microsoft.AspNetCore.App 8.0.19 [C:\Program Files\dotnet\shared\Microsoft.AspNetCore.App]",
        r"Microsoft.NETCore.App 8.0.19 [C:\Program Files\dotnet\shared\Microsoft.NETCore.App]",
        r"Microsoft.WindowsDesktop.App 6.0.36 [C:\Program Files\dotnet\shared\Microsoft.WindowsDesktop.App]",
    ])

    def frameworks(self) -> dict:
        return runtimes._dotnet_frameworks(self.LISTING)

    def test_each_framework_is_read_separately(self) -> None:
        self.assertEqual(self.frameworks(), {"aspnet": (8, 0, 19), "base": (8, 0, 19), "desktop": (6, 0, 36)})

    def test_the_base_runtime_does_not_satisfy_a_desktop_requirement(self) -> None:
        # The trap Registry Explorer would spring: base 8 present, desktop only 6.
        found = self.frameworks()
        minimum = runtimes.parse_minimum(">=8")
        self.assertTrue(runtimes.satisfies(found["base"], minimum))
        self.assertFalse(runtimes.satisfies(found["desktop"], minimum))


class InterpreterGuardTests(unittest.TestCase):
    def test_dfpms_own_interpreter_is_never_selected(self) -> None:
        # An activated virtual environment puts its Scripts directory first on
        # PATH. A packaged tool must never be handed the interpreter dfpm runs on.
        found = runtimes._safe_which("python")
        if found is not None:
            self.assertNotEqual(found.resolve(), Path(sys.executable).resolve())
            self.assertNotEqual(found.parent.resolve(), Path(sys.executable).parent.resolve())

    def test_a_runtime_dfpm_installed_wins_over_one_on_path(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        storage = Storage(base / "dfpm-data")
        _, manifest_path = create_package(base, commands=("perl",), body="@exit /b 0\r\n")
        destination = install(Manifest.load(manifest_path), storage)

        detection = runtimes.detect("perl", storage)
        self.assertEqual(detection.path, destination / "bin" / "perl.cmd")
        self.assertTrue(detection.source.startswith("dfpm:"))


class RequirementManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def load(self, requires: list[dict]) -> Manifest:
        _, manifest_path = create_package(self.base, requires=requires)
        return Manifest.load(manifest_path)

    def test_a_requirement_is_read(self) -> None:
        manifest = self.load([{"runtime": "dotnet", "version": ">=8", "flavor": "desktop"}])
        self.assertEqual(manifest.requires[0], Requirement("dotnet", ">=8", "desktop"))
        self.assertEqual(str(manifest.requires[0]), ".NET desktop >=8")

    def test_no_requirements_is_the_normal_case(self) -> None:
        _, manifest_path = create_package(self.base)
        self.assertEqual(Manifest.load(manifest_path).requires, ())

    def test_an_unknown_runtime_is_rejected(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            self.load([{"runtime": "cobol"}])
        self.assertIn("requires.runtime", str(caught.exception))

    def test_an_unusable_version_constraint_is_rejected(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            self.load([{"runtime": "java", "version": "21"}])
        self.assertIn("requires.version", str(caught.exception))

    def test_a_flavor_the_runtime_does_not_have_is_rejected(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            self.load([{"runtime": "java", "flavor": "desktop"}])
        self.assertIn("requires.flavor", str(caught.exception))

    def test_a_runtime_cannot_be_required_twice(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            self.load([{"runtime": "java"}, {"runtime": "java", "version": ">=8"}])
        self.assertIn("only be required once", str(caught.exception))


class BlockedPackageTests(unittest.TestCase):
    """Installed and runnable are different states."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")
        self.catalog, manifest_path = create_package(self.base, requires=JAVA, body="@exit /b 0\r\n")
        self.manifest_path = manifest_path
        # Nothing named java exists, so the requirement cannot be met.
        self.missing = mock.patch("dfpm.runtimes._from_path", return_value=None)

    def test_installing_succeeds_even_though_it_cannot_run(self) -> None:
        with self.missing:
            destination = install(Manifest.load(self.manifest_path), self.storage)
        self.assertTrue(destination.is_dir())

    def test_the_install_says_it_cannot_be_run_yet(self) -> None:
        output = io.StringIO()
        with self.missing, contextlib.redirect_stdout(output):
            code = main([
                "--root", str(self.storage.root), "--catalog", str(self.catalog),
                "install", "example.tool", "--yes",
            ])
        printed = output.getvalue()
        self.assertEqual(code, 0, "a missing runtime does not fail the install")
        self.assertIn("Installed to", printed)
        self.assertIn("cannot be run yet", printed)
        self.assertIn("Java", printed)

    def test_the_output_stays_ascii(self) -> None:
        # A Windows console defaults to a legacy code page, where anything else
        # is mangled or raises on the way out.
        output = io.StringIO()
        with self.missing, contextlib.redirect_stdout(output):
            main([
                "--root", str(self.storage.root), "--catalog", str(self.catalog),
                "install", "example.tool", "--yes",
            ])
        output.getvalue().encode("ascii")

    def test_running_it_refuses_and_explains(self) -> None:
        with self.missing:
            install(Manifest.load(self.manifest_path), self.storage)
            from dfpm import launcher

            with self.assertRaises(CommandNotRunnable) as caught:
                launcher.run(self.storage, "example-tool", [])
        message = str(caught.exception)
        self.assertEqual(caught.exception.exit_code, 126)
        self.assertIn("Cannot run example-tool", message)
        self.assertIn("Required: Java >=21", message)

    def test_doctor_reports_it_as_blocked_rather_than_failed(self) -> None:
        with self.missing:
            install(Manifest.load(self.manifest_path), self.storage)
            findings = inspect(self.storage)
        self.assertEqual([item.status for item in findings], ["blocked"])
        self.assertIn("Java", findings[0].detail)

    def test_doctor_exits_two_for_blocked_and_one_for_broken(self) -> None:
        with self.missing:
            destination = install(Manifest.load(self.manifest_path), self.storage)
            with contextlib.redirect_stdout(io.StringIO()):
                blocked = main(["--root", str(self.storage.root), "doctor"])
            self.assertEqual(blocked, 2)

            (destination / "bin" / "example-tool.cmd").unlink()
            with contextlib.redirect_stdout(io.StringIO()):
                broken = main(["--root", str(self.storage.root), "doctor"])
            self.assertEqual(broken, 1, "something dfpm owns being broken outranks a missing runtime")

    def test_a_satisfied_requirement_passes(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        storage = Storage(base / "dfpm-data")
        _, manifest_path = create_package(base, requires=[{"runtime": "java", "version": ">=8"}])
        detection = runtimes.Detection("java", path=Path("java.exe"), version=(21, 0, 1))
        with mock.patch("dfpm.runtimes.detect", return_value=detection):
            install(Manifest.load(manifest_path), storage)
            findings = inspect(storage)
        self.assertEqual(findings[0].status, "passing")
        self.assertIn("Java 21.0.1", findings[0].detail)


class DoctorArgumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")

    def test_it_can_be_narrowed_to_one_package(self) -> None:
        _, first = create_package(self.base, package_id="one.tool", commands=("one",))
        _, second = create_package(self.base, package_id="two.tool", commands=("two",))
        install(Manifest.load(first), self.storage)
        install(Manifest.load(second), self.storage)

        findings = inspect(self.storage, "one.tool")
        self.assertEqual([item.package for item in findings], ["one.tool"])

    def test_asking_about_a_package_that_is_not_installed_says_so(self) -> None:
        with self.assertRaises(DfpmError) as caught:
            inspect(self.storage, "nosuch.tool")
        self.assertIn("not installed", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

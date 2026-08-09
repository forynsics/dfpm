from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dfpm.cli import main
from dfpm.errors import DfpmError, ManifestError
from dfpm.manifest import Manifest
from dfpm.storage import Storage
from tests.helpers import create_package

TERMS = "https://example.org/eula"


class TermsTests(unittest.TestCase):
    """Confirming a plan is not the same as asserting that terms permit your use."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")
        self.catalog, self.manifest_path = create_package(self.base, terms_url=TERMS)

    def run_install(self, *extra: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([
                "--root", str(self.storage.root),
                "--catalog", str(self.catalog),
                "install", "example.tool", *extra,
            ])
        return code, out.getvalue(), err.getvalue()

    def test_the_plan_shows_the_terms(self) -> None:
        with mock.patch("builtins.input", return_value="n"):
            _, out, _ = self.run_install()
        self.assertIn(TERMS, out)
        self.assertIn("Acceptance required", out)

    def test_yes_alone_refuses_to_install(self) -> None:
        code, _, err = self.run_install("--yes")
        self.assertEqual(code, 1)
        self.assertIn("restricting who may use it", err)
        self.assertIn("--accept-terms", err)
        self.assertFalse(self.storage.package_version("example.tool", "1.0.0").exists())

    def test_yes_with_accept_terms_installs(self) -> None:
        code, out, _ = self.run_install("--yes", "--accept-terms")
        self.assertEqual(code, 0)
        self.assertIn("Installed to", out)

    def test_answering_the_prompt_is_acceptance_enough(self) -> None:
        # The interactive path gains no extra step; the existing confirmation
        # already puts the terms in front of a person who then says yes.
        with mock.patch("builtins.input", return_value="y"):
            code, out, _ = self.run_install()
        self.assertEqual(code, 0)
        self.assertIn("Installed to", out)

    def test_a_package_without_terms_is_unaffected_by_yes(self) -> None:
        base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        catalog, _ = create_package(base)
        storage = Storage(base / "dfpm-data")
        with contextlib.redirect_stdout(io.StringIO()):
            code = main([
                "--root", str(storage.root), "--catalog", str(catalog),
                "install", "example.tool", "--yes",
            ])
        self.assertEqual(code, 0)

    def test_terms_url_must_be_https(self) -> None:
        _, manifest_path = create_package(self.base, terms_url="http://example.org/eula")
        with self.assertRaises(ManifestError) as caught:
            Manifest.load(manifest_path)
        self.assertIn("project.terms_url", str(caught.exception))

    def test_a_license_expression_is_carried_verbatim(self) -> None:
        # Two licenses in one artifact, as an SPDX expression. dfpm displays it
        # rather than parsing it, so no schema change was needed.
        _, manifest_path = create_package(self.base, terms_url=TERMS)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["project"]["license"] = "AGPL-3.0-only AND LicenseRef-DRL-1.1"
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        manifest = Manifest.load(manifest_path)
        self.assertEqual(manifest.project.license, "AGPL-3.0-only AND LicenseRef-DRL-1.1")


class GuiTermsTests(unittest.TestCase):
    """The local interface applies the same rule as the command line."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage = Storage(self.base / "dfpm-data")
        self.catalog, _ = create_package(self.base, terms_url=TERMS)

    def session(self):
        from dfpm.gui import Session

        return Session(storage=self.storage, catalog=self.catalog, token="test-token")

    def test_installing_without_acceptance_is_refused(self) -> None:
        from dfpm.gui import _do_install

        with self.assertRaises(DfpmError) as caught:
            _do_install(self.session(), {"package": "example.tool"})
        self.assertIn("restricting who may use it", str(caught.exception))

    def test_the_plan_carries_the_terms_url(self) -> None:
        from dfpm.gui import _plan_install

        plan = _plan_install(self.session(), {"package": "example.tool"})["plan"]
        self.assertEqual(plan["termsUrl"], TERMS)

    def test_installing_with_acceptance_proceeds(self) -> None:
        from dfpm.gui import _do_install

        result = _do_install(self.session(), {"package": "example.tool", "acceptTerms": True})
        self.assertIn("Installed", result["message"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dfpm import plan
from dfpm.cli import main
from dfpm.storage import Storage
from tests.helpers import create_package


class BulkFixture(unittest.TestCase):
    """Three packages, so a request can be a set rather than a single thing."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.root = self.base / "root"
        self.storage = Storage(self.root)
        self.catalog, _ = create_package(self.base, package_id="alpha", commands=("alpha",))
        create_package(self.base, package_id="beta", commands=("beta",))
        create_package(self.base, package_id="gamma", commands=("gamma",))

    def run_cli(self, *argv: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = main(["--root", str(self.root), "--catalog", str(self.catalog), *argv])
        return code, output.getvalue()

    def installed(self) -> set[str]:
        from dfpm.inventory import list_packages

        return {record["id"] for record in list_packages(self.storage)}


class ResolutionTests(BulkFixture):
    def test_a_name_asked_for_twice_is_resolved_once(self) -> None:
        # Typing a name twice is a slip, not a request to install it twice, and
        # the plan a person reads back should be the set they meant.
        current = plan.for_install(self.storage, self.catalog, ["alpha", "beta", "alpha"])
        self.assertEqual([item.package for item in current.incoming], ["alpha", "beta"])

    def test_the_order_asked_for_is_the_order_reported(self) -> None:
        current = plan.for_install(self.storage, self.catalog, ["gamma", "alpha", "beta"])
        self.assertEqual([item.package for item in current.incoming], ["gamma", "alpha", "beta"])

    def test_one_unknown_name_blocks_only_itself(self) -> None:
        current = plan.for_install(self.storage, self.catalog, ["alpha", "nosuch", "beta"])
        self.assertEqual([item.package for item in current.incoming], ["alpha", "beta"])
        self.assertEqual([item.reason for item in current.blocked], [plan.NOT_IN_CATALOG])


class PreflightTests(BulkFixture):
    """Nothing is written until the whole set has been checked."""

    def test_a_blocked_package_stops_the_set_before_anything_installs(self) -> None:
        code, printed = self.run_cli("install", "alpha", "nosuch", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("No changes were made.", printed)
        self.assertEqual(self.installed(), set())

    def test_an_already_installed_package_is_skipped_rather_than_failing(self) -> None:
        # A set where some members are present is the ordinary case, not an error.
        self.run_cli("install", "alpha", "--yes")
        code, printed = self.run_cli("install", "alpha", "beta", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("alpha 1.0.0 is already installed", printed)
        self.assertEqual(self.installed(), {"alpha", "beta"})

    def test_installing_only_what_is_already_there_succeeds_quietly(self) -> None:
        self.run_cli("install", "alpha", "--yes")
        code, printed = self.run_cli("install", "alpha", "--yes")
        self.assertEqual(code, 0)
        self.assertNotIn("Install plan", printed)

    def test_declining_a_set_installs_nothing(self) -> None:
        with mock.patch("builtins.input", return_value="n"):
            code, _ = self.run_cli("install", "alpha", "beta")
        self.assertEqual(code, 2)
        self.assertEqual(self.installed(), set())


class SummaryTests(BulkFixture):
    def test_a_set_is_summarised_rather_than_described_one_by_one(self) -> None:
        # Repeating the single-package block would put hundreds of lines between
        # the request and the question it is asking.
        with mock.patch("builtins.input", return_value="n"):
            _, printed = self.run_cli("install", "alpha", "beta", "gamma")
        self.assertIn("Install plan: 3 packages", printed)
        self.assertEqual(printed.count("Install plan"), 1)

    def test_one_package_still_gets_the_whole_story(self) -> None:
        with mock.patch("builtins.input", return_value="n"):
            _, printed = self.run_cli("install", "alpha")
        self.assertIn("Install plan\n", printed)
        self.assertIn("  Package:     ", printed)
        self.assertIn("  Destination: ", printed)

    def test_the_summary_stays_ascii(self) -> None:
        with mock.patch("builtins.input", return_value="n"):
            _, printed = self.run_cli("install", "alpha", "beta", "gamma")
        printed.encode("ascii")

    def test_a_set_reports_what_it_installed(self) -> None:
        code, printed = self.run_cli("install", "alpha", "beta", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("Installed 2 of 2 packages.", printed)


class BulkUninstallTests(BulkFixture):
    def test_several_packages_are_removed_in_one_go(self) -> None:
        self.run_cli("install", "alpha", "beta", "gamma", "--yes")
        code, printed = self.run_cli("uninstall", "alpha", "beta", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("Removal plan: 2 packages", printed)
        self.assertEqual(self.installed(), {"gamma"})

    def test_the_commands_of_removed_packages_go_and_the_rest_stay(self) -> None:
        # Shims are reconciled once for the whole set rather than per package,
        # so this is what proves the single reconcile still did the full job.
        self.run_cli("install", "alpha", "beta", "gamma", "--yes")
        self.run_cli("uninstall", "alpha", "beta", "--yes")
        remaining = {path.stem for path in self.storage.bin.glob("*.cmd")}
        self.assertEqual(remaining, {"gamma"})

    def test_removing_everything_needs_no_names(self) -> None:
        self.run_cli("install", "alpha", "beta", "gamma", "--yes")
        code, _ = self.run_cli("uninstall", "--all", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(self.installed(), set())

    def test_removing_everything_when_nothing_is_installed_is_not_a_failure(self) -> None:
        code, printed = self.run_cli("uninstall", "--all", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("Nothing is installed.", printed)

    def test_naming_packages_and_asking_for_all_is_refused(self) -> None:
        # The two say different things about what should be removed, and
        # guessing which was meant is not dfpm's to do.
        code, printed = self.run_cli("uninstall", "alpha", "--all", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("not both", printed)

    def test_a_package_that_is_not_installed_stops_the_removal(self) -> None:
        self.run_cli("install", "alpha", "--yes")
        code, _ = self.run_cli("uninstall", "alpha", "beta", "--yes")
        self.assertEqual(code, 1)
        self.assertEqual(self.installed(), {"alpha"})


class TermsTests(BulkFixture):
    """Terms are gathered across the set, because one answer covers all of it."""

    def setUp(self) -> None:
        super().setUp()
        create_package(self.base, package_id="restricted", commands=("restricted",),
                       terms_url="https://example.org/terms")

    def test_the_plan_names_every_package_whose_terms_need_accepting(self) -> None:
        current = plan.for_install(self.storage, self.catalog, ["alpha", "restricted"], accept_terms=True)
        self.assertEqual([name for name, _ in current.terms], ["Example Tool"])

    def test_a_scripted_set_is_refused_until_the_terms_are_accepted(self) -> None:
        code, printed = self.run_cli("install", "alpha", "restricted", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("--accept-terms", printed)
        self.assertEqual(self.installed(), set())

    def test_accepting_the_terms_installs_the_whole_set(self) -> None:
        code, _ = self.run_cli("install", "alpha", "restricted", "--yes", "--accept-terms")
        self.assertEqual(code, 0)
        self.assertEqual(self.installed(), {"alpha", "restricted"})


class RuntimeTests(BulkFixture):
    """A runtime wanted by several packages is looked for once."""

    def test_one_requirement_is_reported_once_and_names_who_wants_it(self) -> None:
        requires = [{"runtime": "java", "version": ">=17"}]
        create_package(self.base, package_id="one", commands=("one",), requires=requires)
        create_package(self.base, package_id="two", commands=("two",), requires=requires)
        current = plan.for_install(self.storage, self.catalog, ["one", "two"])
        java = [item for item in current.requirements if item.runtime == "java"]
        self.assertEqual(len(java), 1)
        self.assertEqual(len(java[0].wanted_by), 2)


if __name__ == "__main__":
    unittest.main()


class CollectionTests(BulkFixture):
    """A named set of packages, which is a way of asking rather than a thing installed."""

    def write_collection(self, identifier: str, packages: list[str]) -> None:
        import json

        folder = self.catalog / "collections"
        folder.mkdir(exist_ok=True)
        (folder / f"{identifier}.json").write_text(
            json.dumps({"schema_version": 1, "id": identifier, "name": identifier, "packages": packages}),
            encoding="utf-8",
        )

    def test_a_collection_stands_for_the_packages_it_names(self) -> None:
        self.write_collection("test-kit", ["alpha", "beta"])
        names, blocked = plan.expand(self.catalog, ["@test-kit"])
        self.assertEqual(names, ["alpha", "beta"])
        self.assertEqual(blocked, [])

    def test_collections_and_packages_mix_in_one_request(self) -> None:
        self.write_collection("test-kit", ["alpha", "beta"])
        current = plan.for_install(self.storage, self.catalog, ["@test-kit", "gamma"])
        self.assertEqual([item.package for item in current.incoming], ["alpha", "beta", "gamma"])

    def test_a_package_named_twice_through_a_collection_is_installed_once(self) -> None:
        self.write_collection("test-kit", ["alpha", "beta"])
        current = plan.for_install(self.storage, self.catalog, ["@test-kit", "alpha"])
        self.assertEqual([item.package for item in current.incoming], ["alpha", "beta"])

    def test_an_unknown_collection_says_what_there_is(self) -> None:
        self.write_collection("test-kit", ["alpha"])
        _, blocked = plan.expand(self.catalog, ["@nosuch"])
        self.assertEqual([item.reason for item in blocked], [plan.NO_SUCH_COLLECTION])
        self.assertIn("@test-kit", blocked[0].detail)

    def test_installing_a_collection_records_nothing_called_by_its_name(self) -> None:
        # A collection says what to ask for, never what the machine promises to
        # keep. Recording one would raise the question of whether removing a
        # member had broken it, which is a question with no good answer.
        self.write_collection("test-kit", ["alpha", "beta"])
        self.run_cli("install", "@test-kit", "--yes")
        self.assertEqual(self.installed(), {"alpha", "beta"})
        self.assertFalse((self.storage.state / "packages" / "test-kit.json").exists())

    def test_removing_one_member_is_an_ordinary_removal(self) -> None:
        self.write_collection("test-kit", ["alpha", "beta"])
        self.run_cli("install", "@test-kit", "--yes")
        code, _ = self.run_cli("uninstall", "alpha", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(self.installed(), {"beta"})

    def test_an_id_without_a_hyphen_is_refused(self) -> None:
        # It would be requested as @name, and a shell expands @name when name
        # is a variable -- silently passing something else, or nothing at all.
        from dfpm.errors import ManifestError

        self.write_collection("testkit", ["alpha"])
        with self.assertRaises(ManifestError) as caught:
            plan.expand(self.catalog, ["@testkit"])
        self.assertIn("hyphen", str(caught.exception))

    def test_a_collection_naming_a_missing_package_fails_the_catalog(self) -> None:
        from dfpm.catalog import check_collections
        from dfpm.errors import ManifestError

        self.write_collection("test-kit", ["alpha", "vanished"])
        with self.assertRaises(ManifestError) as caught:
            check_collections(self.catalog)
        self.assertIn("vanished", str(caught.exception))

    def test_a_catalog_with_no_collections_is_not_a_fault(self) -> None:
        from dfpm.catalog import load_collections

        self.assertEqual(load_collections(self.catalog), [])

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dfpm.catalog import load_catalog
from dfpm.classification import VOCABULARIES, matching_keys
from dfpm.errors import ManifestError
from dfpm.manifest import Manifest
from tests.helpers import create_package


class VocabularyTests(unittest.TestCase):
    """Four axes, kept apart on purpose: which discipline, what it does, when, and what it reads."""

    def test_the_axes_do_not_share_terms(self) -> None:
        # A key belonging to two axes would mean the split had stopped meaning
        # anything, which is exactly what the single list before it suffered from.
        keys = [set(vocabulary) for vocabulary in VOCABULARIES.values()]
        for index, first in enumerate(keys):
            for second in keys[index + 1:]:
                self.assertEqual(first & second, set())

    def test_every_term_is_reachable_by_its_own_key(self) -> None:
        for field, vocabulary in VOCABULARIES.items():
            for key, term in vocabulary.items():
                self.assertEqual(term.key, key)
                self.assertIn(key, matching_keys(field, key.replace("-", " ")))

    def test_a_newcomer_browses_by_discipline(self) -> None:
        # Somebody new to the field picks a discipline before they can name a
        # tool or an artifact, which is the entire reason this axis exists.
        self.assertIn("macos-forensics", matching_keys("disciplines", "mac"))
        self.assertIn("macos-forensics", matching_keys("disciplines", "apple"))
        self.assertIn("windows-forensics", matching_keys("disciplines", "windows"))
        self.assertIn("memory-forensics", matching_keys("disciplines", "ram"))
        self.assertIn("cloud-forensics", matching_keys("disciplines", "azure"))
        self.assertIn("smartphone-forensics", matching_keys("disciplines", "iphone"))
        self.assertIn("smartphone-forensics", matching_keys("disciplines", "mobile"))

    def test_the_evidence_vocabulary_is_not_only_windows(self) -> None:
        # It was, which is how a gap this obvious survived: every catalogued
        # package happened to be a Windows tool.
        for query in ("plist", "fsevents", "unified log", "syslog", "journald",
                      "cloudtrail", "itunes backup", "netflow"):
            self.assertTrue(matching_keys("evidence", query), f"nothing reads {query!r}")

    def test_people_find_things_by_the_words_they_use(self) -> None:
        self.assertIn("windows-event-logs", matching_keys("evidence", "evtx"))
        self.assertIn("windows-event-logs", matching_keys("evidence", "event log"))
        self.assertIn("master-file-table", matching_keys("evidence", "mft"))
        self.assertIn("master-file-table", matching_keys("evidence", "ntfs"))
        self.assertIn("onedrive-logs", matching_keys("evidence", "sync log"))
        self.assertIn("memory-images", matching_keys("evidence", "ram dump"))
        self.assertIn("malware-analysis", matching_keys("disciplines", "malware"))
        self.assertIn("incident-response", matching_keys("use_cases", "breach"))
        self.assertIn("file-carving", matching_keys("capabilities", "recover deleted"))

    def test_a_tool_name_is_never_an_alias(self) -> None:
        # An alias is a synonym for the idea. A product name belongs to the
        # package that implements it, or it makes every peer answer to it.
        for name in ("yara", "volatility", "plaso", "hayabusa", "autopsy"):
            for field in VOCABULARIES:
                self.assertEqual(matching_keys(field, name), set(), f"{name!r} leaked into {field}")

    def test_a_format_worth_finding_gets_its_own_term_not_an_alias(self) -> None:
        # Sigma is a real capability that discriminates between tools, so it is
        # a term. What it must not be is an alias on a broader detection term,
        # which would make every detection tool answer to it.
        self.assertEqual(matching_keys("capabilities", "sigma"), {"sigma-detection"})

    def test_an_empty_query_matches_nothing(self) -> None:
        self.assertEqual(matching_keys("capabilities", "   "), set())


class ManifestClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))

    BUILD_FIELDS = frozenset({"version", "platform", "package", "install", "verify", "requires"})

    def load(self, **fields) -> Manifest:
        _, manifest_path = create_package(self.base)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key, value in fields.items():
            target = data["builds"][0] if key in self.BUILD_FIELDS else data
            target[key] = value
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        return Manifest.load(manifest_path)

    def test_a_discipline_is_not_the_platform_the_binary_runs_on(self) -> None:
        # A macOS forensics tool commonly ships as a Windows build. Deriving one
        # from the other would make that package unfindable.
        manifest = self.load(
            disciplines=["macos-forensics"],
            platform={"os": "windows", "arch": "x64"},
        )
        self.assertEqual(manifest.disciplines, ("macos-forensics",))
        self.assertEqual(manifest.platform.system, "windows")

    def test_platform_describes_one_build_and_stays_singular(self) -> None:
        # One manifest, one reviewed file, one digest. A list of platforms would
        # claim a single compiled binary runs on several, and could not express
        # the different entrypoint each would need anyway.
        with self.assertRaises(ManifestError):
            self.load(platform=[{"os": "windows", "arch": "x64"}, {"os": "linux", "arch": "x64"}])

    def test_a_portable_package_omits_the_platform_entirely(self) -> None:
        # Absent means no restriction, which is how something that genuinely
        # runs anywhere is expressed.
        _, manifest_path = create_package(self.base)
        self.assertIsNone(Manifest.load(manifest_path).platform)

    def test_a_package_may_belong_to_no_single_discipline(self) -> None:
        # A cross-cutting tool genuinely belongs to none of them, which is
        # information rather than an omission.
        self.assertEqual(self.load(capabilities=["signature-scanning"]).disciplines, ())

    def test_a_classified_package_is_read(self) -> None:
        manifest = self.load(
            about="A longer plain-English explanation of what this is for.",
            disciplines=["malware-analysis"],
            capabilities=["signature-scanning"],
            use_cases=["threat-hunting", "incident-response"],
            evidence=["files"],
        )
        self.assertEqual(manifest.disciplines, ("malware-analysis",))
        self.assertEqual(manifest.capabilities, ("signature-scanning",))
        self.assertEqual(manifest.use_cases, ("threat-hunting", "incident-response"))
        self.assertEqual(manifest.evidence, ("files",))
        self.assertTrue(manifest.about.startswith("A longer"))

    def test_classification_is_optional(self) -> None:
        _, manifest_path = create_package(self.base)
        manifest = Manifest.load(manifest_path)
        self.assertEqual(
            (manifest.disciplines, manifest.capabilities, manifest.use_cases, manifest.evidence, manifest.about),
            ((), (), (), (), None),
        )

    def test_an_invented_term_is_rejected(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            self.load(capabilities=["vibes"])
        self.assertIn("does not recognise", str(caught.exception))

    def test_a_term_that_moved_axis_is_rejected_on_the_old_one(self) -> None:
        # malware-analysis is a discipline, not a use case. Keeping the term on
        # both would let two manifests disagree about which it is.
        with self.assertRaises(ManifestError):
            self.load(use_cases=["malware-analysis"])
        self.assertEqual(self.load(disciplines=["malware-analysis"]).disciplines, ("malware-analysis",))

    def test_a_term_from_the_wrong_axis_is_rejected(self) -> None:
        with self.assertRaises(ManifestError):
            self.load(capabilities=["windows-event-logs"])
        with self.assertRaises(ManifestError):
            self.load(evidence=["threat-hunting"])
        with self.assertRaises(ManifestError):
            self.load(use_cases=["timeline-generation"])
        with self.assertRaises(ManifestError):
            self.load(disciplines=["registry-hives"])

    def test_a_repeated_term_is_rejected(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            self.load(evidence=["registry-hives", "registry-hives"])
        self.assertIn("twice", str(caught.exception))

    def test_it_must_be_a_list_of_strings(self) -> None:
        with self.assertRaises(ManifestError):
            self.load(capabilities="signature-scanning")


class CataloguedPackageTests(unittest.TestCase):
    """The shipped catalog is classified, or the vocabulary is decoration."""

    def test_every_catalogued_package_is_classified(self) -> None:
        for manifest in load_catalog(Path("catalog")):
            self.assertTrue(manifest.about, f"{manifest.id} has no longer description")
            self.assertTrue(manifest.capabilities, f"{manifest.id} says nothing about what it does")
            self.assertTrue(manifest.use_cases, f"{manifest.id} says nothing about when to use it")
            self.assertTrue(manifest.evidence, f"{manifest.id} says nothing about what it reads")

    def test_the_axes_actually_discriminate(self) -> None:
        # If every package carried the same terms the classification would be
        # decoration. Two packages sharing every axis is the warning sign.
        packages = load_catalog(Path("catalog"))
        signatures = {(p.capabilities, p.use_cases, p.evidence) for p in packages}
        self.assertEqual(len(signatures), len(packages), "two packages are classified identically")




class VocabularyFeedTests(unittest.TestCase):
    """An interface must not carry its own copy of the vocabulary."""

    def test_the_feed_carries_every_term(self) -> None:
        from dfpm.classification import vocabulary

        published = vocabulary()
        self.assertEqual(set(published), set(VOCABULARIES))
        for field, terms in published.items():
            self.assertEqual([t["key"] for t in terms], list(VOCABULARIES[field]))
            self.assertTrue(all(t["label"] for t in terms))

    def test_disciplines_with_no_packages_are_still_offered(self) -> None:
        # A filter that appears only once something is catalogued under it means
        # the buttons on a page change shape as the catalog grows.
        from dfpm.classification import vocabulary

        offered = {term["key"] for term in vocabulary()["disciplines"]}
        catalogued = {key for manifest in load_catalog(Path("catalog")) for key in manifest.disciplines}
        self.assertTrue(offered - catalogued, "every discipline already has a package, so this proves nothing")
        self.assertTrue(catalogued <= offered)


if __name__ == "__main__":
    unittest.main()

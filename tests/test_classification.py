from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dfpm.classification import ARTIFACTS, SOLVES, matching_keys
from dfpm.errors import ManifestError
from dfpm.manifest import Manifest
from tests.helpers import create_package


class VocabularyTests(unittest.TestCase):
    """A closed vocabulary is the point: free tags fragment on the first synonym."""

    def test_the_two_axes_do_not_overlap(self) -> None:
        # What you are trying to find out and what you are looking at are
        # different questions, and a key belonging to both would blur them.
        self.assertEqual(set(SOLVES) & set(ARTIFACTS), set())

    def test_every_term_is_reachable_by_its_own_key(self) -> None:
        for vocabulary in (SOLVES, ARTIFACTS):
            for key, term in vocabulary.items():
                self.assertEqual(term.key, key)
                self.assertIn(key, matching_keys(vocabulary, key.replace("-", " ")))

    def test_people_find_things_by_the_words_they_use(self) -> None:
        self.assertIn("windows-event-log", matching_keys(ARTIFACTS, "evtx"))
        self.assertIn("windows-event-log", matching_keys(ARTIFACTS, "event log"))
        self.assertIn("mft", matching_keys(ARTIFACTS, "master file table"))
        self.assertIn("mft", matching_keys(ARTIFACTS, "ntfs"))
        self.assertIn("onedrive", matching_keys(ARTIFACTS, "sync log"))
        self.assertIn("memory-image", matching_keys(ARTIFACTS, "ram dump"))
        self.assertIn("malware-identification", matching_keys(SOLVES, "malware"))
        self.assertIn("deleted-file-recovery", matching_keys(SOLVES, "carving"))

    def test_a_tool_or_format_name_is_never_a_concept_alias(self) -> None:
        # Putting "sigma" on threat hunting would make every hunting tool answer
        # to a search for one rule language. Those names belong on the package.
        for name in ("sigma", "yara", "volatility", "plaso", "onedrive"):
            self.assertEqual(matching_keys(SOLVES, name), set(), f"{name!r} leaked into a solves alias")

    def test_an_empty_query_matches_nothing(self) -> None:
        self.assertEqual(matching_keys(SOLVES, "   "), set())


class ManifestClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def load(self, **fields) -> Manifest:
        _, manifest_path = create_package(self.base)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data.update(fields)
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        return Manifest.load(manifest_path)

    def test_a_classified_package_is_read(self) -> None:
        manifest = self.load(
            about="A longer plain-English explanation of what this is for.",
            solves=["malware-identification", "threat-hunting"],
            artifacts=["file-contents"],
        )
        self.assertEqual(manifest.solves, ("malware-identification", "threat-hunting"))
        self.assertEqual(manifest.artifacts, ("file-contents",))
        self.assertTrue(manifest.about.startswith("A longer"))

    def test_classification_is_optional(self) -> None:
        _, manifest_path = create_package(self.base)
        manifest = Manifest.load(manifest_path)
        self.assertEqual((manifest.solves, manifest.artifacts, manifest.about), ((), (), None))

    def test_an_invented_term_is_rejected(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            self.load(solves=["vibes"])
        self.assertIn("does not recognise", str(caught.exception))

    def test_a_term_from_the_wrong_axis_is_rejected(self) -> None:
        with self.assertRaises(ManifestError):
            self.load(solves=["windows-event-log"])
        with self.assertRaises(ManifestError):
            self.load(artifacts=["threat-hunting"])

    def test_a_repeated_term_is_rejected(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            self.load(artifacts=["registry", "registry"])
        self.assertIn("twice", str(caught.exception))

    def test_it_must_be_a_list_of_strings(self) -> None:
        with self.assertRaises(ManifestError):
            self.load(solves="malware-identification")


class CataloguedPackageTests(unittest.TestCase):
    """The shipped catalog is classified, or the vocabulary is decoration."""

    def test_every_catalogued_package_is_classified(self) -> None:
        from dfpm.catalog import load_catalog

        for manifest in load_catalog(Path("catalog")):
            self.assertTrue(manifest.about, f"{manifest.id} has no longer description")
            self.assertTrue(manifest.solves, f"{manifest.id} says nothing about what it solves")
            self.assertTrue(manifest.artifacts, f"{manifest.id} says nothing about what it reads")


if __name__ == "__main__":
    unittest.main()

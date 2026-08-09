from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from dfpm.errors import DfpmError
from dfpm.gui import create_server
from dfpm.storage import Storage
from tests.helpers import create_package


class GuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.catalog, _ = create_package(self.base)
        self.storage = Storage(self.base / "dfpm-data")
        self.server, self.session = create_server(self.storage, self.catalog, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)

    def fetch(
        self,
        path: str,
        *,
        body: dict | None = None,
        token: bool = True,
        host: str | None = None,
        origin: str | None = None,
        content_type: str | None = "application/json",
    ) -> tuple[int, bytes]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data)
        request.add_header("Host", host or f"127.0.0.1:{self.port}")
        if token:
            request.add_header("x-dfpm-token", self.session.token)
        if data is not None and content_type is not None:
            request.add_header("Content-Type", content_type)
        if origin is not None:
            request.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read()

    def api(self, path: str, **kwargs) -> tuple[int, dict]:
        status, raw = self.fetch(path, **kwargs)
        return status, json.loads(raw or b"{}")

    def classify(self, **axes: list[str]) -> None:
        """Give the synthetic package a classification, as a catalogued tool has."""
        path = self.catalog / "example.tool.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(axes)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_serves_the_interface_with_the_session_token_substituted(self) -> None:
        status, raw = self.fetch("/", token=False)
        page = raw.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn(self.session.token, page)
        self.assertNotIn("__dfpm_token__", page)

    def test_api_requires_the_session_token(self) -> None:
        status, payload = self.api("/api/state", token=False)
        self.assertEqual(status, 403)
        self.assertIn("token", payload["error"].lower())

    def test_api_rejects_a_foreign_origin(self) -> None:
        status, payload = self.api("/api/state", origin="http://evil.example")
        self.assertEqual(status, 403)
        self.assertIn("origin", payload["error"].lower())

    def test_api_rejects_an_unexpected_host_header(self) -> None:
        status, _ = self.api("/api/state", host="dfpm.evil.example")
        self.assertEqual(status, 403)

    def test_changes_require_a_json_content_type(self) -> None:
        status, payload = self.api("/api/install", body={"package": "example.tool"}, content_type="text/plain")
        self.assertEqual(status, 400)
        self.assertIn("application/json", payload["error"])

    def test_unknown_endpoints_are_not_found(self) -> None:
        self.assertEqual(self.api("/api/nonsense")[0], 404)
        self.assertEqual(self.fetch("/../../secrets.txt", token=False)[0], 404)

    def test_state_reports_catalog_paths_and_packages(self) -> None:
        status, payload = self.api("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(payload["packages"], [])
        self.assertEqual([item["id"] for item in payload["catalog"]], ["example.tool"])
        self.assertIsNone(payload["catalogError"])
        self.assertEqual(payload["paths"]["root"], str(self.storage.root))

    def test_state_carries_the_vocabulary_the_interface_filters_by(self) -> None:
        # The interface offers every discipline, including ones nothing is
        # catalogued under, so it has to be told them rather than deducing the
        # list from whatever happens to be installed.
        from dfpm.classification import vocabulary

        _, payload = self.api("/api/state")
        self.assertEqual(payload["vocabulary"], vocabulary())
        self.assertTrue(payload["vocabulary"]["disciplines"])

    def test_an_installed_package_carries_what_the_interface_shows(self) -> None:
        self.api("/api/install", body={"package": "example.tool"})
        _, payload = self.api("/api/state")
        package = payload["packages"][0]

        # What somebody looking at an installed tool would act on.
        self.assertEqual(package["description"], "A synthetic package used to verify dfpm safely.")
        self.assertEqual(package["location"], str(self.storage.package_version("example.tool", "1.0.0")))
        # Formatted server-side, so it reads the same as the command line does.
        from dfpm.archive import human_size
        from dfpm.inventory import read_package

        recorded = read_package(self.storage, "example.tool")["installed_size"]
        self.assertEqual(package["installedSize"], human_size(recorded))
        self.assertEqual(package["entrypoints"], ["example-tool"])

    def test_an_installed_package_is_classified_like_a_catalog_entry(self) -> None:
        # Both lists are searched by one function, so they have to hold the same
        # shape. The install record stores plain keys; the interface is handed
        # the labels too, exactly as a catalog entry carries them.
        from dfpm.classification import VOCABULARIES

        self.classify(disciplines=["windows-forensics"], evidence=["files"])
        self.api("/api/install", body={"package": "example.tool"})
        _, payload = self.api("/api/state")
        package, entry = payload["packages"][0], payload["catalog"][0]

        for axis in VOCABULARIES:
            with self.subTest(axis=axis):
                self.assertEqual(package.get(axis, []), entry.get(axis, []))
        self.assertTrue(any(package.get(axis) for axis in VOCABULARIES), "the synthetic package is classified")

    def test_the_file_count_is_not_sent_to_the_interface(self) -> None:
        # It exists so the installer can refuse an archive that does not match
        # its manifest. Nobody reading a list of installed tools acts on it.
        self.api("/api/install", body={"package": "example.tool"})
        _, payload = self.api("/api/state")
        self.assertNotIn("files", payload["packages"][0])

    def test_install_update_and_uninstall_through_the_api(self) -> None:
        status, payload = self.api("/api/install/plan", body={"package": "example.tool"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["plan"]["version"], "1.0.0")
        self.assertEqual(len(payload["plan"]["sha256"]), 64)

        self.assertEqual(self.api("/api/install", body={"package": "example.tool"})[0], 200)
        _, state = self.api("/api/state")
        self.assertEqual(state["packages"][0]["version"], "1.0.0")
        self.assertEqual(state["findings"][0]["status"], "passing")

        create_package(self.base, version="1.1.0")
        status, payload = self.api("/api/install", body={"package": "example.tool", "version": "1.1.0"})
        self.assertEqual(status, 200)
        self.assertIn("replacing 1.0.0", payload["message"])
        _, state = self.api("/api/state")
        self.assertEqual(state["packages"][0]["version"], "1.1.0")

        status, payload = self.api("/api/uninstall/plan", body={"package": "example.tool"})
        self.assertEqual(payload["plan"]["version"], "1.1.0")
        self.assertEqual(self.api("/api/uninstall", body={"package": "example.tool"})[0], 200)
        _, state = self.api("/api/state")
        self.assertEqual(state["packages"], [])

    def test_reports_failures_as_readable_messages(self) -> None:
        status, payload = self.api("/api/install", body={"package": "missing.tool"})
        self.assertEqual(status, 400)
        self.assertIn("not found in catalog", payload["error"])

        status, payload = self.api("/api/uninstall", body={"package": "example.tool"})
        self.assertEqual(status, 400)
        self.assertIn("is not installed", payload["error"])

        status, payload = self.api("/api/uninstall", body={})
        self.assertEqual(status, 400)
        self.assertIn("'package' is required", payload["error"])

    def test_refuses_to_bind_a_non_loopback_address(self) -> None:
        with self.assertRaises(DfpmError) as caught:
            create_server(self.storage, self.catalog, host="0.0.0.0", port=0)
        self.assertIn("loopback", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

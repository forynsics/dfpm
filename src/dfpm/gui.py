from __future__ import annotations

import json
import secrets
import threading
import traceback
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import removal
from .catalog import describe, load_catalog, resolve
from .classification import vocabulary
from .doctor import inspect
from .errors import DfpmError
from .installer import check_destination, check_platform, install
from .inventory import list_packages
from .manifest import Manifest
from .storage import Storage

ASSET_DIRECTORY = Path(__file__).resolve().parent / "web"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/refinements.css": ("refinements.css", "text/css; charset=utf-8"),
    "/local.css": ("local.css", "text/css; charset=utf-8"),
    "/brix-sleeping.png": ("brix-sleeping.png", "image/png"),
}
SHARED_STYLESHEETS = ("styles.css", "refinements.css")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
TOKEN_PLACEHOLDER = b"__dfpm_token__"
MAX_BODY_BYTES = 64 * 1024


@dataclass
class Session:
    """Everything one running interface needs, including the secret that authorizes it."""

    storage: Storage
    catalog: Path
    token: str
    hosts: frozenset[str] = frozenset()
    origins: frozenset[str] = frozenset()
    lock: threading.Lock = field(default_factory=threading.Lock)


def create_server(
    storage: Storage,
    catalog: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
) -> tuple[ThreadingHTTPServer, Session]:
    """Bind a loopback server and mint the session token that authorizes requests to it."""
    if host not in LOOPBACK_HOSTS:
        raise DfpmError(
            f"The interface only binds loopback addresses ({', '.join(sorted(LOOPBACK_HOSTS))}), "
            f"because it can install and remove software. Refusing to bind {host}."
        )
    session = Session(storage=storage, catalog=catalog, token=secrets.token_urlsafe(32))
    server = ThreadingHTTPServer((host, port), partial(Handler, session=session))
    bound = server.server_address[1]
    session.hosts = frozenset({f"127.0.0.1:{bound}", f"localhost:{bound}", f"[::1]:{bound}"})
    session.origins = frozenset(f"http://{item}" for item in session.hosts)
    return server, session


def serve(
    storage: Storage,
    catalog: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> int:
    """Run the local management interface until interrupted."""
    server, _ = create_server(storage, catalog, host=host, port=port)
    bound = server.server_address[1]

    url = f"http://{host}:{bound}/"
    print(f"dfpm local interface: {url}")
    print(f"Managing:             {storage.root}")
    print(f"Catalog:              {catalog}")
    print("This interface listens on loopback only. Press Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


class Handler(BaseHTTPRequestHandler):
    server_version = "dfpm"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def __init__(self, *args: Any, session: Session, **kwargs: Any) -> None:
        self.session = session
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature is fixed by the base class
        return

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        denied = self._guard_origin()
        if denied:
            return self._error(HTTPStatus.FORBIDDEN, denied)
        if path.startswith("/api/"):
            denied = self._guard_token()
            if denied:
                return self._error(HTTPStatus.FORBIDDEN, denied)
            if path == "/api/state":
                return self._json(HTTPStatus.OK, self._state())
            return self._error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        if path in ASSETS:
            return self._asset(path)
        return self._error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        denied = self._guard_origin() or self._guard_token()
        if denied:
            return self._error(HTTPStatus.FORBIDDEN, denied)
        action = ACTIONS.get(path)
        if action is None:
            return self._error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        try:
            payload = self._body()
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))

        changes = path not in PREVIEW_ENDPOINTS
        if changes and not self.session.lock.acquire(blocking=False):
            return self._error(HTTPStatus.CONFLICT, "Another operation is already running.")
        try:
            result = action(self.session, payload)
        except DfpmError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception:
            traceback.print_exc()
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "The operation failed unexpectedly. See the dfpm console.")
        finally:
            if changes:
                self.session.lock.release()
        return self._json(HTTPStatus.OK, result)

    def _guard_origin(self) -> str | None:
        """Reject anything not addressed to this interface, which blocks DNS rebinding."""
        if self.headers.get("Host", "") not in self.session.hosts:
            return "This request was not addressed to the local dfpm interface."
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self.session.origins:
            return "Requests from another origin are not allowed."
        return None

    def _guard_token(self) -> str | None:
        token = self.headers.get("x-dfpm-token", "")
        if not secrets.compare_digest(token, self.session.token):
            return "Missing or invalid session token."
        return None

    def _body(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise ValueError("Requests must be sent as application/json.")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length is not a number.") from exc
        if size < 0 or size > MAX_BODY_BYTES:
            raise ValueError("Request body is too large.")
        if size == 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(size))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Request body is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def _state(self) -> dict[str, Any]:
        storage = self.session.storage
        catalog: list[dict[str, Any]] = []
        catalog_error: str | None = None
        try:
            catalog = [describe(manifest) for manifest in load_catalog(self.session.catalog)]
        except DfpmError as exc:
            catalog_error = str(exc)
        return {
            "paths": {
                "root": str(storage.root),
                "tools": str(storage.tools),
                "cache": str(storage.cache),
                "bin": str(storage.bin),
                "state": str(storage.state / "packages"),
                "catalog": str(self.session.catalog),
            },
            "packages": [_summarize(package) for package in list_packages(storage)],
            "catalog": catalog,
            "catalogError": catalog_error,
            # Sent alongside the packages for the same reason the command line
            # prints it: an interface offering disciplines to filter by should
            # read the list rather than keep a copy that drifts, and that
            # includes the ones nothing is catalogued under yet.
            "vocabulary": vocabulary(),
            "findings": [vars(finding) for finding in inspect(storage)],
        }

    def _asset(self, path: str) -> None:
        name, content_type = ASSETS[path]
        try:
            body = (ASSET_DIRECTORY / name).read_bytes()
        except OSError:
            return self._error(HTTPStatus.NOT_FOUND, f"Interface asset is missing: {name}")
        if name == "index.html":
            body = body.replace(TOKEN_PLACEHOLDER, self.session.token.encode("ascii"))
        return self._respond(HTTPStatus.OK, content_type, body)

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._respond(status, "application/json; charset=utf-8", body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json(status, {"error": message})

    def _respond(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)


def _summarize(package: dict[str, Any]) -> dict[str, Any]:
    """Trim a package record for the interface, leaving out per-file detail."""
    return {
        "id": package["id"],
        "name": package.get("name", package["id"]),
        "kind": package.get("kind"),
        "version": package.get("version"),
        "installedAt": package.get("installed_at"),
        "files": package.get("file_count"),
        "platform": package.get("platform"),
        "project": package.get("project"),
        "entrypoints": [item["name"] for item in package.get("entrypoints", [])],
    }


def _require(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DfpmError(f"'{key}' is required.")
    return value.strip()


def _replaced(storage: Storage, package_id: str, previous: str | None) -> dict[str, Any] | None:
    """Describe the version being replaced, whose folder the install deletes."""
    if not previous:
        return None
    outgoing = removal.plan(storage, package_id)
    return {
        "version": previous,
        "root": str(outgoing.root),
        "files": outgoing.file_count,
        "size": outgoing.total_size,
        "installedFiles": outgoing.installed_count,
        "grew": outgoing.grew,
    }


def _install_plan(manifest: Manifest, storage: Storage, previous: str | None = None) -> dict[str, Any]:
    return {
        "replaces": _replaced(storage, manifest.id, previous),
        "package": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "platform": str(manifest.platform) if manifest.platform else None,
        "license": manifest.project.license if manifest.project else None,
        "project": manifest.project.repository if manifest.project else None,
        "source": manifest.package_url(),
        "sha256": manifest.package.sha256,
        "size": manifest.package.size,
        "extractedSize": manifest.extracted_size,
        "entries": manifest.entry_count,
        "termsUrl": manifest.project.terms_url if manifest.project else None,
        "destination": str(storage.package_version(manifest.id, manifest.version)),
    }


def _resolve(session: Session, payload: dict[str, Any]) -> Manifest:
    version = payload.get("version")
    return resolve(session.catalog, _require(payload, "package"), version if version else None)


def _plan_install(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    manifest = _resolve(session, payload)
    check_platform(manifest)
    previous = check_destination(manifest, session.storage)
    return {"plan": _install_plan(manifest, session.storage, previous)}


def _do_install(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    manifest = _resolve(session, payload)
    terms = manifest.project.terms_url if manifest.project else None
    if terms and payload.get("acceptTerms") is not True:
        # Same rule the command line applies: confirming the plan is not the same
        # as asserting that restricted terms permit this particular user.
        raise DfpmError(
            f"{manifest.name} {manifest.version} is distributed under terms restricting who may use it. "
            f"Review {terms} and confirm they permit your use."
        )
    previous = check_destination(manifest, session.storage)
    destination = install(manifest, session.storage)
    replaced = f", replacing {previous}" if previous else ""
    return {"message": f"Installed {manifest.name} {manifest.version}{replaced}", "destination": str(destination)}


def _plan_uninstall(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    plan = removal.plan(session.storage, _require(payload, "package"))
    return {
        "plan": {
            "package": plan.package,
            "name": plan.name,
            "version": plan.version,
            "root": str(plan.root),
            "files": plan.file_count,
            "size": plan.total_size,
            "installedFiles": plan.installed_count,
            "grew": plan.grew,
            "commands": list(plan.commands),
        }
    }


def _do_uninstall(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    plan = removal.plan(session.storage, _require(payload, "package"))
    removal.execute(session.storage, plan)
    return {"message": f"Removed {plan.package} {plan.version}"}


Action = Callable[[Session, dict[str, Any]], dict[str, Any]]
ACTIONS: dict[str, Action] = {
    "/api/install/plan": _plan_install,
    "/api/install": _do_install,
    "/api/uninstall/plan": _plan_uninstall,
    "/api/uninstall": _do_uninstall,
}
PREVIEW_ENDPOINTS = frozenset({"/api/install/plan", "/api/uninstall/plan"})

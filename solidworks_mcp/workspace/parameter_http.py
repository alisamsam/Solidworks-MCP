"""Loopback-only browser access to the shared parameter register."""

from __future__ import annotations

import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .parameter_store import Conflict, ParameterStore, ValidationError


UI_PATH = Path(__file__).with_name("parameter_ui.html")
JS_PATH = Path(__file__).with_name("parameter_ui.js")
CSS_PATH = Path(__file__).with_name("parameter_ui.css")
STATE_PATH = Path(__file__).with_name("parameter_ui_state.js")


def create_server(store: ParameterStore, *, port: int = 0):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            pass  # The one-time URL contains a session token.

        def _reply(self, status, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self, *, page=False):
            host = self.headers.get("Host", "")
            expected = f"127.0.0.1:{self.server.server_port}"
            if host != expected:
                self._reply(403, {"error": "Dostop je dovoljen samo lokalno."})
                return False
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{expected}":
                self._reply(403, {"error": "Izvor zahteve ni dovoljen."})
                return False
            if page:
                supplied = urlsplit(self.path).query.removeprefix("token=")
            else:
                auth = self.headers.get("Authorization", "")
                supplied = auth[7:] if auth.startswith("Bearer ") else ""
            if not hmac.compare_digest(supplied, token):
                self._reply(401, {"error": "Neveljavna lokalna seja."})
                return False
            return True

        def _data(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 65536 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValidationError("Neveljaven ali prevelik JSON zahtevek.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValidationError("Zahtevek mora biti objekt.")
            return data

        def _run(self, method):
            path = urlsplit(self.path).path
            if path == "/" and method == "GET":
                if not self._authorized(page=True):
                    return
                return self._reply(200, UI_PATH.read_bytes().replace(b"{{TOKEN}}", token.encode()),
                                   "text/html; charset=utf-8")
            if path in {"/app.js", "/app.css", "/state.js"} and method == "GET":
                if not self._authorized(page=True):
                    return
                asset = {"/app.js": JS_PATH, "/app.css": CSS_PATH, "/state.js": STATE_PATH}[path]
                content_type = "text/css; charset=utf-8" if path == "/app.css" else "text/javascript; charset=utf-8"
                return self._reply(200, asset.read_bytes(), content_type)
            if path != "/api" and not path.startswith("/api/"):
                return self._reply(404, {"error": "Stran ne obstaja."})
            if not self._authorized():
                return
            try:
                parts = [part for part in path.split("/") if part]
                if method == "GET" and parts == ["api", "projects"]:
                    result = store.list_projects()
                elif method == "POST" and parts == ["api", "projects"]:
                    data = self._data()
                    result = (store.create_stair_railing_project(data.get("name"))
                              if data.get("template") == "stairs_railing" else
                              store.create_project(data.get("name")))
                elif len(parts) >= 3 and parts[:2] == ["api", "projects"]:
                    project_id = parts[2]
                    if method == "GET" and len(parts) == 3:
                        result = store.snapshot(project_id)
                    elif method == "GET" and len(parts) == 4 and parts[3] == "export":
                        result = store.snapshot(project_id)
                    elif method == "POST" and len(parts) == 4:
                        data = self._data()
                        revision = data.get("expected_revision")
                        if parts[3] == "owners":
                            result = store.add_owner(project_id, data, revision)
                        elif parts[3] == "parameters":
                            result = store.add_parameter(project_id, data, revision)
                        elif parts[3] == "drafts":
                            result = store.set_draft(project_id, data.get("parameter_id"), data.get("value"), revision)
                        elif parts[3] == "discard-draft":
                            result = store.discard_draft(project_id, data.get("parameter_id"), revision)
                        elif parts[3] == "requests":
                            result = store.add_request(project_id, data.get("text"), data.get("owner_id"), revision)
                        elif parts[3] == "request-status":
                            result = store.update_request(project_id, data.get("request_id"), data.get("status"), revision)
                        elif parts[3] == "cad-jobs":
                            result = store.queue_cad_job(project_id, revision)
                        elif parts[3] == "cancel-cad-job":
                            result = store.cancel_cad_job(project_id, data.get("job_id"), revision)
                        else:
                            return self._reply(404, {"error": "Operacija ne obstaja."})
                    else:
                        return self._reply(405, {"error": "Metoda ni dovoljena."})
                else:
                    return self._reply(404, {"error": "Operacija ne obstaja."})
                self._reply(200, result)
            except Conflict as error:
                self._reply(409, {"error": str(error), "code": "REVISION_CONFLICT"})
            except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as error:
                self._reply(400, {"error": str(error), "code": "VALIDATION_FAILED"})

        def do_GET(self):
            self._run("GET")

        def do_POST(self):
            self._run("POST")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server, token

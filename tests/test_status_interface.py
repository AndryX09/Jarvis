import asyncio
import base64
import hashlib
import hmac
import importlib
import json
import os
import socket
import subprocess
import struct
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "app" / "server.py"


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_listener(process: subprocess.Popen[str], port: int) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=2)
            raise AssertionError(
                f"HTTP server exited early ({process.returncode}).\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("HTTP server did not listen within 15 seconds")


@contextmanager
def _running_http_server(
    web_note_scope: str = "none",
    password: str = "demo-password",
    extra_regular_notes: int = 0,
    include_late_panorama: bool = False,
    dashboard_enabled: bool = False,
    dashboard_trusted_proxy: bool = False,
    dashboard_trusted_proxy_peer: str | None = None,
    http_mcp_enabled: bool = False,
):
    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        vault = temporary_root / "vault"
        state = temporary_root / "state"
        vault.mkdir()
        state.mkdir()
        (vault / "Idea.md").write_text("# Idea\n", encoding="utf-8")
        password_file = temporary_root / "web-note-password"
        totp_secret_file = temporary_root / "dashboard-totp-secret"
        mcp_token_file = temporary_root / "mcp-token"
        if http_mcp_enabled:
            mcp_token_file.write_text("A" * 43, encoding="ascii")
        if dashboard_enabled:
            totp_secret_file.write_text(
                "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ\n",
                encoding="ascii",
            )
            (state / "audit.jsonl").write_text(
                json.dumps(
                    {
                        "event_id": "event-1",
                        "timestamp_utc": "2026-08-06T12:00:00Z",
                        "action": "capture_material",
                        "path": "Private/Secret.md",
                        "title": "Private title",
                        "summary": "Private summary",
                        "sha256": "not-for-the-dashboard",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        if web_note_scope != "none":
            (vault / "00 — Panoramica.md").write_text(
                "# Panoramica principale\n", encoding="utf-8"
            )
            project = vault / "Progetti" / "Jarvis"
            project.mkdir(parents=True)
            (project / "00 — Panoramica.md").write_text(
                "# Panoramica Jarvis\nContenuto protetto.\n", encoding="utf-8"
            )
            if extra_regular_notes:
                bulk = vault / "Bulk"
                bulk.mkdir()
                for index in range(extra_regular_notes):
                    (bulk / f"Nota {index:04d}.md").write_text(
                        f"# Nota {index}\n", encoding="utf-8"
                    )
            if include_late_panorama:
                late = vault / "Zzz"
                late.mkdir()
                (late / "00 — Panoramica.md").write_text(
                    "# Panoramica tardiva\n", encoding="utf-8"
                )
            password_file.write_text(password + "\n", encoding="utf-8")
        port = _unused_loopback_port()
        env = os.environ.copy()
        env.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "VAULT_ROOT": str(vault),
                "STATE_ROOT": str(state),
                "JARVIS_TRANSPORT": "streamable-http",
                "JARVIS_HTTP_HOST": "127.0.0.1",
                "JARVIS_HTTP_PORT": str(port),
                "JARVIS_HTTP_ALLOWED_HOSTS": "127.0.0.1:*",
                "JARVIS_HTTP_ALLOWED_ORIGINS": "http://127.0.0.1:*",
                "JARVIS_HTTP_MCP_ENABLED": "true" if http_mcp_enabled else "false",
            }
        )
        if web_note_scope != "none":
            env.update(
                {
                    "JARVIS_WEB_NOTE_SCOPE": web_note_scope,
                    "JARVIS_WEB_NOTE_PASSWORD_FILE": str(password_file),
                }
            )
        if dashboard_enabled:
            env["JARVIS_DASHBOARD_TOTP_SECRET_FILE"] = str(totp_secret_file)
        if http_mcp_enabled:
            env["JARVIS_MCP_BEARER_TOKEN_FILE"] = str(mcp_token_file)
        if dashboard_trusted_proxy_peer is not None:
            env["JARVIS_DASHBOARD_TRUSTED_PROXY_PEERS"] = dashboard_trusted_proxy_peer
        elif dashboard_trusted_proxy:
            env["JARVIS_DASHBOARD_TRUSTED_PROXY_PEERS"] = "127.0.0.1"
        process = subprocess.Popen(
            [sys.executable, str(SERVER)],
            cwd=str(SERVER.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_for_listener(process, port)
            yield f"http://127.0.0.1:{port}"
        finally:
            process.terminate()
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)


def _basic_auth_header(password: str) -> dict[str, str]:
    credentials = base64.b64encode(f"jarvis:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {credentials}"}


def _current_totp_code(secret: bytes) -> str:
    counter = int(time.time()) // 30
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


class StatusInterfaceIntegrationTests(unittest.TestCase):
    def test_x_forwarded_for_cannot_impersonate_a_trusted_proxy(self):
        invalid_form = urllib.parse.urlencode({"code": "000000"}).encode("ascii")
        with _running_http_server(
            dashboard_enabled=True,
            dashboard_trusted_proxy_peer="198.51.100.20",
        ) as base_url:
            for index in range(5):
                request = urllib.request.Request(
                    f"{base_url}/login",
                    data=invalid_form,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-Forwarded-For": "198.51.100.20",
                        "CF-Connecting-IP": f"192.0.2.{index + 1}",
                    },
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(rejected.exception.code, 401)

            blocked = urllib.request.Request(
                f"{base_url}/login",
                data=invalid_form,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Forwarded-For": "198.51.100.20",
                    "CF-Connecting-IP": "192.0.2.99",
                },
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(blocked, timeout=5)

        self.assertEqual(rejected.exception.code, 429)

    def test_dashboard_reports_explicitly_enabled_http_mcp(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, file_pointer, code, message, headers, url):
                return None

        form = urllib.parse.urlencode(
            {"code": _current_totp_code(b"12345678901234567890")}
        ).encode("ascii")
        with _running_http_server(
            dashboard_enabled=True, http_mcp_enabled=True
        ) as base_url:
            login = urllib.request.Request(
                f"{base_url}/login",
                data=form,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            opener = urllib.request.build_opener(NoRedirect)
            with self.assertRaises(urllib.error.HTTPError) as accepted:
                opener.open(login, timeout=5)
            cookie = accepted.exception.headers["Set-Cookie"].split(";", 1)[0]
            status_request = urllib.request.Request(
                f"{base_url}/api/dashboard/status", headers={"Cookie": cookie}
            )
            with urllib.request.urlopen(status_request, timeout=5) as response:
                payload = json.load(response)

        self.assertTrue(payload["security"]["http_mcp_enabled"])

    def test_totp_code_cannot_be_reused_for_a_second_session(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, file_pointer, code, message, headers, url):
                return None

        form = urllib.parse.urlencode(
            {"code": _current_totp_code(b"12345678901234567890")}
        ).encode("ascii")
        with _running_http_server(dashboard_enabled=True) as base_url:
            opener = urllib.request.build_opener(NoRedirect)
            first = urllib.request.Request(
                f"{base_url}/login",
                data=form,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with self.assertRaises(urllib.error.HTTPError) as accepted:
                opener.open(first, timeout=5)
            second = urllib.request.Request(
                f"{base_url}/login",
                data=form,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with self.assertRaises(urllib.error.HTTPError) as replayed:
                opener.open(second, timeout=5)

        self.assertEqual(accepted.exception.code, 303)
        self.assertEqual(replayed.exception.code, 401)
        self.assertIsNone(replayed.exception.headers["Set-Cookie"])

    def test_totp_rate_limit_counts_malformed_login_requests(self):
        with _running_http_server(dashboard_enabled=True) as base_url:
            for _ in range(5):
                malformed = urllib.request.Request(
                    f"{base_url}/login",
                    data=b"invalid",
                    method="POST",
                    headers={"Content-Type": "text/plain"},
                )
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(malformed, timeout=5)
                self.assertEqual(denied.exception.code, 400)

            valid_form = urllib.parse.urlencode(
                {"code": _current_totp_code(b"12345678901234567890")}
            ).encode("ascii")
            blocked = urllib.request.Request(
                f"{base_url}/login",
                data=valid_form,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(blocked, timeout=5)

        self.assertEqual(denied.exception.code, 429)

    def test_totp_login_accepts_configured_same_origin(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, file_pointer, code, message, headers, url):
                return None

        code = _current_totp_code(b"12345678901234567890")
        form = urllib.parse.urlencode({"code": code}).encode("ascii")
        with _running_http_server(dashboard_enabled=True) as base_url:
            request = urllib.request.Request(
                f"{base_url}/login",
                data=form,
                method="POST",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": base_url,
                },
            )
            opener = urllib.request.build_opener(NoRedirect)
            with self.assertRaises(urllib.error.HTTPError) as redirected:
                opener.open(request, timeout=10)

        self.assertEqual(redirected.exception.code, 303)
        self.assertEqual(redirected.exception.headers["Location"], "/dashboard")

    def test_totp_rate_limit_separates_clients_from_explicitly_trusted_proxy(self):
        invalid_form = urllib.parse.urlencode({"code": "000000"}).encode("ascii")
        with _running_http_server(
            dashboard_enabled=True, dashboard_trusted_proxy=True
        ) as base_url:
            for _ in range(5):
                request = urllib.request.Request(
                    f"{base_url}/login",
                    data=invalid_form,
                    method="POST",
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "CF-Connecting-IP": "192.0.2.10",
                    },
                )
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(denied.exception.code, 401)

            other_client_request = urllib.request.Request(
                f"{base_url}/login",
                data=invalid_form,
                method="POST",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "CF-Connecting-IP": "192.0.2.11",
                },
            )
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(other_client_request, timeout=5)

        self.assertEqual(denied.exception.code, 401)

    def test_totp_login_rejects_oversized_body_before_reading_it(self):
        with _running_http_server(dashboard_enabled=True) as base_url:
            parsed = urllib.parse.urlsplit(base_url)
            with socket.create_connection((parsed.hostname, parsed.port), timeout=2) as client:
                client.settimeout(2)
                client.sendall(
                    (
                        "POST /login HTTP/1.1\r\n"
                        f"Host: {parsed.hostname}:{parsed.port}\r\n"
                        "Content-Type: application/x-www-form-urlencoded\r\n"
                        "Content-Length: 1000000\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode("ascii")
                )
                response = client.recv(4096)

        self.assertIn(b" 400 ", response.split(b"\r\n", 1)[0])

    def test_dashboard_logout_clears_session_cookie(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, file_pointer, code, message, headers, url):
                return None

        with _running_http_server(dashboard_enabled=True) as base_url:
            request = urllib.request.Request(
                f"{base_url}/logout",
                data=b"",
                headers={"Cookie": "__Host-jarvis_dashboard_session=placeholder"},
                method="POST",
            )
            opener = urllib.request.build_opener(NoRedirect)
            with self.assertRaises(urllib.error.HTTPError) as raised:
                opener.open(request, timeout=10)

        self.assertEqual(raised.exception.code, 303)
        self.assertEqual(raised.exception.headers["Location"], "/login")
        cookie = raised.exception.headers["Set-Cookie"]
        self.assertIn("__Host-jarvis_dashboard_session=", cookie)
        self.assertIn("Max-Age=0", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=strict", cookie)

    def test_totp_login_rate_limits_repeated_failures(self):
        invalid_form = urllib.parse.urlencode({"code": "000000"}).encode("ascii")
        with _running_http_server(dashboard_enabled=True) as base_url:
            for index in range(5):
                request = urllib.request.Request(
                    f"{base_url}/login",
                    data=invalid_form,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "CF-Connecting-IP": f"192.0.2.{index + 1}",
                    },
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=10)
                self.assertEqual(raised.exception.code, 401)

            blocked_request = urllib.request.Request(
                f"{base_url}/login",
                data=invalid_form,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "CF-Connecting-IP": "192.0.2.99",
                },
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as blocked:
                urllib.request.urlopen(blocked_request, timeout=10)

        self.assertEqual(blocked.exception.code, 429)
        self.assertEqual(blocked.exception.headers["Retry-After"], "300")
        self.assertIsNone(blocked.exception.headers["Set-Cookie"])

    def test_authenticated_dashboard_api_returns_only_allowlisted_metadata(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, file_pointer, code, message, headers, url):
                return None

        code = _current_totp_code(b"12345678901234567890")
        form = urllib.parse.urlencode({"code": code}).encode("ascii")
        with _running_http_server(dashboard_enabled=True) as base_url:
            login_request = urllib.request.Request(
                f"{base_url}/login",
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            opener = urllib.request.build_opener(NoRedirect)
            with self.assertRaises(urllib.error.HTTPError) as raised:
                opener.open(login_request, timeout=10)
            session_cookie = raised.exception.headers["Set-Cookie"].split(";", 1)[0]
            api_request = urllib.request.Request(
                f"{base_url}/api/dashboard/status",
                headers={"Cookie": session_cookie},
            )
            with urllib.request.urlopen(api_request, timeout=10) as response:
                dashboard_headers = response.headers
                payload = json.load(response)

        self.assertEqual(dashboard_headers["X-Frame-Options"], "DENY")
        self.assertEqual(dashboard_headers["Referrer-Policy"], "same-origin")
        self.assertIn("frame-ancestors 'none'", dashboard_headers["Content-Security-Policy"])
        self.assertEqual(
            set(payload["core"]),
            {
                "service",
                "version",
                "vault_mode",
                "note_count",
                "audit_event_count",
                "ingestion_available",
                "delete_tool_available",
                "network_required",
            },
        )
        self.assertEqual(
            set(payload["ingestion"]["captures"]),
            {"total", "pending", "ready", "processed", "skipped"},
        )
        self.assertEqual(payload["ingestion"]["captures"]["total"], 0)
        self.assertFalse(payload["security"]["http_mcp_enabled"])
        self.assertEqual(
            payload["activity"],
            [
                {
                    "action": "capture_material",
                    "timestamp_utc": "2026-08-06T12:00:00Z",
                }
            ],
        )
        serialized = json.dumps(payload)
        for forbidden in ("Private/Secret.md", "Private title", "Private summary", "sha256"):
            self.assertNotIn(forbidden, serialized)

    def test_authenticated_dashboard_serves_read_only_interface(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, file_pointer, code, message, headers, url):
                return None

        code = _current_totp_code(b"12345678901234567890")
        form = urllib.parse.urlencode({"code": code}).encode("ascii")
        with _running_http_server(dashboard_enabled=True) as base_url:
            login_request = urllib.request.Request(
                f"{base_url}/login",
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            opener = urllib.request.build_opener(NoRedirect)
            with self.assertRaises(urllib.error.HTTPError) as raised:
                opener.open(login_request, timeout=10)
            session_cookie = raised.exception.headers["Set-Cookie"].split(";", 1)[0]
            dashboard_request = urllib.request.Request(
                f"{base_url}/dashboard",
                headers={"Cookie": session_cookie},
            )
            with urllib.request.urlopen(dashboard_request, timeout=10) as response:
                html = response.read().decode("utf-8")

        self.assertIn("Processi Jarvis", html)
        self.assertIn("Sola lettura", html)
        self.assertIn('id="mcp-http-state"', html)
        self.assertIn("http_mcp_enabled", html)
        self.assertNotIn("<dd>Bloccato</dd>", html)
        self.assertNotIn("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", html)

    def test_valid_totp_login_sets_secure_session_cookie(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, file_pointer, code, message, headers, url):
                return None

        code = _current_totp_code(b"12345678901234567890")
        form = urllib.parse.urlencode({"code": code}).encode("ascii")
        with _running_http_server(dashboard_enabled=True) as base_url:
            request = urllib.request.Request(
                f"{base_url}/login",
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            opener = urllib.request.build_opener(NoRedirect)
            with self.assertRaises(urllib.error.HTTPError) as raised:
                opener.open(request, timeout=10)

        self.assertEqual(raised.exception.code, 303)
        self.assertEqual(raised.exception.headers["Location"], "/dashboard")
        cookie = raised.exception.headers["Set-Cookie"]
        self.assertIn("__Host-jarvis_dashboard_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn("Max-Age=28800", cookie)

    def test_enabled_dashboard_serves_totp_login_form_without_secret(self):
        with _running_http_server(dashboard_enabled=True) as base_url:
            with urllib.request.urlopen(f"{base_url}/login", timeout=10) as response:
                html = response.read().decode("utf-8")

        self.assertIn('action="/login"', html)
        self.assertIn('inputmode="numeric"', html)
        self.assertNotIn("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", html)

    def test_enabled_dashboard_redirects_anonymous_request_to_login(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, file_pointer, code, message, headers, url):
                return None

        with _running_http_server(dashboard_enabled=True) as base_url:
            opener = urllib.request.build_opener(NoRedirect)
            with self.assertRaises(urllib.error.HTTPError) as raised:
                opener.open(f"{base_url}/dashboard", timeout=10)

        self.assertEqual(raised.exception.code, 303)
        self.assertEqual(raised.exception.headers["Location"], "/login")

    def test_note_list_accepts_offsets_beyond_the_previous_ceiling(self):
        with _running_http_server("all-visible-markdown") as base_url:
            request = urllib.request.Request(
                f"{base_url}/api/notes?offset=1000500",
                headers=_basic_auth_header("demo-password"),
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.load(response)

        self.assertEqual(payload["offset"], 1_000_500)
        self.assertEqual(payload["notes"], [])
        self.assertIsNone(payload["next_offset"])

    def test_all_visible_scope_paginates_beyond_500_notes(self):
        with _running_http_server(
            "all-visible-markdown",
            extra_regular_notes=501,
            include_late_panorama=True,
        ) as base_url:
            headers = _basic_auth_header("demo-password")
            first_request = urllib.request.Request(
                f"{base_url}/api/notes", headers=headers
            )
            with urllib.request.urlopen(first_request, timeout=10) as response:
                first = json.load(response)

            second_request = urllib.request.Request(
                f"{base_url}/api/notes?offset=500", headers=headers
            )
            with urllib.request.urlopen(second_request, timeout=10) as response:
                second = json.load(response)

        first_paths = {note["path"] for note in first["notes"]}
        second_paths = {note["path"] for note in second["notes"]}
        self.assertEqual(len(first_paths), 500)
        self.assertEqual(first["page_size"], 500)
        self.assertEqual(first["offset"], 0)
        self.assertEqual(first["next_offset"], 500)
        self.assertEqual(second["offset"], 500)
        self.assertIsNone(second["next_offset"])
        self.assertTrue(first_paths.isdisjoint(second_paths))
        self.assertEqual(len(first_paths | second_paths), 505)
        self.assertIn("Zzz/00 — Panoramica.md", second_paths)

    def test_panorama_scope_filters_before_the_page_limit(self):
        with _running_http_server(
            "panoramas", extra_regular_notes=501, include_late_panorama=True
        ) as base_url:
            request = urllib.request.Request(
                f"{base_url}/api/notes", headers=_basic_auth_header("demo-password")
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.load(response)

        self.assertEqual(
            [note["path"] for note in payload["notes"]],
            [
                "00 — Panoramica.md",
                "Progetti/Jarvis/00 — Panoramica.md",
                "Zzz/00 — Panoramica.md",
            ],
        )
        self.assertIsNone(payload["next_offset"])

    def test_web_note_password_file_rejects_short_password(self):
        app_root = str(ROOT / "app")
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            vault = temporary_root / "vault"
            state = temporary_root / "state"
            vault.mkdir()
            state.mkdir()
            password_file = temporary_root / "password"
            password_file.write_text("short", encoding="utf-8")
            sys.modules.pop("server", None)
            sys.path.insert(0, app_root)
            try:
                with mock.patch.dict(
                    os.environ,
                    {
                        "VAULT_ROOT": str(vault),
                        "STATE_ROOT": str(state),
                        "JARVIS_WEB_NOTE_SCOPE": "none",
                        "JARVIS_WEB_NOTE_PASSWORD_FILE": "",
                    },
                ):
                    server_module = importlib.import_module("server")
                with self.assertRaisesRegex(ValueError, "at least 12 bytes"):
                    server_module._load_web_note_password(str(password_file))
            finally:
                sys.path.remove(app_root)
                sys.modules.pop("server", None)

    def test_all_visible_scope_still_rejects_hidden_non_markdown_and_traversal_paths(self):
        with _running_http_server("all-visible-markdown") as base_url:
            for path in ("../outside.md", ".hidden.md", "Folder/.hidden.md", "plain.txt", ""):
                query = urllib.parse.urlencode({"path": path})
                request = urllib.request.Request(
                    f"{base_url}/api/note?{query}",
                    headers=_basic_auth_header("demo-password"),
                )
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(denied.exception.code, 404)
                self.assertEqual(denied.exception.read(), b"Note not available")

    def test_note_routes_reject_untrusted_host_and_origin(self):
        with _running_http_server("panoramas") as base_url:
            paths = [
                "/notes",
                "/api/notes",
                "/api/note?" + urllib.parse.urlencode({"path": "00 — Panoramica.md"}),
            ]
            for path in paths:
                bad_host_headers = _basic_auth_header("demo-password")
                bad_host_headers["Host"] = "attacker.invalid"
                bad_host = urllib.request.Request(
                    f"{base_url}{path}", headers=bad_host_headers
                )
                with self.assertRaises(urllib.error.HTTPError) as host_error:
                    urllib.request.urlopen(bad_host, timeout=5)
                self.assertEqual(host_error.exception.code, 421)

                bad_origin_headers = _basic_auth_header("demo-password")
                bad_origin_headers["Origin"] = "https://attacker.invalid"
                bad_origin = urllib.request.Request(
                    f"{base_url}{path}", headers=bad_origin_headers
                )
                with self.assertRaises(urllib.error.HTTPError) as origin_error:
                    urllib.request.urlopen(bad_origin, timeout=5)
                self.assertEqual(origin_error.exception.code, 403)

    def test_all_visible_markdown_scope_exposes_every_visible_note(self):
        with _running_http_server("all-visible-markdown") as base_url:
            list_request = urllib.request.Request(
                f"{base_url}/api/notes", headers=_basic_auth_header("demo-password")
            )
            with urllib.request.urlopen(list_request, timeout=5) as response:
                payload = json.load(response)

            note_path = urllib.parse.urlencode({"path": "Idea.md"})
            note_request = urllib.request.Request(
                f"{base_url}/api/note?{note_path}",
                headers=_basic_auth_header("demo-password"),
            )
            with urllib.request.urlopen(note_request, timeout=5) as note_response:
                note = json.load(note_response)

        self.assertEqual(payload["scope"], "all-visible-markdown")
        self.assertEqual(
            {item["path"] for item in payload["notes"]},
            {
                "Idea.md",
                "00 — Panoramica.md",
                "Progetti/Jarvis/00 — Panoramica.md",
            },
        )
        self.assertEqual(note["path"], "Idea.md")

    def test_panorama_scope_reads_allowed_note_and_hides_other_notes(self):
        with _running_http_server("panoramas") as base_url:
            allowed_path = urllib.parse.urlencode(
                {"path": "Progetti/Jarvis/00 — Panoramica.md"}
            )
            allowed_request = urllib.request.Request(
                f"{base_url}/api/note?{allowed_path}",
                headers=_basic_auth_header("demo-password"),
            )
            with urllib.request.urlopen(allowed_request, timeout=5) as response:
                payload = json.load(response)

            denied_path = urllib.parse.urlencode({"path": "Idea.md"})
            denied_request = urllib.request.Request(
                f"{base_url}/api/note?{denied_path}",
                headers=_basic_auth_header("demo-password"),
            )
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(denied_request, timeout=5)

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["path"], "Progetti/Jarvis/00 — Panoramica.md")
        self.assertEqual(
            payload["content"].replace("\r\n", "\n"),
            "# Panoramica Jarvis\nContenuto protetto.\n",
        )
        self.assertEqual(denied.exception.code, 404)
        self.assertEqual(denied.exception.headers["Cache-Control"], "no-store")
        self.assertEqual(denied.exception.read(), b"Note not available")

    def test_panorama_scope_lists_only_panorama_notes(self):
        with _running_http_server("panoramas") as base_url:
            request = urllib.request.Request(
                f"{base_url}/api/notes", headers=_basic_auth_header("demo-password")
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.load(response)

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["scope"], "panoramas")
        self.assertEqual(
            [note["path"] for note in payload["notes"]],
            ["00 — Panoramica.md", "Progetti/Jarvis/00 — Panoramica.md"],
        )

    def test_note_apis_require_password(self):
        with _running_http_server("panoramas") as base_url:
            protected_urls = [
                f"{base_url}/api/notes",
                f"{base_url}/api/note?"
                + urllib.parse.urlencode({"path": "00 — Panoramica.md"}),
            ]
            for url in protected_urls:
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    urllib.request.urlopen(url, timeout=5)
                self.assertEqual(missing.exception.code, 401)
                self.assertIn("Basic", missing.exception.headers["WWW-Authenticate"])

    def test_notes_page_requires_the_configured_password(self):
        with _running_http_server("panoramas") as base_url:
            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(f"{base_url}/notes", timeout=5)
            self.assertEqual(missing.exception.code, 401)
            self.assertIn("Basic", missing.exception.headers["WWW-Authenticate"])

            wrong_request = urllib.request.Request(
                f"{base_url}/notes", headers=_basic_auth_header("wrong-password")
            )
            with self.assertRaises(urllib.error.HTTPError) as wrong:
                urllib.request.urlopen(wrong_request, timeout=5)
            self.assertEqual(wrong.exception.code, 401)

            valid_request = urllib.request.Request(
                f"{base_url}/notes", headers=_basic_auth_header("demo-password")
            )
            with urllib.request.urlopen(valid_request, timeout=5) as response:
                html = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Note consentite", html)
        self.assertIn("/api/notes", html)
        self.assertIn("next_offset", html)
        self.assertIn("offset=", html)

    def test_status_api_returns_live_jarvis_core_data(self):
        with _running_http_server() as base_url:
            with urllib.request.urlopen(f"{base_url}/api/status", timeout=5) as response:
                payload = json.load(response)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get_content_type(), "application/json")
        self.assertEqual(payload["service"], "Jarvis Core")
        self.assertEqual(payload["version"], "1.4.0")
        self.assertEqual(payload["note_count"], 1)
        self.assertTrue(payload["raw_material_is_preserved"])
        self.assertFalse(payload["delete_tool_available"])
        self.assertFalse(payload["web_note_reading_available"])
        self.assertFalse(payload["dashboard_available"])

    def test_status_api_reports_enabled_dashboard_without_exposing_secret(self):
        with _running_http_server(dashboard_enabled=True) as base_url:
            with urllib.request.urlopen(f"{base_url}/api/status", timeout=5) as response:
                payload = json.load(response)

        self.assertTrue(payload["dashboard_available"])
        self.assertNotIn("totp", json.dumps(payload).casefold())
        self.assertNotIn("secret", json.dumps(payload).casefold())

    def test_root_serves_status_page_that_reads_the_status_api(self):
        with _running_http_server() as base_url:
            with urllib.request.urlopen(f"{base_url}/", timeout=5) as response:
                html = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get_content_type(), "text/html")
        self.assertIn("Jarvis Core", html)
        self.assertIn("/api/status", html)
        self.assertIn('href="/notes"', html)
        self.assertIn("web_note_reading_available", html)
        self.assertIn('href="/dashboard"', html)
        self.assertIn("dashboard_available", html)
        self.assertIn('id="status-grid"', html)
        self.assertIn('id="connection-state"', html)

    def test_status_routes_reject_untrusted_host(self):
        with _running_http_server() as base_url:
            for path in ("/", "/api/status"):
                request = urllib.request.Request(
                    f"{base_url}{path}", headers={"Host": "attacker.invalid"}
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(raised.exception.code, 421)
                self.assertEqual(raised.exception.read(), b"Invalid Host header")

    def test_status_routes_reject_untrusted_origin(self):
        with _running_http_server() as base_url:
            for path in ("/", "/api/status"):
                request = urllib.request.Request(
                    f"{base_url}{path}", headers={"Origin": "https://attacker.invalid"}
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(raised.exception.code, 403)
                self.assertEqual(raised.exception.read(), b"Invalid Origin header")

    def test_status_api_hides_internal_error_details(self):
        app_root = str(ROOT / "app")
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            state = Path(temporary) / "state"
            vault.mkdir()
            state.mkdir()
            sys.modules.pop("server", None)
            sys.path.insert(0, app_root)
            try:
                with mock.patch.dict(
                    os.environ,
                    {"VAULT_ROOT": str(vault), "STATE_ROOT": str(state)},
                ):
                    server_module = importlib.import_module("server")
            finally:
                sys.path.remove(app_root)

        request = server_module.Request(
            {
                "type": "http",
                "headers": [(b"host", b"127.0.0.1:8000")],
            }
        )
        private_error = OSError(r"C:\private\vault\audit.jsonl is unavailable")
        with self.assertLogs(server_module.LOGGER, level="ERROR") as captured:
            with mock.patch.object(
                server_module, "get_vault_status", side_effect=private_error
            ):
                response = asyncio.run(server_module.status_api(request))

        self.assertIn("Unable to collect Jarvis status", captured.output[0])
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.body), {"error": "Jarvis status unavailable"}
        )
        self.assertNotIn(b"private", response.body)
        self.assertNotIn(b"audit.jsonl", response.body)


if __name__ == "__main__":
    unittest.main()

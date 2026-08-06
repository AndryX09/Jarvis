#!/usr/bin/env python3
import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from dashboard_page import load_dashboard_page_html  # noqa: E402


DEMO_STATUS = {
    "core": {
        "service": "Preview locale",
        "version": "UI",
        "vault_mode": "preview",
        "note_count": 42,
        "audit_event_count": 128,
        "ingestion_available": True,
        "delete_tool_available": False,
        "network_required": False,
    },
    "ingestion": {
        "captures": {
            "total": 24,
            "pending": 3,
            "ready": 5,
            "processed": 15,
            "skipped": 1,
        },
        "raw_material_is_preserved": True,
        "automatic_deletion_available": False,
    },
    "security": {
        "http_mcp_enabled": False,
        "dashboard_mode": "preview",
    },
    "activity": [
        {"action": "Anteprima interfaccia", "timestamp_utc": "dati demo"},
        {"action": "Nessun vault collegato", "timestamp_utc": "solo UI"},
    ],
}


WATCHER_COMMANDS = {
    "run-cycle",
    "pause",
    "resume",
    "retry-deferred",
    "retry-failed",
    "confirm",
    "cancel",
}


class WatcherPreviewState:
    def __init__(self):
        self._lock = threading.Lock()
        self._mode = "running"
        self._phase = "idle"
        self._cycle_count = 0
        self._pending_confirmation = None
        self._last_heartbeat_at = time.time()
        self._last_cycle = {
            "duration_ms": None,
            "found": 0,
            "processed": 0,
            "deferred": 0,
            "errors": 0,
        }
        self._events = [
            self._event("system", "Console watcher pronta — simulazione locale"),
            self._event("policy", "Policy deterministica caricata"),
            self._event("idle", "In attesa del prossimo ciclo"),
        ]

    @staticmethod
    def _event(kind: str, message: str) -> dict[str, str]:
        return {
            "time": time.strftime("%H:%M:%S"),
            "kind": kind,
            "message": message,
        }

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> dict[str, object]:
        now = time.time()
        if self._mode == "running":
            self._last_heartbeat_at = now
        heartbeat_age = max(0, int(now - self._last_heartbeat_at))
        phase_names = ["scan", "classify", "route", "write", "complete"]
        phase_steps = [
            {
                "name": name,
                "status": (
                    "complete"
                    if self._phase == "complete"
                    else "next" if name == "scan" and self._mode == "running" else "waiting"
                ),
            }
            for name in phase_names
        ]
        return {
            "available": True,
            "simulated": True,
            "mode": self._mode,
            "phase": self._phase,
            "cycle_count": self._cycle_count,
            "heartbeat": {
                "healthy": heartbeat_age < 20,
                "age_seconds": heartbeat_age,
                "last_at": time.strftime("%H:%M:%S", time.localtime(self._last_heartbeat_at)),
            },
            "next_cycle_seconds": 30 - (int(now) % 30) if self._mode == "running" else None,
            "last_cycle": dict(self._last_cycle),
            "backlog": {"pending": 3, "ready": 5},
            "phases": phase_steps,
            "pending_confirmation": self._pending_confirmation,
            "allowed_commands": sorted(WATCHER_COMMANDS),
            "events": [dict(event) for event in self._events],
        }

    def execute(self, command: str) -> dict[str, object]:
        if command not in WATCHER_COMMANDS:
            raise ValueError("unsupported watcher command")
        with self._lock:
            if command == "run-cycle":
                self._cycle_count += 1
                self._phase = "complete"
                self._last_heartbeat_at = time.time()
                has_demo_failure = self._cycle_count % 3 == 0
                self._last_cycle = {
                    "duration_ms": 480 + (self._cycle_count * 37),
                    "found": 4 if has_demo_failure else 3,
                    "processed": 2,
                    "deferred": 1,
                    "errors": 1 if has_demo_failure else 0,
                }
                self._events.extend(
                    [
                        self._event("cycle", f"Ciclo {self._cycle_count} avviato manualmente"),
                        self._event(
                            "scan",
                            f"{self._last_cycle['found']} elementi rilevati nella coda demo",
                        ),
                        self._event(
                            "policy",
                            "2 elaborati · 1 rinviato"
                            + (" · 1 errore demo" if has_demo_failure else ""),
                        ),
                        self._event("done", "Ciclo completato — nessuna mutazione reale"),
                    ]
                )
            elif command == "pause":
                self._mode = "paused"
                self._phase = "paused"
                self._events.append(self._event("paused", "Watcher messo in pausa"))
            elif command == "resume":
                self._mode = "running"
                self._phase = "idle"
                self._last_heartbeat_at = time.time()
                self._events.append(self._event("resumed", "Watcher ripreso"))
            elif command == "retry-deferred":
                self._pending_confirmation = command
                self._events.append(
                    self._event("confirm", "Retry dei rinviati in attesa di conferma")
                )
            elif command == "retry-failed":
                self._pending_confirmation = command
                self._events.append(
                    self._event("confirm", "Retry degli errori in attesa di conferma")
                )
            elif command == "confirm":
                if self._pending_confirmation not in {"retry-deferred", "retry-failed"}:
                    raise ValueError("no pending retry to confirm")
                counter = (
                    "deferred"
                    if self._pending_confirmation == "retry-deferred"
                    else "errors"
                )
                retried = int(self._last_cycle[counter])
                self._last_cycle["processed"] = int(self._last_cycle["processed"]) + retried
                self._last_cycle[counter] = 0
                self._pending_confirmation = None
                self._events.append(
                    self._event("retry", f"Retry simulato completato per {retried} elementi")
                )
            elif command == "cancel":
                if self._pending_confirmation is None:
                    raise ValueError("no pending action to cancel")
                self._pending_confirmation = None
                self._events.append(self._event("cancel", "Retry annullato"))
            self._events = self._events[-40:]
            return self._snapshot_unlocked()


def _handler(ui_file: Path):
    watcher = WatcherPreviewState()

    class PreviewHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path in {"/", "/dashboard"}:
                try:
                    body = load_dashboard_page_html(str(ui_file)).encode("utf-8")
                except (OSError, UnicodeError, ValueError) as exc:
                    self._send(str(exc).encode("utf-8"), 503, "text/plain; charset=utf-8")
                    return
                self._send(body, 200, "text/html; charset=utf-8")
                return
            if path == "/api/dashboard/status":
                status = dict(DEMO_STATUS)
                status["watcher"] = watcher.snapshot()
                body = json.dumps(status).encode("utf-8")
                self._send(body, 200, "application/json")
                return
            if path == "/login":
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
                return
            self._send(b"Not Found", 404, "text/plain; charset=utf-8")

        def do_POST(self):
            path = urlsplit(self.path).path
            if path == "/api/preview/watcher/command":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json({"error": "invalid content length"}, 400)
                    return
                if length < 1 or length > 1024:
                    self._send_json({"error": "invalid request size"}, 413)
                    return
                try:
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("invalid payload")
                    command = payload.get("command")
                    if not isinstance(command, str):
                        raise ValueError("invalid command")
                    state = watcher.execute(command)
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                    self._send_json({"error": str(exc)}, 400)
                    return
                self._send_json(
                    {"accepted_command": command, "watcher": state},
                    200,
                )
                return
            if path == "/logout":
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
                return
            self._send(b"Not Found", 404, "text/plain; charset=utf-8")

        def _send_json(self, payload: dict[str, object], status: int):
            self._send(
                json.dumps(payload).encode("utf-8"),
                status,
                "application/json",
            )

        def _send(self, body: bytes, status: int, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return PreviewHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview locale live della dashboard Jarvis")
    parser.add_argument(
        "--ui-file",
        type=Path,
        default=ROOT / "app" / "dashboard_ui" / "dashboard.html",
    )
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args()
    if args.port < 1 or args.port > 65535:
        parser.error("--port deve essere compresa tra 1 e 65535")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), _handler(args.ui_file))
    print(f"Preview dashboard: http://127.0.0.1:{args.port}", flush=True)
    print(f"File live: {args.ui_file.resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

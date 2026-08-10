from __future__ import annotations

import json
import logging
import os
import signal
import stat
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl.
    fcntl = None

try:
    import vault_core
    from watcher import VaultWatcher, WatchEvent, _fsync_directory
    from watcher_pipeline import ProcessResult, WatcherProcessor
    from watcher_rules import RULE_VERSION
except ModuleNotFoundError:  # Package imports used by the local test suite.
    from app import vault_core
    from app.watcher import VaultWatcher, WatchEvent, _fsync_directory
    from app.watcher_pipeline import ProcessResult, WatcherProcessor
    from app.watcher_rules import RULE_VERSION


LOGGER = logging.getLogger(__name__)
DEFAULT_INTERVAL_SECONDS = 1.0
MIN_INTERVAL_SECONDS = 0.1
MAX_INTERVAL_SECONDS = 60.0


def _utc_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class WatcherService:
    def __init__(self, vault_root: Path, state_root: Path):
        self._state_root = state_root.resolve(strict=True)
        self._status_path = self._state_root / "watcher-service-status.json"
        resolved_vault_root = vault_root.resolve(strict=True)
        if (
            resolved_vault_root == self._state_root
            or resolved_vault_root in self._state_root.parents
            or self._state_root in resolved_vault_root.parents
        ):
            raise ValueError("Watcher vault and state roots must not overlap.")
        self._lock_handle = self._acquire_service_lock()
        try:
            self._initialize(resolved_vault_root)
        except BaseException:
            self.close()
            raise

    def _initialize(self, vault_root: Path) -> None:
        self._watcher = VaultWatcher(vault_root, state_root=self._state_root)
        self._processor = WatcherProcessor(vault_root, self._state_root)
        previous_status = vault_core.watcher_status(self._state_root)
        self._status: dict[str, object] = {
            "service": "starting",
            "rule_version": RULE_VERSION,
            "started_utc": _utc_text(),
            "last_poll_utc": "",
            "events_processed": previous_status["events_processed"],
            "captures_created": previous_status["captures_created"],
            "review_required": previous_status["review_required"],
            "ignored": previous_status["ignored"],
            "errors": previous_status["errors"],
        }
        self._write_status()

    def run_cycle(self) -> list[ProcessResult]:
        results: list[ProcessResult] = []
        def process_event(event: WatchEvent) -> None:
            result = self._processor.process(event)
            results.append(result)
            self._increment("events_processed")
            if result.capture_created is True:
                self._increment("captures_created")
            if result.action == "review_required":
                self._increment("review_required")
            elif result.action == "ignore":
                self._increment("ignored")

        try:
            self._watcher.poll(on_event=process_event)
        except (OSError, UnicodeError, ValueError, vault_core.JarvisError) as exc:
            self._increment("errors")
            LOGGER.error(
                "Watcher event processing failed: %s",
                type(exc).__name__,
            )

        self._status["last_poll_utc"] = _utc_text()
        self._status["service"] = "running"
        self._write_status()
        return results

    def run_forever(
        self,
        stop_event: threading.Event,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        try:
            while not stop_event.is_set():
                try:
                    self.run_cycle()
                except (OSError, UnicodeError, ValueError, vault_core.JarvisError) as exc:
                    self._increment("errors")
                    self._status["last_poll_utc"] = _utc_text()
                    self._write_status()
                    LOGGER.error("Watcher cycle failed: %s", type(exc).__name__)
                stop_event.wait(interval_seconds)
        finally:
            self._status["service"] = "stopped"
            self._write_status()
            self.close()

    def _increment(self, key: str) -> None:
        self._status[key] = int(self._status[key]) + 1

    def _acquire_service_lock(self):
        if fcntl is None:
            return None
        lock_path = self._state_root / "watcher-service.lock"
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            if lock_path.is_symlink():
                raise ValueError("Watcher service lock path is invalid.") from exc
            raise
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or lock_path.is_symlink():
            os.close(descriptor)
            raise ValueError("Watcher service lock path is invalid.")
        handle = os.fdopen(descriptor, "a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise ValueError("Watcher service is already running.") from exc
        _fsync_directory(lock_path.parent)
        return handle

    def close(self) -> None:
        handle = self._lock_handle
        if handle is None:
            return
        self._lock_handle = None
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

    def _write_status(self) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._state_root,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(self._status, temporary, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._status_path)
            _fsync_directory(self._status_path.parent)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def _interval_from_environment() -> float:
    raw_value = os.environ.get(
        "JARVIS_WATCHER_INTERVAL_SECONDS",
        str(DEFAULT_INTERVAL_SECONDS),
    )
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError("JARVIS_WATCHER_INTERVAL_SECONDS must be numeric") from exc
    if not MIN_INTERVAL_SECONDS <= value <= MAX_INTERVAL_SECONDS:
        raise ValueError(
            "JARVIS_WATCHER_INTERVAL_SECONDS must be between "
            f"{MIN_INTERVAL_SECONDS} and {MAX_INTERVAL_SECONDS}"
        )
    return value


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    service = WatcherService(
        vault_core.get_vault_root(),
        vault_core.get_state_root(),
    )
    stop_event = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    service.run_forever(stop_event, _interval_from_environment())


if __name__ == "__main__":
    main()

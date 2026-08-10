from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

try:
    import vault_core
    from watcher import WatchEvent, _read_preserved_blob
    from watcher_rules import WatchPlan, plan_event
except ModuleNotFoundError:  # Package imports used by the local test suite.
    from app import vault_core
    from app.watcher import WatchEvent, _read_preserved_blob
    from app.watcher_rules import WatchPlan, plan_event


@dataclass(frozen=True)
class ProcessResult:
    action: str
    mode: str
    reason: str
    rule_version: str
    capture_id: str | None = None
    capture_created: bool | None = None


class _PermanentReviewRequired(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class WatcherProcessor:
    def __init__(self, vault_root: Path, state_root: Path):
        self._vault_root = vault_root.resolve(strict=True)
        self._state_root = state_root.resolve(strict=True)

    def process(self, event: WatchEvent) -> ProcessResult:
        plan = plan_event(event)
        if plan.action != "queue_capture":
            return self._from_plan(plan)

        try:
            content = self._read_preserved_content(event.sha256)
        except _PermanentReviewRequired as exc:
            return self._review_result(plan, exc.reason)

        title = PurePosixPath(event.relative_path).stem
        if not content.strip():
            return self._review_result(plan, "capture_content_is_empty")
        if len(content.encode("utf-8")) > vault_core.MAX_CAPTURE_BYTES:
            return self._review_result(plan, "capture_content_exceeds_limit")
        if not title.strip() or len(title.strip()) > 200:
            return self._review_result(plan, "capture_title_is_invalid")
        if len(event.relative_path.strip()) > 500:
            return self._review_result(plan, "capture_source_ref_exceeds_limit")

        captured = vault_core.capture_material(
            self._state_root,
            title=title,
            content=content,
            source_kind="file",
            source_ref=event.relative_path,
            labels=["watcher"],
        )
        return ProcessResult(
            action=plan.action,
            mode=plan.mode,
            reason=plan.reason,
            rule_version=plan.rule_version,
            capture_id=str(captured["capture_id"]),
            capture_created=bool(captured["created"]),
        )

    def _read_preserved_content(self, digest: str | None) -> str:
        if (
            digest is None
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise vault_core.JarvisError("Watcher preserved content digest is invalid.")

        originals_root = self._state_root / "watcher-originals"
        preserved = originals_root / f"{digest}.md"
        if (
            originals_root.is_symlink()
            or not originals_root.is_dir()
            or preserved.is_symlink()
            or not preserved.exists()
        ):
            raise vault_core.JarvisError("Watcher preserved content is unavailable.")
        try:
            data = _read_preserved_blob(originals_root, digest)
        except (OSError, ValueError) as exc:
            raise vault_core.JarvisError(
                "Watcher preserved content is unavailable."
            ) from exc
        if hashlib.sha256(data).hexdigest() != digest:
            raise vault_core.JarvisError("Watcher preserved content is corrupt.")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _PermanentReviewRequired("capture_content_is_not_utf8") from exc

    @staticmethod
    def _review_result(plan: WatchPlan, reason: str) -> ProcessResult:
        return ProcessResult(
            action="review_required",
            mode="suggest",
            reason=reason,
            rule_version=plan.rule_version,
        )

    @staticmethod
    def _from_plan(plan: WatchPlan) -> ProcessResult:
        return ProcessResult(
            action=plan.action,
            mode=plan.mode,
            reason=plan.reason,
            rule_version=plan.rule_version,
        )

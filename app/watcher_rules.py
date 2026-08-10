from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

try:
    from watcher import WatchEvent
except ModuleNotFoundError:  # Package import used by the local test suite.
    from app.watcher import WatchEvent


RULE_VERSION = "watcher-policy-v1"


@dataclass(frozen=True)
class WatchPlan:
    action: str
    mode: str
    reason: str
    rule_version: str = RULE_VERSION


def plan_event(event: WatchEvent) -> WatchPlan:
    parts = PurePosixPath(event.relative_path).parts

    if parts[:2] in {
        ("AI Inbox", "_fingerprint"),
        ("Idee", "_snapshot"),
    }:
        return WatchPlan(
            action="ignore",
            mode="auto",
            reason="Generated safety archive path.",
        )

    if parts[:1] == ("AI Inbox",):
        if event.event_type in {"created", "modified"}:
            return WatchPlan(
                action="queue_capture",
                mode="auto",
                reason="Objective AI Inbox acquisition; semantic processing is not authorized.",
            )
        return WatchPlan(
            action="review_required",
            mode="suggest",
            reason="A deletion or move cannot be classified safely from one path event.",
        )

    return WatchPlan(
        action="review_required",
        mode="suggest",
        reason="Vault organization requires semantic context or explicit authorization.",
    )

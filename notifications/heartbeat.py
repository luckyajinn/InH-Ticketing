"""
The worker's heartbeat: one database row saying what the worker last did.

The worker records each finished round, each inbox read and each auto-close
run. Reports and Docker's health check (manage.py check_worker) read it, so
they can tell for sure that the worker is running. Before v0.10.3, Reports
could only guess from emails waiting to be sent, which says nothing on a
quiet day, and a mailbox that couldn't be read showed only in the log.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.conf import settings
from django.utils import timezone

from notifications.models import WorkerHeartbeat

logger = logging.getLogger(__name__)

ERROR_LENGTH = 500


def stale_after() -> dt.timedelta:
    """No finished round for this long: the worker has probably stopped."""
    return max(dt.timedelta(minutes=5), dt.timedelta(seconds=3 * settings.WORKER_INTERVAL_SECONDS))


def record(**fields) -> None:
    """Update the heartbeat row. Never raises: a heartbeat must not stop the worker."""
    try:
        if not WorkerHeartbeat.objects.filter(pk=1).update(**fields):
            WorkerHeartbeat.objects.create(pk=1, **fields)
    except Exception:  # the database is down or not migrated yet: the next round tries again
        logger.exception("Couldn't record the worker's heartbeat")


def started() -> None:
    record(started_at=timezone.now())


def round_done() -> None:
    record(round_at=timezone.now())


def inbox_read(problems: list[str]) -> None:
    """After reading the inbox. `problems`: one line per mailbox that couldn't be read."""
    now = timezone.now()
    if problems:
        record(inbox_at=now, inbox_error="\n".join(problems)[:ERROR_LENGTH])
    else:
        record(inbox_at=now, inbox_ok_at=now, inbox_error="")


def auto_closed(closed: int = 0, error: str = "") -> None:
    record(auto_close_at=timezone.now(), auto_close_closed=closed, auto_close_error=error[:ERROR_LENGTH])


def latest() -> WorkerHeartbeat | None:
    return WorkerHeartbeat.objects.filter(pk=1).first()


def state(beat: WorkerHeartbeat | None, now: dt.datetime | None = None) -> str:
    """'ok', 'late' (no round for stale_after()) or 'never' (no round recorded yet)."""
    if beat is None or beat.round_at is None:
        return "never"
    now = now or timezone.now()
    return "late" if now - beat.round_at > stale_after() else "ok"

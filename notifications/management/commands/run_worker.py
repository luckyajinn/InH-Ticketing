"""
The background worker: sends queued emails and, if INBOUND_EMAIL=graph,
reads the help-desk inbox, and closes Resolved tickets nobody replied to.

    python manage.py run_worker          keep running (Ctrl+C to stop)
    python manage.py run_worker --once   one round, then exit

Run exactly one worker.
"""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from notifications.sender import send_pending
from tickets.services import close_resolved_tickets

logger = logging.getLogger(__name__)

AUTO_CLOSE_EVERY_SECONDS = 60 * 60  # once an hour is plenty for a days-long delay


class Command(BaseCommand):
    help = "Send queued emails and read the help-desk inbox, then keep checking."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one round, then exit.")

    def _poll_inbox(self):
        from inbound.graph_inbox import poll  # only needed when email-in is on

        try:
            handled, failed = poll()
        except Exception as exc:  # Graph unreachable or not set up yet: keep sending
            logger.error("Couldn't read the inbox: %s", exc)
            self.stdout.write(f"Inbox: couldn't read it ({type(exc).__name__}: {exc})")
            return
        if handled or failed:
            self.stdout.write(f"Inbox: {handled} email(s) processed, {failed} failed (will retry)")

    def _auto_close(self):
        try:
            closed = close_resolved_tickets()
        except Exception as exc:  # a failure here must not stop emails going out
            logger.exception("Couldn't auto-close resolved tickets")
            self.stdout.write(f"Auto-close: failed ({type(exc).__name__}: {exc})")
            return
        if closed:
            self.stdout.write(f"Auto-close: {closed} resolved ticket(s) closed")

    def handle(self, *args, once=False, **options):
        interval = settings.WORKER_INTERVAL_SECONDS
        inbox_on = settings.INBOUND_EMAIL == "graph"
        self.stdout.write(
            f"Worker started. Email backend: {settings.EMAIL_BACKEND}. Checking every {interval}s."
        )
        self.stdout.write(
            f"Email-in: reading {settings.HELPDESK_MAILBOX} every {settings.INBOUND_POLL_SECONDS}s."
            if inbox_on else "Email-in: off (INBOUND_EMAIL=off)."
        )
        last_poll = 0.0
        last_auto_close = None  # None = not yet this run, so the first round does it
        try:
            while True:
                close_old_connections()  # don't hold a stale database connection
                if inbox_on and (once or time.monotonic() - last_poll >= settings.INBOUND_POLL_SECONDS):
                    self._poll_inbox()
                    last_poll = time.monotonic()
                if (
                    once or last_auto_close is None
                    or time.monotonic() - last_auto_close >= AUTO_CLOSE_EVERY_SECONDS
                ):
                    self._auto_close()
                    last_auto_close = time.monotonic()
                sent, failed = send_pending()
                if sent or failed:
                    self.stdout.write(f"Emails: {sent} sent, {failed} failed (will retry)")
                if once:
                    return
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped.")

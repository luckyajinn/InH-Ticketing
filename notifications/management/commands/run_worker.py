"""
The background worker. Sends queued emails; milestone 4 will add reading the
help-desk inbox here too.

    python manage.py run_worker          keep running (Ctrl+C to stop)
    python manage.py run_worker --once   send what's due, then exit

Run exactly one worker.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from notifications.sender import send_pending


class Command(BaseCommand):
    help = "Send queued emails, then keep checking every WORKER_INTERVAL_SECONDS."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one round, then exit.")

    def handle(self, *args, once=False, **options):
        interval = settings.WORKER_INTERVAL_SECONDS
        self.stdout.write(
            f"Worker started. Email backend: {settings.EMAIL_BACKEND}. Checking every {interval}s."
        )
        try:
            while True:
                close_old_connections()  # don't hold a stale database connection
                sent, failed = send_pending()
                if sent or failed:
                    self.stdout.write(f"Emails: {sent} sent, {failed} failed (will retry)")
                if once:
                    return
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped.")

"""
Close Resolved tickets that nobody has replied to for AUTO_CLOSE_RESOLVED_DAYS.

    python manage.py close_resolved

The worker does this by itself about once an hour; this command is for running
it by hand (or from a scheduler if you don't run the worker).
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from tickets.services import close_resolved_tickets


class Command(BaseCommand):
    help = "Close Resolved tickets with no reply for AUTO_CLOSE_RESOLVED_DAYS days."

    def handle(self, *args, **options):
        if settings.AUTO_CLOSE_RESOLVED_DAYS <= 0:
            self.stdout.write("Auto-close is off (AUTO_CLOSE_RESOLVED_DAYS=0). Closed 0 tickets.")
            return
        closed = close_resolved_tickets()
        self.stdout.write(f"Closed {closed} ticket{'' if closed == 1 else 's'}.")

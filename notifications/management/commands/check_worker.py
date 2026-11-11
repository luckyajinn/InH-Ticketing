"""
Is the background worker running? Docker's health check for the worker
container (compose.yaml), and handy by hand:

    docker compose exec worker python manage.py check_worker

Exits 0 if the worker finished a round in the last 5 minutes, 1 if not.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from notifications import heartbeat


class Command(BaseCommand):
    help = "Exit 0 if the worker finished a round recently, 1 if it hasn't."
    requires_system_checks = []  # runs every minute: keep it quick and quiet

    def handle(self, *args, **options):
        beat = heartbeat.latest()
        state = heartbeat.state(beat)
        if state == "never":
            raise CommandError("The worker hasn't finished a round yet.")
        seconds = round((timezone.now() - beat.round_at).total_seconds())
        if state == "late":
            raise CommandError(f"The worker may have stopped: its last round was {seconds} seconds ago.")
        self.stdout.write(f"The worker is running: its last round was {seconds} seconds ago.")

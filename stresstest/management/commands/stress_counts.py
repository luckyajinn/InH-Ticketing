"""Print the size of the data set as JSON, for the stress-test report. STRESS-TEST BRANCH ONLY."""

import json

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Min, Sum
from django.utils import timezone

from accounts.models import User
from notifications.models import OutboundEmail
from tickets.models import Attachment, Comment, Ticket, TicketEvent


class Command(BaseCommand):
    help = "Print counts of people, tickets, replies, emails and attachments as JSON."

    def handle(self, *args, **options):
        # "tickets" must stay followed by another key: stress/server-setup.sh looks for '"tickets": 0,'.
        oldest = Ticket.objects.aggregate(oldest=Min("created_at"))["oldest"]
        counts = {
            "requesters": User.objects.filter(role=User.Role.REQUESTER).count(),
            "agents": User.objects.filter(role__in=[User.Role.AGENT, User.Role.ADMIN]).count(),
            "tickets": Ticket.objects.count(),
            "open_tickets": Ticket.objects.open().count(),
            "comments": Comment.objects.count(),
            "events": TicketEvent.objects.count(),
            "emails": OutboundEmail.objects.count(),
            "attachments": Attachment.objects.count(),
            "attachments_mb": round((Attachment.objects.aggregate(total=Sum("size"))["total"] or 0) / 1e6),
            "years": round((timezone.now() - oldest).days / 365, 1) if oldest else 0,
        }
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_database_size(current_database())")
                counts["database_mb"] = round(cursor.fetchone()[0] / 1e6)
        self.stdout.write(json.dumps(counts))

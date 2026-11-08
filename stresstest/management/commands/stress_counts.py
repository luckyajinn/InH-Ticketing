"""Print the size of the data set as JSON, for the stress-test report. STRESS-TEST BRANCH ONLY."""

import json

from django.core.management.base import BaseCommand

from accounts.models import User
from tickets.models import Attachment, Comment, Ticket, TicketEvent


class Command(BaseCommand):
    help = "Print counts of people, tickets, replies and attachments as JSON."

    def handle(self, *args, **options):
        self.stdout.write(json.dumps({
            "requesters": User.objects.filter(role=User.Role.REQUESTER).count(),
            "agents": User.objects.filter(role__in=[User.Role.AGENT, User.Role.ADMIN]).count(),
            "tickets": Ticket.objects.count(),
            "open_tickets": Ticket.objects.open().count(),
            "comments": Comment.objects.count(),
            "events": TicketEvent.objects.count(),
            "attachments": Attachment.objects.count(),
        }))

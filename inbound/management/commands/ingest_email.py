"""
Feed an email into InH-Ticketing as if it had arrived at the help-desk mailbox.
Handy for trying email-in on your PC before the mailbox is connected.

    # a saved email (in Outlook, drag a message to the desktop to get one)
    python manage.py ingest_email path\\to\\message.eml

    # or type one
    python manage.py ingest_email --from dana@mckennalabs.com --subject "Printer jammed" --body "Tray 2 again"
    python manage.py ingest_email --from dana@mckennalabs.com --subject "RE: [#1028] Outlook" --body "Still happening"
"""

import uuid
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from inbound import eml
from inbound.processing import IncomingMessage, process


class Command(BaseCommand):
    help = "Process an email (.eml file, or --from/--subject/--body) exactly as email-in would."

    def add_arguments(self, parser):
        parser.add_argument("file", nargs="?", help="A .eml file.")
        parser.add_argument("--from", dest="from_address", help="Sender's address.")
        parser.add_argument("--name", default="", help="Sender's name.")
        parser.add_argument("--subject", default="")
        parser.add_argument("--body", default="")

    def handle(self, *args, file=None, from_address=None, name="", subject="", body="", **options):
        if file:
            path = Path(file)
            if not path.is_file():
                raise CommandError(f"No such file: {path}")
            message = eml.from_bytes(path.read_bytes())
        elif from_address:
            message = IncomingMessage(
                message_id=f"<{uuid.uuid4().hex}@ingest.local>", from_address=from_address,
                from_name=name, subject=subject, body_text=body, source="command",
            )
        else:
            raise CommandError("Give a .eml file, or --from with --subject and --body.")

        result = process(message)
        ticket = f" #{result.ticket.number}" if result.ticket else ""
        detail = f" ({result.detail})" if result.detail else ""
        prefix = "Already processed: " if result.duplicate else ""
        self.stdout.write(f"{prefix}{result.record.get_outcome_display()}{ticket}{detail}")

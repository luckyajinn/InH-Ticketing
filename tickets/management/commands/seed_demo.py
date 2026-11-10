"""
Fill a development database with fictional people and tickets.

    python manage.py seed_demo          add demo data
    python manage.py seed_demo --clear  remove it again

Demo people have usernames starting with "demo-" and can't sign in. To try
the app as them, sign in yourself: as an Agent/Admin you'll see their tickets
in the queue.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from tickets import services
from tickets.models import Category, Comment, Ticket, TicketEvent

PREFIX = "demo-"

PEOPLE = {
    "sam": ("Sam Patel", "sam.patel", User.Role.AGENT),
    "alex": ("Alex Morgan", "alex.morgan", User.Role.AGENT),
    "dana": ("Dana Whitfield", "dana.whitfield", User.Role.REQUESTER),
    "tom": ("Tom Reyes", "tom.reyes", User.Role.REQUESTER),
    "elena": ("Elena Brooks", "elena.brooks", User.Role.REQUESTER),
    "marcus": ("Marcus Delaney", "marcus.delaney", User.Role.REQUESTER),
    "owen": ("Owen Castillo", "owen.castillo", User.Role.REQUESTER),
    "aisha": ("Aisha Kamara", "aisha.kamara", User.Role.REQUESTER),
    "morgan": ("Morgan Lee", "morgan.lee", User.Role.REQUESTER),  # Owen's manager
}

# (requester, category, subject, description, blocking, hours ago)
TICKETS = [
    ("tom", "Network", "VPN drops every 10 minutes",
     "Since this morning the VPN disconnects about every 10 minutes when I'm working from home. "
     "Wi-Fi itself stays up.", True, 4),
    ("dana", "Software", "Outlook keeps prompting for my password",
     "Outlook asks for my password every hour or so. I type it in and it works for a while, then asks again.",
     False, 50),
    ("elena", "Access", "New phone: can't approve MFA sign-in requests",
     "I replaced my phone and the authenticator app doesn't get sign-in requests any more.", True, 1),
    ("marcus", "Hardware", "New-hire laptop setup: Jordan Kim, starts Monday",
     "Jordan Kim joins Finance on Monday. They'll need a laptop, a monitor and the usual Finance apps.",
     False, 48),
    ("owen", "Access", "Request access to the Finance shared drive",
     "I've moved to the Finance team and need read/write access to the Finance shared drive.", False, 26),
    ("aisha", "Hardware", "2nd-floor printer by the kitchen keeps jamming",
     "The printer next to the 2nd-floor kitchen jams every few pages. Tray 2 seems to be the problem.",
     False, 0.4),
    ("dana", "Software", "Teams camera not detected",
     "Teams says no camera found. The camera works in the Windows Camera app.", False, 170),
    ("tom", "Software", "Software install request: Power BI Desktop",
     "Please install Power BI Desktop on my laptop for the quarterly reports.", False, 0.25),
]


class Command(BaseCommand):
    help = "Add (or with --clear, remove) fictional demo people and tickets."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Remove demo data instead.")
        parser.add_argument("--force", action="store_true", help="Allow when DEBUG is off.")

    def handle(self, *args, clear=False, force=False, **options):
        if not settings.DEBUG and not force:
            raise CommandError("Demo data is for development. Use --force if you really mean it.")
        if clear:
            self._clear()
        else:
            self._seed()

    @transaction.atomic
    def _clear(self):
        demo_users = User.objects.filter(username__startswith=PREFIX)
        tickets = Ticket.objects.filter(requester__in=demo_users)
        count = tickets.count()
        # Remove demo activity on anyone's tickets, then the demo tickets themselves.
        Comment.objects.filter(author__in=demo_users).delete()
        TicketEvent.objects.filter(actor__in=demo_users).delete()
        for ticket in tickets:
            for attachment in ticket.attachments.all():
                attachment.file.delete(save=False)
        tickets.delete()
        users = demo_users.delete()[1].get("accounts.User", 0)
        self.stdout.write(self.style.SUCCESS(f"Removed {count} demo tickets and {users} demo people."))

    def _closed_with_follow_up(self, people, category, now):
        """A ticket that was resolved and closed, and the follow-up Aisha started from it."""
        sam, aisha = people["sam"], people["aisha"]
        original = services.create_ticket(
            requester=aisha, subject="Badge reader at the lab door won't open",
            description="My badge doesn't open the lab door any more. It beeps twice and stays locked.",
            category=category,
        )
        services.update_ticket(ticket=original, actor=sam, assignee=sam)
        services.update_ticket(ticket=original, actor=sam, status=Ticket.Status.RESOLVED)
        services.update_ticket(ticket=original, actor=sam, status=Ticket.Status.CLOSED)
        Ticket.objects.filter(pk=original.pk).update(
            created_at=now - timedelta(days=12),
            resolved_at=now - timedelta(days=10), closed_at=now - timedelta(days=3),
        )
        follow_up = services.create_ticket(
            requester=aisha, subject=original.subject,
            description="The badge worked for a few days, but now it's doing the same thing again.",
            category=category, follows_up=original,
        )
        Ticket.objects.filter(pk=follow_up.pk).update(created_at=now - timedelta(hours=5))
        return follow_up

    @transaction.atomic
    def _seed(self):
        if User.objects.filter(username__startswith=PREFIX).exists():
            raise CommandError("Demo data is already there. Run with --clear first to start over.")

        people = {}
        for key, (name, email_name, role) in PEOPLE.items():
            people[key] = User.objects.create(
                username=f"{PREFIX}{key}", display_name=name,
                email=f"{email_name}@example.invalid", role=role,
            )
            people[key].set_unusable_password()
            people[key].save()

        categories = {c.name: c for c in Category.objects.all()}
        now = timezone.now()
        created = []
        for requester, category, subject, description, blocking, hours in TICKETS:
            ticket = services.create_ticket(
                requester=people[requester], subject=subject, description=description,
                category=categories[category], is_blocking=blocking,
            )
            Ticket.objects.filter(pk=ticket.pk).update(created_at=now - timedelta(hours=hours))
            ticket.refresh_from_db()
            created.append(ticket)

        sam, alex = people["sam"], people["alex"]
        # The printer and Power BI tickets are left New and unassigned on purpose.
        vpn, outlook, mfa, laptop, finance, printer, teams, _powerbi = created
        # The printer ticket arrived by email to the help-desk mailbox.
        Ticket.objects.filter(pk=printer.pk).update(source=Ticket.Source.EMAIL)

        services.update_ticket(ticket=vpn, actor=sam, priority=Ticket.Priority.URGENT, assignee=sam)
        services.update_ticket(ticket=mfa, actor=alex, priority=Ticket.Priority.HIGH)

        services.update_ticket(ticket=outlook, actor=sam, priority=Ticket.Priority.HIGH, assignee=sam)
        services.add_comment(
            ticket=outlook, author=sam,
            body="Hi Dana, could you sign out of Outlook, close it, and sign back in? "
                 "Let me know if the prompt comes back.",
        )
        services.add_comment(
            ticket=outlook, author=people["dana"],
            body="I did that and it was fine all morning, but the box came back at about 4pm.\n\n"
                 "Thanks,\nDana Whitfield\nFinance Analyst | Example Company\n"
                 "T: +1 (555) 010-0100 | F: +1 (555) 010-0101\nwww.example.com\n\n"
                 "Please consider the environment before printing this email.",
            # Dana replied to the notification email; the signature shows folded.
            source=Ticket.Source.EMAIL,
        )
        services.add_comment(
            ticket=outlook, author=sam, is_internal=True,
            body="Same thing on two other Finance laptops after the firmware push. "
                 "Re-enrolment fixed both and took about 15 minutes.",
        )
        services.add_comment(
            ticket=outlook, author=sam,
            body="Thanks Dana. Are you free at 2:30 today? I'll need about 15 minutes on your laptop.",
            then_status=Ticket.Status.WAITING,  # the composer's "Send and set Waiting on User"
        )

        services.update_ticket(ticket=laptop, actor=alex, assignee=alex, status=Ticket.Status.IN_PROGRESS)
        services.add_comment(ticket=laptop, author=alex, is_internal=True,
                             body="Imaging the spare from stock. Monitor arrives Friday.")

        services.update_ticket(ticket=finance, actor=sam, assignee=sam)
        services.add_comment(ticket=finance, author=sam,
                             body="Owen, can you ask your manager to reply here to approve the access?",
                             then_status=Ticket.Status.WAITING)
        # Owen's manager answered by email. Not the requester, so it's an internal note.
        services.add_email_from_third_party(
            ticket=finance, sender=people["morgan"],
            body="Approved. Owen can have read/write access to the Finance drive.",
        )

        services.update_ticket(ticket=teams, actor=alex, assignee=alex, priority=Ticket.Priority.LOW)
        services.add_comment(ticket=teams, author=alex,
                             body="Teams had camera access turned off in Windows privacy settings. "
                                  "I've switched it back on.",
                             then_status=Ticket.Status.RESOLVED)  # "Send and resolve"

        # Resolved a couple of days ago, so the requester page shows its close date.
        Ticket.objects.filter(pk=teams.pk).update(resolved_at=now - timedelta(days=2))

        # A closed ticket with a follow-up linked to it.
        badge = self._closed_with_follow_up(people, categories["Access"], now)

        self.stdout.write(self.style.SUCCESS(
            f"Added {len(PEOPLE)} demo people and {len(created) + 2} demo tickets "
            f"(#{created[0].number}-#{badge.number})."
        ))

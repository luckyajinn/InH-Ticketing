"""
Generate fake data for stress tests. STRESS-TEST BRANCH ONLY: never merge into main.

    python manage.py generate_load_data                 defaults: 300 requesters, 5 agents,
                                                        12,000 tickets over 5 years
    python manage.py generate_load_data --clear         remove generated data first
    python manage.py generate_load_data --tickets 500   a small set, for a quick try

Everything is invented: people are "stress-..." accounts at example.invalid,
and ticket text comes from word lists. It writes in large batches so even big
data sets take seconds. It only runs in stress-test mode, and refuses a
database that holds any real (Microsoft 365) account.
"""

import random
import time
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from notifications.models import OutboundEmail
from stresstest.guard import FAKE_EMAIL_DOMAIN, FAKE_USER_PREFIX
from tickets.models import Attachment, Category, Comment, Ticket, TicketEvent

Status, Priority = Ticket.Status, Ticket.Priority
BATCH = 1000

FIRST = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery", "Quinn",
         "Dana", "Robin", "Drew", "Skyler", "Reese", "Parker", "Rowan", "Emerson", "Finley", "Hayden"]
LAST = ["Rivera", "Patel", "Nguyen", "Kim", "Brooks", "Castillo", "Kamara", "Reyes", "Delaney",
        "Whitfield", "Moreno", "Okafor", "Lindqvist", "Haddad", "Novak", "Sato", "Mensah", "Varga"]
THINGS = ["laptop", "monitor", "printer", "VPN", "Outlook", "Teams", "Wi-Fi", "docking station",
          "keyboard", "shared drive", "MFA app", "phone", "Excel", "badge reader", "label printer",
          "scanner", "headset", "webcam", "password", "Deacom login"]
PROBLEMS = ["not working", "very slow", "keeps disconnecting", "won't start", "shows an error",
            "asks for my password again", "can't connect", "needs installing", "stopped printing",
            "is frozen", "needs access", "makes a strange noise", "won't sync"]
SENTENCES = [
    "It started this morning after the update.", "I've already tried restarting it.",
    "The error message says something about permissions.", "It happens every few minutes.",
    "This is stopping me from finishing the weekly report.", "A colleague has the same problem.",
    "It worked fine yesterday.", "I'm working from the second floor today.",
    "Screenshot attached.", "Please let me know if you need anything else.",
    "It only happens when I'm on the VPN.", "I can still use it on my phone.",
]
IT_REPLIES = [
    "Thanks, I'm looking into it now.", "Could you try signing out and back in?",
    "I've pushed an update to your machine; please restart when convenient.",
    "Can you send a screenshot of the error?", "That should be fixed now; let me know if not.",
    "I've reset the settings on our side.", "I'll come by your desk this afternoon.",
    "This is a known issue; a fix is rolling out today.",
]
NOTES = [
    "Same issue on two other machines; possibly the latest driver.", "Escalated to the vendor.",
    "Waiting on a replacement part.", "Checked the logs; nothing obvious.",
    "Linked to the network change on Monday.", "Re-imaged the device.",
]


def paragraph(rng, n_min=1, n_max=4):
    return " ".join(rng.sample(SENTENCES, rng.randint(n_min, n_max)))


@contextmanager
def manual_timestamps(*fields):
    """Let us set created_at / updated_at ourselves instead of 'now'."""
    saved = [(f, f.auto_now, f.auto_now_add) for f in fields]
    for f in fields:
        f.auto_now = f.auto_now_add = False
    try:
        yield
    finally:
        for f, auto_now, auto_now_add in saved:
            f.auto_now, f.auto_now_add = auto_now, auto_now_add


class Command(BaseCommand):
    help = "Generate fake people and tickets for stress tests (stress-test mode only)."

    def add_arguments(self, parser):
        parser.add_argument("--requesters", type=int, default=300)
        parser.add_argument("--agents", type=int, default=5)
        parser.add_argument("--tickets", type=int, default=12000)
        parser.add_argument("--days", type=int, default=5 * 365, help="Spread tickets over this many days.")
        parser.add_argument("--avg-replies", type=float, default=3.0)
        parser.add_argument("--attachments", type=int, default=1500, help="Small fake files.")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--clear", action="store_true", help="Delete generated data first.")

    def handle(self, *args, **o):
        if not getattr(settings, "STRESS_TEST_MODE", False):
            raise CommandError("This only runs with STRESS_TEST_MODE=1 (the stress-test server).")
        if User.objects.exclude(username__startswith=FAKE_USER_PREFIX).filter(entra_oid__isnull=False).exists():
            raise CommandError("This database holds real Microsoft 365 accounts. Use a separate, empty database.")

        started = time.monotonic()
        if o["clear"]:
            self._clear()
        if User.objects.filter(username__startswith=FAKE_USER_PREFIX).exists():
            raise CommandError("Generated data already exists. Run with --clear to replace it.")

        rng = random.Random(o["seed"])
        with transaction.atomic():
            requesters, agents = self._people(rng, o["requesters"], o["agents"])
            categories = list(Category.objects.filter(is_active=True))
            with manual_timestamps(
                Ticket._meta.get_field("created_at"), Ticket._meta.get_field("updated_at"),
                Comment._meta.get_field("created_at"), TicketEvent._meta.get_field("created_at"),
                Attachment._meta.get_field("created_at"),
            ):
                tickets = self._tickets(rng, o["tickets"], o["days"], requesters, agents, categories)
                n_comments = self._comments(rng, tickets, agents, o["avg_replies"])
                n_events = self._events(rng, tickets, agents)
                n_follow = self._follow_ups(rng, tickets)
                n_files = self._attachments(rng, tickets, o["attachments"])

        self.stdout.write(self.style.SUCCESS(
            f"Generated {len(requesters)} requesters, {len(agents)} agents, {len(tickets)} tickets, "
            f"{n_comments} replies/notes, {n_events} history events, {n_follow} follow-up links, "
            f"{n_files} attachments in {time.monotonic() - started:.1f}s."
        ))

    # ------------------------------------------------------------------
    def _clear(self):
        fake = User.objects.filter(username__startswith=FAKE_USER_PREFIX)
        tickets = Ticket.objects.filter(requester__in=fake)
        for att in Attachment.objects.filter(ticket__in=tickets).iterator():
            att.file.delete(save=False)
        OutboundEmail.objects.filter(ticket__in=tickets).delete()
        Comment.objects.filter(author__in=fake).delete()
        tickets.delete()
        count = fake.delete()[1].get("accounts.User", 0)
        self.stdout.write(f"Removed generated data ({count} fake people and their tickets).")

    def _people(self, rng, n_req, n_agents):
        def person(username, role, i):
            name = f"{FIRST[i % len(FIRST)]} {LAST[(i * 7) % len(LAST)]}"
            user = User(username=username, display_name=name, role=role,
                        email=f"{username}@{FAKE_EMAIL_DOMAIN}")
            user.set_unusable_password()
            return user

        users = [person(f"{FAKE_USER_PREFIX}agent-{i:02d}", User.Role.AGENT, i) for i in range(1, n_agents + 1)]
        users += [person(f"{FAKE_USER_PREFIX}req-{i:04d}", User.Role.REQUESTER, i) for i in range(1, n_req + 1)]
        User.objects.bulk_create(users, batch_size=BATCH)
        created = list(User.objects.filter(username__startswith=FAKE_USER_PREFIX))
        return [u for u in created if u.role == User.Role.REQUESTER], [u for u in created if u.is_agent]

    def _tickets(self, rng, n, days, requesters, agents, categories):
        now = timezone.now()
        objs = []
        for _ in range(n):
            # More tickets in recent times (the company grows), ~1 in 20 urgent.
            age = timedelta(days=days * (rng.random() ** 1.4), seconds=rng.randint(0, 86399))
            created = now - age
            if age > timedelta(days=21):
                status = rng.choices([Status.CLOSED, Status.RESOLVED], [97, 3])[0]
            else:
                status = rng.choices(
                    [Status.NEW, Status.OPEN, Status.IN_PROGRESS, Status.WAITING, Status.RESOLVED, Status.CLOSED],
                    [10, 20, 15, 10, 15, 30])[0]
            done_after = timedelta(hours=rng.uniform(0.5, 120))
            resolved_at = created + done_after if status in (Status.RESOLVED, Status.CLOSED) else None
            closed_at = resolved_at + timedelta(days=7) if status == Status.CLOSED else None
            if closed_at and closed_at > now:
                closed_at = now
            objs.append(Ticket(
                subject=f"{rng.choice(THINGS).capitalize()} {rng.choice(PROBLEMS)}",
                description=paragraph(rng, 2, 5),
                requester=rng.choice(requesters),
                assignee=None if status == Status.NEW else rng.choice(agents),
                category=rng.choice(categories),
                status=status,
                priority=rng.choices([Priority.LOW, Priority.NORMAL, Priority.HIGH, Priority.URGENT], [15, 60, 20, 5])[0],
                is_blocking=rng.random() < 0.15,
                source=rng.choices([Ticket.Source.WEB, Ticket.Source.EMAIL], [70, 30])[0],
                created_at=created,
                updated_at=closed_at or resolved_at or created + timedelta(hours=rng.uniform(0, 48)),
                resolved_at=resolved_at,
                closed_at=closed_at,
            ))
        Ticket.objects.bulk_create(objs, batch_size=BATCH)
        return list(Ticket.objects.filter(requester__username__startswith=FAKE_USER_PREFIX)
                    .select_related("requester", "assignee"))

    def _comments(self, rng, tickets, agents, avg):
        now, objs = timezone.now(), []
        for t in tickets:
            end = t.closed_at or t.resolved_at or now
            span = max((end - t.created_at).total_seconds(), 60)
            for k in range(min(int(rng.expovariate(1 / avg)) if avg > 0 else 0, 15)):
                at = t.created_at + timedelta(seconds=span * (k + rng.random()) / 16)
                if rng.random() < 0.2:
                    objs.append(Comment(ticket=t, author=t.assignee or rng.choice(agents),
                                        body=rng.choice(NOTES), is_internal=True, created_at=at))
                elif k % 2 == 0:
                    objs.append(Comment(ticket=t, author=t.assignee or rng.choice(agents),
                                        body=rng.choice(IT_REPLIES), created_at=at))
                else:
                    objs.append(Comment(ticket=t, author=t.requester, body=paragraph(rng, 1, 2),
                                        source=rng.choice([Ticket.Source.WEB, Ticket.Source.EMAIL]),
                                        created_at=at))
        Comment.objects.bulk_create(objs, batch_size=BATCH)
        return len(objs)

    def _events(self, rng, tickets, agents):
        objs = []
        for t in tickets:
            if t.status == Status.NEW:
                continue
            actor = t.assignee or rng.choice(agents)
            at = t.created_at + timedelta(minutes=rng.randint(5, 240))
            objs.append(TicketEvent(ticket=t, actor=actor, kind=TicketEvent.Kind.ASSIGNEE,
                                    new_value=str(t.assignee or actor), created_at=at))
            objs.append(TicketEvent(ticket=t, actor=actor, kind=TicketEvent.Kind.STATUS, old_value="New",
                                    new_value="Open", note="assigned", created_at=at))
            if t.resolved_at:
                objs.append(TicketEvent(ticket=t, actor=actor, kind=TicketEvent.Kind.STATUS, old_value="Open",
                                        new_value="Resolved", created_at=t.resolved_at))
            if t.closed_at:
                objs.append(TicketEvent(ticket=t, actor=None, kind=TicketEvent.Kind.STATUS, old_value="Resolved",
                                        new_value="Closed", note="no reply for 7 days", created_at=t.closed_at))
        TicketEvent.objects.bulk_create(objs, batch_size=BATCH)
        return len(objs)

    def _follow_ups(self, rng, tickets):
        closed_by_requester = {}
        for t in tickets:
            if t.status == Status.CLOSED:
                closed_by_requester.setdefault(t.requester_id, []).append(t)
        changed = []
        for t in tickets:
            options = [c for c in closed_by_requester.get(t.requester_id, []) if c.created_at < t.created_at]
            if options and rng.random() < 0.03:
                t.follows_up = rng.choice(options)
                changed.append(t)
        Ticket.objects.bulk_update(changed, ["follows_up"], batch_size=BATCH)
        return len(changed)

    def _attachments(self, rng, tickets, n):
        for t in rng.sample(tickets, min(n, len(tickets))):
            ext = rng.choice([".png", ".jpg", ".pdf", ".log", ".txt"])
            size = rng.randint(2_000, 60_000)
            att = Attachment(ticket=t, uploaded_by=t.requester, original_name=f"screenshot-{t.pk}{ext}",
                             size=size, content_type="application/octet-stream", created_at=t.created_at)
            att.file.save(f"fake{ext}", ContentFile(rng.randbytes(size)), save=False)
            att.save()
        return min(n, len(tickets))

"""
Generate fake data for stress tests. STRESS-TEST BRANCH ONLY: never merge into main.

    python manage.py generate_load_data                 defaults: 300 requesters, 5 agents,
                                                        12,000 tickets over 5 years (200 a month)
    python manage.py generate_load_data --clear         remove generated data first
    python manage.py generate_load_data --tickets 500   a small set, for a quick try

Everything is invented: people are "stress-..." accounts at example.invalid,
and ticket text comes from word lists. It writes in large batches, so even big
data sets take seconds; the attachment files take longest. It only runs in
stress-test mode, and refuses a database that holds any real (Microsoft 365) account.

The data is shaped like a real help desk's, so every page does realistic work:
  * tickets arrive evenly (200 a month by default) and each stays open for a
    realistic time, so a few dozen are open at once, as for a team of five;
  * resolved tickets close after AUTO_CLOSE_RESOLVED_DAYS, as the worker does,
    so the worker has no backlog to close when it starts;
  * every ticket has the emails the app would have sent (the biggest table in
    real use) and, if it came by email, the record of that email;
  * attachment files are sized like real ones: about 800 KB typically,
    1.5 MB on average, up to the 10 MB limit.
"""

import math
import random
import time
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from accounts.models import User
from inbound.models import InboundEmail
from notifications import notify
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
FILE_KINDS = [("screenshot", ".png", "image/png"), ("photo", ".jpg", "image/jpeg"),
              ("error-report", ".pdf", "application/pdf"), ("log", ".txt", "text/plain"),
              ("spreadsheet", ".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")]


def paragraph(rng, n_min=1, n_max=4):
    return " ".join(rng.sample(SENTENCES, rng.randint(n_min, n_max)))


def open_time(rng) -> timedelta:
    """How long a ticket stays open: usually a day or two; 1 in 10 waits weeks (parts, people)."""
    if rng.random() < 0.1:
        return timedelta(days=rng.uniform(5, 30))
    return timedelta(hours=min(rng.lognormvariate(math.log(30), 1.3), 30 * 24))


def file_size(rng, median_kb: int) -> int:
    """Attachment sizes: median `median_kb`, a long tail of big photos, capped at the upload limit."""
    size = rng.lognormvariate(math.log(median_kb * 1000), 1.1)
    return int(min(max(size, 5_000), settings.ATTACHMENT_MAX_BYTES))


def close_days() -> int:
    """Resolved tickets close after this many days (7 when auto-close is off and IT closes them)."""
    return settings.AUTO_CLOSE_RESOLVED_DAYS if settings.AUTO_CLOSE_RESOLVED_DAYS > 0 else 7


def email_bodies(sample: Ticket) -> dict[str, tuple[str, str]]:
    """
    One real rendered email (text, HTML) per kind. Every fake email reuses the
    one for its kind, so the outbound-email table has its real size without
    rendering tens of thousands of templates.
    """
    kinds = {
        "received": ("requester", "We've received your request", "Request is with IT.", sample.description),
        "it_replied": ("requester", "IT replied to your request", "Your request is open.", IT_REPLIES[0]),
        "requester_replied": ("it", "The requester replied", "New reply.", SENTENCES[0]),
        "resolved": ("requester", "Your request has been resolved", "IT marked it as resolved.", None),
    }
    bodies = {}
    for kind, (audience, heading, intro, message) in kinds.items():
        context = {
            "reply_hint": notify._reply_hint(sample, audience), "ticket": sample,
            "ticket_url": settings.SITE_URL + sample.get_absolute_url(), "heading": heading,
            "intro": intro, "message": message, "message_author": "They wrote" if message else None,
            "action": "View your request", "reason": "you raised this request", "app_name": "InH-Ticketing",
        }
        bodies[kind] = (render_to_string("emails/notification.txt", context),
                        render_to_string("emails/notification.html", context))
    return bodies


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
        parser.add_argument("--attachments", type=int, default=1500,
                            help="Fake files (default 1,500: about 2 GB, a year's worth).")
        parser.add_argument("--file-median-kb", type=int, default=800,
                            help="Typical attachment size in KB (default 800; the average is about twice that).")
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
                Attachment._meta.get_field("created_at"), OutboundEmail._meta.get_field("created_at"),
                InboundEmail._meta.get_field("created_at"), InboundEmail._meta.get_field("updated_at"),
            ):
                tickets = self._tickets(rng, o["tickets"], o["days"], requesters, agents, categories)
                comments = self._comments(rng, tickets, agents, o["avg_replies"])
                n_events = self._events(rng, tickets, agents)
                n_follow = self._follow_ups(rng, tickets)
                n_emails = self._emails(tickets, comments)
                n_inbound = self._inbound(tickets, comments)
                n_files, file_bytes = self._attachments(rng, tickets, o["attachments"], o["file_median_kb"])

        n_open = sum(1 for t in tickets if t.is_open)
        self.stdout.write(self.style.SUCCESS(
            f"Generated {len(requesters)} requesters, {len(agents)} agents, {len(tickets)} tickets "
            f"({n_open} open), {len(comments)} replies/notes, {n_events} history events, {n_follow} follow-up "
            f"links, {n_emails} sent emails, {n_inbound} received emails, {n_files} attachments "
            f"({file_bytes / 1e6:,.0f} MB) in {time.monotonic() - started:.1f}s."
        ))

    # ------------------------------------------------------------------
    def _clear(self):
        fake = User.objects.filter(username__startswith=FAKE_USER_PREFIX)
        tickets = Ticket.objects.filter(requester__in=fake)
        for att in Attachment.objects.filter(ticket__in=tickets).iterator():
            att.file.delete(save=False)
        OutboundEmail.objects.filter(ticket__in=tickets).delete()
        InboundEmail.objects.filter(ticket__in=tickets).delete()
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
        close_after = timedelta(days=close_days())
        objs = []
        for _ in range(n):
            created = now - timedelta(seconds=rng.uniform(0, days * 86400))
            age = now - created
            resolved_at = created + open_time(rng)
            if resolved_at > now:  # still being worked on
                resolved_at = closed_at = None
                if age < timedelta(hours=4) and rng.random() < 0.6:
                    status = Status.NEW  # not picked up yet
                else:
                    status = rng.choices([Status.OPEN, Status.IN_PROGRESS, Status.WAITING], [40, 35, 25])[0]
                updated_at = created + age * rng.random()
            elif resolved_at + close_after <= now:
                status, closed_at = Status.CLOSED, resolved_at + close_after
                updated_at = closed_at
            else:
                status, closed_at, updated_at = Status.RESOLVED, None, resolved_at
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
                updated_at=updated_at,
                resolved_at=resolved_at,
                closed_at=closed_at,
            ))
        Ticket.objects.bulk_create(objs, batch_size=BATCH)
        return list(Ticket.objects.filter(requester__username__startswith=FAKE_USER_PREFIX)
                    .select_related("requester", "assignee"))

    def _comments(self, rng, tickets, agents, avg):
        now, objs = timezone.now(), []
        for t in tickets:
            if t.status == Status.NEW:
                continue  # nobody in IT has touched it yet
            end = t.resolved_at or now
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
        return objs

    def _events(self, rng, tickets, agents):
        days = close_days()
        objs = []
        for t in tickets:
            if t.status == Status.NEW:
                continue
            actor = t.assignee or rng.choice(agents)
            at = t.created_at + timedelta(minutes=rng.randint(5, 240))
            if t.resolved_at and at > t.resolved_at:
                at = t.created_at + (t.resolved_at - t.created_at) / 2
            objs.append(TicketEvent(ticket=t, actor=actor, kind=TicketEvent.Kind.ASSIGNEE,
                                    new_value=str(t.assignee or actor), created_at=at))
            objs.append(TicketEvent(ticket=t, actor=actor, kind=TicketEvent.Kind.STATUS, old_value="New",
                                    new_value="Open", note="assigned", created_at=at))
            if t.resolved_at:
                objs.append(TicketEvent(ticket=t, actor=actor, kind=TicketEvent.Kind.STATUS, old_value="Open",
                                        new_value="Resolved", created_at=t.resolved_at))
            if t.closed_at:
                objs.append(TicketEvent(ticket=t, actor=None, kind=TicketEvent.Kind.STATUS, old_value="Resolved",
                                        new_value="Closed", note=f"no reply for {days} days",
                                        created_at=t.closed_at))
        TicketEvent.objects.bulk_create(objs, batch_size=BATCH)
        return len(objs)

    def _follow_ups(self, rng, tickets):
        closed_by_requester = {}
        for t in tickets:
            if t.status == Status.CLOSED:
                closed_by_requester.setdefault(t.requester_id, []).append(t)
        changed = []
        for t in tickets:
            options = [c for c in closed_by_requester.get(t.requester_id, []) if c.closed_at < t.created_at]
            if options and rng.random() < 0.03:
                t.follows_up = rng.choice(options)
                changed.append(t)
        Ticket.objects.bulk_update(changed, ["follows_up"], batch_size=BATCH)
        return len(changed)

    def _emails(self, tickets, comments):
        """The emails the app would have sent, all marked as sent."""
        if not tickets:
            return 0
        bodies = email_bodies(tickets[0])

        def email(kind, ticket, to, at):
            text, html = bodies[kind]
            return OutboundEmail(
                ticket=ticket, kind=kind, to=to, subject=f"[#{ticket.number}] {ticket.subject}"[:255],
                body_text=text, body_html=html, status=OutboundEmail.Status.SENT, attempts=1,
                next_attempt_at=at, created_at=at, sent_at=at + timedelta(seconds=20),
            )

        objs = [email("received", t, t.requester.email, t.created_at) for t in tickets]
        for c in comments:
            t = c.ticket
            if c.is_internal:
                continue  # internal notes never send email
            if c.author_id == t.requester_id:
                if t.assignee:
                    objs.append(email("requester_replied", t, t.assignee.email, c.created_at))
            else:
                objs.append(email("it_replied", t, t.requester.email, c.created_at))
        objs += [email("resolved", t, t.requester.email, t.resolved_at) for t in tickets if t.resolved_at]
        OutboundEmail.objects.bulk_create(objs, batch_size=BATCH)
        return len(objs)

    def _inbound(self, tickets, comments):
        """The record of each email that arrived (new tickets and replies sent by email)."""
        objs = [
            InboundEmail(message_id=f"<stress-ticket-{t.pk}@{FAKE_EMAIL_DOMAIN}>", source="graph",
                         from_address=t.requester.email, from_name=str(t.requester), subject=t.subject,
                         received_at=t.created_at, outcome=InboundEmail.Outcome.NEW_TICKET, ticket=t,
                         created_at=t.created_at, updated_at=t.created_at)
            for t in tickets if t.source == Ticket.Source.EMAIL
        ]
        objs += [
            InboundEmail(message_id=f"<stress-reply-{c.ticket.pk}-{i}@{FAKE_EMAIL_DOMAIN}>", source="graph",
                         from_address=c.ticket.requester.email, from_name=str(c.ticket.requester),
                         subject=f"RE: [#{c.ticket.number}] {c.ticket.subject}"[:500], received_at=c.created_at,
                         outcome=InboundEmail.Outcome.REPLY, ticket=c.ticket,
                         created_at=c.created_at, updated_at=c.created_at)
            for i, c in enumerate(comments) if c.source == Ticket.Source.EMAIL
        ]
        InboundEmail.objects.bulk_create(objs, batch_size=BATCH)
        return len(objs)

    def _attachments(self, rng, tickets, n, median_kb):
        total = 0
        chosen = rng.sample(tickets, min(n, len(tickets)))
        for t in chosen:
            stem, ext, content_type = rng.choice(FILE_KINDS)
            size = file_size(rng, median_kb)
            att = Attachment(ticket=t, uploaded_by=t.requester, original_name=f"{stem}-{t.pk}{ext}",
                             size=size, content_type=content_type, created_at=t.created_at)
            att.file.save(f"fake{ext}", ContentFile(rng.randbytes(size)), save=False)
            att.save()
            total += size
        return len(chosen), total

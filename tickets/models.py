"""
Ticket data model.

    Department     The teams that work tickets: IT (built in), and any an admin adds
    Category       Admin-editable list: Hardware, Software, ..., each in one department
    Ticket         One request from one person
    Comment        A public reply or an internal note (is_internal) on a ticket
    TicketEvent    History: who changed status/priority/assignee/category, and when
    Attachment     A file on a ticket, or on a specific comment
    PasswordWarning  Audit trail of the "this might include a password" check
"""

import uuid
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse

from core import departments

# The longest description or reply, on the web (a clear message) and by email
# (cut short there). A long log belongs in an attached file.
TEXT_MAX_CHARS = 20_000


class Department(models.Model):
    """
    A team that works tickets. IT is built in; an admin adds the others in the
    admin site. Each category belongs to one, and each agent works for one, from
    their Entra app role. Tickets, notes and people store the key, so it never changes.
    """

    # Reports' team colours, in this order: checked for colour-blind separation
    # between neighbours, and contrast, in light and dark (static/css/app.css).
    COLOURS = [(1, "Teal"), (2, "Orange"), (3, "Blue"), (4, "Yellow"), (5, "Pink"), (6, "Green"),
               (7, "Violet"), (8, "Red")]

    key = models.CharField(
        max_length=16, unique=True,
        validators=[RegexValidator(r"^[a-z][a-z0-9-]*\Z", "Lower-case letters, digits and hyphens, starting with a letter.")],
        help_text='A short name, e.g. "mechanics", used in settings such as DEPARTMENT_MAILBOXES. '
                  "It can't be changed later.",
    )
    name = models.CharField(max_length=40, unique=True, help_text='As people see it, e.g. "Mechanics".')
    entra_role = models.CharField(
        "Entra app role", max_length=100, blank=True,
        help_text='The value of the Entra app role that makes someone this department\'s agent, e.g. '
                  '"Agent.Mechanics". Create the role in Entra with exactly this value.',
    )
    alert_email = models.EmailField(
        "alert address", blank=True,
        help_text="Where its new-request and unassigned-reply alerts go: a team list, or a Teams "
                  "channel's email address. Blank: to each of its agents.",
    )
    colour = models.PositiveSmallIntegerField(
        choices=COLOURS, unique=True, editable=False,
        help_text="Its colour in Reports, given in the order departments are added.",
    )

    class Meta:
        ordering = ["colour"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_it(self) -> bool:
        return self.key == departments.IT

    def clean(self):
        super().clean()
        errors = {}
        if self.is_it:
            return
        if not self.pk and self.colour is None and Department.objects.count() >= len(self.COLOURS):
            raise ValidationError(f"There can be up to {len(self.COLOURS)} departments.")
        role = self.entra_role.strip()
        if not role:
            errors["entra_role"] = "Every department other than IT needs its own Entra app role."
        elif role.lower() in {settings.ENTRA_ROLE_AGENT.lower(), settings.ENTRA_ROLE_ADMIN.lower()}:
            errors["entra_role"] = f'"{role}" is IT\'s or the admins\' role. Give this department its own.'
        elif Department.objects.exclude(pk=self.pk).filter(entra_role__iexact=role).exists():
            errors["entra_role"] = "Another department already uses that role."
        email = self.alert_email.strip().lower()
        if email:
            from notifications.graph import own_addresses  # the app's own mailboxes

            domain = email.rsplit("@", 1)[-1]
            if email in own_addresses():
                errors["alert_email"] = "Not one of the app's own mailboxes: it would read its own alerts."
            elif settings.INBOUND_ALLOWED_DOMAINS and domain not in settings.INBOUND_ALLOWED_DOMAINS:
                errors["alert_email"] = "Use an address in the organisation: " + ", ".join(settings.INBOUND_ALLOWED_DOMAINS)
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.entra_role = self.entra_role.strip()
        if self.colour is None:
            taken = set(Department.objects.values_list("colour", flat=True))
            self.colour = next((value for value, _ in self.COLOURS if value not in taken), None)
            if self.colour is None:
                raise ValidationError(f"There can be up to {len(self.COLOURS)} departments.")
        super().save(*args, **kwargs)


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)
    hint = models.CharField(
        max_length=120, blank=True,
        help_text='Examples shown to requesters, e.g. "laptop, monitor, printer, phone".',
    )
    is_active = models.BooleanField(
        default=True, help_text="Untick to stop offering this category on new requests."
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    department = models.CharField(
        max_length=16, default=departments.IT,
        help_text="Which department works these requests. Only admins move a ticket to another department.",
    )
    subject_options = models.TextField(
        "common requests", blank=True,
        help_text="One subject per line. Shown as quick picks on the New request form: a picked one "
                  "becomes the subject (instead of anything typed) and fills in this category.",
    )

    MAX_SUBJECT_OPTIONS = 20

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name

    @property
    def label(self) -> str:
        """What requesters see in the dropdown."""
        return f"{self.name}: {self.hint}" if self.hint else self.name

    @property
    def subject_choices(self) -> list[str]:
        """The quick-pick subjects, without blank lines."""
        lines = (line.strip()[:200] for line in (self.subject_options or "").splitlines())
        return [line for line in lines if line][: self.MAX_SUBJECT_OPTIONS]


class TicketQuerySet(models.QuerySet):
    def visible_to(self, user):
        """
        Admins see every ticket. An agent sees their department's tickets, and
        everyone sees their own requests.
        """
        if user.is_admin:
            return self
        if user.is_agent:
            return self.filter(Q(category__department=user.agent_department) | Q(requester=user))
        return self.filter(requester=user)

    def worked_by(self, user):
        """The tickets this person works on: their department's, or all of them for admins."""
        if user.is_admin:
            return self
        if user.is_agent:
            return self.filter(category__department=user.agent_department)
        return self.none()

    def open(self):
        return self.filter(status__in=Ticket.OPEN_STATUSES)

    def archived(self):
        return self.filter(archived_at__isnull=False)

    def not_archived(self):
        return self.filter(archived_at__isnull=True)


class Ticket(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        WAITING = "waiting", "Waiting on User"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    # Stored as numbers so "highest priority first" is a simple sort.
    class Priority(models.IntegerChoices):
        LOW = 1, "Low"
        NORMAL = 2, "Normal"
        HIGH = 3, "High"
        URGENT = 4, "Urgent"

    class Source(models.TextChoices):
        WEB = "web", "Web form"
        EMAIL = "email", "Email"

    OPEN_STATUSES = (Status.NEW, Status.OPEN, Status.IN_PROGRESS, Status.WAITING)

    subject = models.CharField(max_length=200)
    description = models.TextField()
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_tickets"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_tickets",
    )
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="tickets")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.NORMAL)
    is_blocking = models.BooleanField(
        "blocking work", default=False,
        help_text="The requester said this stops them working. IT uses it to set priority.",
    )
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.WEB)
    # Set when this ticket was started from a closed one ("Start a follow-up",
    # or an email reply to a closed ticket).
    follows_up = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="follow_ups"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # Closed tickets are archived: read-only, out of the working views, and kept
    # for ARCHIVE_KEEP_DAYS (deleting them after that isn't switched on yet).
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = TicketQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-priority", "created_at"]),
            models.Index(fields=["assignee", "status"]),
            models.Index(fields=["requester", "status"]),
        ]

    def __str__(self) -> str:
        return f"#{self.number} {self.subject}"

    # People see "#1001"; the database key stays internal.
    @property
    def number(self) -> int:
        return settings.TICKET_NUMBER_OFFSET + self.pk

    @classmethod
    def pk_from_number(cls, number: int) -> int:
        return number - settings.TICKET_NUMBER_OFFSET

    def get_absolute_url(self) -> str:
        return reverse("tickets:detail", args=[self.number])

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def keep_until(self) -> datetime | None:
        """When an archived ticket's time is up (ARCHIVE_KEEP_DAYS after archiving)."""
        if not self.archived_at:
            return None
        return self.archived_at + timedelta(days=settings.ARCHIVE_KEEP_DAYS)

    @property
    def department(self) -> str:
        return self.category.department

    @property
    def department_label(self) -> str:
        return departments.label(self.category.department)

    @property
    def auto_close_at(self) -> datetime | None:
        """
        When a Resolved ticket will close by itself, or None if it won't
        (not Resolved, or AUTO_CLOSE_RESOLVED_DAYS is 0). Shown to requesters.
        """
        days = settings.AUTO_CLOSE_RESOLVED_DAYS
        if days <= 0 or self.status != self.Status.RESOLVED or not self.resolved_at:
            return None
        return self.resolved_at + timedelta(days=days)

    @property
    def status_css(self) -> str:
        return {"in_progress": "progress"}.get(self.status, self.status)

    @property
    def priority_css(self) -> str:
        return self.get_priority_display().lower()


class Comment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ticket_comments"
    )
    body = models.TextField()
    # The key safety flag: internal notes are never shown or sent to requesters.
    is_internal = models.BooleanField(default=False)
    source = models.CharField(max_length=8, choices=Ticket.Source.choices, default=Ticket.Source.WEB)
    created_at = models.DateTimeField(auto_now_add=True)
    # Internal notes belong to the department that wrote them. If an admin moves
    # the ticket, only notes marked share_on_move go with it to the new department.
    department = models.CharField(max_length=16, blank=True)
    share_on_move = models.BooleanField(
        "share with the new department if this ticket moves", default=False,
    )

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        kind = "Internal note" if self.is_internal else "Reply"
        return f"{kind} on #{self.ticket.number} by {self.author}"

    @property
    def department_label(self) -> str:
        """The department an internal note belongs to ("" for a reply)."""
        return departments.label(self.department)


class TicketEvent(models.Model):
    """
    One line of history. Values are stored as display text ("Waiting on User",
    "Sam Patel") so the history still reads correctly if names change later.
    """

    class Kind(models.TextChoices):
        STATUS = "status", "Status"
        PRIORITY = "priority", "Priority"
        ASSIGNEE = "assignee", "Assignee"
        CATEGORY = "category", "Category"
        # A possible password was sent anyway, or arrived by email.
        PASSWORD = "password", "Possible password"
        ARCHIVE = "archive", "Archive"
        DEPARTMENT = "department", "Department"
        MOVE_REQUEST = "move_request", "Move request"
        # Something taken out of the ticket (a pasted password, a file). Never what.
        REMOVED = "removed", "Removed"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", help_text="Empty for automatic changes.",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    old_value = models.CharField(max_length=200, blank=True)
    new_value = models.CharField(max_length=200, blank=True)
    note = models.CharField(max_length=200, blank=True, help_text='Why, e.g. "requester replied".')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        return f"#{self.ticket.number} {self.kind}: {self.old_value} -> {self.new_value}"


def attachment_path(instance: "Attachment", filename: str) -> str:
    # A random file name on disk; the original name is kept in the database.
    # Nothing a requester types ends up in a server path.
    ext = Path(filename).suffix.lower()[:10]
    return f"attachments/{instance.ticket_id}/{uuid.uuid4().hex}{ext}"


class Attachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    # Empty for files sent with the original request.
    comment = models.ForeignKey(
        Comment, on_delete=models.CASCADE, null=True, blank=True, related_name="attachments"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    file = models.FileField(upload_to=attachment_path)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        return self.original_name

    @property
    def is_internal(self) -> bool:
        """Files on an internal note are as private as the note."""
        return bool(self.comment_id and self.comment.is_internal)

    def get_absolute_url(self) -> str:
        return reverse("tickets:attachment", args=[self.pk, self.original_name])


class PasswordWarning(models.Model):
    """
    Audit trail of the "this might include a password" check
    (tickets/password_guard.py). One row each time someone:
      - was warned and took the password out before sending  (removed)
      - was warned and sent it anyway                         (sent anyway)
      - emailed the help desk something that looks like one   (emailed)
    The text that matched is never stored, only where and which checks matched.
    """

    class Place(models.TextChoices):
        NEW_REQUEST = "new_request", "New request"
        REPLY = "reply", "Reply"
        INTERNAL_NOTE = "internal_note", "Internal note"
        EMAIL = "email", "Email"

    class Outcome(models.TextChoices):
        REMOVED = "removed", "Removed before sending"
        SENT_ANYWAY = "sent_anyway", "Sent anyway"
        EMAILED = "emailed", "Arrived by email"

    # How the ticket's history line names the place.
    PLACE_PHRASES = {
        Place.NEW_REQUEST: "the request",
        Place.REPLY: "a reply",
        Place.INTERNAL_NOTE: "an internal note",
        Place.EMAIL: "an email",
    }

    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    ticket = models.ForeignKey(
        Ticket, on_delete=models.SET_NULL, null=True, blank=True, related_name="password_warnings"
    )
    comment = models.ForeignKey(
        Comment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="The reply or note it was in. Empty for a new request.",
    )
    place = models.CharField(max_length=16, choices=Place.choices)
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    fields = models.CharField(max_length=100, blank=True, help_text='Where it matched, e.g. "subject, description".')
    rules = models.CharField(
        max_length=100, blank=True, help_text='Which checks matched, e.g. "labelled, token". Never the text.'
    )

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "password warning"

    def __str__(self) -> str:
        where = f" on #{self.ticket.number}" if self.ticket_id else ""
        return f"{self.get_outcome_display()}: {self.get_place_display()}{where}"

"""
Ticket data model.

    Category       Admin-editable list: Hardware, Software, Access, Network, Other
    Ticket         One request from one person
    Comment        A public reply or an internal note (is_internal) on a ticket
    TicketEvent    History: who changed status/priority/assignee/category, and when
    Attachment     A file on a ticket, or on a specific comment
"""

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.urls import reverse


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

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name

    @property
    def label(self) -> str:
        """What requesters see in the dropdown."""
        return f"{self.name}: {self.hint}" if self.hint else self.name


class TicketQuerySet(models.QuerySet):
    def visible_to(self, user):
        """IT sees every ticket. Everyone else sees only their own."""
        if user.is_agent:
            return self
        return self.filter(requester=user)

    def open(self):
        return self.filter(status__in=Ticket.OPEN_STATUSES)


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

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

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        kind = "Internal note" if self.is_internal else "Reply"
        return f"{kind} on #{self.ticket.number} by {self.author}"


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

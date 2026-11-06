from django.db import models
from django.utils import timezone


class OutboundEmail(models.Model):
    """
    One email waiting to go out, or already sent.

    Ticket changes add rows here in the same database transaction, and the
    background worker (`manage.py run_worker`) sends them. A slow or broken
    mail server therefore never stops anyone saving a ticket, and failed
    sends are retried. One recipient per row, so nobody sees anyone else's
    address and each send succeeds or fails on its own.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.SET_NULL, null=True, blank=True, related_name="emails"
    )
    kind = models.CharField(max_length=40, help_text='What triggered it, e.g. "it_replied".')
    to = models.EmailField()
    subject = models.CharField(max_length=255)
    body_text = models.TextField()
    body_html = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "next_attempt_at"])]
        verbose_name = "outbound email"

    def __str__(self) -> str:
        return f"{self.subject} -> {self.to}"

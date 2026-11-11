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


class WorkerHeartbeat(models.Model):
    """
    What the background worker last did: a single row (pk 1), updated every
    round. Reports and Docker's health check read it to tell for sure that the
    worker is running, even on a quiet day with no emails to send.
    Written only through notifications.heartbeat.
    """

    started_at = models.DateTimeField(null=True, blank=True, help_text="When the worker last started.")
    round_at = models.DateTimeField(null=True, blank=True, help_text="When it last finished a round.")
    inbox_at = models.DateTimeField(null=True, blank=True, help_text="When it last tried to read the inbox.")
    inbox_ok_at = models.DateTimeField(null=True, blank=True,
                                       help_text="When it last read every mailbox without a problem.")
    inbox_error = models.TextField(blank=True, help_text="What went wrong on the last read; empty if nothing.")
    auto_close_at = models.DateTimeField(null=True, blank=True, help_text="When auto-close last ran.")
    auto_close_closed = models.PositiveIntegerField(default=0, help_text="How many it closed that time.")
    auto_close_error = models.TextField(blank=True, help_text="What went wrong that time; empty if nothing.")

    class Meta:
        verbose_name = "worker heartbeat"

    def __str__(self) -> str:
        return f"Worker, last round {self.round_at:%Y-%m-%d %H:%M:%S}" if self.round_at else "Worker, no round yet"

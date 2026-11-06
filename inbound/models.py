from django.db import models


class InboundEmail(models.Model):
    """
    One email that arrived at the help-desk mailbox, and what the app did with it.
    It also stops the same email being processed twice.
    """

    class Outcome(models.TextChoices):
        NEW_TICKET = "new_ticket", "Created a ticket"
        REPLY = "reply", "Added a reply"
        NOTE = "note", "Added as an internal note"
        IGNORED = "ignored", "Ignored"
        ERROR = "error", "Error"

    message_id = models.CharField(
        max_length=500, unique=True, help_text="The email's Internet Message-ID."
    )
    source = models.CharField(max_length=20, default="graph", help_text='"graph" or "command".')
    from_address = models.EmailField(blank=True)
    from_name = models.CharField(max_length=200, blank=True)
    subject = models.CharField(max_length=500, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    detail = models.TextField(blank=True, help_text="Why it was ignored, or what went wrong.")
    attempts = models.PositiveSmallIntegerField(default=1)
    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.SET_NULL, null=True, blank=True, related_name="inbound_emails"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "inbound email"

    def __str__(self) -> str:
        return f"{self.from_address}: {self.subject}"

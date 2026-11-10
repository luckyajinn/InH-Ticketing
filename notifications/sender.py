"""Send queued emails. Run by the background worker (`manage.py run_worker`)."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from notifications import graph
from notifications.models import OutboundEmail

logger = logging.getLogger(__name__)

# Wait longer after each failure: 1 minute, 5, 15, then an hour.
RETRY_DELAYS = [timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1)]


def send_pending(limit: int = 25) -> tuple[int, int]:
    """Send up to `limit` due emails. Returns (sent, failed this round)."""
    now = timezone.now()
    due = list(
        OutboundEmail.objects.filter(
            status=OutboundEmail.Status.PENDING, next_attempt_at__lte=now
        ).select_related("ticket__category").order_by("created_at")[:limit]
    )
    sent = failed = 0
    for email in due:
        # A department's ticket emails come from its own mailbox, so replies go back to that team.
        from_email = settings.DEFAULT_FROM_EMAIL
        if email.ticket_id and settings.DEPARTMENT_MAILBOXES:
            from_email = graph.sending_mailbox(email.ticket.category.department) or from_email
        message = EmailMultiAlternatives(
            subject=email.subject,
            body=email.body_text,
            from_email=from_email,
            to=[email.to],
        )
        message.attach_alternative(email.body_html, "text/html")
        try:
            message.send(fail_silently=False)
        except Exception as exc:  # any backend error: log it and retry later
            failed += 1
            email.attempts += 1
            email.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            if email.attempts >= settings.EMAIL_MAX_ATTEMPTS:
                email.status = OutboundEmail.Status.FAILED
                logger.error("Gave up on email %s to %s: %s", email.pk, email.to, email.last_error)
            else:
                delay = RETRY_DELAYS[min(email.attempts - 1, len(RETRY_DELAYS) - 1)]
                email.next_attempt_at = timezone.now() + delay
                logger.warning("Email %s to %s failed (attempt %s): %s",
                               email.pk, email.to, email.attempts, email.last_error)
            email.save(update_fields=["attempts", "last_error", "status", "next_attempt_at"])
        else:
            sent += 1
            email.status = OutboundEmail.Status.SENT
            email.sent_at = timezone.now()
            email.attempts += 1
            email.last_error = ""
            email.save(update_fields=["status", "sent_at", "attempts", "last_error"])
    return sent, failed

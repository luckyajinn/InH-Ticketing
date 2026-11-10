"""
Send email through Microsoft Graph, from the shared mailbox in HELPDESK_MAILBOX,
or from a department's own mailbox (DEPARTMENT_MAILBOXES) for its tickets.
Exchange Online must restrict the app to those mailboxes; see docs/email-setup.md.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend

from notifications import graph

logger = logging.getLogger(__name__)

# Kept for older imports; the error type now lives in notifications.graph.
GraphSendError = graph.GraphError


class GraphEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        if not settings.HELPDESK_MAILBOX:
            raise ImproperlyConfigured("EMAIL_BACKEND=graph needs HELPDESK_MAILBOX set in .env.")

    @staticmethod
    def _payload(message) -> dict:
        html = next((body for body, kind in getattr(message, "alternatives", []) if kind == "text/html"), None)
        return {
            "message": {
                "subject": message.subject,
                "body": {"contentType": "HTML", "content": html} if html
                else {"contentType": "Text", "content": message.body},
                "toRecipients": [{"emailAddress": {"address": a}} for a in message.to],
                "ccRecipients": [{"emailAddress": {"address": a}} for a in message.cc],
                # Ask Exchange not to send out-of-office or other automatic
                # replies to our notifications, which would loop back as email-in.
                "internetMessageHeaders": [{"name": "X-Auto-Response-Suppress", "value": "All"}],
            },
            "saveToSentItems": True,
        }

    def send_messages(self, email_messages) -> int:
        sent = 0
        for message in email_messages or []:
            try:
                # From the address the sender chose, if it's one of our mailboxes; never any other.
                sender = (message.from_email or "").lower()
                address = sender if sender in graph.own_addresses() else None
                graph.call("POST", f"{graph.mailbox(address)}/sendMail", json=self._payload(message), expected=(202,))
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
                logger.exception("Graph send failed")
        return sent

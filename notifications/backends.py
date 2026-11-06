"""
Send email through Microsoft Graph, from the shared mailbox in HELPDESK_MAILBOX.

Uses the same Entra app registration as sign-in, with an *application*
permission to send mail. Exchange Online must restrict that permission to
the one shared mailbox; see docs/email-setup.md.
"""

from __future__ import annotations

import logging

import msal
import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

_msal_app = None  # kept between sends so MSAL can reuse its cached token


def _app() -> msal.ConfidentialClientApplication:
    global _msal_app
    if _msal_app is None:
        _msal_app = msal.ConfidentialClientApplication(
            client_id=settings.ENTRA_CLIENT_ID,
            client_credential=settings.ENTRA_CLIENT_SECRET,
            authority=f"https://login.microsoftonline.com/{settings.ENTRA_TENANT_ID}",
        )
    return _msal_app


class GraphSendError(Exception):
    pass


class GraphEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        if not settings.HELPDESK_MAILBOX:
            raise ImproperlyConfigured("EMAIL_BACKEND=graph needs HELPDESK_MAILBOX set in .env.")

    def _token(self) -> str:
        result = _app().acquire_token_for_client(scopes=GRAPH_SCOPE)
        if "access_token" not in result:
            raise GraphSendError(
                f"Couldn't get a Graph token: {result.get('error')}: {result.get('error_description', '')[:300]}"
            )
        return result["access_token"]

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
            },
            "saveToSentItems": True,
        }

    def send_messages(self, email_messages) -> int:
        if not email_messages:
            return 0
        sent = 0
        try:
            token = self._token()
        except Exception:
            if self.fail_silently:
                return 0
            raise
        url = f"{GRAPH}/users/{settings.HELPDESK_MAILBOX}/sendMail"
        for message in email_messages:
            try:
                response = requests.post(
                    url, json=self._payload(message), timeout=30,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code != 202:
                    raise GraphSendError(f"Graph returned {response.status_code}: {response.text[:300]}")
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
                logger.exception("Graph send failed")
        return sent

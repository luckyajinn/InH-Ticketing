"""
A small Microsoft Graph client, shared by sending (notifications/backends.py)
and reading (inbound/graph_inbox.py) the help-desk mailbox.

It signs in as the app itself (no user), with the same Entra app
registration as staff sign-in. Exchange Online limits what it may touch to
the one shared mailbox; see docs/email-setup.md.
"""

from __future__ import annotations

import msal
import requests
from django.conf import settings

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = ["https://graph.microsoft.com/.default"]

_msal_app = None  # kept between calls so MSAL can reuse its cached token


class GraphError(Exception):
    pass


def _msal() -> msal.ConfidentialClientApplication:
    global _msal_app
    if _msal_app is None:
        _msal_app = msal.ConfidentialClientApplication(
            client_id=settings.ENTRA_CLIENT_ID,
            client_credential=settings.ENTRA_CLIENT_SECRET,
            authority=f"https://login.microsoftonline.com/{settings.ENTRA_TENANT_ID}",
        )
    return _msal_app


def token() -> str:
    result = _msal().acquire_token_for_client(scopes=SCOPE)
    if "access_token" not in result:
        raise GraphError(
            f"Couldn't get a Graph token: {result.get('error')}: "
            f"{(result.get('error_description') or '')[:300]}"
        )
    return result["access_token"]


def mailbox() -> str:
    """The URL path of the help-desk mailbox, e.g. /users/helpdesk-test@contoso.com"""
    if not settings.HELPDESK_MAILBOX:
        raise GraphError("HELPDESK_MAILBOX isn't set in .env.")
    return f"/users/{settings.HELPDESK_MAILBOX}"


def call(method: str, path: str, *, json=None, params=None, headers=None, expected=(200,)):
    url = path if path.startswith("https://") else GRAPH + path
    response = requests.request(
        method, url, json=json, params=params, timeout=30,
        headers={"Authorization": f"Bearer {token()}", **(headers or {})},
    )
    if response.status_code not in expected:
        raise GraphError(f"Graph {method} returned {response.status_code}: {response.text[:300]}")
    return response

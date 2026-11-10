"""
A small Microsoft Graph client, shared by sending (notifications/backends.py)
and reading (inbound/graph_inbox.py) the help-desk mailbox, and each
department's mailbox (DEPARTMENT_MAILBOXES).

It signs in as the app itself (no user), with the same Entra app
registration as staff sign-in. Exchange Online limits what it may touch to
those shared mailboxes; see docs/email-setup.md.
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


def mailbox(address: str | None = None) -> str:
    """The URL path of a mailbox (the help-desk one by default), e.g. /users/helpdesk-test@contoso.com"""
    if address:
        return f"/users/{address}"
    if not settings.HELPDESK_MAILBOX:
        raise GraphError("HELPDESK_MAILBOX isn't set in .env.")
    return f"/users/{settings.HELPDESK_MAILBOX}"


def mailboxes() -> list[tuple[str, str, str]]:
    """Every mailbox the app reads: (department, address, folder). Folder "" = the Inbox."""
    result = [("it", settings.HELPDESK_MAILBOX.lower(), "")] if settings.HELPDESK_MAILBOX else []
    for department, box in settings.DEPARTMENT_MAILBOXES.items():
        result.append((department, box["address"], box["folder"]))
    return result


def own_addresses() -> set[str]:
    """The app's own mailboxes: email from these is never turned into a ticket."""
    return {address for _, address, _ in mailboxes()}


def sending_mailbox(department: str) -> str:
    """Which mailbox a department's ticket emails go out from: its own, or the help-desk one."""
    box = settings.DEPARTMENT_MAILBOXES.get(department)
    return box["address"] if box else settings.HELPDESK_MAILBOX


def call(method: str, path: str, *, json=None, params=None, headers=None, expected=(200,)):
    url = path if path.startswith("https://") else GRAPH + path
    response = requests.request(
        method, url, json=json, params=params, timeout=30,
        headers={"Authorization": f"Bearer {token()}", **(headers or {})},
    )
    if response.status_code not in expected:
        raise GraphError(f"Graph {method} returned {response.status_code}: {response.text[:300]}")
    return response

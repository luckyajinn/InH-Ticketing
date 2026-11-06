"""
Read the help-desk mailbox through Microsoft Graph. Called by the worker.

For each unread email in the Inbox: process it, then mark it read and move
it to the "Processed by InH-Ticketing" folder. An email that fails is left
unread and retried, at most INBOUND_MAX_ATTEMPTS times; after that it's
marked read but left in the Inbox for a person to look at.
"""

from __future__ import annotations

import base64
import logging

from django.conf import settings
from django.utils.dateparse import parse_datetime

from inbound.processing import IncomingAttachment, IncomingMessage, process, record_error
from notifications import graph

logger = logging.getLogger(__name__)

# Ask for plain text, so we never store or render HTML from outside.
TEXT = {"Prefer": 'outlook.body-content-type="text"'}
FIELDS = ",".join([
    "id", "subject", "from", "receivedDateTime", "internetMessageId",
    "internetMessageHeaders", "hasAttachments", "body", "uniqueBody",
])
_folder_id = None


def _processed_folder() -> str:
    """The id of the folder processed emails move to, created on first use."""
    global _folder_id
    if _folder_id:
        return _folder_id
    name = settings.INBOUND_PROCESSED_FOLDER
    found = graph.call("GET", f"{graph.mailbox()}/mailFolders",
                       params={"$filter": f"displayName eq '{name}'", "$select": "id"}).json()
    if found.get("value"):
        _folder_id = found["value"][0]["id"]
    else:
        _folder_id = graph.call("POST", f"{graph.mailbox()}/mailFolders",
                                json={"displayName": name}, expected=(201,)).json()["id"]
    return _folder_id


def _attachments(graph_id: str) -> list[IncomingAttachment]:
    data = graph.call("GET", f"{graph.mailbox()}/messages/{graph_id}/attachments").json()
    result = []
    for item in data.get("value", []):
        if item.get("@odata.type") != "#microsoft.graph.fileAttachment":
            continue  # attached emails and links aren't files
        result.append(IncomingAttachment(
            name=item.get("name") or "attachment",
            content_type=item.get("contentType") or "",
            data=base64.b64decode(item.get("contentBytes") or ""),
            is_inline=bool(item.get("isInline")),
        ))
    return result


def to_message(item: dict) -> IncomingMessage:
    sender = (item.get("from") or {}).get("emailAddress") or {}
    headers = {h["name"]: h.get("value", "") for h in item.get("internetMessageHeaders") or []}
    unique = (item.get("uniqueBody") or {}).get("content")
    return IncomingMessage(
        message_id=item.get("internetMessageId") or f"graph:{item['id']}",
        from_address=sender.get("address", ""),
        from_name=sender.get("name", ""),
        subject=item.get("subject") or "",
        body_text=(item.get("body") or {}).get("content", ""),
        new_text=unique if unique is not None else None,
        headers=headers,
        received_at=parse_datetime(item["receivedDateTime"]) if item.get("receivedDateTime") else None,
        source="graph",
    )


def _mark_read(graph_id: str) -> None:
    graph.call("PATCH", f"{graph.mailbox()}/messages/{graph_id}", json={"isRead": True})


def _move_to_processed(graph_id: str) -> None:
    graph.call("POST", f"{graph.mailbox()}/messages/{graph_id}/move",
               json={"destinationId": _processed_folder()}, expected=(200, 201))


def poll(limit: int = 25) -> tuple[int, int]:
    """Process up to `limit` unread emails. Returns (handled, failed)."""
    items = graph.call(
        "GET", f"{graph.mailbox()}/mailFolders/inbox/messages", headers=TEXT,
        params={"$filter": "isRead eq false", "$top": str(limit), "$select": FIELDS},
    ).json().get("value", [])
    items.sort(key=lambda i: i.get("receivedDateTime") or "")  # oldest first

    handled = failed = 0
    for item in items:
        message = to_message(item)
        try:
            if item.get("hasAttachments"):
                message.attachments = _attachments(item["id"])
            result = process(message)
        except Exception as exc:
            failed += 1
            row = record_error(message, exc)
            if row.attempts >= settings.INBOUND_MAX_ATTEMPTS:
                _mark_read(item["id"])  # stop retrying; a person needs to look at it
            continue
        handled += 1
        _mark_read(item["id"])
        _move_to_processed(item["id"])
        logger.info("Email from %s: %s %s", message.from_address, result.outcome, result.detail)
    return handled, failed

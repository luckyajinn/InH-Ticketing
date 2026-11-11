"""
Read the help-desk mailbox, and each department's (DEPARTMENT_MAILBOXES),
through Microsoft Graph. Called by the worker.

For each unread email in the Inbox (or the department's chosen folder):
process it, then mark it read and move it to the "Processed by InH-Ticketing"
folder. An email that fails is left unread and retried, at most
INBOUND_MAX_ATTEMPTS times; after that it's marked read but left where it is
for a person to look at.
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
_folder_ids: dict[str, str] = {}  # (mailbox, folder name) -> Graph folder id, found once


def _quote(name: str) -> str:
    return name.replace("'", "''")  # OData string literal


def _find_folder(box: str, name: str) -> str | None:
    """A folder by its name: at the top of the mailbox, or inside the Inbox."""
    for path in (f"{box}/mailFolders", f"{box}/mailFolders/inbox/childFolders"):
        found = graph.call("GET", path, params={"$filter": f"displayName eq '{_quote(name)}'", "$select": "id"}).json()
        if found.get("value"):
            return found["value"][0]["id"]
    return None


def _processed_folder(box: str) -> str:
    """The id of the folder processed emails move to, created on first use."""
    key = f"{box}|processed"
    if key not in _folder_ids:
        name = settings.INBOUND_PROCESSED_FOLDER
        _folder_ids[key] = _find_folder(box, name) or graph.call(
            "POST", f"{box}/mailFolders", json={"displayName": name}, expected=(201,)
        ).json()["id"]
    return _folder_ids[key]


def _read_folder(box: str, folder: str) -> str:
    """The Graph path of the folder to read: the Inbox, or a department's chosen folder."""
    if not folder:
        return f"{box}/mailFolders/inbox"
    key = f"{box}|{folder}"
    if key not in _folder_ids:
        found = _find_folder(box, folder)
        if not found:
            raise graph.GraphError(f"No folder called {folder!r} in {box} (DEPARTMENT_MAILBOXES).")
        _folder_ids[key] = found
    return f"{box}/mailFolders/{_folder_ids[key]}"


def _attachments(box: str, graph_id: str) -> list[IncomingAttachment]:
    data = graph.call("GET", f"{box}/messages/{graph_id}/attachments").json()
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
    # A header can appear more than once (Authentication-Results, Received): keep every value.
    headers: dict[str, str] = {}
    for h in item.get("internetMessageHeaders") or []:
        name, value = h.get("name", ""), h.get("value", "")
        headers[name] = f"{headers[name]}\n{value}" if name in headers else value
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


def _mark_read(box: str, graph_id: str) -> None:
    graph.call("PATCH", f"{box}/messages/{graph_id}", json={"isRead": True})


def _move_to_processed(box: str, graph_id: str) -> None:
    graph.call("POST", f"{box}/messages/{graph_id}/move",
               json={"destinationId": _processed_folder(box)}, expected=(200, 201))


def poll(limit: int = 25, problems: list[str] | None = None) -> tuple[int, int]:
    """
    Process up to `limit` unread emails from each mailbox. Returns (handled, failed).
    Each mailbox that couldn't be read adds a line to `problems`, if given
    (the worker's heartbeat, shown in Reports).
    """
    handled = failed = 0
    errors = []
    boxes = graph.mailboxes()
    for department, address, folder in boxes:
        try:
            done, broken = poll_mailbox(department, address, folder, limit)
        except graph.GraphError as exc:
            # One mailbox not set up yet (permissions, a folder name) mustn't stop the others.
            logger.error("Couldn't read %s: %s", address, exc)
            errors.append(exc)
            if problems is not None:
                problems.append(f"{address}: {exc}")
            continue
        handled += done
        failed += broken
    if errors and len(errors) == len(boxes):
        raise errors[0]  # none could be read: the worker says so
    return handled, failed + len(errors)


def poll_mailbox(department: str, address: str, folder: str, limit: int = 25) -> tuple[int, int]:
    box = graph.mailbox(address)
    items = graph.call(
        "GET", f"{_read_folder(box, folder)}/messages", headers=TEXT,
        params={"$filter": "isRead eq false", "$top": str(limit), "$select": FIELDS},
    ).json().get("value", [])
    items.sort(key=lambda i: i.get("receivedDateTime") or "")  # oldest first

    handled = failed = 0
    for item in items:
        message = to_message(item)
        message.department = department
        try:
            if item.get("hasAttachments"):
                message.attachments = _attachments(box, item["id"])
            result = process(message)
        except Exception as exc:
            failed += 1
            row = record_error(message, exc)
            if row.attempts >= settings.INBOUND_MAX_ATTEMPTS:
                _mark_read(box, item["id"])  # stop retrying; a person needs to look at it
            continue
        handled += 1
        _mark_read(box, item["id"])
        _move_to_processed(box, item["id"])
        logger.info("Email to %s from %s: %s %s", address, message.from_address, result.outcome, result.detail)
    return handled, failed

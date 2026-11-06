"""Read a saved email (.eml file, e.g. dragged out of Outlook) into an IncomingMessage."""

from __future__ import annotations

import email
import uuid
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from inbound.processing import IncomingAttachment, IncomingMessage


class _TextOnly(HTMLParser):
    """Crude HTML-to-text for emails with no plain-text part."""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextOnly()
    parser.feed(html)
    lines = [line.strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def from_bytes(raw: bytes) -> IncomingMessage:
    msg = email.message_from_bytes(raw, policy=policy.default)
    name, address = parseaddr(str(msg.get("From", "")))
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        content = body.get_content()
        text = html_to_text(content) if body.get_content_type() == "text/html" else content

    attachments = []
    for part in msg.iter_attachments():
        data = part.get_payload(decode=True) or b""
        attachments.append(IncomingAttachment(
            name=part.get_filename() or "attachment",
            content_type=part.get_content_type(),
            data=data,
            is_inline=part.get_content_disposition() == "inline" and bool(part.get("Content-ID")),
        ))

    received = None
    if msg.get("Date"):
        try:
            received = parsedate_to_datetime(str(msg["Date"]))
        except (TypeError, ValueError):
            received = None

    return IncomingMessage(
        message_id=str(msg.get("Message-ID") or f"<{uuid.uuid4().hex}@ingest.local>").strip(),
        from_address=address,
        from_name=name,
        subject=str(msg.get("Subject", "")),
        body_text=text,
        new_text=None,  # .eml has no "new part only" view; strip_quoted() handles replies
        headers={k: str(v) for k, v in msg.items()},
        attachments=attachments,
        received_at=received,
        source="command",
    )

"""Small text helpers for email-in: subjects, ticket tags, quoted replies, auto-replies."""

from __future__ import annotations

import re

TICKET_TAG = re.compile(r"\[#(\d{1,9})\]")
# "Re:", "RE:", "Fwd:", "FW:", "AW:" (German), "SV:" (Nordic), "Automatic reply:" ...
SUBJECT_PREFIX = re.compile(
    r"^\s*((re|fw|fwd|aw|sv|wg|antw|automatic reply|auto(matic)?[- ]?reply|out of office)\s*(\[\d+\])?\s*[:：]\s*)+",
    re.IGNORECASE,
)


def find_ticket_number(subject: str) -> int | None:
    match = TICKET_TAG.search(subject or "")
    return int(match.group(1)) if match else None


def clean_subject(subject: str) -> str:
    """'RE: [#1001] Printer jammed' -> 'Printer jammed'"""
    text = TICKET_TAG.sub("", subject or "")
    previous = None
    while previous != text:  # prefixes can come back after removing the tag
        previous = text
        text = SUBJECT_PREFIX.sub("", text).strip()
    return text[:200] or "(no subject)"


# Lines where the quoted earlier email starts, in the common mail apps.
_QUOTE_STARTS = [
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE),       # Outlook (older)
    re.compile(r"^_{10,}\s*$"),                                               # Outlook separator line
    re.compile(r"^On .{0,200}\bwrote:\s*$", re.IGNORECASE),                   # Gmail, Apple Mail
    re.compile(r"^-{2,}\s*Forwarded message\s*-{2,}", re.IGNORECASE),
]
_HEADER_BLOCK = re.compile(r"^(From|Sent|Date|To|Subject)\s*:", re.IGNORECASE)


def strip_quoted(text: str) -> str:
    """
    Keep only the new part of a reply. Microsoft Graph already does this for
    mail it reads (uniqueBody); this is the fallback for .eml files and other sources.
    """
    lines = (text or "").replace("\r\n", "\n").split("\n")
    kept: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if any(p.match(stripped) for p in _QUOTE_STARTS):
            break
        # Outlook: "From: ..." followed within a few lines by "Sent:" / "To:"
        if stripped.lower().startswith("from:") and any(
            _HEADER_BLOCK.match(nxt.strip()) for nxt in lines[i + 1:i + 4]
        ):
            break
        if stripped.startswith(">"):
            continue
        kept.append(line)
    result = "\n".join(kept).strip()
    return result or (text or "").strip()


_AUTOMATIC_SUBJECT = re.compile(
    r"^\s*(automatic reply|auto(matic)?[- ]?reply|out of (the )?office|undeliverable|"
    r"delivery (status notification|has failed)|mail delivery (failed|failure)|returned mail)\b",
    re.IGNORECASE,
)


def is_automatic(headers: dict[str, str], from_address: str, subject: str = "") -> str:
    """
    Why this looks like an automatic email (out-of-office, bounce, mailing
    list), or "" if a person sent it. Answering automatic email is how loops start.
    Headers are the reliable signal; the subject check catches mail systems
    that don't set them.
    """
    if _AUTOMATIC_SUBJECT.match(subject or ""):
        return "subject looks automatic"
    h = {k.lower(): (v or "").strip().lower() for k, v in headers.items()}
    if h.get("auto-submitted", "no") not in ("", "no"):
        return f"Auto-Submitted: {h['auto-submitted']}"
    if h.get("precedence") in ("bulk", "junk", "list", "auto_reply"):
        return f"Precedence: {h['precedence']}"
    for name in ("x-autoreply", "x-autorespond", "x-auto-response-suppress-reply", "list-id", "list-unsubscribe"):
        if name in h:
            return f"{name} header"
    if h.get("x-ms-exchange-generated-message-source"):
        return "Exchange-generated message"
    local = (from_address or "").split("@", 1)[0].lower()
    if local in ("mailer-daemon", "postmaster", "no-reply", "noreply", "do-not-reply", "donotreply"):
        return f"sent from {local}@"
    return ""

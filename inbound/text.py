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


# ---------------------------------------------------------------------------
# Email signatures (the CodeTwo block: name, title, address, phone and fax,
# website, logo placeholder, "consider the environment" and the
# confidentiality notice). Tickets show them folded behind "Show email
# signature", so IT sees the request first but can still find the number.
# ---------------------------------------------------------------------------

_SIG_DELIMITER = re.compile(r"^--\s*$")
_SIGN_OFF = re.compile(
    r"^(thanks|thank you|many thanks|thanks again|thx|regards|best regards|kind regards|warm regards"
    r"|best wishes|best|cheers|sincerely|respectfully|all the best|have a (great|good|nice) (day|week|weekend))"
    r"[\s,.!-]*$",
    re.IGNORECASE,
)
# A line that's part of contact details.
_CONTACT = re.compile(
    r"\b(tel|telephone|phone|ph|mobile|mob|cell|fax|direct|office|main|ext|t|f|m|p|o|d)\b\.?\s*[:.]?\s*[+(]?\d"
    r"|^\s*[+(]?\d[\d\s().-]{7,}\d\s*$"                         # a phone number on its own
    r"|^\s*(www\.\S+|https?://\S+|[\w-]+\.(com|net|org|co|us|io)\S*)\s*$"   # a website on its own
    r"|^\s*[\w.+-]+@[\w-]+\.[\w.]+\s*$"                          # an email address on its own
    r"|\b\d{2,6}\s+[A-Za-z]+(\s[A-Za-z]+){0,3}\s(st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|way"
    r"|lane|ln|ct|court|pkwy|parkway|hwy|highway|pl|place|cir|circle)\b"   # a street address
    r"|\b(suite|ste\.?|unit|floor)\s+\d",
    re.IGNORECASE,
)
# Lines that are always signature or mail-app boilerplate.
_BOILERPLATE = re.compile(
    r"consider the environment|before printing (this|the)|think before you print"
    r"|confidential(ity)?\s+(notice|statement|warning)|privileged (and|&) confidential"
    r"|this (e-?mail|message|communication)\b.{0,60}\b(confidential|privileged|intended (only|solely))"
    r"|if you (have )?received this (e-?mail|message|communication) in error"
    r"|\[cid:|\[image|\[logo|<image\d+\.(png|jpe?g|gif)>"
    r"|^sent from my \w+|^get outlook for",
    re.IGNORECASE,
)


def _paragraphs_with_boilerplate(lines: list[str]) -> set[int]:
    """
    Line numbers that are boilerplate. Notices wrap onto many lines, so the rest
    of a paragraph after a match counts too, and so do long wrapped lines just
    before it; short lines before it ("Thanks,", a name) are left alone.
    """
    flagged: set[int] = set()
    block: list[int] = []
    for i, line in enumerate(lines + [""]):
        if line.strip():
            block.append(i)
            continue
        first = next((k for k, j in enumerate(block) if _BOILERPLATE.search(lines[j])), None)
        if first is not None:
            flagged.update(block[first:])
            for j in reversed(block[:first]):
                text = lines[j].strip()
                if len(text) <= 40 or _SIGN_OFF.match(text):
                    break
                flagged.add(j)
        block = []
    return flagged


def _looks_like_name_line(line: str) -> bool:
    """'Dana Whitfield', 'Quality Analyst | McKenna Labs': short, title case, no sentence."""
    if len(line) > 60 or line[-1] in ".?!:":
        return False
    words = [w for w in re.split(r"[\s|,/–—-]+", line) if any(c.isalpha() for c in w)]
    if not 1 <= len(words) <= 8:
        return False
    capitalised = sum(1 for w in words if w[0].isupper() or w.isupper())
    return capitalised / len(words) >= 0.6


def split_signature(text: str) -> tuple[str, str]:
    """
    (message, signature). The signature is "" when none is found, or when
    folding it would leave nothing to read. It needs at least two signs of a
    signature (contact lines or boilerplate) before it folds anything.
    """
    text = (text or "").replace("\r\n", "\n")
    lines = text.split("\n")

    delimiter = next((i for i, line in enumerate(lines) if i > 0 and _SIG_DELIMITER.match(line)), None)
    if delimiter is not None:
        start = delimiter
    else:
        boiler = _paragraphs_with_boilerplate(lines)
        start, signals, names = None, 0, 0
        i = len(lines) - 1
        while i >= 0:
            line = lines[i].strip()
            if not line:
                i -= 1
                continue
            if i in boiler or _CONTACT.search(line):
                signals += 1
                names = 0
                start = i
            elif _SIGN_OFF.match(line):
                break  # "Thanks," stays with the message
            elif start is not None and names < 4 and _looks_like_name_line(line):
                names += 1
                start = i
            else:
                break
            i -= 1
        if start is None or signals < 2:
            return text.strip(), ""

    message = "\n".join(lines[:start]).strip()
    signature = "\n".join(lines[start:]).strip()
    if not message or not signature:
        return text.strip(), ""
    return message, signature


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

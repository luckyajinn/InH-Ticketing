"""
Turn one incoming email into a ticket, a reply, or nothing.

Both the Graph inbox reader and the `ingest_email` command build an
IncomingMessage and call process(), so they follow exactly the same rules:

  1. Seen this Message-ID before?                  -> skip (never process twice)
  2. Automatic email (out-of-office, bounce, list)? -> ignore (stops mail loops)
  3. From our own mailbox, or a domain we don't accept? -> ignore (no reply sent)
  4. Subject has [#1001] and that ticket exists:
       from the requester or IT  -> public reply (Closed? -> a new follow-up ticket)
       from anyone else          -> internal note for IT
  5. Otherwise                   -> a new ticket from the sender

Anything that looks like a password is logged in the password audit trail and
flagged in the ticket's history for IT (tickets/password_guard.py): an email
can't be warned about before it's sent, the way the web forms are.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.template.defaultfilters import filesizeformat

from accounts.models import User
from inbound.models import InboundEmail
from inbound.text import clean_subject, find_ticket_number, is_automatic, strip_quoted
from tickets import password_guard, services
from tickets.models import Category, Ticket

logger = logging.getLogger(__name__)
Outcome = InboundEmail.Outcome
MAX_BODY = 20_000


@dataclass
class IncomingAttachment:
    name: str
    content_type: str
    data: bytes
    is_inline: bool = False


@dataclass
class IncomingMessage:
    message_id: str
    from_address: str
    from_name: str = ""
    subject: str = ""
    body_text: str = ""
    # Only the new part of a reply, when the source can tell (Graph's uniqueBody).
    new_text: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    attachments: list[IncomingAttachment] = field(default_factory=list)
    received_at: datetime | None = None
    source: str = "graph"


@dataclass
class Result:
    outcome: str
    detail: str = ""
    ticket: Ticket | None = None
    record: InboundEmail | None = None
    duplicate: bool = False


def _allowed_domain(address: str) -> bool:
    allowed = settings.INBOUND_ALLOWED_DOMAINS
    return not allowed or address.rsplit("@", 1)[-1].lower() in allowed


def _sender(address: str, name: str) -> User:
    """
    The person who sent it. Staff who have never signed in get an account now;
    it's linked to their Microsoft 365 account the first time they sign in.
    """
    user = User.objects.filter(email__iexact=address).order_by("-is_active", "pk").first()
    if user:
        return user
    return User.objects.create(
        username=f"email:{address.lower()}"[:150],
        email=address.lower(),
        display_name=(name or address)[:255],
        role=User.Role.REQUESTER,
    )


def _files(message: IncomingMessage) -> tuple[list[ContentFile], list[str]]:
    """Attachments we keep, and a note about any we didn't."""
    kept, skipped = [], []
    for att in message.attachments:
        if att.is_inline:
            continue  # logos and pictures inside signatures
        ext = Path(att.name).suffix.lower()
        if ext not in settings.ATTACHMENT_EXTENSIONS:
            skipped.append(f"{att.name} (file type not accepted)")
        elif len(att.data) > settings.ATTACHMENT_MAX_BYTES:
            skipped.append(f"{att.name} ({filesizeformat(len(att.data))}, over the limit)")
        elif len(kept) >= settings.ATTACHMENT_MAX_FILES:
            skipped.append(f"{att.name} (too many files)")
        else:
            upload = ContentFile(att.data, name=Path(att.name).name or f"attachment-{uuid.uuid4().hex[:6]}")
            upload.content_type = att.content_type
            kept.append(upload)
    return kept, skipped


def _with_skipped_note(body: str, skipped: list[str]) -> str:
    if not skipped:
        return body
    return body + "\n\n[Not attached: " + "; ".join(skipped) + "]"


def process(message: IncomingMessage) -> Result:
    message.from_address = (message.from_address or "").strip().lower()
    existing = InboundEmail.objects.filter(message_id=message.message_id).first()
    if existing and existing.outcome != Outcome.ERROR:
        return Result(existing.outcome, existing.detail, existing.ticket, existing, duplicate=True)

    def record(outcome, detail="", ticket=None) -> Result:
        fields = {
            "source": message.source, "from_address": message.from_address,
            "from_name": message.from_name[:200], "subject": message.subject[:500],
            "received_at": message.received_at, "outcome": outcome, "detail": detail, "ticket": ticket,
        }
        row, created = InboundEmail.objects.update_or_create(message_id=message.message_id, defaults=fields)
        return Result(outcome, detail, ticket, row)

    # Rules 2 and 3: things we never answer.
    automatic = is_automatic(message.headers, message.from_address, message.subject)
    if automatic:
        return record(Outcome.IGNORED, f"Automatic email ({automatic}).")
    if not message.from_address or "@" not in message.from_address:
        return record(Outcome.IGNORED, "No sender address.")
    if settings.HELPDESK_MAILBOX and message.from_address == settings.HELPDESK_MAILBOX.lower():
        return record(Outcome.IGNORED, "Sent from the help-desk mailbox itself.")
    if not _allowed_domain(message.from_address):
        return record(Outcome.IGNORED, "Sender's domain isn't accepted (INBOUND_ALLOWED_DOMAINS).")

    with transaction.atomic():
        sender = _sender(message.from_address, message.from_name)
        if not sender.is_active:
            return record(Outcome.IGNORED, "Sender's account is disabled.")
        files, skipped = _files(message)
        number = find_ticket_number(message.subject)
        ticket = None
        if number:
            ticket = Ticket.objects.select_related("requester", "assignee").filter(
                pk=Ticket.pk_from_number(number)
            ).first()

        if ticket:
            reply = message.new_text if message.new_text is not None else strip_quoted(message.body_text)
            reply = _with_skipped_note(reply.strip()[:MAX_BODY] or "(empty email)", skipped)
            is_party = sender.pk == ticket.requester_id or sender.is_agent

            if not is_party:
                note = services.add_email_from_third_party(ticket=ticket, sender=sender, body=reply, files=files)
                password_guard.record_email(sender=sender, ticket=ticket, comment=note, texts={"body": reply})
                return record(Outcome.NOTE, f"{sender} isn't the requester or IT.", ticket)

            if ticket.status == Ticket.Status.CLOSED and not sender.is_agent:
                subject = clean_subject(message.subject)
                follow_up = services.create_ticket(
                    requester=sender, subject=subject,
                    description=f"(Follow-up to closed ticket #{ticket.number})\n\n{reply}",
                    category=ticket.category, files=files, source=Ticket.Source.EMAIL,
                    follows_up=ticket,
                )
                password_guard.record_email(
                    sender=sender, ticket=follow_up, texts={"subject": subject, "description": reply}
                )
                return record(Outcome.NEW_TICKET, f"#{ticket.number} was closed, so this is a new ticket.", follow_up)

            comment = services.add_comment(
                ticket=ticket, author=sender, body=reply, files=files, source=Ticket.Source.EMAIL
            )
            password_guard.record_email(sender=sender, ticket=ticket, comment=comment, texts={"body": reply})
            return record(Outcome.REPLY, "", ticket)

        # Rule 5: a new ticket.
        description = _with_skipped_note((message.body_text or "").strip()[:MAX_BODY] or "(empty email)", skipped)
        category = (
            Category.objects.filter(name__iexact=settings.INBOUND_DEFAULT_CATEGORY).first()
            or Category.objects.filter(is_active=True).last()
        )
        subject = clean_subject(message.subject)
        new = services.create_ticket(
            requester=sender, subject=subject, description=description,
            category=category, files=files, source=Ticket.Source.EMAIL,
        )
        password_guard.record_email(sender=sender, ticket=new, texts={"subject": subject, "description": description})
        detail = f"Subject mentioned #{number}, which doesn't exist." if number else ""
        return record(Outcome.NEW_TICKET, detail, new)


def record_error(message: IncomingMessage, error: Exception) -> InboundEmail:
    """Remember a failure so the email is retried, but only a few times."""
    row, created = InboundEmail.objects.get_or_create(
        message_id=message.message_id,
        defaults={
            "source": message.source, "from_address": (message.from_address or "")[:254],
            "subject": (message.subject or "")[:500], "received_at": message.received_at,
            "outcome": Outcome.ERROR, "detail": f"{type(error).__name__}: {error}"[:2000],
        },
    )
    if not created:
        row.attempts += 1
        row.outcome = Outcome.ERROR
        row.detail = f"{type(error).__name__}: {error}"[:2000]
        row.save(update_fields=["attempts", "outcome", "detail", "updated_at"])
    logger.error("Couldn't process email %s (attempt %s): %s", message.message_id, row.attempts, row.detail)
    return row

"""
Ticket rules. Every change to a ticket goes through these functions, so the
rules and the history log live in one place instead of being spread across views.

Automatic status changes:
    New -> Open              when IT replies publicly or assigns the ticket
    Waiting on User -> Open  when the requester replies
    Resolved -> Open         when the requester replies or says it's still a problem
"""

from __future__ import annotations

from pathlib import Path

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from tickets.models import Attachment, Category, Comment, Ticket, TicketEvent

Status = Ticket.Status
_UNSET = object()
STATUS_FIELDS = ["status", "resolved_at", "closed_at"]


def _save(ticket: Ticket, fields) -> None:
    # Save only what changed, so two people editing the same ticket at once
    # don't overwrite each other's other fields with stale values.
    ticket.save(update_fields=sorted(set(fields) | {"updated_at"}))


def _log(ticket, actor, kind, old="", new="", note=""):
    TicketEvent.objects.create(
        ticket=ticket, actor=actor, kind=kind,
        old_value=str(old)[:200], new_value=str(new)[:200], note=note[:200],
    )


def _set_status(ticket: Ticket, actor, new_status: str, note: str = "") -> bool:
    """Change status, keep resolved_at/closed_at right, and log it. Caller saves."""
    if ticket.status == new_status:
        return False
    old_label = ticket.get_status_display()
    ticket.status = new_status
    now = timezone.now()
    if new_status == Status.RESOLVED:
        ticket.resolved_at = now
        ticket.closed_at = None
    elif new_status == Status.CLOSED:
        ticket.resolved_at = ticket.resolved_at or now
        ticket.closed_at = now
    else:
        ticket.resolved_at = None
        ticket.closed_at = None
    _log(ticket, actor, TicketEvent.Kind.STATUS, old_label, ticket.get_status_display(), note)
    return True


def _save_attachments(ticket: Ticket, user, files, comment: Comment | None = None) -> None:
    for upload in files or ():
        Attachment.objects.create(
            ticket=ticket,
            comment=comment,
            uploaded_by=user,
            file=upload,
            original_name=Path(upload.name).name[:255],
            size=upload.size,
            content_type=(getattr(upload, "content_type", "") or "")[:100],
        )


@transaction.atomic
def create_ticket(
    *, requester, subject: str, description: str, category: Category,
    is_blocking: bool = False, files=(), source: str = Ticket.Source.WEB,
) -> Ticket:
    ticket = Ticket.objects.create(
        requester=requester,
        subject=subject.strip(),
        description=description.strip(),
        category=category,
        is_blocking=is_blocking,
        source=source,
    )
    _save_attachments(ticket, requester, files)
    return ticket


@transaction.atomic
def add_comment(
    *, ticket: Ticket, author, body: str, is_internal: bool = False, files=(),
    source: str = Ticket.Source.WEB,
) -> Comment:
    if is_internal and not author.is_agent:
        raise PermissionDenied("Only IT can add internal notes.")
    is_requester = author.pk == ticket.requester_id
    if not is_requester and not author.is_agent:
        raise PermissionDenied("You can't reply to this ticket.")
    if is_requester and not author.is_agent and ticket.status == Status.CLOSED:
        raise PermissionDenied("This ticket is closed.")

    comment = Comment.objects.create(
        ticket=ticket, author=author, body=body.strip(), is_internal=is_internal, source=source
    )
    _save_attachments(ticket, author, files, comment)

    changed = []
    if not is_internal:
        if is_requester and ticket.status in (Status.WAITING, Status.RESOLVED):
            _set_status(ticket, author, Status.OPEN, note="requester replied")
            changed = STATUS_FIELDS
        elif not is_requester and ticket.status == Status.NEW:
            _set_status(ticket, author, Status.OPEN, note="IT replied")
            changed = STATUS_FIELDS

    _save(ticket, changed)  # always bumps updated_at
    return comment


@transaction.atomic
def update_ticket(
    *, ticket: Ticket, actor, status: str | None = None, priority: int | None = None,
    assignee=_UNSET, category: Category | None = None,
) -> list[str]:
    """IT changes ticket properties. Returns a short description of each change."""
    if not actor.is_agent:
        raise PermissionDenied("Only IT can change ticket properties.")
    changes: list[str] = []
    fields: set[str] = set()
    status_requested = status is not None and status != ticket.status

    if priority is not None and int(priority) != ticket.priority:
        old = ticket.get_priority_display()
        ticket.priority = int(priority)
        _log(ticket, actor, TicketEvent.Kind.PRIORITY, old, ticket.get_priority_display())
        changes.append(f"priority set to {ticket.get_priority_display()}")
        fields.add("priority")

    if category is not None and category.pk != ticket.category_id:
        old = ticket.category.name
        ticket.category = category
        _log(ticket, actor, TicketEvent.Kind.CATEGORY, old, category.name)
        changes.append(f"category set to {category.name}")
        fields.add("category")

    if assignee is not _UNSET and (assignee.pk if assignee else None) != ticket.assignee_id:
        old = str(ticket.assignee) if ticket.assignee else ""
        ticket.assignee = assignee
        _log(ticket, actor, TicketEvent.Kind.ASSIGNEE, old, str(assignee) if assignee else "")
        changes.append(f"assigned to {assignee}" if assignee else "unassigned")
        fields.add("assignee")
        if assignee and ticket.status == Status.NEW and not status_requested:
            _set_status(ticket, actor, Status.OPEN, note="assigned")
            changes.append("status set to Open")
            fields.update(STATUS_FIELDS)

    if status_requested and _set_status(ticket, actor, status):
        changes.append(f"status set to {ticket.get_status_display()}")
        fields.update(STATUS_FIELDS)

    if fields:
        _save(ticket, fields)
    return changes


def assign_to_me(*, ticket: Ticket, actor) -> list[str]:
    return update_ticket(ticket=ticket, actor=actor, assignee=actor)


@transaction.atomic
def resolve_by_requester(*, ticket: Ticket, user) -> bool:
    """The requester says it's fixed or no longer needed."""
    if user.pk != ticket.requester_id:
        raise PermissionDenied
    if not ticket.is_open:
        return False
    _set_status(ticket, user, Status.RESOLVED, note="marked resolved by requester")
    _save(ticket, STATUS_FIELDS)
    return True


@transaction.atomic
def reopen_by_requester(*, ticket: Ticket, user) -> bool:
    """'This is still a problem' on a Resolved ticket."""
    if user.pk != ticket.requester_id:
        raise PermissionDenied
    if ticket.status != Status.RESOLVED:
        return False
    _set_status(ticket, user, Status.OPEN, note="reopened by requester")
    _save(ticket, STATUS_FIELDS)
    return True

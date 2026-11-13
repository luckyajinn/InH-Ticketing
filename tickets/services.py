"""
Ticket rules. Every change to a ticket goes through these functions, so the
rules and the history log live in one place instead of being spread across views.

Automatic status changes:
    New -> Open              when IT replies publicly or assigns the ticket
    Waiting on User -> Open  when the requester replies
    Resolved -> Open         when the requester replies or says it's still a problem
    Resolved -> Closed       automatically, AUTO_CLOSE_RESOLVED_DAYS after it was resolved
    Closed                   is archived at once: read-only, kept ARCHIVE_KEEP_DAYS

Departments: staff work only their own department's tickets (User.works_on);
admins work them all, and only an admin moves a ticket to another department.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.formats import date_format

from core import departments
from notifications import notify
from tickets.models import Attachment, Category, Comment, Ticket, TicketEvent

Status = Ticket.Status
_UNSET = object()
# Pass as update_ticket(assignee=UNCHANGED) to leave the assignee alone.
UNCHANGED = _UNSET
STATUS_FIELDS = ["status", "resolved_at", "closed_at", "archived_at"]
ARCHIVED = "This ticket is archived, so it can't be changed. Start a follow-up instead."


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
        ticket.archived_at = now  # closed tickets go straight to the archive
    else:
        ticket.resolved_at = None
        ticket.closed_at = None
    _log(ticket, actor, TicketEvent.Kind.STATUS, old_label, ticket.get_status_display(), note)
    if new_status == Status.CLOSED:
        until = date_format(timezone.localtime(ticket.keep_until), "M j, Y")
        _log(ticket, actor, TicketEvent.Kind.ARCHIVE, "", "Archived", f"kept until {until}")
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
    follows_up: Ticket | None = None, opened_by=None,
) -> Ticket:
    """
    A new request. `opened_by` is staff opening it for someone else (at the
    desk, say): the requester is still the one it's for, who gets the emails
    and sees it as their own. Staff can do this only for their own
    department's categories; admins for any.
    """
    if opened_by is not None and opened_by.pk == requester.pk:
        opened_by = None
    if opened_by is not None:
        if not opened_by.is_agent:
            raise PermissionDenied("Only staff can open a request for someone else.")
        if not opened_by.is_admin and category.department != opened_by.agent_department:
            raise PermissionDenied("Staff can open requests for someone else only in their own department.")
    ticket = Ticket.objects.create(
        requester=requester,
        subject=subject.strip(),
        description=description.strip(),
        category=category,
        is_blocking=is_blocking,
        source=source,
        follows_up=follows_up,
        opened_by=opened_by,
    )
    _save_attachments(ticket, opened_by or requester, files)
    if opened_by is not None:
        _log(ticket, opened_by, TicketEvent.Kind.OPENED_FOR, "", str(requester))
    notify.request_received(ticket)
    return ticket


# Statuses IT can set in the same click as sending a reply.
REPLY_THEN_STATUSES = (Status.WAITING, Status.RESOLVED)


@transaction.atomic
def add_comment(
    *, ticket: Ticket, author, body: str, is_internal: bool = False, files=(),
    source: str = Ticket.Source.WEB, then_status: str | None = None, share_on_move: bool = False,
) -> Comment:
    """
    Add a reply or internal note. Staff can pass then_status ("waiting" or
    "resolved") to change the status in the same step, as the composer's
    "Send and ..." buttons do. The requester then gets one email, not two.
    An internal note belongs to the ticket's department; share_on_move lets it
    go with the ticket if an admin moves it to another department.
    """
    works = author.works_on(ticket)
    if ticket.is_archived:
        raise PermissionDenied(ARCHIVED)
    if is_internal and not works:
        raise PermissionDenied("Only staff working this ticket can add internal notes.")
    is_requester = author.pk == ticket.requester_id
    if not is_requester and not works:
        raise PermissionDenied("You can't reply to this ticket.")
    if is_requester and not works and ticket.status == Status.CLOSED:
        raise PermissionDenied("This ticket is closed.")
    if then_status and (not works or then_status not in REPLY_THEN_STATUSES):
        raise PermissionDenied("Only staff working this ticket can change the status when replying.")

    comment = Comment.objects.create(
        ticket=ticket, author=author, body=body.strip(), is_internal=is_internal, source=source,
        department=ticket.department if is_internal else "",
        share_on_move=bool(share_on_move and is_internal),
    )
    _save_attachments(ticket, author, files, comment)

    changed = []
    if not is_internal:
        if is_requester and ticket.status in (Status.WAITING, Status.RESOLVED):
            _set_status(ticket, author, Status.OPEN, note="requester replied")
            changed = STATUS_FIELDS
        elif not is_requester and ticket.status == Status.NEW:
            _set_status(ticket, author, Status.OPEN, note=f"{ticket.department_label} replied")
            changed = STATUS_FIELDS
    if then_status and _set_status(ticket, author, then_status):
        changed = STATUS_FIELDS

    _save(ticket, changed)  # always bumps updated_at
    notify.comment_added(comment)
    return comment


@transaction.atomic
def add_email_from_third_party(*, ticket: Ticket, sender, body: str, files=(), why: str = "") -> Comment:
    """
    Someone who is neither the requester nor IT emailed about a ticket (a
    manager approving access, say), or an email claims to be from IT but
    Exchange couldn't confirm it (`why` says so). Keep it as an internal note
    so IT decides what to share, and alert the assignee. Only email-in calls this.
    """
    why = why or "who isn't the requester"
    comment = Comment.objects.create(
        ticket=ticket, author=sender, is_internal=True, source=Ticket.Source.EMAIL,
        body=f"Email from {sender} <{sender.email}>, {why}:\n\n{body.strip()}",
        department=ticket.department,
    )
    _save_attachments(ticket, sender, files, comment)
    _save(ticket, [])
    notify.third_party_email(comment, unconfirmed=bool(why))
    return comment


@transaction.atomic
def update_ticket(
    *, ticket: Ticket, actor, status: str | None = None, priority: int | None = None,
    assignee=_UNSET, category: Category | None = None,
) -> list[str]:
    """
    Staff change ticket properties. Returns a short description of each change.
    The category can only change within the ticket's department: moving it to
    another department is move_ticket(), for admins.
    """
    if not actor.works_on(ticket):
        raise PermissionDenied("Only staff working this ticket can change it.")
    if ticket.is_archived:
        raise PermissionDenied(ARCHIVED)
    if category is not None and category.department != ticket.category.department:
        raise PermissionDenied("Only an admin can move a ticket to another department.")
    changes: list[str] = []
    fields: set[str] = set()
    status_requested = status is not None and status != ticket.status
    newly_assigned = False

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
        newly_assigned = assignee is not None
        if assignee and ticket.status == Status.NEW and not status_requested:
            _set_status(ticket, actor, Status.OPEN, note="assigned")
            changes.append("status set to Open")
            fields.update(STATUS_FIELDS)

    resolved_now = closed_now = False
    if status_requested and _set_status(ticket, actor, status):
        changes.append(f"status set to {ticket.get_status_display()}")
        fields.update(STATUS_FIELDS)
        resolved_now = ticket.status == Status.RESOLVED
        closed_now = ticket.status == Status.CLOSED

    if fields:
        _save(ticket, fields)
    if newly_assigned:
        notify.assigned(ticket, actor)
    if resolved_now:
        notify.resolved(ticket, actor)
    if closed_now:
        notify.closed(ticket, actor)
    return changes


def assign_to_me(*, ticket: Ticket, actor) -> list[str]:
    return update_ticket(ticket=ticket, actor=actor, assignee=actor)


@transaction.atomic
def move_ticket(*, ticket: Ticket, actor, category: Category) -> list[str]:
    """
    An admin moves a ticket to another department, once the receiving
    department has agreed to take it (they confirm that outside the app; the
    form asks). Internal notes stay with the department that wrote them,
    except those marked "share with the new department". If the assignee
    doesn't work for the new department, the ticket is unassigned.
    """
    if not actor.is_admin:
        raise PermissionDenied("Only an admin can move a ticket to another department.")
    if ticket.is_archived:
        raise PermissionDenied(ARCHIVED)
    if category.department == ticket.category.department:
        return update_ticket(ticket=ticket, actor=actor, category=category)
    old_category, old_department = ticket.category, ticket.department_label
    notes = ticket.comments.filter(is_internal=True)
    shared = notes.filter(share_on_move=True).count()
    kept = notes.count() - shared
    ticket.category = category
    new_department = departments.label(category.department)
    _log(ticket, actor, TicketEvent.Kind.CATEGORY, old_category.name, category.name)
    _log(ticket, actor, TicketEvent.Kind.DEPARTMENT, old_department, new_department,
         f"confirmed with {new_department}; {shared} internal note{'' if shared == 1 else 's'} shared, "
         f"{kept} kept with {old_department}")
    fields = {"category"}
    changes = [f"moved to {new_department} ({category.name})"]
    if ticket.assignee_id and not ticket.assignee.works_on(ticket):
        _log(ticket, actor, TicketEvent.Kind.ASSIGNEE, str(ticket.assignee), "", "moved to another department")
        ticket.assignee = None
        fields.add("assignee")
        changes.append("unassigned")
    _save(ticket, fields)
    notify.moved(ticket, actor, old_department)
    return changes


def pending_move_request(ticket: Ticket) -> TicketEvent | None:
    """The latest "please move this" from staff, unless the ticket has moved since."""
    last = ticket.events.filter(
        kind__in=[TicketEvent.Kind.MOVE_REQUEST, TicketEvent.Kind.DEPARTMENT]
    ).select_related("actor").order_by("created_at", "pk").last()
    return last if last and last.kind == TicketEvent.Kind.MOVE_REQUEST else None


@transaction.atomic
def request_move(*, ticket: Ticket, actor, department: str, reason: str = "") -> None:
    """Staff ask an admin to move a ticket that landed in the wrong department."""
    if not actor.works_on(ticket):
        raise PermissionDenied("Only staff working this ticket can ask for it to be moved.")
    if ticket.is_archived:
        raise PermissionDenied(ARCHIVED)
    if department not in departments.keys() or department == ticket.department:
        raise PermissionDenied("Choose another department.")
    label = departments.label(department)
    _log(ticket, actor, TicketEvent.Kind.MOVE_REQUEST, ticket.department_label, label, reason.strip())
    _save(ticket, [])
    notify.move_requested(ticket, actor, label, reason.strip())


REMOVED = "[removed by IT]"
REMOVED_MESSAGE = "[This message was removed by IT.]"


def _scrub_copies(ticket: Ticket, passages: list[str]) -> None:
    """
    Take the passages out of the copies the app keeps: the emails it sent
    about this ticket (subject, text and HTML) and the subjects of emails it
    received. Emails already delivered stay in people's mailboxes.
    """
    from django.utils.html import escape

    from inbound.models import InboundEmail
    from notifications.models import OutboundEmail

    passages = [p for p in passages if p]
    if not passages:
        return
    for email in OutboundEmail.objects.filter(ticket=ticket):
        before = (email.subject, email.body_text, email.body_html)
        for passage in passages:
            email.subject = email.subject.replace(passage, REMOVED)
            email.body_text = email.body_text.replace(passage, REMOVED)
            email.body_html = email.body_html.replace(escape(passage), escape(REMOVED))
        if (email.subject, email.body_text, email.body_html) != before:
            email.save(update_fields=["subject", "body_text", "body_html"])
    for received in InboundEmail.objects.filter(ticket=ticket):
        subject = received.subject
        for passage in passages:
            subject = subject.replace(passage, REMOVED)
        if subject != received.subject:
            received.subject = subject
            received.save(update_fields=["subject", "updated_at"])


def _lines_of(text: str) -> list[str]:
    """A whole message's lines (as emails show them), longest first, to scrub from the copies."""
    return sorted({line.strip() for line in text.splitlines() if len(line.strip()) >= 4}, key=len, reverse=True)


@transaction.atomic
def remove_content(*, ticket: Ticket, actor, part: str, comment: Comment | None = None,
                   text: str = "", whole: bool = False, attachments=()) -> str:
    """
    An admin takes something out of a ticket: a pasted password (every place
    the text appears in that part), a whole message, and/or files. The
    history says who removed what kind of thing, and when, never what it was.
    `part` is "subject", "description" or "comment". Returns what was removed,
    e.g. "text from the request and 1 file".
    """
    if not actor.is_admin:
        raise PermissionDenied("Only an admin can remove something from a ticket.")
    where = {"subject": "the subject", "description": "the request"}.get(part)
    if part == "comment":
        kind = "internal note" if comment.is_internal else "reply"
        where = f"a {kind} from {comment.author}"
    removed = []
    if whole and part in ("description", "comment"):
        original = ticket.description if part == "description" else comment.body
        if part == "description":
            ticket.description = REMOVED_MESSAGE
            ticket.save(update_fields=["description"])
        else:
            comment.body = REMOVED_MESSAGE
            comment.save(update_fields=["body"])
        _scrub_copies(ticket, [original, *_lines_of(original)])
        removed.append(f"the whole of {where}")
    elif text:
        if part == "subject":
            ticket.subject = ticket.subject.replace(text, REMOVED)[:200]
            ticket.save(update_fields=["subject"])
        elif part == "description":
            ticket.description = ticket.description.replace(text, REMOVED)
            ticket.save(update_fields=["description"])
        else:
            comment.body = comment.body.replace(text, REMOVED)
            comment.save(update_fields=["body"])
        _scrub_copies(ticket, [text])
        removed.append(f"text from {where}")
    files = list(attachments)
    for attachment in files:
        attachment.file.delete(save=False)
        attachment.delete()
    if files:
        removed.append(f"{len(files)} file{'' if len(files) == 1 else 's'}" + ("" if removed else f" from {where}"))
    if not removed:
        return ""
    summary = " and ".join(removed)
    _log(ticket, actor, TicketEvent.Kind.REMOVED, "", summary[:200])
    _save(ticket, [])
    return summary


@transaction.atomic
def unarchive(*, ticket: Ticket, actor) -> bool:
    """An admin takes a ticket out of the archive (closed by mistake, say). It stays Closed."""
    if not actor.is_admin:
        raise PermissionDenied("Only an admin can take a ticket out of the archive.")
    if not ticket.is_archived:
        return False
    ticket.archived_at = None
    _log(ticket, actor, TicketEvent.Kind.ARCHIVE, "Archived", "Not archived", "taken out of the archive")
    _save(ticket, ["archived_at"])
    return True


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
    notify.reopened(ticket, user)
    return True


def close_resolved_tickets() -> int:
    """
    Close Resolved tickets nobody has replied to for AUTO_CLOSE_RESOLVED_DAYS.
    Returns how many were closed. Does nothing when the setting is 0.

    A requester reply sets the ticket back to Open (clearing resolved_at), so
    only tickets that stayed quiet are closed. Each ticket is re-checked inside
    its own transaction in case the requester replied since the list was read.
    No email goes out: the requester was already told the close date.
    """
    days = settings.AUTO_CLOSE_RESOLVED_DAYS
    if days <= 0:
        return 0
    cutoff = timezone.now() - timedelta(days=days)
    due = Ticket.objects.filter(status=Status.RESOLVED, resolved_at__lte=cutoff)
    closed = 0
    for pk in list(due.values_list("pk", flat=True)):
        with transaction.atomic():
            ticket = due.select_for_update().filter(pk=pk).first()
            if ticket is None:
                continue  # changed since we looked
            note = f"no reply for {days} day{'' if days == 1 else 's'}"
            _set_status(ticket, None, Status.CLOSED, note=note)
            _save(ticket, STATUS_FIELDS)
            closed += 1
    return closed

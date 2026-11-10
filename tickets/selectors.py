"""
What each person is allowed to see. Views read through these functions so the
rules are enforced on the server, in one place:

  * Requesters never see internal notes, files on them, or the history.
  * Staff see only their own department's tickets (admins see all).
  * Internal notes stay with the department that wrote them: after an admin
    moves a ticket, the new department sees only the notes that were marked
    "share with the new department". Admins see every note.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q

from tickets.models import Attachment, Comment, Ticket, TicketEvent


def can_view(user, ticket: Ticket) -> bool:
    return user.works_on(ticket) or ticket.requester_id == user.pk


def _notes_seen(ticket: Ticket, prefix: str = "") -> Q:
    """Internal notes staff (not admins) see: their department's, or shared on a move."""
    return (Q(**{f"{prefix}department__in": [ticket.department, ""]})
            | Q(**{f"{prefix}share_on_move": True}))


def note_visible(user, ticket: Ticket, comment: Comment) -> bool:
    if not comment.is_internal:
        return True
    if not user.works_on(ticket):
        return False
    return user.is_admin or comment.department in (ticket.department, "") or comment.share_on_move


def visible_comments(ticket: Ticket, user):
    qs = ticket.comments.select_related("author").prefetch_related("attachments")
    if not user.works_on(ticket):
        return qs.filter(is_internal=False)
    if user.is_admin:
        return qs
    return qs.filter(Q(is_internal=False) | _notes_seen(ticket))


def visible_attachments(ticket: Ticket, user):
    qs = ticket.attachments.select_related("comment")
    public = Q(comment__isnull=True) | Q(comment__is_internal=False)
    if not user.works_on(ticket):
        return qs.filter(public)
    if user.is_admin:
        return qs
    return qs.filter(public | _notes_seen(ticket, "comment__"))


def can_download(user, attachment: Attachment) -> bool:
    if not can_view(user, attachment.ticket):
        return False
    if attachment.comment_id is None:
        return True
    return note_visible(user, attachment.ticket, attachment.comment)


def linked_tickets(ticket: Ticket, user) -> tuple[Ticket | None, list[Ticket]]:
    """
    The ticket this one follows up, and the follow-ups started from it, limited
    to tickets this person may view. A requester never learns about a ticket
    that isn't theirs, even if it's linked to theirs.
    """
    original = ticket.follows_up
    if original is not None and not can_view(user, original):
        original = None
    follow_ups = Ticket.objects.visible_to(user).filter(follows_up=ticket).order_by("created_at")
    return original, list(follow_ups)


@dataclass
class TimelineItem:
    kind: str  # "comment" or "event"
    at: datetime
    comment: Comment | None = None
    event: TicketEvent | None = None


def timeline(ticket: Ticket, user) -> list[TimelineItem]:
    """
    Replies, notes and (for IT only) history, oldest first. The original
    request is shown separately above the timeline.
    """
    items = [TimelineItem("comment", c.created_at, comment=c) for c in visible_comments(ticket, user)]
    if user.works_on(ticket):
        events = ticket.events.select_related("actor")
        items += [TimelineItem("event", e.created_at, event=e) for e in events]
    items.sort(key=lambda item: item.at)
    return items

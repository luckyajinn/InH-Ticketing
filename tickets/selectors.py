"""
What each person is allowed to see. Views read through these functions so the
"requesters never see internal notes" rule is enforced on the server, in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q

from tickets.models import Attachment, Comment, Ticket, TicketEvent


def can_view(user, ticket: Ticket) -> bool:
    return user.is_agent or ticket.requester_id == user.pk


def visible_comments(ticket: Ticket, user):
    qs = ticket.comments.select_related("author").prefetch_related("attachments")
    if not user.is_agent:
        qs = qs.filter(is_internal=False)
    return qs


def visible_attachments(ticket: Ticket, user):
    qs = ticket.attachments.select_related("comment")
    if not user.is_agent:
        qs = qs.filter(Q(comment__isnull=True) | Q(comment__is_internal=False))
    return qs


def can_download(user, attachment: Attachment) -> bool:
    if not can_view(user, attachment.ticket):
        return False
    return user.is_agent or not attachment.is_internal


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
    if user.is_agent:
        events = ticket.events.select_related("actor")
        items += [TimelineItem("event", e.created_at, event=e) for e in events]
    items.sort(key=lambda item: item.at)
    return items

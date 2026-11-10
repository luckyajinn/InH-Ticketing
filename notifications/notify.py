"""
Who gets an email, and when. Called from tickets/services.py, inside the same
transaction as the ticket change, so an email is only queued if the change saved.

    Event                         Goes to
    ----------------------------  ---------------------------------------------
    Request submitted             the requester (receipt) + IT_NOTIFY_EMAIL
    IT posts a public reply       the requester
    Requester replies / reopens   the assignee, or IT_NOTIFY_EMAIL if unassigned
    Ticket assigned               the new assignee (unless they assigned themselves)
    IT resolves the ticket        the requester

Rules that always apply:
  * Internal notes never trigger an email, and never appear in one.
  * Nobody is emailed about their own action.
  * Inactive people and people without an email address are skipped.
"""

from __future__ import annotations

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.formats import date_format

from notifications.models import OutboundEmail


def _ticket_url(ticket) -> str:
    return settings.SITE_URL + ticket.get_absolute_url()


def _reachable(user) -> bool:
    return bool(user and user.is_active and user.email)


def _reply_hint(ticket, audience: str) -> str:
    """What replying to the email does: tell people before they try it."""
    if settings.INBOUND_EMAIL != "graph":
        return "Replies to this email aren't added to the ticket yet. Please use the link instead."
    if audience == "it":
        return (f"Replying to this email posts a public reply that {ticket.requester} will see. "
                "For an internal note, use the ticket page.")
    return f"Reply to this email to add to your request. Keep [#{ticket.number}] in the subject."


def _close_notice(ticket) -> str:
    """' It closes automatically on Nov 13 if we don't hear back.' Empty if auto-close is off."""
    closes = ticket.auto_close_at
    if not closes:
        return ""
    return f" It closes automatically on {date_format(timezone.localtime(closes), 'M j')} if we don't hear back."


def _queue(*, kind, ticket, to, heading, intro, reason, message=None, message_author=None,
           action="View your request", audience="requester"):
    if not to:
        return None
    context = {
        "reply_hint": _reply_hint(ticket, audience),
        "ticket": ticket,
        "ticket_url": _ticket_url(ticket),
        "heading": heading,
        "intro": intro,
        "message": message,
        "message_author": message_author,
        "action": action,
        "reason": reason,
        "app_name": "InH-Ticketing",
    }
    return OutboundEmail.objects.create(
        ticket=ticket,
        kind=kind,
        to=to,
        # The same subject for every email about a ticket, so mail apps group
        # them into one conversation. The [#1001] tag will also let replies be
        # matched to the ticket once email-in arrives (milestone 4).
        subject=f"[#{ticket.number}] {ticket.subject}"[:255],
        body_text=render_to_string("emails/notification.txt", context),
        body_html=render_to_string("emails/notification.html", context),
    )


def _it_recipient(ticket, actor) -> str:
    """The assignee if there is one, otherwise the IT alert address."""
    if ticket.assignee_id:
        assignee = ticket.assignee
        if _reachable(assignee) and assignee.pk != actor.pk:
            return assignee.email
        return ""
    return settings.IT_NOTIFY_EMAIL


def request_received(ticket) -> None:
    requester = ticket.requester
    if _reachable(requester):
        _queue(
            kind="received", ticket=ticket, to=requester.email,
            heading="We've received your request",
            intro=f"Thanks, {requester}. We've got request #{ticket.number}, and someone will pick it up soon.",
            message=ticket.description, message_author="You wrote",
            reason="you raised this request",
        )
    _queue(
        kind="new_ticket", ticket=ticket, to=settings.IT_NOTIFY_EMAIL, audience="it",
        heading=f"New request from {requester}",
        intro=f"{ticket.category} · {'blocking their work' if ticket.is_blocking else 'not marked as blocking'}",
        message=ticket.description, message_author=f"{requester} wrote",
        action="Open the ticket", reason="this address gets IT's new-request alerts",
    )


def comment_added(comment) -> None:
    if comment.is_internal:
        return  # Internal notes are never emailed to anyone.
    ticket, author = comment.ticket, comment.author

    if author.pk == ticket.requester_id:
        to = _it_recipient(ticket, author)
        _queue(
            kind="requester_replied", ticket=ticket, to=to, audience="it",
            heading=f"{author} replied",
            intro=f"New reply on #{ticket.number}, now {ticket.get_status_display()}.",
            message=comment.body, message_author=f"{author} wrote",
            action="Open the ticket",
            reason="you're assigned to this ticket" if ticket.assignee_id else "this address gets IT's alerts",
        )
        return

    requester = ticket.requester
    if author.is_agent and _reachable(requester):
        if ticket.status == "waiting":
            intro = f"{author} is waiting for your reply."
        elif ticket.status == "resolved":
            intro = (
                f"{author} has marked your request as resolved. If it's still not working, "
                "open the ticket and choose \"This is still a problem\"."
                + _close_notice(ticket)
            )
        else:
            intro = f"Your request is {ticket.get_status_display().lower()}."
        _queue(
            kind="it_replied", ticket=ticket, to=requester.email,
            heading=f"{author} replied to your request",
            intro=intro,
            message=comment.body, message_author=f"{author} wrote",
            action="Reply on the ticket", reason="you raised this request",
        )


def third_party_email(comment) -> None:
    """An email from someone other than the requester, saved as an internal note."""
    ticket, sender = comment.ticket, comment.author
    _queue(
        kind="third_party_email", ticket=ticket, to=_it_recipient(ticket, sender), audience="it",
        heading=f"Email from {sender} on #{ticket.number}",
        intro=f"{sender} isn't the requester, so it was saved as an internal note. {ticket.requester} can't see it.",
        message=comment.body, message_author=f"{sender} wrote",
        action="Open the ticket",
        reason="you're assigned to this ticket" if ticket.assignee_id else "this address gets IT's alerts",
    )


def assigned(ticket, actor) -> None:
    assignee = ticket.assignee
    if not assignee or assignee.pk == actor.pk or not _reachable(assignee):
        return
    _queue(
        kind="assigned", ticket=ticket, to=assignee.email, audience="it",
        heading=f"{actor} assigned #{ticket.number} to you",
        intro=f"From {ticket.requester} · {ticket.category} · {ticket.get_priority_display()} priority",
        message=ticket.description, message_author=f"{ticket.requester} wrote",
        action="Open the ticket", reason="this ticket was assigned to you",
    )


def resolved(ticket, actor) -> None:
    requester = ticket.requester
    if actor.pk == requester.pk or not _reachable(requester):
        return
    _queue(
        kind="resolved", ticket=ticket, to=requester.email,
        heading="Your request has been resolved",
        intro=(
            f"{actor} marked #{ticket.number} as resolved. If it's still not working, "
            "open the ticket and choose \"This is still a problem\"."
            + _close_notice(ticket)
        ),
        action="View your request", reason="you raised this request",
    )


def reopened(ticket, actor) -> None:
    _queue(
        kind="reopened", ticket=ticket, to=_it_recipient(ticket, actor), audience="it",
        heading=f"{actor} reopened #{ticket.number}",
        intro="They say it's still a problem.",
        action="Open the ticket",
        reason="you're assigned to this ticket" if ticket.assignee_id else "this address gets IT's alerts",
    )

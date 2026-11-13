"""
Who gets an email, and when. Called from tickets/services.py, inside the same
transaction as the ticket change, so an email is only queued if the change saved.

    Event                         Goes to
    ----------------------------  ---------------------------------------------
    Request submitted             the requester (receipt) + the department's alerts
    Staff post a public reply     the requester
    Requester replies / reopens   the assignee, or the department's alerts if unassigned
    Ticket assigned               the new assignee (unless they assigned themselves)
    Staff resolve the ticket      the requester
    Staff close the ticket        the requester (not when it closes by itself)
    Staff ask for a move          every admin
    An admin moves the ticket     the new department's alerts

The department's alerts: IT_NOTIFY_EMAIL for IT. For any other department,
its alert address (admin site, Tickets > Departments), or else each of its agents.

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

from core import departments
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
    if ticket.status == ticket.Status.CLOSED:
        return "Replying to this email starts a new request, linked to this one."
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


def department_alerts(ticket) -> list[str]:
    """Where a department's new-request and unassigned alerts go."""
    from accounts.models import User  # notify is imported by the ticket models' services

    department = ticket.department
    if department == departments.IT:
        return [settings.IT_NOTIFY_EMAIL] if settings.IT_NOTIFY_EMAIL else []
    row = departments.get(department)
    if row and row.alert_email:
        return [row.alert_email]
    agents = User.objects.filter(role=User.Role.AGENT, department=department, is_active=True).exclude(email="")
    return sorted({agent.email for agent in agents})


def _alerts_reason(ticket) -> str:
    return f"this address gets {ticket.department_label}'s alerts"


def _staff_recipients(ticket, actor) -> list[str]:
    """The assignee if there is one, otherwise the department's alerts."""
    if ticket.assignee_id:
        assignee = ticket.assignee
        if _reachable(assignee) and assignee.pk != actor.pk:
            return [assignee.email]
        return []
    return department_alerts(ticket)


def _queue_each(addresses, **kwargs):
    for address in addresses:
        _queue(to=address, **kwargs)


def request_received(ticket) -> None:
    requester = ticket.requester
    # Staff who opened it for the requester (someone at the desk, say) wrote it.
    opener = ticket.opened_by
    if _reachable(requester):
        if opener:
            _queue(
                kind="received", ticket=ticket, to=requester.email,
                heading="We've opened a request for you",
                intro=(f"{opener} opened request #{ticket.number} for you. "
                       "You'll get an email when there's an update."),
                message=ticket.description, message_author=f"{opener} wrote",
                reason=f"{opener} opened this request for you",
            )
        else:
            _queue(
                kind="received", ticket=ticket, to=requester.email,
                heading="We've received your request",
                intro=f"Thanks, {requester}. We've got request #{ticket.number}, and someone will pick it up soon.",
                message=ticket.description, message_author="You wrote",
                reason="you raised this request",
            )
    blocking = "blocking their work" if ticket.is_blocking else "not marked as blocking"
    _queue_each(
        department_alerts(ticket),
        kind="new_ticket", ticket=ticket, audience="it",
        heading=f"New request for {requester}" if opener else f"New request from {requester}",
        intro=f"Opened by {opener} · {ticket.category} · {blocking}" if opener else f"{ticket.category} · {blocking}",
        message=ticket.description, message_author=f"{opener or requester} wrote",
        action="Open the ticket", reason=f"this address gets {ticket.department_label}'s new-request alerts",
    )


def comment_added(comment) -> None:
    if comment.is_internal:
        return  # Internal notes are never emailed to anyone.
    ticket, author = comment.ticket, comment.author

    if author.pk == ticket.requester_id:
        _queue_each(
            _staff_recipients(ticket, author),
            kind="requester_replied", ticket=ticket, audience="it",
            heading=f"{author} replied",
            intro=f"New reply on #{ticket.number}, now {ticket.get_status_display()}.",
            message=comment.body, message_author=f"{author} wrote",
            action="Open the ticket",
            reason="you're assigned to this ticket" if ticket.assignee_id else _alerts_reason(ticket),
        )
        return

    requester = ticket.requester
    if author.works_on(ticket) and _reachable(requester):
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


def third_party_email(comment, unconfirmed: bool = False) -> None:
    """An email from someone other than the requester (or not confirmed as IT's), saved as an internal note."""
    ticket, sender = comment.ticket, comment.author
    why = (f"It says it's from {sender}, but Exchange couldn't confirm that" if unconfirmed
           else f"{sender} isn't the requester")
    _queue_each(
        _staff_recipients(ticket, sender),
        kind="third_party_email", ticket=ticket, audience="it",
        heading=f"Email from {sender} on #{ticket.number}",
        intro=f"{why}, so it was saved as an internal note. {ticket.requester} can't see it.",
        message=comment.body, message_author=f"{sender} wrote",
        action="Open the ticket",
        reason="you're assigned to this ticket" if ticket.assignee_id else _alerts_reason(ticket),
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


def closed(ticket, actor) -> None:
    """Staff closed the ticket. Auto-close sends nothing: the resolved email gave its date."""
    requester = ticket.requester
    if actor.pk == requester.pk or not _reachable(requester):
        return
    _queue(
        kind="closed", ticket=ticket, to=requester.email,
        heading="Your request is closed and complete",
        intro=(
            f"{actor} closed #{ticket.number}. It can't be changed now. If you need more help "
            "with it, open the request and choose \"Start a follow-up\"."
        ),
        action="View your request", reason="you raised this request",
    )


def reopened(ticket, actor) -> None:
    _queue_each(
        _staff_recipients(ticket, actor),
        kind="reopened", ticket=ticket, audience="it",
        heading=f"{actor} reopened #{ticket.number}",
        intro="They say it's still a problem.",
        action="Open the ticket",
        reason="you're assigned to this ticket" if ticket.assignee_id else _alerts_reason(ticket),
    )


def move_requested(ticket, actor, department_label: str, reason: str) -> None:
    """Staff asked for a ticket to be moved: every admin hears, since only admins move tickets."""
    from accounts.models import User

    admins = User.objects.filter(role=User.Role.ADMIN, is_active=True).exclude(email="").exclude(pk=actor.pk)
    _queue_each(
        sorted({a.email for a in admins}),
        kind="move_requested", ticket=ticket, audience="it",
        heading=f"{actor} asked to move #{ticket.number} to {department_label}",
        intro=(f"It's with {ticket.department_label} now. Check with {department_label} that they'll take it, "
               "then move it from the ticket page."),
        message=reason or None, message_author=f"{actor} wrote" if reason else None,
        action="Open the ticket", reason="you're an admin, and only admins move tickets",
    )


def moved(ticket, actor, old_department_label: str) -> None:
    """An admin moved a ticket to another department: tell its new department."""
    _queue_each(
        department_alerts(ticket),
        kind="moved", ticket=ticket, audience="it",
        heading=f"#{ticket.number} moved to {ticket.department_label}",
        intro=f"{actor} moved it from {old_department_label}. From {ticket.requester} · {ticket.category}",
        message=ticket.description, message_author=f"{ticket.requester} wrote",
        action="Open the ticket", reason=f"this address gets {ticket.department_label}'s alerts",
    )

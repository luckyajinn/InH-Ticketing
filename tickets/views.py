from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Max, Q
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from tickets import password_guard, selectors, services
from tickets.forms import NewTicketForm, ReplyForm, TicketPropertiesForm
from tickets.models import Attachment, Category, PasswordWarning, Ticket

Status = Ticket.Status


def agent_required(view):
    """IT-only pages. Requesters get a 403, not a redirect loop."""

    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_agent:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def _get_ticket(request, number: int) -> Ticket:
    """The ticket, or 404 if it doesn't exist *or* this person may not see it."""
    pk = Ticket.pk_from_number(number)
    queryset = Ticket.objects.visible_to(request.user).select_related(
        "requester", "assignee", "category"
    )
    return get_object_or_404(queryset, pk=pk)


# ---------------------------------------------------------------------------
# Requester pages
# ---------------------------------------------------------------------------
@login_required
@require_GET
def my_tickets(request):
    show = "closed" if request.GET.get("show") == "closed" else "open"
    mine = Ticket.objects.filter(requester=request.user)
    counts = {
        "open": mine.filter(status__in=Ticket.OPEN_STATUSES).count(),
        "closed": mine.exclude(status__in=Ticket.OPEN_STATUSES).count(),
    }
    tickets = (
        mine.filter(status__in=Ticket.OPEN_STATUSES)
        if show == "open"
        else mine.exclude(status__in=Ticket.OPEN_STATUSES)
    )
    # "Updated" means the last public activity: internal notes don't count,
    # so requesters can't tell when IT is talking about them privately.
    tickets = (
        tickets.select_related("assignee", "category")
        .annotate(
            last_public=Coalesce(
                Max("comments__created_at", filter=Q(comments__is_internal=False)), "created_at"
            )
        )
        .order_by("-last_public")
    )
    page = Paginator(tickets, 25).get_page(request.GET.get("page"))
    return render(
        request, "tickets/my_tickets.html", {"page": page, "show": show, "counts": counts}
    )


def _follow_up_target(request) -> Ticket | None:
    """
    The ticket a new request follows up (?follow_up=1001, or the hidden field on
    the form), but only if this person may view it. Anything else is ignored
    without a word, so the page never reveals whether a ticket exists.
    """
    raw = request.POST.get("follow_up") or request.GET.get("follow_up") or ""
    if not raw.isdecimal():
        return None
    ticket = Ticket.objects.filter(pk=Ticket.pk_from_number(int(raw))).first()
    return ticket if ticket and selectors.can_view(request.user, ticket) else None


@login_required
@require_http_methods(["GET", "POST"])
def new_ticket(request):
    follow_up = _follow_up_target(request)
    initial = {"subject": follow_up.subject} if follow_up else None
    form = NewTicketForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        ticket = services.create_ticket(
            requester=request.user,
            subject=form.cleaned_data["subject"],
            description=form.cleaned_data["description"],
            category=form.cleaned_data["category"],
            is_blocking=form.cleaned_data["is_blocking"],
            files=form.cleaned_data["attachments"],
            follows_up=follow_up,
        )
        password_guard.record_form(
            form, user=request.user, place=PasswordWarning.Place.NEW_REQUEST, ticket=ticket
        )
        messages.success(request, f"Request #{ticket.number} sent. You'll get an email when there's an update.")
        return redirect(ticket)
    status = 400 if request.method == "POST" else 200
    return render(request, "tickets/new.html", {"form": form, "follow_up": follow_up}, status=status)


@login_required
@require_GET
def go_to_ticket(request):
    """
    "Have a ticket number?" on the Not found page. Sends #1042 to its page,
    which shows Not found itself if the ticket doesn't exist or isn't yours,
    so this never reveals whether a ticket exists.
    """
    raw = request.GET.get("number", "").strip().lstrip("#").strip()
    # Ticket numbers are short; a huge number would only ever be not found.
    if raw.isdecimal() and len(raw) <= 9:
        return redirect("tickets:detail", number=int(raw))
    messages.error(request, "Enter a ticket number, like 1042.")
    return redirect("tickets:mine")


# ---------------------------------------------------------------------------
# Ticket detail (one URL, two views: IT sees everything, requesters see public)
# ---------------------------------------------------------------------------
def _render_detail(request, ticket, *, reply_form=None, props_form=None, status=200):
    user = request.user
    context = {
        "ticket": ticket,
        "timeline": selectors.timeline(ticket, user),
        "original_attachments": [
            a for a in selectors.visible_attachments(ticket, user) if a.comment_id is None
        ],
        "reply_form": reply_form or ReplyForm(user=user),
    }
    context["follows_up"], context["follow_ups"] = selectors.linked_tickets(ticket, user)
    if user.is_agent:
        context["props_form"] = props_form or TicketPropertiesForm(ticket=ticket, me=user)
        context["all_attachments"] = selectors.visible_attachments(ticket, user)
        context["other_tickets"] = (
            Ticket.objects.filter(requester=ticket.requester_id)
            .exclude(pk=ticket.pk)
            .order_by("-created_at")[:5]
        )
        template = "tickets/detail_agent.html"
    else:
        context["reopened"] = request.GET.get("reopened") == "1"
        context["resolved_event"] = (
            ticket.events.filter(kind="status", new_value=Status.RESOLVED.label)
            .select_related("actor")
            .last()
        )
        template = "tickets/detail_requester.html"
    return render(request, template, context, status=status)


@login_required
@require_GET
def ticket_detail(request, number: int):
    return _render_detail(request, _get_ticket(request, number))


@login_required
@require_POST
def add_reply(request, number: int):
    ticket = _get_ticket(request, number)
    form = ReplyForm(request.POST, request.FILES, user=request.user)
    if not form.is_valid():
        return _render_detail(request, ticket, reply_form=form, status=400)
    then_status = form.cleaned_data.get("then_status") or None
    try:
        comment = services.add_comment(
            ticket=ticket,
            author=request.user,
            body=form.cleaned_data["body"],
            is_internal=form.is_internal,
            files=form.cleaned_data["attachments"],
            then_status=then_status,
        )
    except PermissionDenied as exc:
        messages.error(request, str(exc) or "You can't reply to this ticket.")
        return redirect(ticket)
    place = PasswordWarning.Place.INTERNAL_NOTE if form.is_internal else PasswordWarning.Place.REPLY
    password_guard.record_form(form, user=request.user, place=place, ticket=ticket, comment=comment)
    if form.is_internal:
        messages.success(request, "Internal note added. The requester can't see it.")
    elif request.user.is_agent and request.user.pk != ticket.requester_id:
        done = f" Status set to {ticket.get_status_display()}." if then_status else ""
        messages.success(request, f"Public reply sent to {ticket.requester}.{done}")
    else:
        messages.success(request, "Reply sent.")
    return redirect(ticket)


@login_required
@require_POST
def check_text(request):
    """
    The "this might include a password" check, for app.js to ask before a form
    is sent, so chosen files stay attached. It only answers about the text it
    was sent, and stores nothing; the form is checked again when it arrives.
    """
    found = {}
    for name in ("subject", "description", "body"):
        findings = password_guard.find(request.POST.get(name, "")[:50_000])
        if findings:
            found[name] = findings
    return JsonResponse({"found": bool(found), "hints": password_guard.hints(found)})


def _changed_here(request, name: str, value) -> bool:
    """
    Did the person change this side-panel field? The panel also sends what it
    showed when the page loaded (shown_status, ...), so a page left open can't
    put back a value someone else has changed since. A page from before this
    check sends no shown_ values, and every field counts as changed, as before.
    """
    shown = request.POST.get(f"shown_{name}")
    return shown is None or str("" if value is None else value) != shown


@agent_required
@require_POST
def update_properties(request, number: int):
    ticket = _get_ticket(request, number)
    form = TicketPropertiesForm(request.POST, ticket=ticket, me=request.user)
    if not form.is_valid():
        return _render_detail(request, ticket, props_form=form, status=400)
    data = form.cleaned_data
    assignee = data["assignee"]
    changes = services.update_ticket(
        ticket=ticket,
        actor=request.user,
        status=data["status"] if _changed_here(request, "status", data["status"]) else None,
        priority=data["priority"] if _changed_here(request, "priority", data["priority"]) else None,
        assignee=(assignee if _changed_here(request, "assignee", assignee.pk if assignee else None)
                  else services.UNCHANGED),
        category=data["category"] if _changed_here(request, "category", data["category"].pk) else None,
    )
    if changes:
        messages.success(request, "Saved: " + ", ".join(changes) + ".")
    return redirect(ticket)


@agent_required
@require_POST
def assign_to_me(request, number: int):
    ticket = _get_ticket(request, number)
    if services.assign_to_me(ticket=ticket, actor=request.user):
        messages.success(request, f"#{ticket.number} is assigned to you.")
    return redirect(ticket)


@login_required
@require_POST
def resolve(request, number: int):
    ticket = _get_ticket(request, number)
    if ticket.requester_id != request.user.pk:
        raise PermissionDenied
    if services.resolve_by_requester(ticket=ticket, user=request.user):
        messages.success(request, "Marked as resolved. Thanks for letting us know.")
    return redirect(ticket)


@login_required
@require_POST
def reopen(request, number: int):
    ticket = _get_ticket(request, number)
    if ticket.requester_id != request.user.pk:
        raise PermissionDenied
    if services.reopen_by_requester(ticket=ticket, user=request.user):
        messages.info(request, "Request reopened. Say what's still wrong below.")
        return redirect(ticket.get_absolute_url() + "?reopened=1#reply")
    return redirect(ticket)


@login_required
@require_GET
def download_attachment(request, pk: int, filename: str):
    attachment = get_object_or_404(
        Attachment.objects.select_related("ticket", "comment"), pk=pk
    )
    # 404 rather than 403, so people can't probe for files that exist.
    if not selectors.can_download(request.user, attachment):
        raise Http404
    try:
        handle = attachment.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    # Always a download, never shown in the browser, so an uploaded file
    # can't run as a web page on our site.
    return FileResponse(handle, as_attachment=True, filename=attachment.original_name)


# ---------------------------------------------------------------------------
# IT queue
# ---------------------------------------------------------------------------
QUEUE_VIEWS = [
    {"id": "unassigned", "label": "Unassigned", "icon": "inbox"},
    {"id": "mine", "label": "Assigned to me", "icon": "user"},
    {"id": "open", "label": "All open", "icon": "users"},
    {"id": "waiting", "label": "Waiting on user", "icon": "pause"},
    {"id": "resolved", "label": "Recently resolved", "icon": "check-circle"},
]
RECENT = timedelta(days=14)


def _queue_queryset(view_id: str, user):
    tickets = Ticket.objects.all()
    if view_id == "unassigned":
        return tickets.open().filter(assignee__isnull=True)
    if view_id == "mine":
        return tickets.open().filter(assignee=user)
    if view_id == "waiting":
        return tickets.filter(status=Status.WAITING)
    if view_id == "resolved":
        return tickets.filter(
            status__in=[Status.RESOLVED, Status.CLOSED],
            updated_at__gte=timezone.now() - RECENT,
        )
    return tickets.open()


@agent_required
@require_GET
def queue(request):
    view_ids = [v["id"] for v in QUEUE_VIEWS]
    view_id = request.GET.get("view") if request.GET.get("view") in view_ids else "open"
    views = [
        {**v, "count": _queue_queryset(v["id"], request.user).count(), "current": v["id"] == view_id}
        for v in QUEUE_VIEWS
    ]
    current = next(v for v in views if v["current"])

    tickets = _queue_queryset(view_id, request.user).select_related(
        "requester", "assignee", "category"
    )
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    priority = request.GET.get("priority", "")
    if q:
        term = q.lstrip("#")
        match = (
            Q(subject__icontains=term)
            | Q(requester__display_name__icontains=term)
            | Q(requester__email__icontains=term)
        )
        if term.isdecimal():
            match |= Q(pk=Ticket.pk_from_number(int(term)))
        tickets = tickets.filter(match)
    if category.isdecimal():
        tickets = tickets.filter(category_id=int(category))
    if priority.isdecimal():
        tickets = tickets.filter(priority=int(priority))

    if view_id == "resolved":
        tickets = tickets.order_by("-updated_at")
        sort_label = "last 14 days, most recent first"
    else:
        tickets = tickets.order_by("-priority", "created_at")
        sort_label = "priority, then oldest first"

    page = Paginator(tickets, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "tickets/queue.html",
        {
            "views": views,
            "current": current,
            "page": page,
            "q": q,
            "category": category,
            "priority": priority,
            "filtered": bool(q or category or priority),
            "categories": Category.objects.all(),
            "priorities": sorted(Ticket.Priority.choices, reverse=True),
            "sort_label": sort_label,
        },
    )

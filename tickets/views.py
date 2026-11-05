from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Max, Q
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from tickets import selectors, services
from tickets.forms import NewTicketForm, ReplyForm, TicketPropertiesForm
from tickets.models import Attachment, Category, Ticket

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


@login_required
@require_http_methods(["GET", "POST"])
def new_ticket(request):
    form = NewTicketForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        ticket = services.create_ticket(
            requester=request.user,
            subject=form.cleaned_data["subject"],
            description=form.cleaned_data["description"],
            category=form.cleaned_data["category"],
            is_blocking=form.cleaned_data["is_blocking"],
            files=form.cleaned_data["attachments"],
        )
        messages.success(request, f"Request #{ticket.number} sent. IT will pick it up soon.")
        return redirect(ticket)
    status = 400 if request.method == "POST" else 200
    return render(request, "tickets/new.html", {"form": form}, status=status)


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
    try:
        services.add_comment(
            ticket=ticket,
            author=request.user,
            body=form.cleaned_data["body"],
            is_internal=form.is_internal,
            files=form.cleaned_data["attachments"],
        )
    except PermissionDenied as exc:
        messages.error(request, str(exc) or "You can't reply to this ticket.")
        return redirect(ticket)
    if form.is_internal:
        messages.success(request, "Internal note added. The requester can't see it.")
    elif request.user.is_agent and request.user.pk != ticket.requester_id:
        messages.success(request, f"Public reply added. {ticket.requester} can see it.")
    else:
        messages.success(request, "Reply sent.")
    return redirect(ticket)


@agent_required
@require_POST
def update_properties(request, number: int):
    ticket = _get_ticket(request, number)
    form = TicketPropertiesForm(request.POST, ticket=ticket, me=request.user)
    if not form.is_valid():
        return _render_detail(request, ticket, props_form=form, status=400)
    changes = services.update_ticket(
        ticket=ticket,
        actor=request.user,
        status=form.cleaned_data["status"],
        priority=form.cleaned_data["priority"],
        assignee=form.cleaned_data["assignee"],
        category=form.cleaned_data["category"],
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
        messages.success(request, "Marked as resolved. Thanks for letting IT know.")
    return redirect(ticket)


@login_required
@require_POST
def reopen(request, number: int):
    ticket = _get_ticket(request, number)
    if ticket.requester_id != request.user.pk:
        raise PermissionDenied
    if services.reopen_by_requester(ticket=ticket, user=request.user):
        messages.info(request, "Request reopened. Tell IT what's still wrong.")
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
        if term.isdigit():
            match |= Q(pk=Ticket.pk_from_number(int(term)))
        tickets = tickets.filter(match)
    if category.isdigit():
        tickets = tickets.filter(category_id=int(category))
    if priority.isdigit():
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

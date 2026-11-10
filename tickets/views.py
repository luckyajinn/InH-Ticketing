from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Max, Q
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.departments import Department
from tickets import password_guard, reports, selectors, services
from tickets.forms import MoveForm, MoveRequestForm, NewTicketForm, RemovalForm, ReplyForm, TicketPropertiesForm
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


def admin_required(view):
    """Admin-only pages (Reports). Agents and requesters get a 403."""

    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_admin:
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
def _render_detail(request, ticket, *, reply_form=None, props_form=None, move_form=None,
                   move_request_form=None, status=200):
    user = request.user
    context = {
        "ticket": ticket,
        "timeline": selectors.timeline(ticket, user),
        "original_attachments": [
            a for a in selectors.visible_attachments(ticket, user) if a.comment_id is None
        ],
        "reply_form": reply_form or ReplyForm(user=user, ticket=ticket),
    }
    context["follows_up"], context["follow_ups"] = selectors.linked_tickets(ticket, user)
    if user.works_on(ticket):
        context["props_form"] = props_form or TicketPropertiesForm(ticket=ticket, me=user)
        context["all_attachments"] = selectors.visible_attachments(ticket, user)
        # Only this person's department's tickets (all of them for admins).
        context["other_tickets"] = (
            Ticket.objects.worked_by(user).filter(requester=ticket.requester_id)
            .exclude(pk=ticket.pk).select_related("category")
            .order_by("-created_at")[:5]
        )
        if user.is_admin:
            context["move_form"] = move_form or MoveForm(ticket=ticket)
            context["move_request"] = services.pending_move_request(ticket)
        else:
            context["move_request_form"] = move_request_form or MoveRequestForm(ticket=ticket)
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
    if ticket.is_archived:
        messages.error(request, services.ARCHIVED)
        return redirect(ticket)
    form = ReplyForm(request.POST, request.FILES, user=request.user, ticket=ticket)
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
            share_on_move=form.shares_on_move,
        )
    except PermissionDenied as exc:
        messages.error(request, str(exc) or "You can't reply to this ticket.")
        return redirect(ticket)
    place = PasswordWarning.Place.INTERNAL_NOTE if form.is_internal else PasswordWarning.Place.REPLY
    password_guard.record_form(form, user=request.user, place=place, ticket=ticket, comment=comment)
    if form.is_internal:
        messages.success(request, "Internal note added. The requester can't see it.")
    elif request.user.works_on(ticket) and request.user.pk != ticket.requester_id:
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


def _get_worked_ticket(request, number: int) -> Ticket:
    """A ticket this person works on and can still change, or 404 / 403 / back to it."""
    ticket = _get_ticket(request, number)
    if not request.user.works_on(ticket):
        raise PermissionDenied
    return ticket


@agent_required
@require_POST
def update_properties(request, number: int):
    ticket = _get_worked_ticket(request, number)
    if ticket.is_archived:
        messages.error(request, services.ARCHIVED)
        return redirect(ticket)
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
    ticket = _get_worked_ticket(request, number)
    if ticket.is_archived:
        messages.error(request, services.ARCHIVED)
    elif services.assign_to_me(ticket=ticket, actor=request.user):
        messages.success(request, f"#{ticket.number} is assigned to you.")
    return redirect(ticket)


@admin_required
@require_POST
def move_ticket(request, number: int):
    """An admin moves a ticket to another department, once that department has agreed."""
    ticket = _get_ticket(request, number)
    if ticket.is_archived:
        messages.error(request, services.ARCHIVED)
        return redirect(ticket)
    form = MoveForm(request.POST, ticket=ticket)
    if not form.is_valid():
        return _render_detail(request, ticket, move_form=form, status=400)
    changes = services.move_ticket(ticket=ticket, actor=request.user, category=form.cleaned_data["category"])
    messages.success(request, "Done: " + ", ".join(changes) + ".")
    return redirect(ticket)


@agent_required
@require_POST
def ask_to_move(request, number: int):
    """Staff ask an admin to move a ticket that's in the wrong department."""
    ticket = _get_worked_ticket(request, number)
    if ticket.is_archived:
        messages.error(request, services.ARCHIVED)
        return redirect(ticket)
    form = MoveRequestForm(request.POST, ticket=ticket)
    if not form.is_valid():
        return _render_detail(request, ticket, move_request_form=form, status=400)
    department = form.cleaned_data["department"]
    services.request_move(ticket=ticket, actor=request.user, department=department,
                          reason=form.cleaned_data["reason"])
    messages.success(request, f"Asked an admin to move it to {Department(department).label}. "
                              "Let them know once that team has agreed to take it.")
    return redirect(ticket)


def _removal_part(ticket: Ticket, raw: str):
    """(part, comment, current text, label, files) for ?part=subject|description|c<id>, or None."""
    if raw == "subject":
        return "subject", None, ticket.subject, "the subject", []
    if raw == "description":
        files = list(ticket.attachments.filter(comment__isnull=True))
        return "description", None, ticket.description, "the request", files
    if raw.startswith("c") and raw[1:].isdecimal():
        comment = ticket.comments.select_related("author").filter(pk=int(raw[1:])).first()
        if comment:
            kind = "internal note" if comment.is_internal else "reply"
            return "comment", comment, comment.body, f"a {kind} from {comment.author}", list(comment.attachments.all())
    return None


@admin_required
@never_cache
@require_http_methods(["GET", "POST"])
def remove_content(request, number: int):
    """Take a pasted password or a file out of a ticket. Admins only; the history says that, never what."""
    ticket = _get_ticket(request, number)
    raw = request.POST.get("part") or request.GET.get("part") or ""
    found = _removal_part(ticket, raw)
    if found is None:
        raise Http404
    part, comment, current, label, files = found
    form = RemovalForm(request.POST or None, current=current, files=files, allow_whole=part != "subject")
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        summary = services.remove_content(
            ticket=ticket, actor=request.user, part=part, comment=comment,
            text=data["text"], whole=data["whole"], attachments=data["attachments"],
        )
        messages.success(request, f"Removed {summary}. Emails already delivered are still in people's "
                                  "mailboxes: ask them to delete those, and reset the password if it was one.")
        return redirect(ticket)
    status = 400 if request.method == "POST" else 200
    return render(request, "tickets/remove.html", {
        "ticket": ticket, "form": form, "part": raw, "label": label, "current": current,
        "files": files, "allow_whole": part != "subject",
    }, status=status)


@admin_required
@require_POST
def unarchive(request, number: int):
    """An admin takes a ticket out of the archive, so it can be reopened."""
    ticket = _get_ticket(request, number)
    if services.unarchive(ticket=ticket, actor=request.user):
        messages.success(request, f"#{ticket.number} is out of the archive. It's still Closed; reopen it from Status.")
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
    {"id": "archive", "label": "Archive", "icon": "archive"},
]
RECENT = timedelta(days=14)


def _queue_queryset(view_id: str, user, department: str = ""):
    """A queue view's tickets: this person's department's (all of them, or one, for admins)."""
    tickets = Ticket.objects.worked_by(user)
    if user.is_admin and department in Department.values:
        tickets = tickets.filter(category__department=department)
    if view_id == "archive":
        return tickets.archived()
    tickets = tickets.not_archived()
    if view_id == "unassigned":
        return tickets.open().filter(assignee__isnull=True)
    if view_id == "mine":
        return tickets.open().filter(assignee=user)
    if view_id == "waiting":
        return tickets.filter(status=Status.WAITING)
    if view_id == "resolved":
        return tickets.filter(status=Status.RESOLVED, updated_at__gte=timezone.now() - RECENT)
    return tickets.open()


@agent_required
@require_GET
def queue(request):
    view_ids = [v["id"] for v in QUEUE_VIEWS]
    view_id = request.GET.get("view") if request.GET.get("view") in view_ids else "open"
    department = request.GET.get("dept", "") if request.user.is_admin else ""
    department = department if department in Department.values else ""
    views = [
        {**v, "count": _queue_queryset(v["id"], request.user, department).count(), "current": v["id"] == view_id}
        for v in QUEUE_VIEWS
    ]
    current = next(v for v in views if v["current"])

    tickets = _queue_queryset(view_id, request.user, department).select_related(
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
    elif view_id == "archive":
        tickets = tickets.order_by("-archived_at")
        sort_label = "most recently archived first"
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
            "filtered": bool(q or category or priority or department),
            "categories": (Category.objects.all() if request.user.is_admin
                           else Category.objects.filter(department=request.user.agent_department)),
            "department": department,
            "departments": Department.choices if request.user.is_admin else [],
            "department_label": (Department(department).label if department
                                 else "All departments" if request.user.is_admin
                                 else Department(request.user.agent_department).label),
            "priorities": sorted(Ticket.Priority.choices, reverse=True),
            "sort_label": sort_label,
        },
    )


# --- Reports (admins only) ---------------------------------------------------

@admin_required
@never_cache
@require_GET
def reports_page(request):
    """How the help desk is doing, by team: counts and times, never per person."""
    data = reports.build(request.GET.get("period", reports.DEFAULT_PERIOD), request.GET.get("team", ""))
    return render(request, "tickets/reports.html", data)


@admin_required
@never_cache
@require_GET
def reports_csv(request):
    """The requests behind the report, one row each, for a spreadsheet."""
    period = request.GET.get("period", reports.DEFAULT_PERIOD)
    team = request.GET.get("team", "")
    response = HttpResponse(reports.csv_export(period, team), content_type="text/csv; charset=utf-8")
    window = reports.window_for(period, timezone.now())
    name = f"inh-requests-{timezone.localtime(window.start):%Y-%m-%d}-to-{timezone.localtime(window.end):%Y-%m-%d}.csv"
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response

"""
Reports for admins (/reports/): how the help desk is doing, by team.

Counts and times per team, never per person: no figures for one agent or
one requester. Everything is read on request from records the app already
keeps (tickets, their history, the email queues and the password audit
trail); nothing new is collected. Volumes are small (a few thousand tickets
a year), so the sums are done in Python, the same on PostgreSQL and SQLite.

Definitions (also shown at the bottom of the page):
- First response: the first public reply from someone other than the
  requester, or the ticket being resolved or closed by someone else,
  whichever comes first. Wall-clock time, nights and weekends included.
- Time to resolve: from the request to its (last) resolution, not counting
  time spent waiting on the requester or already resolved before a reopen.
- Reopened: put back to Open from Resolved or Closed, by the requester
  ("This is still a problem") or by IT. A requester's reply to a resolved
  ticket also reopens it, but thank-you replies would inflate that, so it
  isn't counted.
- Documentation: a ticket's write-up by the staff working it, counted in the
  period it was last updated, under the ticket's team. Blank write-ups don't
  count. Who last updated one is shown as a record, never counted per person.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass

from django.conf import settings
from django.db.models import F, Max, Min, Q
from django.db.models.functions import Trim
from django.utils import timezone
from django.utils.text import capfirst

from core import departments
from inbound.models import InboundEmail
from notifications import heartbeat
from notifications.models import OutboundEmail
from tickets.models import Category, Comment, PasswordWarning, Ticket, TicketDocumentation, TicketEvent

Status = Ticket.Status


class Teams:
    """
    The teams are the departments: each category belongs to one. Each keeps its
    own colour (Department.colour), never one by rank, and they're listed in
    colour order, the order the colours were checked for telling neighbours apart.
    """

    def __init__(self):
        rows = departments.all_departments()
        self.keys = [d.key for d in rows] or [departments.IT]
        self.labels = {d.key: d.name for d in rows} or {departments.IT: departments.IT_NAME}
        self.slots = {d.key: d.colour for d in rows} or {departments.IT: 1}

    def __contains__(self, key) -> bool:
        return key in self.labels

    def of(self, department: str) -> str:
        """A ticket's team: its category's department (IT if that's gone)."""
        return department if department in self.labels else departments.IT

    @property
    def choices(self) -> list[tuple[str, str]]:
        return [(key, self.labels[key]) for key in self.keys]


PERIODS = {
    "7": (7, "Last 7 days"),
    "30": (30, "Last 30 days"),
    "90": (90, "Last 90 days"),
    "365": (365, "Last 12 months"),
}
DEFAULT_PERIOD = "30"

PILOT_PREFIX = "Pilot:"
WAITING_LONG = dt.timedelta(days=7)
# The worker sends email every 15 seconds; an email due for longer than this means it isn't running.
WORKER_LATE = dt.timedelta(minutes=2)
AGE_BANDS = [
    ("Under a day", dt.timedelta(days=1)),
    ("1 to 3 days", dt.timedelta(days=3)),
    ("3 to 7 days", dt.timedelta(days=7)),
    ("Over 7 days", None),
]
_PAUSED = {Status.WAITING.label, Status.RESOLVED.label}


def _team_q(team: str) -> Q:
    return Q(category__department=team)


def reports_from() -> dt.datetime | None:
    """settings.REPORTS_FROM as local midnight, or None (blank or not a date)."""
    try:
        day = dt.date.fromisoformat(settings.REPORTS_FROM)
    except ValueError:
        return None
    return timezone.make_aware(dt.datetime.combine(day, dt.time.min))


def counted_tickets(team: str = ""):
    """The tickets reports count: no pilot feedback, nothing before REPORTS_FROM."""
    tickets = Ticket.objects.exclude(subject__istartswith=PILOT_PREFIX)
    start = reports_from()
    if start:
        tickets = tickets.filter(created_at__gte=start)
    if team:
        tickets = tickets.filter(_team_q(team))
    return tickets


# ---------------------------------------------------------------------------
# The period
# ---------------------------------------------------------------------------

def _midnight(day: dt.date) -> dt.datetime:
    return timezone.make_aware(dt.datetime.combine(day, dt.time.min))


def _add_months(day: dt.date, months: int) -> dt.date:
    index = day.year * 12 + day.month - 1 + months
    return dt.date(index // 12, index % 12 + 1, 1)


@dataclass
class Window:
    key: str
    label: str
    start: dt.datetime
    end: dt.datetime
    prev_start: dt.datetime
    bucket: str  # "day", "week" or "month"

    @property
    def prev_phrase(self) -> str:
        return "the 12 months before" if self.key == "365" else f"the {PERIODS[self.key][0]} days before"


def window_for(key: str, now: dt.datetime) -> Window:
    key = key if key in PERIODS else DEFAULT_PERIOD
    days, label = PERIODS[key]
    today = timezone.localtime(now).date()
    if key == "365":
        first = _add_months(today.replace(day=1), -11)
        start, prev_start, bucket = _midnight(first), _midnight(_add_months(first, -12)), "month"
    elif key == "7":
        start = _midnight(today - dt.timedelta(days=6))
        prev_start, bucket = start - dt.timedelta(days=7), "day"
    else:
        start = now - dt.timedelta(days=days)
        prev_start, bucket = start - dt.timedelta(days=days), "week"
    return Window(key, label, start, now, prev_start, bucket)


def _bucket_of(when: dt.datetime, bucket: str) -> dt.date:
    day = timezone.localtime(when).date()
    if bucket == "week":
        return day - dt.timedelta(days=day.weekday())
    if bucket == "month":
        return day.replace(day=1)
    return day


def _buckets(window: Window) -> list[dt.date]:
    first, last = _bucket_of(window.start, window.bucket), _bucket_of(window.end, window.bucket)
    keys, day = [], first
    while day <= last:
        keys.append(day)
        day = _add_months(day, 1) if window.bucket == "month" else day + dt.timedelta(
            days=7 if window.bucket == "week" else 1)
    return keys


def _bucket_labels(day: dt.date, bucket: str) -> tuple[str, str]:
    """(short label under the column, long label for the tooltip and table)."""
    if bucket == "month":
        return f"{day:%b}", f"{day:%B %Y}"
    if bucket == "week":
        return f"{day:%b} {day.day}", f"Week of {day:%b} {day.day}, {day.year}"
    return f"{day:%a} {day.day}", f"{day:%A}, {day:%b} {day.day}"


# ---------------------------------------------------------------------------
# Per-ticket times
# ---------------------------------------------------------------------------

def first_responses(tickets) -> dict[int, dt.datetime]:
    """When each ticket first got a response from someone other than its requester."""
    replies = (
        Comment.objects.filter(ticket__in=tickets, is_internal=False)
        .exclude(author_id=F("ticket__requester_id"))
        .values("ticket_id").annotate(at=Min("created_at"))
    )
    resolutions = (
        TicketEvent.objects.filter(
            ticket__in=tickets, kind=TicketEvent.Kind.STATUS,
            new_value__in=[Status.RESOLVED.label, Status.CLOSED.label], actor__isnull=False,
        )
        .exclude(actor_id=F("ticket__requester_id"))
        .values("ticket_id").annotate(at=Min("created_at"))
    )
    first = {}
    for row in [*replies, *resolutions]:
        if row["ticket_id"] not in first or row["at"] < first[row["ticket_id"]]:
            first[row["ticket_id"]] = row["at"]
    return first


def resolve_seconds(tickets) -> dict[int, float]:
    """Time to (last) resolution, minus time waiting on the requester or already resolved."""
    rows = list(tickets.values_list("pk", "created_at", "resolved_at"))
    paused = defaultdict(float)
    since = {}
    resolved = {pk: resolved_at for pk, _, resolved_at in rows}
    events = (
        TicketEvent.objects.filter(ticket__in=tickets, kind=TicketEvent.Kind.STATUS)
        .order_by("ticket_id", "created_at", "pk").values_list("ticket_id", "new_value", "created_at")
    )
    for pk, new_value, at in events:
        if at >= resolved[pk]:
            # The last resolution (or a later close) ends the count.
            if pk in since:
                paused[pk] += (resolved[pk] - since.pop(pk)).total_seconds()
            continue
        if pk in since:
            paused[pk] += (at - since.pop(pk)).total_seconds()
        if new_value in _PAUSED:
            since[pk] = at
    return {
        pk: max((resolved_at - created_at).total_seconds() - paused[pk], 0.0)
        for pk, created_at, resolved_at in rows
    }


def _median(values) -> float | None:
    values = list(values)
    return statistics.median(values) if values else None


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes = seconds / 60
    if minutes < 60:
        return f"{max(round(minutes), 1)} min"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} h" if hours < 10 else f"{round(hours)} h"
    days = hours / 24
    return f"{days:.1f} days" if days < 10 else f"{round(days)} days"


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def _period_stats(team: str, start: dt.datetime, end: dt.datetime, teams: Teams | None = None) -> dict:
    """Ticket figures for one period: new requests, response and resolve times, per team."""
    teams = teams or Teams()
    base = counted_tickets(team)
    new = base.filter(created_at__gte=start, created_at__lt=end)
    rows = list(new.values("pk", "created_at", "category__name", "category__department", "is_blocking", "source", "subject"))
    first = first_responses(new)
    resolved = base.filter(resolved_at__gte=start, resolved_at__lt=end, status__in=[Status.RESOLVED, Status.CLOSED])
    resolve = resolve_seconds(resolved)
    resolved_team = dict(resolved.values_list("pk", "category__department"))
    reopened = (
        TicketEvent.objects.filter(
            ticket__in=base, kind=TicketEvent.Kind.STATUS, created_at__gte=start, created_at__lt=end,
            old_value__in=[Status.RESOLVED.label, Status.CLOSED.label], new_value=Status.OPEN.label,
        )
        .exclude(note="requester replied").values_list("ticket__category__department", flat=True)
    )

    per_team = {key: {"new": 0, "web": 0, "blocking": 0, "first": [], "resolve": [], "resolved": 0, "reopened": 0}
                for key in teams.keys}
    for row in rows:
        stats = per_team[teams.of(row["category__department"])]
        stats["new"] += 1
        if row["source"] == Ticket.Source.WEB:
            stats["web"] += 1
            stats["blocking"] += row["is_blocking"]
        if row["pk"] in first:
            stats["first"].append((first[row["pk"]] - row["created_at"]).total_seconds())
    for pk, seconds in resolve.items():
        stats = per_team[teams.of(resolved_team[pk])]
        stats["resolved"] += 1
        stats["resolve"].append(seconds)
    for department in reopened:
        per_team[teams.of(department)]["reopened"] += 1

    every = {
        "new": len(rows),
        "web": sum(s["web"] for s in per_team.values()),
        "blocking": sum(s["blocking"] for s in per_team.values()),
        "first": [x for s in per_team.values() for x in s["first"]],
        "resolve": [x for s in per_team.values() for x in s["resolve"]],
        "resolved": len(resolve),
        "reopened": sum(s["reopened"] for s in per_team.values()),
    }
    return {"rows": rows, "per_team": per_team, "all": every}


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _tiles(cur: dict, prev: dict, window: Window) -> list[dict]:
    def duration_delta(now_value, before):
        if now_value is None or before is None:
            return None, None
        diff = now_value - before
        if abs(diff) < max(60, 0.05 * before):
            return f"About the same as {window.prev_phrase}", "flat"
        word = "faster" if diff < 0 else "slower"
        return f"{format_duration(abs(diff))} {word} than {window.prev_phrase}", "good" if diff < 0 else "bad"

    c, p = cur["all"], prev["all"]
    new_delta = c["new"] - p["new"]
    first_now, first_before = _median(c["first"]), _median(p["first"])
    resolve_now, resolve_before = _median(c["resolve"]), _median(p["resolve"])
    blocking_now, blocking_before = _share(c["blocking"], c["web"]), _share(p["blocking"], p["web"])
    tiles = [
        {
            "label": "New requests", "value": f"{c['new']:,}",
            "detail": f"{c['resolved']:,} resolved",
            "delta": (f"{new_delta:+,} vs {window.prev_phrase}" if new_delta else f"Same as {window.prev_phrase}")
            if p["new"] or c["new"] else None,
            "tone": "flat",
        },
        {
            "label": "First response", "value": format_duration(first_now),
            "detail": f"Median of {len(c['first'])} request{'s' if len(c['first']) != 1 else ''}",
        },
        {
            "label": "Time to resolve", "value": format_duration(resolve_now),
            "detail": "Median, not counting time waiting on the requester",
        },
        {
            "label": "Blocking work", "value": "—" if blocking_now is None else f"{blocking_now:.0%}",
            "detail": f"{c['blocking']} of {c['web']} web requests said they couldn't work",
        },
    ]
    tiles[1]["delta"], tiles[1]["tone"] = duration_delta(first_now, first_before)
    tiles[2]["delta"], tiles[2]["tone"] = duration_delta(resolve_now, resolve_before)
    if blocking_now is not None and blocking_before is not None:
        points = round((blocking_now - blocking_before) * 100)
        tiles[3]["delta"] = (f"{points:+d} points vs {window.prev_phrase}" if points
                             else f"Same as {window.prev_phrase}")
        tiles[3]["tone"] = "flat"
    return tiles


def _nice_axis(peak: int) -> tuple[int, list[int]]:
    """A round axis top and its ticks: 0-5 by 1, 0-10 by 2, then 1/2/5 steps."""
    if peak <= 5:
        return 5, list(range(0, 6))
    for step in (2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        top = -(-peak // step) * step
        if top / step <= 5:
            return top, list(range(0, top + 1, step))
    top = -(-peak // 1000) * 1000
    return top, list(range(0, top + 1, top // 5))


def _rounded_top(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    """A bar path with 4px rounded top corners and a square foot on the baseline."""
    r = min(r, w / 2, h)
    return (f"M{x:.1f},{y + h:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}"
            f"H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{y + h:.1f}Z")


def _rect(x: float, y: float, w: float, h: float) -> str:
    return f"M{x:.1f},{y + h:.1f}V{y:.1f}H{x + w:.1f}V{y + h:.1f}Z"


def column_chart(buckets: list[dict], series: list[str], width: int = 720, height: int = 230,
                 teams: Teams | None = None) -> dict:
    """Stacked columns, one per bucket, as SVG geometry (no inline styles, so a CSP stays strict)."""
    teams = teams or Teams()
    left, right, top_pad, bottom = 34, 8, 20, 26
    plot_w, plot_h = width - left - right, height - top_pad - bottom
    base = top_pad + plot_h
    totals = [sum(b["values"].get(s, 0) for s in series) for b in buckets]
    top, ticks = _nice_axis(max(totals, default=0))
    slot = plot_w / max(len(buckets), 1)
    bar_w = min(24.0, slot * 0.6)
    peak = max(totals, default=0)
    labelled = {len(buckets) - 1} | ({totals.index(peak)} if peak else set())
    columns = []
    for i, bucket in enumerate(buckets):
        x = left + i * slot + (slot - bar_w) / 2
        segments, cumulative = [], 0.0
        parts = [(s, bucket["values"].get(s, 0)) for s in series if bucket["values"].get(s, 0)]
        for j, (key, value) in enumerate(parts):
            lower = base - cumulative / top * plot_h
            cumulative += value
            upper = base - cumulative / top * plot_h
            gap = 2 if j else 0  # the surface gap between stacked segments
            h = max(lower - upper - gap, 1.0)
            last = j == len(parts) - 1
            segments.append({
                "d": _rounded_top(x, upper, bar_w, h) if last else _rect(x, upper, bar_w, h),
                "slot": teams.slots[key],
            })
        total_y = base - totals[i] / top * plot_h
        columns.append({
            "segments": segments,
            "total": totals[i],
            "label": i in labelled and totals[i] > 0,
            "label_x": x + bar_w / 2, "label_y": total_y - 6,
            "hit_x": left + i * slot, "hit_w": slot,
            "short": bucket["short"], "long": bucket["long"],
            "tip_rows": ";".join(f"{teams.labels[s]}|{bucket['values'].get(s, 0)}|{teams.slots[s]}" for s in series),
            "center": left + i * slot + slot / 2,
        })
    every = 1 if len(buckets) <= 14 else 2
    return {
        "width": width, "height": height, "top": top_pad, "plot_h": plot_h, "base": base,
        "left": left, "right": width - right,
        "grid": [{"y": base - t / top * plot_h, "label": f"{t:,}"} for t in ticks],
        "columns": columns,
        "x_labels": [c for i, c in enumerate(columns) if i % every == 0 or i == len(columns) - 1],
    }


def _ranked(counts: Counter, limit: int) -> list[dict]:
    items = counts.most_common(limit)
    peak = items[0][1] if items else 0
    return [{"name": name, "count": n, "pct": round(n / peak * 100, 1) if peak else 0} for name, n in items]


def build(period: str = DEFAULT_PERIOD, team: str = "", now: dt.datetime | None = None) -> dict:
    now = now or timezone.now()
    teams = Teams()
    team = team if team in teams else ""
    window = window_for(period, now)
    cur = _period_stats(team, window.start, window.end, teams)
    prev = _period_stats(team, window.prev_start, window.start, teams)
    series = [team] if team else list(teams.keys)

    # Requests over time
    by_bucket = defaultdict(Counter)
    for row in cur["rows"]:
        by_bucket[_bucket_of(row["created_at"], window.bucket)][teams.of(row["category__department"])] += 1
    buckets = []
    for day in _buckets(window):
        short, long = _bucket_labels(day, window.bucket)
        buckets.append({"short": short, "long": long, "values": dict(by_bucket[day])})
    chart = column_chart(buckets, series, teams=teams)
    chart_rows = [{"long": b["long"], "values": [b["values"].get(s, 0) for s in series],
                   "total": sum(b["values"].get(s, 0) for s in series)} for b in buckets]

    # By team
    team_rows = []
    for key, label in teams.choices:
        if team and key != team:
            continue
        s = cur["per_team"][key]
        team_rows.append({
            "key": key, "label": label, "slot": teams.slots[key], "new": s["new"], "resolved": s["resolved"],
            "first": format_duration(_median(s["first"])), "resolve": format_duration(_median(s["resolve"])),
            "blocking": "—" if not s["web"] else f"{s['blocking'] / s['web']:.0%}", "reopened": s["reopened"],
        })

    # Open now (not limited to the period)
    open_tickets = counted_tickets(team).open()
    open_rows = list(open_tickets.order_by("created_at").values(
        "pk", "subject", "status", "created_at", "assignee_id", "category__department"))
    for row in team_rows:
        row["open"] = sum(1 for r in open_rows if teams.of(r["category__department"]) == row["key"])
    bands = Counter()
    for row in open_rows:
        age = now - row["created_at"]
        for i, (_, limit) in enumerate(AGE_BANDS):
            if limit is None or age < limit:
                bands[i] += 1
                break
    band_peak = max(bands.values(), default=0)
    age_bars = [{"name": name, "count": bands[i], "step": i + 1,
                 "pct": round(bands[i] / band_peak * 100, 1) if band_peak else 0}
                for i, (name, _) in enumerate(AGE_BANDS)]
    waiting_since = dict(
        TicketEvent.objects.filter(ticket__in=open_tickets.filter(status=Status.WAITING),
                                   kind=TicketEvent.Kind.STATUS, new_value=Status.WAITING.label)
        .values("ticket_id").annotate(at=Max("created_at")).values_list("ticket_id", "at")
    )
    oldest = [{
        "number": r["pk"] + settings.TICKET_NUMBER_OFFSET, "subject": r["subject"], "team": teams.labels[teams.of(r["category__department"])],
        "status": Status(r["status"]).label, "age": format_duration((now - r["created_at"]).total_seconds()),
    } for r in open_rows[:5]]

    # What people ask for
    categories = Counter(row["category__name"] for row in cur["rows"])
    choices = {text for c in Category.objects.filter(is_active=True) for text in c.subject_choices}
    picked = Counter(row["subject"] for row in cur["rows"] if row["subject"] in choices)

    return {
        "window": window, "period": window.key, "team": team,
        "team_label": teams.labels.get(team, "All teams"),
        "periods": [(key, label) for key, (_, label) in PERIODS.items()],
        "teams": teams.choices,
        "tiles": _tiles(cur, prev, window),
        "chart": chart, "chart_rows": chart_rows, "series": [(s, teams.labels[s], teams.slots[s]) for s in series],
        "team_rows": team_rows,
        "open_count": len(open_rows),
        "unassigned": sum(1 for r in open_rows if r["assignee_id"] is None),
        "waiting_long": sum(1 for at in waiting_since.values() if now - at > WAITING_LONG),
        "age_bars": age_bars, "oldest": oldest,
        "categories": _ranked(categories, 7),
        "common_requests": _ranked(picked, 5),
        "health": health(window, now),
        "documentation": documentation_summary(window, team, teams),
        "reports_from": reports_from(),
        "now": now,
    }


def health(window: Window, now: dt.datetime) -> dict:
    """Email in and out, auto-close and the password check (all teams, the same period)."""
    start, end = window.start, window.end
    outbound = OutboundEmail.objects
    overdue = (outbound.filter(status=OutboundEmail.Status.PENDING, next_attempt_at__lte=now - WORKER_LATE)
               .order_by("next_attempt_at").values_list("next_attempt_at", flat=True).first())
    inbound = Counter(InboundEmail.objects.filter(created_at__gte=start, created_at__lt=end)
                      .values_list("outcome", flat=True))
    warnings = Counter(PasswordWarning.objects.filter(created_at__gte=start, created_at__lt=end)
                       .values_list("outcome", flat=True))
    return {
        "inbound_on": settings.INBOUND_EMAIL == "graph",
        "auto_close_days": settings.AUTO_CLOSE_RESOLVED_DAYS,
        "sent": outbound.filter(status=OutboundEmail.Status.SENT, sent_at__gte=start, sent_at__lt=end).count(),
        "failed": outbound.filter(status=OutboundEmail.Status.FAILED, created_at__gte=start, created_at__lt=end).count(),
        "retrying": outbound.filter(status=OutboundEmail.Status.PENDING, attempts__gt=0).count(),
        "worker_late": format_duration((now - overdue).total_seconds()) if overdue else "",
        "worker": worker_health(now),
        "in_tickets": inbound[InboundEmail.Outcome.NEW_TICKET],
        "in_replies": inbound[InboundEmail.Outcome.REPLY] + inbound[InboundEmail.Outcome.NOTE],
        "in_ignored": inbound[InboundEmail.Outcome.IGNORED],
        "in_errors": inbound[InboundEmail.Outcome.ERROR],
        "pw_removed": warnings[PasswordWarning.Outcome.REMOVED],
        "pw_sent": warnings[PasswordWarning.Outcome.SENT_ANYWAY],
        "pw_emailed": warnings[PasswordWarning.Outcome.EMAILED],
        "auto_closed": TicketEvent.objects.filter(
            kind=TicketEvent.Kind.STATUS, new_value=Status.CLOSED.label, actor__isnull=True,
            created_at__gte=start, created_at__lt=end,
        ).count(),
    }


def _ago(start: dt.datetime | None, now: dt.datetime) -> str:
    """'under a minute', '12 min', '3.0 h'; empty if it never happened."""
    if start is None:
        return ""
    seconds = max((now - start).total_seconds(), 0)
    return "under a minute" if seconds < 60 else format_duration(seconds)


def worker_health(now: dt.datetime) -> dict:
    """What the worker last did, from its heartbeat (notifications.heartbeat)."""
    beat = heartbeat.latest()
    if beat is None:
        return {"state": "never"}
    return {
        "state": heartbeat.state(beat, now),
        "seen_ago": _ago(beat.round_at, now),
        "started_at": beat.started_at,
        "inbox_at": beat.inbox_at,
        "inbox_ago": _ago(beat.inbox_at, now),
        "inbox_ok_ago": _ago(beat.inbox_ok_at, now),
        "inbox_error": beat.inbox_error,
        "auto_close_at": beat.auto_close_at,
        "auto_close_ago": _ago(beat.auto_close_at, now),
        "auto_close_error": beat.auto_close_error,
    }


# ---------------------------------------------------------------------------
# Ticket documentation (admins read it here; staff write it on the ticket)
# ---------------------------------------------------------------------------

RECENT_DOCUMENTATION = 5


def filled_documentation():
    """Write-ups with something in them. Whitespace alone (spaces) counts as blank, like is_empty."""
    fields = TicketDocumentation.TEXT_FIELDS
    return (TicketDocumentation.objects
            .alias(**{f"trimmed_{name}": Trim(name) for name in fields})
            .exclude(**{f"trimmed_{name}": "" for name in fields}))


def documentation_in(window: Window, team: str = ""):
    """Filled write-ups last updated in the period, on tickets the reports count (pilot ones out)."""
    return filled_documentation().filter(
        ticket__in=counted_tickets(team), updated_at__gte=window.start, updated_at__lt=window.end,
    )


def documentation_summary(window: Window, team: str = "", teams: Teams | None = None) -> dict:
    """The Reports card: how many were written or updated, how many finished tickets have none, the latest few."""
    teams = teams or Teams()
    # One light query for the count and the latest rows (no text fields), one for the gaps.
    rows = list(documentation_in(window, team).order_by("-updated_at", "-pk").values(
        "updated_at", "ticket_id", "ticket__subject", "ticket__status", "ticket__category__department",
        "updated_by__display_name", "updated_by__email",
    ))
    missing = (
        counted_tickets(team)
        .filter(resolved_at__gte=window.start, resolved_at__lt=window.end, status__in=[Status.RESOLVED, Status.CLOSED])
        .exclude(pk__in=filled_documentation().values("ticket_id"))
        .count()
    )
    return {
        "count": len(rows),
        "missing": missing,
        "recent": [{
            "number": r["ticket_id"] + settings.TICKET_NUMBER_OFFSET, "subject": r["ticket__subject"],
            "team": teams.labels[teams.of(r["ticket__category__department"])],
            "status": Status(r["ticket__status"]).label, "updated_at": r["updated_at"],
            "updated_by": r["updated_by__display_name"] or r["updated_by__email"] or "",
        } for r in rows[:RECENT_DOCUMENTATION]],
    }


def documentation_entries(period: str = DEFAULT_PERIOD, team: str = "", q: str = "",
                          now: dt.datetime | None = None) -> dict:
    """The full list (/reports/documentation/): the card's write-ups, newest first, searchable."""
    now = now or timezone.now()
    teams = Teams()
    team = team if team in teams else ""
    window = window_for(period, now)
    entries = documentation_in(window, team)
    q = q.strip()
    if q:
        term = q.lstrip("#").strip()
        match = Q(ticket__subject__icontains=term)
        for name in TicketDocumentation.TEXT_FIELDS:
            match |= Q(**{f"{name}__icontains": term})
        if term.isdecimal() and len(term) < 10:  # a ticket number, not a number too big for the database
            match |= Q(ticket_id=Ticket.pk_from_number(int(term)))
        entries = entries.filter(match)
    entries = entries.select_related("ticket__category", "updated_by").order_by("-updated_at", "-pk")
    return {
        "entries": entries, "window": window, "period": window.key, "team": team, "q": q,
        "team_label": teams.labels.get(team, "All teams"),
        "periods": [(key, label) for key, (_, label) in PERIODS.items()],
        "teams": teams.choices, "team_names": teams,
    }


def label_entries(entries, teams: Teams) -> None:
    """Team names and headed sections for a page of write-ups (team names from one lookup, not a query each)."""
    headings = [(name, capfirst(TicketDocumentation._meta.get_field(name).verbose_name))
                for name in TicketDocumentation.TEXT_FIELDS]
    for doc in entries:
        doc.sections = [(heading, getattr(doc, name).strip()) for name, heading in headings]
        team = teams.of(doc.ticket.category.department)
        doc.team_label = teams.labels[team]
        # The department that wrote it, when the ticket has moved to another team since.
        doc.written_by_label = (teams.labels[doc.department]
                                if doc.department in teams and doc.department != team else "")


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

CSV_HEADER = [
    "Ticket", "Created", "Team", "Category", "Priority", "Source", "Status", "Blocking",
    "First response (hours)", "Time to resolve (hours)", "Resolved", "Documented", "Subject",
]


def _cell(value) -> str:
    """Spreadsheet-safe text: a cell starting with = + - @ (or a tab) is shown, never run."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def csv_export(period: str = DEFAULT_PERIOD, team: str = "", now: dt.datetime | None = None) -> str:
    """One row per request created in the period. No descriptions, no names, no documentation text."""
    now = now or timezone.now()
    teams = Teams()
    team = team if team in teams else ""
    window = window_for(period, now)
    tickets = counted_tickets(team).filter(created_at__gte=window.start, created_at__lt=window.end)
    first = first_responses(tickets)
    resolve = resolve_seconds(tickets.filter(status__in=[Status.RESOLVED, Status.CLOSED], resolved_at__isnull=False))
    documented = set(filled_documentation().filter(ticket__in=tickets).values_list("ticket_id", flat=True))
    out = io.StringIO()
    out.write("﻿")  # so Excel reads it as UTF-8
    writer = csv.writer(out)
    writer.writerow(CSV_HEADER)
    for t in tickets.select_related("category").order_by("created_at"):
        local = timezone.localtime(t.created_at)
        writer.writerow([_cell(v) for v in [
            t.number, f"{local:%Y-%m-%d %H:%M}", teams.labels[teams.of(t.category.department)], t.category.name,
            t.get_priority_display(), t.get_source_display(), t.get_status_display(),
            "Yes" if t.is_blocking else "No",
            f"{(first[t.pk] - t.created_at).total_seconds() / 3600:.1f}" if t.pk in first else "",
            f"{resolve[t.pk] / 3600:.1f}" if t.pk in resolve else "",
            f"{timezone.localtime(t.resolved_at):%Y-%m-%d %H:%M}" if t.resolved_at else "",
            "Yes" if t.pk in documented else "No",
            t.subject,
        ]])
    return out.getvalue()

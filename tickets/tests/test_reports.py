"""Reports (/reports/): admins only, per team, never per person."""

import datetime as dt
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from inbound.models import InboundEmail
from notifications import heartbeat
from notifications.models import OutboundEmail
from tickets import reports, services
from tickets.examples import add_example_departments
from tickets.models import Category, Comment, PasswordWarning, Ticket, TicketEvent
from tickets.tests.helpers import MediaTestCase, make_ticket, make_user

LA = ZoneInfo("America/Los_Angeles")
NOW = dt.datetime(2026, 11, 10, 12, 0, tzinfo=LA)
Status = Ticket.Status


def at(ticket, created, resolved=None, status=None):
    """Move a ticket (and its own creation events) to fixed times."""
    fields = {"created_at": created}
    if resolved:
        fields.update(resolved_at=resolved, status=status or Status.RESOLVED)
    elif status:
        fields["status"] = status
    Ticket.objects.filter(pk=ticket.pk).update(**fields)
    ticket.refresh_from_db()
    return ticket


def event(ticket, when, new, old="", actor=None, note=""):
    e = TicketEvent.objects.create(ticket=ticket, actor=actor, kind=TicketEvent.Kind.STATUS,
                                   old_value=old, new_value=new, note=note)
    TicketEvent.objects.filter(pk=e.pk).update(created_at=when)


def comment(ticket, author, when, internal=False):
    c = Comment.objects.create(ticket=ticket, author=author, body="x", is_internal=internal)
    Comment.objects.filter(pk=c.pk).update(created_at=when)


class ReportsTestCase(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.admin = make_user("Ada Admin", User.Role.ADMIN)
        User.objects.filter(pk=self.admin.pk).update(is_staff=True, is_superuser=True)
        self.admin.refresh_from_db()
        examples = add_example_departments()
        self.mechanics, self.cleaning = examples["mechanics"], examples["cleaning"]

    def ticket(self, created, subject="Printer jammed", category=None, **kwargs):
        t = make_ticket(self.requester, subject=subject, category=category)
        # Only the ticket itself: no creation-time comments or events to move.
        TicketEvent.objects.filter(ticket=t).delete()
        return at(t, created, **kwargs)


class AccessTests(ReportsTestCase):
    def test_admins_only(self):
        for url in (reverse("tickets:reports"), reverse("tickets:reports_csv")):
            with self.subTest(url=url):
                self.client.logout()
                self.assertRedirects(self.client.get(url), f"{reverse('accounts:signin')}?next={url}",
                                     fetch_redirect_response=False)
                for user in (self.requester, self.agent):
                    self.client.force_login(user)
                    self.assertEqual(self.client.get(url).status_code, 403)
                self.client.force_login(self.admin)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])

    def test_link_only_for_admins(self):
        self.client.force_login(self.agent)
        self.assertNotContains(self.client.get(reverse("tickets:queue")), 'href="/reports/"')
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("tickets:queue")), 'href="/reports/"')
        self.assertContains(self.client.get("/admin/"), 'href="/reports/"')

    def test_page_renders_with_no_data(self):
        self.client.force_login(self.admin)
        for period in ("7", "30", "90", "365", "bogus"):
            for team in ("", "it", "mechanics", "cleaning", "nonsense"):
                with self.subTest(period=period, team=team):
                    response = self.client.get(reverse("tickets:reports"), {"period": period, "team": team})
                    self.assertContains(response, "Requests over time")
                    self.assertContains(response, "never figures for one person")

    def test_no_names_on_the_page(self):
        self.ticket(NOW - dt.timedelta(days=2))
        self.client.force_login(self.admin)
        page = self.client.get(reverse("tickets:reports")).content.decode()
        for name in ("Dana Whitfield", "Sam Patel", "Alex Morgan"):
            self.assertNotIn(name, page)


class TimeTests(ReportsTestCase):
    def test_first_response_is_the_first_public_reply_by_someone_else(self):
        t0 = NOW - dt.timedelta(days=2)
        t = self.ticket(t0)
        comment(t, self.agent, t0 + dt.timedelta(minutes=10), internal=True)  # internal note: no
        comment(t, self.requester, t0 + dt.timedelta(minutes=20))  # the requester: no
        comment(t, self.agent, t0 + dt.timedelta(hours=2))  # IT's public reply: yes
        first = reports.first_responses(Ticket.objects.filter(pk=t.pk))
        self.assertEqual(first[t.pk], t0 + dt.timedelta(hours=2))

    def test_being_resolved_by_it_counts_as_a_response(self):
        t0 = NOW - dt.timedelta(days=2)
        t = self.ticket(t0)
        event(t, t0 + dt.timedelta(hours=1), Status.RESOLVED.label, Status.NEW.label, actor=self.agent)
        first = reports.first_responses(Ticket.objects.filter(pk=t.pk))
        self.assertEqual(first[t.pk], t0 + dt.timedelta(hours=1))

    def test_resolving_it_yourself_isnt_a_response(self):
        t0 = NOW - dt.timedelta(days=2)
        t = self.ticket(t0)
        event(t, t0 + dt.timedelta(hours=1), Status.RESOLVED.label, actor=self.requester,
              note="marked resolved by requester")
        self.assertEqual(reports.first_responses(Ticket.objects.filter(pk=t.pk)), {})

    def test_time_to_resolve_leaves_out_waiting_on_the_requester(self):
        t0 = NOW - dt.timedelta(days=3)
        t = self.ticket(t0, resolved=t0 + dt.timedelta(hours=6))
        event(t, t0 + dt.timedelta(hours=1), Status.WAITING.label, actor=self.agent)
        event(t, t0 + dt.timedelta(hours=5), Status.OPEN.label, actor=self.requester, note="requester replied")
        event(t, t0 + dt.timedelta(hours=6), Status.RESOLVED.label, actor=self.agent)
        seconds = reports.resolve_seconds(Ticket.objects.filter(pk=t.pk))
        self.assertEqual(seconds[t.pk], 2 * 3600)

    def test_time_resolved_before_a_reopen_is_left_out_too(self):
        t0 = NOW - dt.timedelta(days=3)
        t = self.ticket(t0, resolved=t0 + dt.timedelta(hours=10))
        event(t, t0 + dt.timedelta(hours=1), Status.RESOLVED.label, actor=self.agent)
        event(t, t0 + dt.timedelta(hours=9), Status.OPEN.label, actor=self.requester, note="reopened by requester")
        event(t, t0 + dt.timedelta(hours=10), Status.RESOLVED.label, actor=self.agent)
        self.assertEqual(reports.resolve_seconds(Ticket.objects.filter(pk=t.pk))[t.pk], 2 * 3600)

    def test_format_duration(self):
        cases = [(None, "—"), (20, "1 min"), (45 * 60, "45 min"), (90 * 60, "1.5 h"), (30 * 3600, "30 h"),
                 (3 * 86400, "3.0 days"), (15 * 86400, "15 days")]
        for seconds, text in cases:
            with self.subTest(seconds=seconds):
                self.assertEqual(reports.format_duration(seconds), text)


class CountingTests(ReportsTestCase):
    def test_teams_come_from_the_category(self):
        self.ticket(NOW - dt.timedelta(days=1))
        self.ticket(NOW - dt.timedelta(days=1), category=self.mechanics)
        self.ticket(NOW - dt.timedelta(days=1), category=self.mechanics)
        self.ticket(NOW - dt.timedelta(days=1), category=self.cleaning)
        data = reports.build("30", now=NOW)
        self.assertEqual({r["key"]: r["new"] for r in data["team_rows"]}, {"it": 1, "mechanics": 2, "cleaning": 1})
        only = reports.build("30", team="mechanics", now=NOW)
        self.assertEqual([(r["key"], r["new"]) for r in only["team_rows"]], [("mechanics", 2)])
        self.assertEqual(only["tiles"][0]["value"], "2")

    def test_pilot_feedback_and_tickets_before_reports_from_are_left_out(self):
        self.ticket(NOW - dt.timedelta(days=1), subject="Pilot: the queue button is odd")
        self.ticket(NOW - dt.timedelta(days=8))
        self.ticket(NOW - dt.timedelta(days=1))
        self.assertEqual(reports.build("30", now=NOW)["tiles"][0]["value"], "2")
        with override_settings(REPORTS_FROM="2026-11-05"):
            self.assertEqual(reports.build("30", now=NOW)["tiles"][0]["value"], "1")
        with override_settings(REPORTS_FROM="not a date"):
            self.assertEqual(reports.build("30", now=NOW)["tiles"][0]["value"], "2")

    def test_late_on_the_last_day_of_the_month_counts_in_that_month(self):
        # 23:30 on Oct 31 in Los Angeles is already Nov 1 in UTC.
        self.ticket(dt.datetime(2026, 10, 31, 23, 30, tzinfo=LA))
        rows = {r["long"]: r["total"] for r in reports.build("365", now=NOW)["chart_rows"]}
        self.assertEqual(rows["October 2026"], 1)
        self.assertEqual(rows["November 2026"], 0)
        self.assertEqual(len(rows), 12)

    def test_reopens_by_people_count_but_replies_to_a_resolved_ticket_dont(self):
        t = self.ticket(NOW - dt.timedelta(days=5))
        event(t, NOW - dt.timedelta(days=3), Status.OPEN.label, Status.RESOLVED.label, actor=self.requester,
              note="reopened by requester")
        event(t, NOW - dt.timedelta(days=2), Status.OPEN.label, Status.RESOLVED.label, actor=self.requester,
              note="requester replied")
        self.assertEqual(reports.build("30", now=NOW)["team_rows"][0]["reopened"], 1)

    def test_blocking_share_is_of_web_requests(self):
        for blocking in (True, False, False, False):
            t = self.ticket(NOW - dt.timedelta(days=1))
            Ticket.objects.filter(pk=t.pk).update(is_blocking=blocking)
        t = self.ticket(NOW - dt.timedelta(days=1))
        Ticket.objects.filter(pk=t.pk).update(source=Ticket.Source.EMAIL)
        tile = reports.build("30", now=NOW)["tiles"][3]
        self.assertEqual(tile["value"], "25%")
        self.assertIn("1 of 4 web requests", tile["detail"])

    def test_open_now_by_age(self):
        self.ticket(NOW - dt.timedelta(hours=2))
        self.ticket(NOW - dt.timedelta(days=2))
        self.ticket(NOW - dt.timedelta(days=10))
        self.ticket(NOW - dt.timedelta(days=10), resolved=NOW - dt.timedelta(days=9))
        data = reports.build("30", now=NOW)
        self.assertEqual([b["count"] for b in data["age_bars"]], [1, 1, 0, 1])
        self.assertEqual(data["open_count"], 3)
        self.assertEqual(data["oldest"][0]["age"], "10 days")

    def test_common_requests_are_counted_by_their_subject(self):
        pick = self.mechanics.subject_choices[0]
        self.ticket(NOW - dt.timedelta(days=1), subject=pick, category=self.mechanics)
        self.ticket(NOW - dt.timedelta(days=1), subject=pick, category=self.mechanics)
        self.ticket(NOW - dt.timedelta(days=1), subject="Something of my own")
        data = reports.build("30", now=NOW)
        self.assertEqual(data["common_requests"], [{"name": pick, "count": 2, "pct": 100.0}])

    def test_faster_and_slower_than_before(self):
        for days_ago, hours in ((40, 4), (5, 1)):
            t0 = NOW - dt.timedelta(days=days_ago)
            t = self.ticket(t0)
            comment(t, self.agent, t0 + dt.timedelta(hours=hours))
        tile = reports.build("30", now=NOW)["tiles"][1]
        self.assertEqual(tile["value"], "1.0 h")
        self.assertEqual((tile["delta"], tile["tone"]), ("3.0 h faster than the 30 days before", "good"))


class HealthTests(ReportsTestCase):
    def test_email_and_password_checks(self):
        OutboundEmail.objects.create(kind="x", to="a@example.invalid", subject="s", body_text="b", body_html="b",
                                     status=OutboundEmail.Status.FAILED, attempts=5)
        OutboundEmail.objects.create(kind="x", to="a@example.invalid", subject="s", body_text="b", body_html="b",
                                     next_attempt_at=timezone.now() - dt.timedelta(minutes=30))
        InboundEmail.objects.create(message_id="m1", outcome=InboundEmail.Outcome.ERROR)
        PasswordWarning.objects.create(place=PasswordWarning.Place.REPLY, outcome=PasswordWarning.Outcome.SENT_ANYWAY)
        health = reports.build("30")["health"]
        self.assertEqual((health["failed"], health["in_errors"], health["pw_sent"]), (1, 1, 1))
        self.assertTrue(health["worker_late"])

        self.client.force_login(self.admin)
        page = self.client.get(reverse("tickets:reports"))
        self.assertContains(page, "The email worker may have stopped")
        self.assertContains(page, "may include a password")

    def page(self):
        self.client.force_login(self.admin)
        return self.client.get(reverse("tickets:reports"))

    def test_no_sign_of_the_worker(self):
        self.assertContains(self.page(), "No sign of the worker yet")

    def test_the_worker_is_running(self):
        heartbeat.started()
        heartbeat.round_done()
        heartbeat.auto_closed(2)
        page = self.page()
        self.assertContains(page, "The worker is running: last seen under a minute ago.")
        self.assertContains(page, "Started ")
        self.assertContains(page, "<dt>Last run</dt><dd>under a minute ago</dd>", html=True)
        self.assertNotContains(page, "<dt>Last read</dt>")  # email-in is off

    def test_the_worker_has_stopped(self):
        heartbeat.record(round_at=timezone.now() - dt.timedelta(hours=3))
        page = self.page()
        self.assertContains(page, "The worker may have stopped: last seen 3.0 h ago.")
        self.assertContains(page, "no emails go out and resolved tickets don't close")

    @override_settings(INBOUND_EMAIL="graph")
    def test_an_unreadable_mailbox_is_shown(self):
        heartbeat.round_done()
        heartbeat.inbox_read(["mech-test@example.invalid: Graph GET returned 403: <denied>"])
        page = self.page()
        self.assertContains(page, "no emails go out", count=0)
        self.assertContains(page, "failed: emails may be waiting in the Inbox. Last read without a problem: not yet.")
        self.assertContains(page, "mech-test@example.invalid: Graph GET returned 403: &lt;denied&gt;")
        heartbeat.inbox_read([])
        page = self.page()
        self.assertContains(page, "Reading normally")
        self.assertContains(page, "<dt>Last read</dt><dd>under a minute ago</dd>", html=True)

    def test_a_failed_auto_close_is_shown(self):
        heartbeat.round_done()
        heartbeat.auto_closed(error="RuntimeError: database locked")
        page = self.page()
        self.assertContains(page, "failed. It tries again within the hour.")
        self.assertContains(page, "RuntimeError: database locked")

    def test_an_overdue_email_while_the_worker_runs(self):
        heartbeat.round_done()
        OutboundEmail.objects.create(kind="x", to="a@example.invalid", subject="s", body_text="b", body_html="b",
                                     next_attempt_at=timezone.now() - dt.timedelta(minutes=30))
        page = self.page()
        self.assertContains(page, "though the worker is running. Check the worker's log.")
        self.assertNotContains(page, "The email worker may have stopped")

    def test_all_quiet(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("tickets:reports"))
        self.assertContains(page, "Sending normally")
        self.assertContains(page, "Nothing to check")


class CsvTests(ReportsTestCase):
    def test_one_row_per_request_without_descriptions_or_names(self):
        t = self.ticket(NOW - dt.timedelta(days=1), subject='=HYPERLINK("http://example.invalid")')
        Ticket.objects.filter(pk=t.pk).update(description="Secret details here")
        self.ticket(NOW - dt.timedelta(days=1), subject="@SUM(A1)")
        text = reports.csv_export("30", now=NOW)
        self.assertTrue(text.startswith("﻿"))
        lines = text.lstrip("﻿").splitlines()
        self.assertEqual(lines[0].split(",")[0], "Ticket")
        self.assertNotIn("Description", lines[0])
        self.assertEqual(len(lines), 3)
        self.assertNotIn("Secret details", text)
        self.assertNotIn("Dana Whitfield", text)
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("'@SUM(A1)", text)

    def test_download(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("tickets:reports_csv"), {"period": "7", "team": "it"})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn('attachment; filename="inh-requests-', response["Content-Disposition"])


class ChartTests(ReportsTestCase):
    def test_axis(self):
        self.assertEqual(reports._nice_axis(0), (5, [0, 1, 2, 3, 4, 5]))
        self.assertEqual(reports._nice_axis(7), (8, [0, 2, 4, 6, 8]))
        self.assertEqual(reports._nice_axis(23), (25, [0, 5, 10, 15, 20, 25]))
        self.assertEqual(reports._nice_axis(140), (150, [0, 50, 100, 150]))

    def test_stacked_columns_keep_team_colours(self):
        buckets = [{"short": "a", "long": "A", "values": {"mechanics": 2}},
                   {"short": "b", "long": "B", "values": {"it": 1, "cleaning": 3}}]
        chart = reports.column_chart(buckets, ["it", "mechanics", "cleaning"])
        self.assertEqual([s["slot"] for s in chart["columns"][0]["segments"]], [2])
        self.assertEqual([s["slot"] for s in chart["columns"][1]["segments"]], [1, 3])
        self.assertIn("IT|1|1;Mechanics|0|2;Cleaning & sanitization|3|3", chart["columns"][1]["tip_rows"])

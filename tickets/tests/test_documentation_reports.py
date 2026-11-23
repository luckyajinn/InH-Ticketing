"""Ticket documentation in Reports: admins only, by team, never per person."""

import csv
import datetime as dt
import io

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tickets import reports
from tickets.models import Ticket, TicketDocumentation
from tickets.tests.helpers import make_user
from tickets.tests.test_reports import NOW, ReportsTestCase

Status = Ticket.Status
LIST = reverse("tickets:reports_documentation")


class DocumentationTestCase(ReportsTestCase):
    def document(self, ticket, when, by=None, department="it", **texts):
        """A write-up on the ticket, last updated at `when`."""
        texts = texts or {"solution": "Replaced the fuser."}
        doc = TicketDocumentation.objects.create(ticket=ticket, department=department,
                                                 created_by=by, updated_by=by, **texts)
        TicketDocumentation.objects.filter(pk=doc.pk).update(updated_at=when)
        return doc

    def summary(self, period="30", team=""):
        return reports.build(period, team=team, now=NOW)["documentation"]

    def page(self, **params):
        self.client.force_login(self.admin)
        return self.client.get(LIST, params)


class AccessTests(DocumentationTestCase):
    def test_admins_only(self):
        mechanic = make_user("Mo Mechanic", User.Role.AGENT)
        User.objects.filter(pk=mechanic.pk).update(department="mechanics")
        self.client.logout()
        self.assertRedirects(self.client.get(LIST), f"{reverse('accounts:signin')}?next={LIST}",
                             fetch_redirect_response=False)
        # self.agent is an IT agent; agents of other teams and requesters are turned away too.
        for user in (self.requester, self.agent, mechanic):
            with self.subTest(user=user.display_name):
                self.client.force_login(user)
                self.assertEqual(self.client.get(LIST).status_code, 403)
                self.assertEqual(self.client.get(reverse("tickets:reports")).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(LIST)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.post(LIST).status_code, 405)

    def test_the_card_is_on_reports_with_a_link_to_the_list(self):
        t = self.ticket(timezone.now() - dt.timedelta(days=3))
        self.document(t, timezone.now() - dt.timedelta(days=1), by=self.agent)
        self.client.force_login(self.admin)
        page = self.client.get(reverse("tickets:reports"), {"period": "7", "team": "it"})
        self.assertContains(page, "Ticket documentation")
        self.assertContains(page, f'href="{LIST}?period=7&amp;team=it"')
        self.assertContains(page, f'<a href="{t.get_absolute_url()}">#{t.number} Printer jammed</a>', html=True)
        self.assertContains(page, "by Sam Patel")
        self.assertContains(page, "<dt>Written or updated</dt><dd>1</dd>", html=True)

    def test_list_and_card_render_with_no_data(self):
        self.client.force_login(self.admin)
        for period in ("7", "30", "90", "365", "bogus"):
            for team in ("", "it", "mechanics", "nonsense"):
                with self.subTest(period=period, team=team):
                    self.assertContains(self.client.get(LIST, {"period": period, "team": team}),
                                        "No documentation was written or updated in this period.")
                    self.assertContains(self.client.get(reverse("tickets:reports"), {"period": period, "team": team}),
                                        "Nothing written in this period.")
        self.assertContains(self.client.get(LIST), f'href="{reverse("tickets:reports")}?period=30"')


class CountingTests(DocumentationTestCase):
    def test_counted_in_the_period_it_was_last_updated(self):
        self.document(self.ticket(NOW - dt.timedelta(days=20)), NOW - dt.timedelta(days=10))
        self.document(self.ticket(NOW - dt.timedelta(days=3)), NOW - dt.timedelta(days=2))
        self.document(self.ticket(NOW - dt.timedelta(days=60)), NOW - dt.timedelta(days=45))
        self.assertEqual(self.summary("7")["count"], 1)
        self.assertEqual(self.summary("30")["count"], 2)
        self.assertEqual(self.summary("90")["count"], 3)

    def test_by_the_tickets_team(self):
        self.document(self.ticket(NOW - dt.timedelta(days=2)), NOW - dt.timedelta(days=1))
        # Written by IT, then moved to Mechanics: it's Mechanics' ticket now.
        self.document(self.ticket(NOW - dt.timedelta(days=2), category=self.mechanics), NOW - dt.timedelta(days=1))
        self.assertEqual(self.summary()["count"], 2)
        self.assertEqual(self.summary(team="it")["count"], 1)
        mechanics = self.summary(team="mechanics")
        self.assertEqual(mechanics["count"], 1)
        self.assertEqual(mechanics["recent"][0]["team"], "Mechanics")
        self.assertEqual(self.summary(team="cleaning")["count"], 0)

    def test_blank_write_ups_dont_count(self):
        self.document(self.ticket(NOW - dt.timedelta(days=2)), NOW - dt.timedelta(days=1),
                      troubleshooting="", steps_taken="   ", solution="", other_problems="")
        self.assertEqual(self.summary()["count"], 0)
        self.assertEqual(self.summary()["recent"], [])

    def test_pilot_feedback_and_tickets_before_reports_from_are_left_out(self):
        self.document(self.ticket(NOW - dt.timedelta(days=2), subject="Pilot: odd button"), NOW - dt.timedelta(days=1))
        self.document(self.ticket(NOW - dt.timedelta(days=8)), NOW - dt.timedelta(days=1))
        self.assertEqual(self.summary()["count"], 1)
        with override_settings(REPORTS_FROM="2026-11-05"):
            self.assertEqual(self.summary()["count"], 0)

    def test_resolved_or_closed_without_any(self):
        done = [self.ticket(NOW - dt.timedelta(days=5), resolved=NOW - dt.timedelta(days=4)) for _ in range(3)]
        Ticket.objects.filter(pk=done[2].pk).update(status=Status.CLOSED)
        self.document(done[0], NOW - dt.timedelta(days=4))
        # Written long before the period still counts as documented.
        self.document(done[1], NOW - dt.timedelta(days=60), department="it")
        self.ticket(NOW - dt.timedelta(days=5))  # still open: not missing anything yet
        blank = self.ticket(NOW - dt.timedelta(days=5), resolved=NOW - dt.timedelta(days=4))
        self.document(blank, NOW - dt.timedelta(days=4), solution="  ")
        self.ticket(NOW - dt.timedelta(days=5), subject="Pilot: x", resolved=NOW - dt.timedelta(days=4))
        self.assertEqual(self.summary()["missing"], 2)  # done[2] and the blank one
        self.assertEqual(self.summary(team="mechanics")["missing"], 0)

    def test_latest_few_newest_first(self):
        for days in range(1, 8):
            self.document(self.ticket(NOW - dt.timedelta(days=10), subject=f"Ticket {days}"),
                          NOW - dt.timedelta(days=days))
        recent = self.summary()["recent"]
        self.assertEqual([r["subject"] for r in recent], [f"Ticket {d}" for d in range(1, 6)])
        self.assertEqual(self.summary()["count"], 7)

    def test_two_queries(self):
        for _ in range(3):
            self.document(self.ticket(NOW - dt.timedelta(days=2)), NOW - dt.timedelta(days=1), by=self.agent)
        window, teams = reports.window_for("30", NOW), reports.Teams()
        with self.assertNumQueries(2):
            reports.documentation_summary(window, "", teams)

    def test_no_per_person_figures(self):
        for _ in range(2):
            self.document(self.ticket(NOW - dt.timedelta(days=2)), NOW - dt.timedelta(days=1), by=self.agent)
        self.assertEqual(set(self.summary()), {"count", "missing", "recent"})


class ListTests(DocumentationTestCase):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()

    def test_sections_with_headings(self):
        t = self.ticket(self.now - dt.timedelta(days=2))
        self.document(t, self.now - dt.timedelta(days=1), by=self.agent, troubleshooting="Checked the tray.",
                      steps_taken="Cleaned the rollers.", solution="", other_problems="Toner low, replaced.")
        page = self.page()
        self.assertContains(page, f'<a href="{t.get_absolute_url()}">#{t.number} Printer jammed</a>', html=True)
        for heading in ("Troubleshooting", "Steps taken", "Solution", "Other problems found"):
            self.assertContains(page, f'<h3 class="report-subtitle">{heading}</h3>', html=True)
        self.assertContains(page, "Checked the tray.")
        self.assertContains(page, "Not filled in", count=1)
        self.assertContains(page, "by Sam Patel")
        self.assertContains(page, "1 ticket with documentation updated last 30 days")

    def test_html_is_escaped_and_line_breaks_kept(self):
        t = self.ticket(self.now - dt.timedelta(days=2))
        self.document(t, self.now - dt.timedelta(days=1), troubleshooting="<script>alert(1)</script>\nSecond line")
        page = self.page()
        self.assertNotContains(page, "<script>alert(1)</script>")
        self.assertContains(page, "&lt;script&gt;alert(1)&lt;/script&gt;<br>Second line")

    def test_blank_and_pilot_write_ups_are_not_listed(self):
        self.document(self.ticket(self.now - dt.timedelta(days=2), subject="Blank one"), self.now - dt.timedelta(days=1),
                      troubleshooting="", solution=" ")
        self.document(self.ticket(self.now - dt.timedelta(days=2), subject="Pilot: feedback"),
                      self.now - dt.timedelta(days=1))
        page = self.page()
        self.assertNotContains(page, "Blank one")
        self.assertNotContains(page, "Pilot: feedback")
        self.assertContains(page, "No documentation was written or updated in this period.")

    def test_period_and_team_filters(self):
        it = self.ticket(self.now - dt.timedelta(days=30), subject="IT recent")
        self.document(it, self.now - dt.timedelta(days=2))
        old = self.ticket(self.now - dt.timedelta(days=30), subject="IT older")
        self.document(old, self.now - dt.timedelta(days=20))
        mech = self.ticket(self.now - dt.timedelta(days=30), subject="Mechanics recent", category=self.mechanics)
        self.document(mech, self.now - dt.timedelta(days=2))

        page = self.page(period="7").content.decode()
        self.assertIn("IT recent", page)
        self.assertIn("Mechanics recent", page)
        self.assertNotIn("IT older", page)
        page = self.page(period="30", team="it").content.decode()
        self.assertIn("IT recent", page)
        self.assertIn("IT older", page)
        self.assertNotIn("Mechanics recent", page)
        page = self.page(team="mechanics").content.decode()
        self.assertEqual((page.count("IT recent"), page.count("Mechanics recent")), (0, 1))
        self.assertIn("written by IT", page)  # moved from IT since

    def test_search_by_number_and_text(self):
        printer = self.ticket(self.now - dt.timedelta(days=2), subject="Printer jammed")
        self.document(printer, self.now - dt.timedelta(days=1), steps_taken="Reseated the fuser unit.")
        vpn = self.ticket(self.now - dt.timedelta(days=2), subject="VPN drops")
        self.document(vpn, self.now - dt.timedelta(days=1), other_problems="Router firmware was old.")
        cases = {
            f"#{printer.number}": "Printer jammed", str(vpn.number): "VPN drops",
            "FUSER": "Printer jammed", "firmware": "VPN drops", "vpn": "VPN drops",
        }
        for q, expected in cases.items():
            with self.subTest(q=q):
                page = self.page(q=q).content.decode()
                self.assertIn(expected, page)
                self.assertNotIn({"Printer jammed", "VPN drops"}.difference({expected}).pop(), page)
        self.assertContains(self.page(q="nothing like this"), "No documentation matches your search")
        self.assertEqual(self.page(q="9" * 30).status_code, 200)

    def test_pagination(self):
        for i in range(30):
            self.document(self.ticket(self.now - dt.timedelta(days=3), subject=f"Ticket no {i:02d}"),
                          self.now - dt.timedelta(hours=i + 1))
        first = self.page()
        self.assertContains(first, "30 tickets with documentation")
        self.assertContains(first, "Page 1 of 2")
        self.assertContains(first, "Ticket no 00")
        self.assertNotContains(first, "Ticket no 25")
        self.assertContains(first, 'href="?page=2"')
        second = self.page(page="2", q="Ticket no")
        self.assertContains(second, "Ticket no 29")
        self.assertNotContains(second, "Ticket no 00")
        for bogus in ("0", "99", "abc"):
            with self.subTest(page=bogus):
                self.assertEqual(self.page(page=bogus).status_code, 200)

    def test_a_handful_of_queries_whatever_the_page_size(self):
        for i in range(10):
            self.document(self.ticket(self.now - dt.timedelta(days=3)), self.now - dt.timedelta(hours=i + 1),
                          by=self.agent)
        self.client.force_login(self.admin)
        self.client.get(LIST)  # warm up the session
        # Session, user, teams, count, the page: no query per entry.
        with self.assertNumQueries(5):
            self.client.get(LIST)


class CsvTests(DocumentationTestCase):
    def test_documented_column_without_the_text(self):
        documented = self.ticket(NOW - dt.timedelta(days=2))
        self.document(documented, NOW - dt.timedelta(days=1), solution="Secret fix details")
        blank = self.ticket(NOW - dt.timedelta(days=2))
        self.document(blank, NOW - dt.timedelta(days=1), solution="")
        self.ticket(NOW - dt.timedelta(days=2))
        text = reports.csv_export("30", now=NOW)
        rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
        self.assertEqual(rows[0], reports.CSV_HEADER)
        column = rows[0].index("Documented")
        self.assertEqual({r[0]: r[column] for r in rows[1:]},
                         {str(documented.number): "Yes", str(blank.number): "No", str(blank.number + 1): "No"})
        self.assertNotIn("Secret fix", text)

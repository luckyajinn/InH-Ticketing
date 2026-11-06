"""Milestone 5: auto-close, follow-up links and the IT-only notice."""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from notifications.models import OutboundEmail
from tickets import selectors, services
from tickets.models import Ticket, TicketEvent
from tickets.tests.helpers import MediaTestCase, make_ticket

Status = Ticket.Status
NOTICE = ("For IT issues and requests only. Product complaints or reactions go to QA, "
          "not here. Please don't include passwords.")


def resolve(test, ticket, days_ago):
    """Resolve a ticket as IT, then pretend that happened days_ago days ago."""
    services.update_ticket(ticket=ticket, actor=test.agent, status=Status.RESOLVED)
    Ticket.objects.filter(pk=ticket.pk).update(resolved_at=timezone.now() - timedelta(days=days_ago))
    ticket.refresh_from_db()
    return ticket


@override_settings(AUTO_CLOSE_RESOLVED_DAYS=7)
class AutoCloseTests(MediaTestCase):
    def test_closes_only_resolved_tickets_past_the_cutoff(self):
        old = resolve(self, make_ticket(self.requester, subject="Old"), days_ago=8)
        recent = resolve(self, make_ticket(self.requester, subject="Recent"), days_ago=3)
        still_open = make_ticket(self.requester, subject="Open")
        self.assertEqual(services.close_resolved_tickets(), 1)
        for t in (old, recent, still_open):
            t.refresh_from_db()
        self.assertEqual(old.status, Status.CLOSED)
        self.assertIsNotNone(old.closed_at)
        self.assertIsNotNone(old.resolved_at)
        self.assertEqual(recent.status, Status.RESOLVED)
        self.assertEqual(still_open.status, Status.NEW)

    def test_logs_an_automatic_event_and_sends_no_email(self):
        ticket = resolve(self, make_ticket(self.requester), days_ago=7)
        emails_before = OutboundEmail.objects.count()
        services.close_resolved_tickets()
        event = TicketEvent.objects.filter(ticket=ticket, kind="status").last()
        self.assertIsNone(event.actor)
        self.assertEqual((event.old_value, event.new_value), ("Resolved", "Closed"))
        self.assertEqual(event.note, "no reply for 7 days")
        self.assertEqual(OutboundEmail.objects.count(), emails_before)

    @override_settings(AUTO_CLOSE_RESOLVED_DAYS=0)
    def test_does_nothing_when_turned_off(self):
        ticket = resolve(self, make_ticket(self.requester), days_ago=400)
        self.assertEqual(services.close_resolved_tickets(), 0)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.RESOLVED)

    def test_ticket_the_requester_replied_to_is_not_closed(self):
        ticket = resolve(self, make_ticket(self.requester), days_ago=10)
        services.add_comment(ticket=ticket, author=self.requester, body="Still broken.")
        self.assertEqual(services.close_resolved_tickets(), 0)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.OPEN)

    def test_command_reports_how_many_it_closed(self):
        resolve(self, make_ticket(self.requester), days_ago=9)
        resolve(self, make_ticket(self.requester, subject="Second"), days_ago=9)
        out = StringIO()
        call_command("close_resolved", stdout=out)
        self.assertIn("Closed 2 tickets.", out.getvalue())
        self.assertEqual(Ticket.objects.filter(status=Status.CLOSED).count(), 2)

    def test_worker_once_runs_it(self):
        ticket = resolve(self, make_ticket(self.requester), days_ago=9)
        out = StringIO()
        call_command("run_worker", "--once", stdout=out)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Status.CLOSED)
        self.assertIn("1 resolved ticket(s) closed", out.getvalue())

    def test_worker_keeps_going_if_auto_close_fails(self):
        out = StringIO()
        with mock.patch("notifications.management.commands.run_worker.close_resolved_tickets",
                        side_effect=RuntimeError("boom")):
            call_command("run_worker", "--once", stdout=out)
        self.assertIn("Auto-close: failed", out.getvalue())


@override_settings(AUTO_CLOSE_RESOLVED_DAYS=7, SITE_URL="https://helpdesk.example.invalid")
class CloseDateTests(MediaTestCase):
    def close_text(self, ticket):
        closes = timezone.localtime(ticket.resolved_at + timedelta(days=7))
        return f"It closes automatically on {closes:%b} {closes.day} if we don't hear back."

    def test_resolved_email_and_page_show_the_close_date(self):
        ticket = make_ticket(self.requester)
        services.update_ticket(ticket=ticket, actor=self.agent, status=Status.RESOLVED)
        ticket.refresh_from_db()
        [email] = OutboundEmail.objects.filter(kind="resolved")
        self.assertIn(self.close_text(ticket), email.body_text)
        self.client.force_login(self.requester)
        self.assertContains(self.client.get(ticket.get_absolute_url()), self.close_text(ticket))

    def test_send_and_resolve_email_shows_the_close_date(self):
        ticket = make_ticket(self.requester)
        services.add_comment(ticket=ticket, author=self.agent, body="Fixed.", then_status=Status.RESOLVED)
        ticket.refresh_from_db()
        [email] = OutboundEmail.objects.filter(kind="it_replied")
        self.assertIn(self.close_text(ticket), email.body_text)

    @override_settings(AUTO_CLOSE_RESOLVED_DAYS=0)
    def test_sentence_is_left_out_when_auto_close_is_off(self):
        ticket = make_ticket(self.requester)
        services.add_comment(ticket=ticket, author=self.agent, body="Fixed.", then_status=Status.RESOLVED)
        services.update_ticket(ticket=ticket, actor=self.agent, status=Status.OPEN)
        services.update_ticket(ticket=ticket, actor=self.agent, status=Status.RESOLVED)
        emails = OutboundEmail.objects.filter(kind__in=["resolved", "it_replied"])
        self.assertEqual(emails.count(), 2)
        for email in emails:
            self.assertNotIn("closes automatically", email.body_text)
        self.client.force_login(self.requester)
        self.assertNotContains(self.client.get(ticket.get_absolute_url()), "closes automatically")


class FollowUpTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.closed = make_ticket(self.requester, subject="Badge reader broken")
        services.update_ticket(ticket=self.closed, actor=self.agent, status=Status.CLOSED)
        self.new_url = reverse("tickets:new")

    def post_data(self, **extra):
        data = {"subject": "Badge again", "description": "Same thing.",
                "category": self.closed.category_id, **extra}
        return self.client.post(self.new_url, data)

    def test_closed_ticket_offers_a_follow_up_button(self):
        self.client.force_login(self.requester)
        response = self.client.get(self.closed.get_absolute_url())
        self.assertContains(response, "Start a follow-up")
        self.assertContains(response, f"{self.new_url}?follow_up={self.closed.number}")
        self.assertNotContains(response, "Start a new request")

    def test_new_request_page_prefills_and_links(self):
        self.client.force_login(self.requester)
        response = self.client.get(f"{self.new_url}?follow_up={self.closed.number}")
        self.assertContains(response, f"Follow-up to #{self.closed.number}: Badge reader broken")
        self.assertContains(response, 'value="Badge reader broken"')
        self.assertContains(response, f'name="follow_up" value="{self.closed.number}"')

    def test_submitting_creates_a_linked_ticket(self):
        self.client.force_login(self.requester)
        self.assertEqual(self.post_data(follow_up=self.closed.number).status_code, 302)
        self.assertEqual(Ticket.objects.latest("pk").follows_up, self.closed)

    def test_link_to_a_ticket_the_user_cannot_see_is_ignored(self):
        self.client.force_login(self.other_requester)
        response = self.client.get(f"{self.new_url}?follow_up={self.closed.number}")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Follow-up to #")
        self.assertNotContains(response, "Badge reader broken")
        self.assertNotContains(response, 'name="follow_up"')
        self.assertEqual(self.post_data(follow_up=self.closed.number).status_code, 302)
        self.assertIsNone(Ticket.objects.latest("pk").follows_up)

    def test_nonsense_follow_up_is_ignored(self):
        self.client.force_login(self.requester)
        for value in ("abc", "99999", "-5", ""):
            self.assertEqual(self.client.get(f"{self.new_url}?follow_up={value}").status_code, 200)

    def test_agent_page_lists_links_both_ways(self):
        follow_up = make_ticket(self.requester, subject="Badge again", follows_up=self.closed)
        self.client.force_login(self.agent)
        original_page = self.client.get(self.closed.get_absolute_url())
        self.assertContains(original_page, "Linked tickets")
        self.assertContains(original_page, f'Follow-up <span class="ticket-num">#{follow_up.number}</span>')
        follow_page = self.client.get(follow_up.get_absolute_url())
        self.assertContains(follow_page, f'Follow-up to <span class="ticket-num">#{self.closed.number}</span>')

    def test_requester_sees_their_own_links(self):
        follow_up = make_ticket(self.requester, subject="Badge again", follows_up=self.closed)
        self.client.force_login(self.requester)
        self.assertContains(self.client.get(self.closed.get_absolute_url()), f'Follow-up <span class="ticket-num">#{follow_up.number}</span>')
        self.assertContains(self.client.get(follow_up.get_absolute_url()),
                            f'Follow-up to <span class="ticket-num">#{self.closed.number}</span>')

    def test_requester_cannot_see_links_to_tickets_they_dont_own(self):
        # IT started a follow-up under their own name, and Dana's ticket points at Tom's.
        agents_follow_up = make_ticket(self.agent, subject="IT-only follow-up", follows_up=self.closed)
        theirs = make_ticket(self.other_requester, subject="Tom ticket")
        mine = make_ticket(self.requester, subject="Dana later ticket", follows_up=theirs)
        self.client.force_login(self.requester)
        page = self.client.get(self.closed.get_absolute_url())
        self.assertNotContains(page, "IT-only follow-up")
        self.assertNotContains(page, f"#{agents_follow_up.number}")
        page = self.client.get(mine.get_absolute_url())
        self.assertNotContains(page, "Tom ticket")
        self.assertEqual(selectors.linked_tickets(mine, self.requester), (None, []))


class NoticeTests(MediaTestCase):
    def test_it_only_notice_is_on_the_new_request_page(self):
        self.client.force_login(self.requester)
        response = self.client.get(reverse("tickets:new"))
        self.assertContains(response, NOTICE)
        self.assertContains(response, "hint-box")

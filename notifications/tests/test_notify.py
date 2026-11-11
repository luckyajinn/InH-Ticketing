from datetime import timedelta

from django.test import override_settings

from accounts.models import User
from notifications.models import OutboundEmail
from tickets import services
from tickets.models import Ticket
from tickets.tests.helpers import MediaTestCase, make_ticket, make_user

Status = Ticket.Status
IT_ALERTS = "it-alerts@example.invalid"
SECRET_NOTE = "Firmware bug on the whole Finance fleet. Don't share yet."


def queued(**filters):
    return list(OutboundEmail.objects.filter(**filters).order_by("pk"))


@override_settings(IT_NOTIFY_EMAIL=IT_ALERTS, SITE_URL="https://helpdesk.example.invalid")
class WhoGetsWhatTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester, subject="Outlook keeps prompting")

    def test_new_ticket_emails_requester_and_it_alerts(self):
        [receipt] = queued(kind="received")
        self.assertEqual(receipt.to, self.requester.email)
        self.assertEqual(receipt.subject, f"[#{self.ticket.number}] Outlook keeps prompting")
        self.assertIn(f"https://helpdesk.example.invalid/tickets/{self.ticket.number}/", receipt.body_text)
        [alert] = queued(kind="new_ticket")
        self.assertEqual(alert.to, IT_ALERTS)

    @override_settings(IT_NOTIFY_EMAIL="")
    def test_no_it_alert_when_not_configured(self):
        make_ticket(self.requester)
        self.assertFalse(queued(kind="new_ticket", to=""))
        self.assertEqual(len(queued(kind="new_ticket")), 1)  # only the one from setUp

    def test_it_public_reply_emails_requester(self):
        services.add_comment(ticket=self.ticket, author=self.agent, body="Please restart Outlook.")
        [email] = queued(kind="it_replied")
        self.assertEqual(email.to, self.requester.email)
        self.assertIn("Please restart Outlook.", email.body_text)
        self.assertIn("Please restart Outlook.", email.body_html)

    def test_internal_note_is_never_emailed(self):
        before = OutboundEmail.objects.count()
        services.add_comment(ticket=self.ticket, author=self.agent, body=SECRET_NOTE, is_internal=True)
        self.assertEqual(OutboundEmail.objects.count(), before)
        services.add_comment(ticket=self.ticket, author=self.agent, body="Public answer")
        for email in OutboundEmail.objects.all():
            self.assertNotIn(SECRET_NOTE, email.body_text)
            self.assertNotIn(SECRET_NOTE, email.body_html)

    def test_requester_reply_goes_to_assignee(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, assignee=self.agent2)
        services.add_comment(ticket=self.ticket, author=self.requester, body="Still happening")
        [email] = queued(kind="requester_replied")
        self.assertEqual(email.to, self.agent2.email)

    def test_requester_reply_on_unassigned_goes_to_it_alerts(self):
        services.add_comment(ticket=self.ticket, author=self.requester, body="Any update?")
        [email] = queued(kind="requester_replied")
        self.assertEqual(email.to, IT_ALERTS)

    def test_assignment_emails_the_assignee_but_not_self_assignment(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, assignee=self.agent2)
        [email] = queued(kind="assigned")
        self.assertEqual(email.to, self.agent2.email)
        services.update_ticket(ticket=self.ticket, actor=self.agent, assignee=self.agent)
        self.assertEqual(len(queued(kind="assigned")), 1)

    def test_resolve_by_it_emails_requester(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.RESOLVED)
        [email] = queued(kind="resolved")
        self.assertEqual(email.to, self.requester.email)
        self.assertIn("This is still a problem", email.body_text)

    def test_close_by_it_emails_requester(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.CLOSED)
        [email] = queued(kind="closed")
        self.assertEqual(email.to, self.requester.email)
        self.assertEqual(email.subject, f"[#{self.ticket.number}] Outlook keeps prompting")
        self.assertIn("Your request is closed and complete", email.body_text)
        self.assertIn("Sam Patel closed", email.body_text)
        self.assertIn("Start a follow-up", email.body_text)
        self.assertIn("Your request is closed and complete", email.body_html)

    def test_close_by_admin_emails_requester(self):
        admin = make_user("Jo Admin", User.Role.ADMIN)
        services.update_ticket(ticket=self.ticket, actor=admin, status=Status.CLOSED)
        [email] = queued(kind="closed")
        self.assertEqual(email.to, self.requester.email)
        self.assertIn("Jo Admin closed", email.body_text)

    def test_resolve_then_close_sends_both(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.RESOLVED)
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.CLOSED)
        self.assertEqual([e.kind for e in queued(to=self.requester.email, kind__in=["resolved", "closed"])],
                         ["resolved", "closed"])

    def test_closing_your_own_ticket_sends_nothing(self):
        own = make_ticket(self.agent, subject="My own monitor")
        services.update_ticket(ticket=own, actor=self.agent, status=Status.CLOSED)
        self.assertFalse(queued(kind="closed"))

    def test_other_changes_on_close_send_no_closed_email(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.WAITING)
        services.update_ticket(ticket=self.ticket, actor=self.agent, priority=1)
        self.assertFalse(queued(kind="closed"))

    @override_settings(INBOUND_EMAIL="graph")
    def test_closed_email_says_a_reply_starts_a_new_request(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.CLOSED)
        [email] = queued(kind="closed")
        self.assertIn("Replying to this email starts a new request, linked to this one.", email.body_text)
        self.assertNotIn("Keep [#", email.body_text)

    def test_auto_close_sends_no_closed_email(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.RESOLVED)
        Ticket.objects.filter(pk=self.ticket.pk).update(resolved_at=self.ticket.resolved_at - timedelta(days=30))
        self.assertEqual(services.close_resolved_tickets(), 1)
        self.assertFalse(queued(kind="closed"))

    def test_requester_resolving_their_own_ticket_sends_nothing(self):
        before = OutboundEmail.objects.count()
        services.resolve_by_requester(ticket=self.ticket, user=self.requester)
        self.assertEqual(OutboundEmail.objects.count(), before)

    def test_reopen_alerts_it(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, assignee=self.agent2)
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.RESOLVED)
        services.reopen_by_requester(ticket=self.ticket, user=self.requester)
        [email] = queued(kind="reopened")
        self.assertEqual(email.to, self.agent2.email)

    def test_send_and_resolve_sends_one_email(self):
        services.add_comment(ticket=self.ticket, author=self.agent, body="Fixed it remotely.",
                             then_status=Status.RESOLVED)
        self.assertEqual(self.ticket.status, Status.RESOLVED)
        [email] = queued(to=self.requester.email, kind__in=["it_replied", "resolved"])
        self.assertEqual(email.kind, "it_replied")
        self.assertIn("marked your request as resolved", email.body_text)

    def test_inactive_or_emailless_people_are_skipped(self):
        quiet = make_user("No Email")
        User.objects.filter(pk=quiet.pk).update(email="")
        quiet.refresh_from_db()
        make_ticket(quiet)
        self.assertFalse(queued(kind="received", to=""))
        User.objects.filter(pk=self.requester.pk).update(is_active=False)
        self.requester.refresh_from_db()
        services.add_comment(ticket=self.ticket, author=self.agent, body="Hello?")
        self.assertFalse(queued(kind="it_replied"))

    def test_html_is_escaped(self):
        evil = make_ticket(self.requester, subject="x", description="<script>alert(1)</script>")
        email = queued(kind="received", ticket=evil)[0]
        self.assertNotIn("<script>alert(1)</script>", email.body_html)
        self.assertIn("&lt;script&gt;", email.body_html)

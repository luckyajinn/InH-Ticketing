from django.test import override_settings

from accounts.models import User
from inbound.models import InboundEmail
from inbound.processing import IncomingAttachment, IncomingMessage, process
from notifications.models import OutboundEmail
from tickets import services
from tickets.models import Comment, Ticket
from tickets.tests.helpers import MediaTestCase, make_ticket, make_user

Status = Ticket.Status
_counter = iter(range(1, 10_000))


def email(from_address="dana.whitfield@example.invalid", subject="Printer jammed", body="Tray 2 again.",
          **extra):
    return IncomingMessage(
        message_id=f"<test-{next(_counter)}@example.invalid>", from_address=from_address,
        from_name=extra.pop("from_name", ""), subject=subject, body_text=body, source="command", **extra,
    )


@override_settings(INBOUND_ALLOWED_DOMAINS=["example.invalid"], HELPDESK_MAILBOX="helpdesk-test@example.invalid")
class NewTicketTests(MediaTestCase):
    def test_known_person_gets_a_ticket_and_a_receipt(self):
        result = process(email())
        ticket = result.ticket
        self.assertEqual(result.outcome, InboundEmail.Outcome.NEW_TICKET)
        self.assertEqual(ticket.requester, self.requester)
        self.assertEqual(ticket.source, Ticket.Source.EMAIL)
        self.assertEqual(ticket.subject, "Printer jammed")
        self.assertEqual(ticket.description, "Tray 2 again.")
        self.assertEqual(ticket.category.name, "Other")
        self.assertTrue(OutboundEmail.objects.filter(kind="received", ticket=ticket).exists())

    def test_unknown_colleague_gets_an_account(self):
        result = process(email(from_address="Jordan.Kim@example.invalid", from_name="Jordan Kim"))
        user = result.ticket.requester
        self.assertEqual(user.username, "email:jordan.kim@example.invalid")
        self.assertEqual(user.display_name, "Jordan Kim")
        self.assertEqual(user.role, User.Role.REQUESTER)
        self.assertIsNone(user.entra_oid)

    def test_other_domains_are_ignored_without_a_reply(self):
        result = process(email(from_address="stranger@elsewhere.example"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.IGNORED)
        self.assertFalse(Ticket.objects.exists())
        self.assertFalse(User.objects.filter(email="stranger@elsewhere.example").exists())
        self.assertFalse(OutboundEmail.objects.exists())

    def test_automatic_emails_are_ignored(self):
        result = process(email(headers={"Auto-Submitted": "auto-replied"}))
        self.assertEqual(result.outcome, InboundEmail.Outcome.IGNORED)
        self.assertFalse(Ticket.objects.exists())

    def test_out_of_office_reply_to_a_notification_is_ignored(self):
        ticket = make_ticket(self.requester)
        before = ticket.comments.count()
        result = process(email(subject=f"Automatic reply: [#{ticket.number}] Printer", body="I'm away"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.IGNORED)
        self.assertEqual(ticket.comments.count(), before)

    def test_own_mailbox_is_ignored(self):
        result = process(email(from_address="helpdesk-test@example.invalid"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.IGNORED)

    def test_disabled_account_is_ignored(self):
        User.objects.filter(pk=self.requester.pk).update(is_active=False)
        self.assertEqual(process(email()).outcome, InboundEmail.Outcome.IGNORED)

    def test_same_email_twice_is_processed_once(self):
        message = email()
        first = process(message)
        second = process(message)
        self.assertTrue(second.duplicate)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(second.ticket, first.ticket)

    def test_attachments(self):
        result = process(email(attachments=[
            IncomingAttachment("error.png", "image/png", b"png bytes"),
            IncomingAttachment("logo.png", "image/png", b"signature logo", is_inline=True),
            IncomingAttachment("tool.exe", "application/octet-stream", b"MZ"),
        ]))
        ticket = result.ticket
        self.assertEqual([a.original_name for a in ticket.attachments.all()], ["error.png"])
        self.assertIn("Not attached: tool.exe (file type not accepted)", ticket.description)
        self.assertNotIn("logo.png", ticket.description)

    def test_unknown_ticket_number_starts_a_new_ticket(self):
        result = process(email(subject="RE: [#99999] Old thing"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.NEW_TICKET)
        self.assertEqual(result.ticket.subject, "Old thing")


@override_settings(INBOUND_ALLOWED_DOMAINS=["example.invalid"])
class ReplyTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester, subject="Outlook keeps prompting")
        services.add_comment(ticket=self.ticket, author=self.agent, body="Are you free at 2:30?",
                             then_status=Status.WAITING)
        self.subject = f"RE: [#{self.ticket.number}] Outlook keeps prompting"

    def test_requester_reply_is_added_and_reopens(self):
        quoted = "Yes, 2:30 works.\n\nOn Tue, Sam wrote:\n> Are you free at 2:30?"
        result = process(email(subject=self.subject, body=quoted))
        self.assertEqual(result.outcome, InboundEmail.Outcome.REPLY)
        comment = self.ticket.comments.last()
        self.assertEqual(comment.body, "Yes, 2:30 works.")
        self.assertEqual(comment.source, Ticket.Source.EMAIL)
        self.assertFalse(comment.is_internal)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.OPEN)

    def test_graph_unique_body_is_preferred(self):
        process(email(subject=self.subject, body="Yes.\n\nlots of quoted history", new_text="Yes."))
        self.assertEqual(self.ticket.comments.last().body, "Yes.")

    def test_it_reply_by_email_is_public(self):
        process(email(from_address=self.agent.email, subject=self.subject, body="On my way over."))
        comment = self.ticket.comments.last()
        self.assertEqual(comment.author, self.agent)
        self.assertFalse(comment.is_internal)
        self.assertTrue(OutboundEmail.objects.filter(kind="it_replied", to=self.requester.email,
                                                     body_text__contains="On my way over.").exists())

    def test_someone_else_becomes_an_internal_note(self):
        manager = make_user("Morgan Lee")
        result = process(email(from_address=manager.email, subject=self.subject, body="Approved."))
        self.assertEqual(result.outcome, InboundEmail.Outcome.NOTE)
        note = self.ticket.comments.last()
        self.assertTrue(note.is_internal)
        self.assertIn("isn't the requester", note.body)
        self.assertIn("Approved.", note.body)
        # The requester never sees it.
        self.client.force_login(self.requester)
        self.assertNotContains(self.client.get(self.ticket.get_absolute_url()), "Approved.")

    def test_reply_to_closed_ticket_starts_a_follow_up(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.CLOSED)
        result = process(email(subject=self.subject, body="It's back again."))
        self.assertEqual(result.outcome, InboundEmail.Outcome.NEW_TICKET)
        self.assertNotEqual(result.ticket, self.ticket)
        self.assertIn(f"Follow-up to closed ticket #{self.ticket.number}", result.ticket.description)
        self.assertEqual(result.ticket.follows_up, self.ticket)
        self.assertEqual(Comment.objects.filter(ticket=self.ticket, body__contains="back again").count(), 0)

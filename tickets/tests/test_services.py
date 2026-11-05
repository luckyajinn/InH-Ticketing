from django.core.exceptions import PermissionDenied

from tickets import services
from tickets.models import Category, Ticket, TicketEvent
from tickets.tests.helpers import MediaTestCase, make_ticket, upload

Status = Ticket.Status


class CreateTicketTests(MediaTestCase):
    def test_defaults(self):
        ticket = make_ticket(self.requester, is_blocking=True)
        self.assertEqual(ticket.status, Status.NEW)
        self.assertEqual(ticket.priority, Ticket.Priority.NORMAL)
        self.assertEqual(ticket.source, Ticket.Source.WEB)
        self.assertTrue(ticket.is_blocking)
        self.assertIsNone(ticket.assignee)
        self.assertEqual(ticket.number, 1000 + ticket.pk)

    def test_attachments_are_saved_with_a_random_name(self):
        ticket = make_ticket(self.requester, files=[upload("error message.png")])
        attachment = ticket.attachments.get()
        self.assertEqual(attachment.original_name, "error message.png")
        self.assertIsNone(attachment.comment)
        self.assertNotIn("error message", attachment.file.name)
        self.assertTrue(attachment.file.name.endswith(".png"))


class CommentRuleTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester)

    def _last_status_event(self):
        return self.ticket.events.filter(kind=TicketEvent.Kind.STATUS).last()

    def test_it_public_reply_moves_new_to_open(self):
        services.add_comment(ticket=self.ticket, author=self.agent, body="Looking now")
        self.assertEqual(self.ticket.status, Status.OPEN)
        event = self._last_status_event()
        self.assertEqual((event.old_value, event.new_value, event.note), ("New", "Open", "IT replied"))

    def test_internal_note_does_not_change_status(self):
        services.add_comment(ticket=self.ticket, author=self.agent, body="Hmm", is_internal=True)
        self.assertEqual(self.ticket.status, Status.NEW)

    def test_requester_reply_moves_waiting_to_open(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.WAITING)
        services.add_comment(ticket=self.ticket, author=self.requester, body="Here you go")
        self.assertEqual(self.ticket.status, Status.OPEN)
        self.assertEqual(self._last_status_event().note, "requester replied")

    def test_requester_reply_reopens_resolved(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.RESOLVED)
        services.add_comment(ticket=self.ticket, author=self.requester, body="Still broken")
        self.assertEqual(self.ticket.status, Status.OPEN)
        self.assertIsNone(self.ticket.resolved_at)

    def test_requester_cannot_add_internal_note(self):
        with self.assertRaises(PermissionDenied):
            services.add_comment(ticket=self.ticket, author=self.requester, body="x", is_internal=True)
        self.assertFalse(self.ticket.comments.exists())

    def test_other_requester_cannot_reply(self):
        with self.assertRaises(PermissionDenied):
            services.add_comment(ticket=self.ticket, author=self.other_requester, body="x")

    def test_requester_cannot_reply_to_closed_ticket(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.CLOSED)
        with self.assertRaises(PermissionDenied):
            services.add_comment(ticket=self.ticket, author=self.requester, body="x")

    def test_comment_attachments_belong_to_the_comment(self):
        comment = services.add_comment(
            ticket=self.ticket, author=self.agent, body="Log attached", is_internal=True,
            files=[upload("debug.log", b"log", "text/plain")],
        )
        attachment = comment.attachments.get()
        self.assertTrue(attachment.is_internal)


class UpdateTicketTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester)

    def test_each_change_is_logged(self):
        network = Category.objects.get(name="Network")
        changes = services.update_ticket(
            ticket=self.ticket, actor=self.agent, priority=Ticket.Priority.URGENT,
            category=network, assignee=self.agent2,
        )
        self.assertEqual(len(changes), 4)  # priority, category, assignee, auto New -> Open
        kinds = list(self.ticket.events.values_list("kind", "old_value", "new_value"))
        self.assertIn(("priority", "Normal", "Urgent"), kinds)
        self.assertIn(("category", "Hardware", "Network"), kinds)
        self.assertIn(("assignee", "", "Alex Morgan"), kinds)
        self.assertIn(("status", "New", "Open"), kinds)

    def test_assigning_keeps_an_explicit_status(self):
        services.update_ticket(
            ticket=self.ticket, actor=self.agent, assignee=self.agent, status=Status.IN_PROGRESS
        )
        self.assertEqual(self.ticket.status, Status.IN_PROGRESS)
        self.assertEqual(self.ticket.events.filter(kind="status").count(), 1)

    def test_no_changes_logs_nothing(self):
        changes = services.update_ticket(
            ticket=self.ticket, actor=self.agent, status=Status.NEW,
            priority=Ticket.Priority.NORMAL, assignee=None,
        )
        self.assertEqual(changes, [])
        self.assertFalse(self.ticket.events.exists())

    def test_resolved_and_closed_timestamps(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.RESOLVED)
        self.assertIsNotNone(self.ticket.resolved_at)
        self.assertIsNone(self.ticket.closed_at)
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.CLOSED)
        self.assertIsNotNone(self.ticket.closed_at)
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.OPEN)
        self.assertIsNone(self.ticket.resolved_at)
        self.assertIsNone(self.ticket.closed_at)

    def test_requester_cannot_update(self):
        with self.assertRaises(PermissionDenied):
            services.update_ticket(ticket=self.ticket, actor=self.requester, status=Status.CLOSED)


class RequesterActionTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester)

    def test_resolve_then_reopen(self):
        self.assertTrue(services.resolve_by_requester(ticket=self.ticket, user=self.requester))
        self.assertEqual(self.ticket.status, Status.RESOLVED)
        self.assertTrue(services.reopen_by_requester(ticket=self.ticket, user=self.requester))
        self.assertEqual(self.ticket.status, Status.OPEN)

    def test_reopen_only_from_resolved(self):
        self.assertFalse(services.reopen_by_requester(ticket=self.ticket, user=self.requester))
        self.assertEqual(self.ticket.status, Status.NEW)

    def test_only_the_requester(self):
        with self.assertRaises(PermissionDenied):
            services.resolve_by_requester(ticket=self.ticket, user=self.other_requester)

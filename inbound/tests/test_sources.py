import base64
import tempfile
from email.message import EmailMessage
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from accounts import entra
from accounts.tests.helpers import ENTRA_SETTINGS, claims
from inbound import eml, graph_inbox
from inbound.models import InboundEmail
from notifications import graph
from notifications.models import OutboundEmail
from tickets.models import Ticket
from tickets.tests.helpers import MediaTestCase


def sample_eml(**overrides) -> bytes:
    msg = EmailMessage()
    msg["From"] = overrides.get("from_", "Dana Whitfield <dana.whitfield@example.invalid>")
    msg["To"] = "helpdesk-test@example.invalid"
    msg["Subject"] = overrides.get("subject", "Second monitor not detected")
    msg["Message-ID"] = overrides.get("message_id", "<abc123@example.invalid>")
    msg.set_content(overrides.get("body", "It stopped after the dock update."))
    msg.add_attachment(b"png bytes", maintype="image", subtype="png", filename="photo.png")
    return msg.as_bytes()


@override_settings(INBOUND_ALLOWED_DOMAINS=["example.invalid"])
class EmlTests(MediaTestCase):
    def test_parse(self):
        message = eml.from_bytes(sample_eml())
        self.assertEqual(message.from_address, "dana.whitfield@example.invalid")
        self.assertEqual(message.from_name, "Dana Whitfield")
        self.assertEqual(message.message_id, "<abc123@example.invalid>")
        self.assertIn("dock update", message.body_text)
        self.assertEqual([a.name for a in message.attachments], ["photo.png"])

    def test_html_only_email(self):
        msg = EmailMessage()
        msg["From"] = "dana.whitfield@example.invalid"
        msg["Subject"] = "Hi"
        msg.set_content("<p>Hello <b>IT</b></p><script>evil()</script>", subtype="html")
        self.assertEqual(eml.from_bytes(msg.as_bytes()).body_text, "Hello IT")

    def test_ingest_command_with_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "message.eml"
            path.write_bytes(sample_eml())
            out = StringIO()
            call_command("ingest_email", str(path), stdout=out)
        ticket = Ticket.objects.get()
        self.assertIn(f"Created a ticket #{ticket.number}", out.getvalue())
        self.assertEqual(ticket.attachments.get().original_name, "photo.png")

    def test_ingest_command_with_flags(self):
        out = StringIO()
        call_command("ingest_email", "--from", "dana.whitfield@example.invalid",
                     "--subject", "VPN drops", "--body", "Every 10 minutes", stdout=out)
        self.assertEqual(Ticket.objects.get().subject, "VPN drops")


@override_settings(
    INBOUND_EMAIL="graph", INBOUND_ALLOWED_DOMAINS=["example.invalid"],
    HELPDESK_MAILBOX="helpdesk-test@example.invalid",
)
class GraphInboxTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        graph_inbox._folder_id = "folder-1"
        patcher = mock.patch.object(graph_inbox.graph, "call")
        self.call = patcher.start()
        self.addCleanup(patcher.stop)

    def _graph_message(self, **overrides):
        item = {
            "id": "AAMk-1", "subject": "Printer jammed", "receivedDateTime": "2026-11-06T09:00:00Z",
            "internetMessageId": "<graph-1@example.invalid>",
            "from": {"emailAddress": {"address": "Dana.Whitfield@example.invalid", "name": "Dana Whitfield"}},
            "internetMessageHeaders": [{"name": "Auto-Submitted", "value": "no"}],
            "hasAttachments": True, "body": {"content": "Tray 2 again."}, "uniqueBody": {"content": "Tray 2 again."},
        }
        item.update(overrides)
        return item

    def _respond(self, messages, attachments=()):
        def fake(method, path, **kwargs):
            response = mock.Mock()
            if method == "GET" and path.endswith("/mailFolders/inbox/messages"):
                response.json.return_value = {"value": messages}
            elif method == "GET" and path.endswith("/attachments"):
                response.json.return_value = {"value": list(attachments)}
            else:
                response.json.return_value = {}
            return response
        self.call.side_effect = fake

    def test_poll_processes_marks_read_and_moves(self):
        attachment = {"@odata.type": "#microsoft.graph.fileAttachment", "name": "jam.jpg",
                      "contentType": "image/jpeg", "isInline": False,
                      "contentBytes": base64.b64encode(b"jpeg").decode()}
        self._respond([self._graph_message()], [attachment])
        self.assertEqual(graph_inbox.poll(), (1, 0))

        ticket = Ticket.objects.get()
        self.assertEqual(ticket.requester, self.requester)
        self.assertEqual(ticket.attachments.get().original_name, "jam.jpg")
        calls = [(c.args[0], c.args[1]) for c in self.call.call_args_list]
        mailbox = "/users/helpdesk-test@example.invalid"
        self.assertIn(("PATCH", f"{mailbox}/messages/AAMk-1"), calls)
        self.assertIn(("POST", f"{mailbox}/messages/AAMk-1/move"), calls)
        # Plain text was requested, so no outside HTML is ever stored.
        list_call = next(c for c in self.call.call_args_list if c.args[1].endswith("/inbox/messages"))
        self.assertIn("text", list_call.kwargs["headers"]["Prefer"])

    def test_failure_is_retried_then_left_for_a_person(self):
        self._respond([self._graph_message(hasAttachments=False)])
        with mock.patch.object(graph_inbox, "process", side_effect=RuntimeError("boom")):
            for _ in range(3):
                self.assertEqual(graph_inbox.poll(), (0, 1))
        row = InboundEmail.objects.get()
        self.assertEqual((row.outcome, row.attempts), (InboundEmail.Outcome.ERROR, 3))
        marked = [c for c in self.call.call_args_list if c.args[0] == "PATCH"]
        moved = [c for c in self.call.call_args_list if c.args[1].endswith("/move")]
        self.assertEqual(len(marked), 1)  # only after the last attempt
        self.assertEqual(moved, [])  # left in the Inbox

    def test_worker_reads_the_inbox(self):
        self._respond([self._graph_message(hasAttachments=False)])
        out = StringIO()
        call_command("run_worker", "--once", stdout=out)
        self.assertIn("Inbox: 1 email(s) processed", out.getvalue())
        self.assertIn("Emails: 1 sent", out.getvalue())  # the receipt

    def test_worker_survives_graph_being_unreachable(self):
        self.call.side_effect = graph.GraphError("401 Unauthorized")
        out = StringIO()
        call_command("run_worker", "--once", stdout=out)
        self.assertIn("Inbox: couldn't read it", out.getvalue())


class ReplyHintTests(MediaTestCase):
    def test_footer_says_replies_are_not_read_when_email_in_is_off(self):
        from tickets.tests.helpers import make_ticket
        make_ticket(self.requester)
        self.assertIn("aren't added to the ticket yet", OutboundEmail.objects.get(kind="received").body_text)

    @override_settings(INBOUND_EMAIL="graph")
    def test_footers_explain_replying_when_email_in_is_on(self):
        from tickets import services
        from tickets.tests.helpers import make_ticket
        ticket = make_ticket(self.requester)
        services.update_ticket(ticket=ticket, actor=self.agent, assignee=self.agent2)
        requester_email = OutboundEmail.objects.get(kind="received")
        it_email = OutboundEmail.objects.get(kind="assigned")
        self.assertIn(f"Keep [#{ticket.number}] in the subject", requester_email.body_text)
        self.assertIn("public reply that Dana Whitfield will see", it_email.body_text)


@override_settings(**ENTRA_SETTINGS, INBOUND_ALLOWED_DOMAINS=["example.com"])
class AccountLinkingTests(TestCase):
    def test_first_sign_in_links_the_account_made_by_email(self):
        from inbound.processing import IncomingMessage, process
        result = process(IncomingMessage(message_id="<x@1>", from_address="dana.whitfield@example.com",
                                         subject="Help", body_text="Hi", source="command"))
        provisional = result.ticket.requester
        signed_in = entra.sync_user(claims())  # preferred_username dana.whitfield@example.com
        self.assertEqual(signed_in.pk, provisional.pk)
        self.assertIsNotNone(signed_in.entra_oid)
        self.assertFalse(signed_in.username.startswith("email:"))
        self.assertEqual(Ticket.objects.get().requester, signed_in)

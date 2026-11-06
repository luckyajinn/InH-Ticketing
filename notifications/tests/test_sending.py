from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from notifications import backends
from notifications.models import OutboundEmail
from notifications.sender import send_pending


def make_email(**overrides):
    data = {"kind": "it_replied", "to": "dana@example.invalid", "subject": "[#1001] Printer",
            "body_text": "Hello", "body_html": "<p>Hello</p>"}
    data.update(overrides)
    return OutboundEmail.objects.create(**data)


@override_settings(DEFAULT_FROM_EMAIL="helpdesk-test@example.invalid")
class SenderTests(TestCase):
    def test_sends_due_emails(self):
        email = make_email()
        self.assertEqual(send_pending(), (1, 0))
        email.refresh_from_db()
        self.assertEqual(email.status, OutboundEmail.Status.SENT)
        self.assertIsNotNone(email.sent_at)
        [sent] = mail.outbox
        self.assertEqual(sent.to, ["dana@example.invalid"])
        self.assertEqual(sent.from_email, "helpdesk-test@example.invalid")
        self.assertEqual(sent.alternatives[0].mimetype, "text/html")

    def test_skips_emails_not_yet_due(self):
        make_email(next_attempt_at=timezone.now() + timedelta(minutes=5))
        self.assertEqual(send_pending(), (0, 0))

    def test_failure_is_retried_later_then_given_up(self):
        email = make_email()
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("mail server down")):
            self.assertEqual(send_pending(), (0, 1))
            email.refresh_from_db()
            self.assertEqual(email.status, OutboundEmail.Status.PENDING)
            self.assertEqual(email.attempts, 1)
            self.assertIn("mail server down", email.last_error)
            self.assertGreater(email.next_attempt_at, timezone.now())

            for _ in range(10):
                OutboundEmail.objects.filter(pk=email.pk).update(next_attempt_at=timezone.now())
                send_pending()
            email.refresh_from_db()
        self.assertEqual(email.status, OutboundEmail.Status.FAILED)
        self.assertEqual(email.attempts, 5)

    def test_worker_once(self):
        make_email()
        out = StringIO()
        call_command("run_worker", "--once", stdout=out)
        self.assertIn("1 sent", out.getvalue())


@override_settings(
    HELPDESK_MAILBOX="helpdesk-test@example.invalid",
    ENTRA_TENANT_ID="11111111-1111-1111-1111-111111111111",
    ENTRA_CLIENT_ID="client", ENTRA_CLIENT_SECRET="not-a-real-secret",
)
class GraphBackendTests(TestCase):
    def setUp(self):
        backends._msal_app = None
        app = mock.Mock()
        app.acquire_token_for_client.return_value = {"access_token": "token-123"}
        patcher = mock.patch.object(backends, "_app", return_value=app)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _message(self):
        message = mail.EmailMultiAlternatives("[#1001] Printer", "Hello", "x@example.invalid",
                                              ["dana@example.invalid"])
        message.attach_alternative("<p>Hello</p>", "text/html")
        return message

    def test_posts_html_to_the_shared_mailbox(self):
        with mock.patch.object(backends.requests, "post") as post:
            post.return_value.status_code = 202
            sent = backends.GraphEmailBackend().send_messages([self._message()])
        self.assertEqual(sent, 1)
        url = post.call_args.args[0]
        self.assertEqual(url, "https://graph.microsoft.com/v1.0/users/helpdesk-test@example.invalid/sendMail")
        payload = post.call_args.kwargs["json"]["message"]
        self.assertEqual(payload["body"], {"contentType": "HTML", "content": "<p>Hello</p>"})
        self.assertEqual(payload["toRecipients"], [{"emailAddress": {"address": "dana@example.invalid"}}])
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer token-123")

    def test_error_response_raises_so_the_worker_retries(self):
        with mock.patch.object(backends.requests, "post") as post:
            post.return_value.status_code = 403
            post.return_value.text = "ErrorAccessDenied"
            with self.assertRaises(backends.GraphSendError):
                backends.GraphEmailBackend().send_messages([self._message()])

    @override_settings(HELPDESK_MAILBOX="")
    def test_needs_a_mailbox(self):
        with self.assertRaises(ImproperlyConfigured):
            backends.GraphEmailBackend()

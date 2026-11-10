"""
Attack strings in every input. Each must be stored and shown as plain text:
never run as SQL, as a shell command or as a template, and never cause an
error page. The database must be intact afterwards and no command may run.
"""

import tempfile
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test import override_settings
from django.urls import reverse
from django.utils.html import escape

from accounts.models import User
from inbound.processing import IncomingMessage, process
from inbound.text import clean_subject
from tickets.models import Attachment, Category, Comment, Ticket
from tickets.tests.helpers import MediaTestCase, make_ticket, make_user, upload

# If any shell payload ran, this file would appear.
CANARY = Path(tempfile.gettempdir()) / "inh_injection_canary"

SQL = [
    "' OR '1'='1",
    "' OR 1=1 --",
    "'; DROP TABLE tickets_ticket; --",
    "1; DELETE FROM accounts_user",
    '" OR ""="',
    "1' UNION SELECT username, email FROM accounts_user --",
    "%' OR 1=1 --",
    "'); SELECT pg_sleep(5); --",
    "admin'--",
    "1) OR (1=1",
]
SHELL = [
    f"; touch {CANARY}",
    f"&& echo pwned > {CANARY}",
    f"| type nul > {CANARY}",
    f"$(touch {CANARY})",
    f"`touch {CANARY}`",
    "; rm -rf / --no-preserve-root",
    "& whoami",
]
TEMPLATE = ["{{ 7*7 }}", "{% debug %}", "${7*7}", "<%= 7*7 %>", "{{ settings.SECRET_KEY }}"]
PAYLOADS = SQL + SHELL + TEMPLATE


class InjectionTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        CANARY.unlink(missing_ok=True)
        self.hardware = Category.objects.get(name="Hardware")
        self.users_before = User.objects.count()

    def assert_intact(self):
        tables = connection.introspection.table_names()
        for table in ("tickets_ticket", "tickets_comment", "tickets_category", "accounts_user"):
            self.assertIn(table, tables, f"table {table} is gone")
        self.assertGreaterEqual(User.objects.count(), self.users_before, "users were deleted")
        self.assertFalse(CANARY.exists(), "a shell command ran")

    def assert_shown_as_text(self, response, payload, status=200):
        self.assertLess(response.status_code, 500)
        self.assertContains(response, escape(payload), status_code=status)
        self.assertNotContains(response, settings.SECRET_KEY, status_code=status)

    # --- forms people type into ------------------------------------------------

    def test_new_request_subject_and_description(self):
        self.client.force_login(self.requester)
        for payload in PAYLOADS:
            with self.subTest(payload=payload):
                response = self.client.post(reverse("tickets:new"), {
                    "subject": payload, "category": self.hardware.pk,
                    "description": f"Description: {payload}", "password_ack": "on",
                })
                self.assertEqual(response.status_code, 302, response.content[:300])
                ticket = Ticket.objects.get(subject=payload.strip())
                self.assertEqual(ticket.description, f"Description: {payload}".strip())
                self.assert_shown_as_text(self.client.get(ticket.get_absolute_url()), payload)
        self.assertEqual(Ticket.objects.count(), len(PAYLOADS))
        self.assert_intact()

    def test_replies_and_internal_notes(self):
        ticket = make_ticket(self.requester)
        for payload in PAYLOADS:
            with self.subTest(payload=payload):
                self.client.force_login(self.requester)
                self.client.post(reverse("tickets:reply", args=[ticket.number]),
                                 {"body": payload, "password_ack": "on"})
                self.client.force_login(self.agent)
                self.client.post(reverse("tickets:reply", args=[ticket.number]),
                                 {"body": f"note {payload}", "visibility": "internal", "password_ack": "on"})
                self.assertTrue(Comment.objects.filter(ticket=ticket, body=payload.strip()).exists())
                self.assertTrue(Comment.objects.filter(ticket=ticket, body=f"note {payload}", is_internal=True).exists())
        self.assert_shown_as_text(self.client.get(ticket.get_absolute_url()), PAYLOADS[0])
        self.assert_intact()

    def test_password_precheck(self):
        self.client.force_login(self.requester)
        for payload in PAYLOADS:
            with self.subTest(payload=payload):
                response = self.client.post(reverse("tickets:check_text"), {"body": payload, "subject": payload})
                self.assertEqual(response.status_code, 200)
                self.assertIn("found", response.json())
        self.assert_intact()

    # --- search, filters and addresses -----------------------------------------

    def test_queue_search_and_filters(self):
        for i in range(3):
            make_ticket(self.requester, subject=f"Printer {i}")
        self.client.force_login(self.agent)
        for payload in PAYLOADS:
            with self.subTest(payload=payload):
                response = self.client.get(reverse("tickets:queue"), {
                    "q": payload, "category": payload, "priority": payload, "view": payload,
                })
                self.assertEqual(response.status_code, 200)
                # A tautology like ' OR '1'='1 must match nothing, not every ticket.
                self.assertEqual(response.context["page"].paginator.count, 0)
        self.assert_intact()

    def test_side_panel_values(self):
        ticket = make_ticket(self.requester)
        self.client.force_login(self.agent)
        for payload in PAYLOADS:
            with self.subTest(payload=payload):
                response = self.client.post(reverse("tickets:update", args=[ticket.number]), {
                    "status": payload, "priority": payload, "assignee": payload, "category": payload,
                })
                self.assertEqual(response.status_code, 400)
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.category), (Ticket.Status.NEW, Category.objects.get(name="Hardware")))
        self.assert_intact()

    def test_ticket_number_box_links_and_sign_in(self):
        self.client.force_login(self.requester)
        for payload in PAYLOADS:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.get(reverse("tickets:go"), {"number": payload}).status_code, 302)
                self.assertEqual(self.client.get(reverse("tickets:new"), {"follow_up": payload}).status_code, 200)
                self.assertEqual(self.client.get(f"/tickets/{payload}/").status_code, 404)
                self.assertLess(self.client.get(reverse("accounts:signin"), {"next": payload}).status_code, 500)
        self.assert_intact()

    def test_admin_search(self):
        admin = make_user("Ada Admin", User.Role.ADMIN)
        User.objects.filter(pk=admin.pk).update(is_staff=True, is_superuser=True)
        self.client.force_login(User.objects.get(pk=admin.pk))
        for payload in PAYLOADS:
            with self.subTest(payload=payload):
                response = self.client.get("/admin/tickets/ticket/", {"q": payload})
                self.assertEqual(response.status_code, 200)
        self.assert_intact()

    # --- files and email --------------------------------------------------------

    def test_attachment_file_names(self):
        self.client.force_login(self.requester)
        names = [f"{p}.txt" for p in SQL[:4]] + ["../../etc/passwd.txt", "..\\..\\windows\\win.ini.txt"]
        for name in names:
            with self.subTest(name=name):
                self.client.post(reverse("tickets:new"), {
                    "subject": "File test", "category": self.hardware.pk, "description": "See file",
                    "attachments": [upload(name, b"hello", "text/plain")], "password_ack": "on",
                })
        for attachment in Attachment.objects.all():
            stored = Path(attachment.file.path).resolve()
            self.assertTrue(str(stored).startswith(str(Path(settings.MEDIA_ROOT).resolve())), stored)
            self.assertNotIn("..", attachment.original_name.replace("...", ""))
            response = self.client.get(attachment.get_absolute_url())
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(Attachment.objects.count(), len(names))
        self.assert_intact()

    @override_settings(INBOUND_ALLOWED_DOMAINS=["example.invalid"], HELPDESK_MAILBOX="helpdesk-test@example.invalid")
    def test_email_in(self):
        for i, payload in enumerate(PAYLOADS):
            with self.subTest(payload=payload):
                result = process(IncomingMessage(
                    message_id=f"<attack-{i}@example.invalid>", from_address=f"new.person{i}@example.invalid",
                    from_name=payload, subject=payload, body_text=f"Body: {payload}", source="command",
                ))
                ticket = result.ticket
                self.assertIsNotNone(ticket, result.detail)
                self.assertEqual(ticket.subject, clean_subject(payload))
                self.assertIn(payload, ticket.description)
                self.assertEqual(ticket.requester.display_name, payload)
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(reverse("tickets:queue")).status_code, 200)
        self.assert_intact()

"""
Tests for stress-test mode. STRESS-TEST BRANCH ONLY: never merge into main.

The normal test run has stress-test mode off (the app isn't installed and the
auto sign-in isn't in the middleware), so these tests switch the pieces on
with override_settings and call the commands directly. SettingsTests loads
config/settings.py itself with STRESS_TEST_MODE=1, to check the real switch.
"""

import io
import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from core.tests.test_security import load_settings
from inbound.models import InboundEmail
from notifications.models import OutboundEmail
from stresstest import guard
from stresstest.management.commands import generate_load_data, stress_counts, stress_prune_files
from tickets.models import Attachment, Comment, Ticket

STRESS_MIDDLEWARE = "stresstest.middleware.StressAutoLoginMiddleware"
BANNER = "STRESS TEST: fake data only"


def stress_middleware():
    middleware = list(settings.MIDDLEWARE)
    auth = middleware.index("django.contrib.auth.middleware.AuthenticationMiddleware")
    middleware.insert(auth + 1, STRESS_MIDDLEWARE)
    return middleware


def fake_user(username, role=User.Role.AGENT, **kwargs):
    return User.objects.create(username=username, display_name=username, role=role,
                               email=f"{username}@example.invalid", **kwargs)


class GuardTests(SimpleTestCase):
    def test_allows_no_credentials_and_no_inbound_email(self):
        guard.check(entra_values=["", "  ", ""], inbound_email="off")
        guard.check(entra_values=["", "", ""], inbound_email="")

    def test_refuses_any_microsoft_365_value(self):
        for values in (["tenant", "", ""], ["", "client", ""], ["", "", "secret"]):
            with self.subTest(values=values), self.assertRaises(ImproperlyConfigured):
                guard.check(entra_values=values, inbound_email="off")

    def test_refuses_reading_a_mailbox(self):
        with self.assertRaises(ImproperlyConfigured):
            guard.check(entra_values=["", "", ""], inbound_email="graph")


class SettingsTests(SimpleTestCase):
    """The STRESS_TEST_MODE switch in config/settings.py, loaded for real."""

    def test_off_by_default(self):
        s = load_settings(STRESS_TEST_MODE="0")
        self.assertNotIn("stresstest", s["INSTALLED_APPS"])
        self.assertNotIn(STRESS_MIDDLEWARE, s["MIDDLEWARE"])

    def test_on_signs_in_automatically_and_sends_no_email(self):
        s = load_settings(STRESS_TEST_MODE="1", EMAIL_BACKEND="graph", INBOUND_EMAIL="off",
                          HELPDESK_MAILBOX="helpdesk-test@example.invalid", IT_NOTIFY_EMAIL="it@example.invalid")
        self.assertIn("stresstest", s["INSTALLED_APPS"])
        auth = s["MIDDLEWARE"].index("django.contrib.auth.middleware.AuthenticationMiddleware")
        self.assertEqual(s["MIDDLEWARE"][auth + 1], STRESS_MIDDLEWARE)
        self.assertEqual(s["EMAIL_BACKEND"], "django.core.mail.backends.dummy.EmailBackend")
        self.assertEqual((s["INBOUND_EMAIL"], s["HELPDESK_MAILBOX"], s["IT_NOTIFY_EMAIL"]), ("off", "", ""))

    def test_refuses_to_start_with_microsoft_365_settings_or_mailbox_reading(self):
        for env in ({"ENTRA_CLIENT_SECRET": "a-secret"}, {"ENTRA_TENANT_ID": "tenant"}, {"INBOUND_EMAIL": "graph"}):
            with self.subTest(env=env), self.assertRaises(ImproperlyConfigured):
                load_settings(STRESS_TEST_MODE="1", **env)


@unittest.skipIf(settings.STRESS_TEST_MODE, "checks normal mode; this test run has STRESS_TEST_MODE on")
class NormalModeTests(TestCase):
    def test_no_automatic_sign_in_without_stress_mode(self):
        fake_user("stress-agent-01")
        self.assertFalse(settings.STRESS_TEST_MODE)
        self.assertNotIn(STRESS_MIDDLEWARE, settings.MIDDLEWARE)
        response = self.client.get("/", HTTP_X_STRESS_USER="stress-agent-01", follow=True)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertNotContains(response, BANNER)


@override_settings(STRESS_TEST_MODE=True, MIDDLEWARE=stress_middleware())
class AutoSignInTests(TestCase):
    def setUp(self):
        self.agent = fake_user("stress-agent-01")
        self.requester = fake_user("stress-req-0001", User.Role.REQUESTER)
        self.real = fake_user("dana.whitfield")

    def signed_in_as(self, response):
        user = response.wsgi_request.user
        return user.username if user.is_authenticated else None

    def test_signs_in_the_first_fake_agent_by_default(self):
        response = self.client.get("/", follow=True)
        self.assertEqual(self.signed_in_as(response), "stress-agent-01")
        self.assertContains(response, BANNER)

    def test_header_picks_the_fake_user(self):
        response = self.client.get("/", HTTP_X_STRESS_USER="stress-req-0001")
        self.assertEqual(self.signed_in_as(response), "stress-req-0001")

    def test_as_switches_user_and_is_remembered(self):
        self.client.get("/")
        response = self.client.get("/?as=stress-req-0001")
        self.assertEqual(self.signed_in_as(response), "stress-req-0001")
        self.assertEqual(response.cookies["stress_user"].value, "stress-req-0001")

        fresh = Client()
        fresh.cookies["stress_user"] = "stress-req-0001"
        self.assertEqual(self.signed_in_as(fresh.get("/")), "stress-req-0001")

    def test_never_signs_in_an_account_without_the_stress_prefix(self):
        self.assertIsNone(self.signed_in_as(self.client.get("/", HTTP_X_STRESS_USER="dana.whitfield")))
        self.assertIsNone(self.signed_in_as(Client().get("/?as=dana.whitfield")))
        cookie_client = Client()
        cookie_client.cookies["stress_user"] = "dana.whitfield"
        self.assertIsNone(self.signed_in_as(cookie_client.get("/")))

    def test_ignores_inactive_and_unknown_fake_users(self):
        fake_user("stress-agent-09", is_active=False)
        self.assertIsNone(self.signed_in_as(self.client.get("/", HTTP_X_STRESS_USER="stress-agent-09")))
        self.assertIsNone(self.signed_in_as(Client().get("/", HTTP_X_STRESS_USER="stress-nobody")))


class GenerateLoadDataTests(TestCase):
    SMALL = ["--requesters", "6", "--agents", "2", "--tickets", "40", "--attachments", "3", "--days", "90",
             "--file-median-kb", "20"]

    @classmethod
    def setUpClass(cls):
        cls._media_dir = tempfile.mkdtemp(prefix="inh-stress-media-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(self._media_dir, ignore_errors=True)  # each test starts with no stored files

    def generate(self, *args):
        call_command(generate_load_data.Command(), *args, stdout=io.StringIO())

    def counts(self):
        out = io.StringIO()
        call_command(stress_counts.Command(), stdout=out)
        return json.loads(out.getvalue())

    def stored_files(self):
        return [p for p in Path(self._media_dir).rglob("*") if p.is_file()]

    @override_settings(STRESS_TEST_MODE=False)
    def test_refuses_outside_stress_mode(self):
        with self.assertRaisesMessage(CommandError, "STRESS_TEST_MODE"):
            self.generate(*self.SMALL)
        self.assertFalse(User.objects.exists())
        with self.assertRaisesMessage(CommandError, "STRESS_TEST_MODE"):
            call_command(stress_prune_files.Command(), stdout=io.StringIO())

    @override_settings(STRESS_TEST_MODE=True)
    def test_refuses_a_database_with_real_accounts(self):
        fake_user("dana.whitfield", entra_oid="00000000-0000-0000-0000-000000000001")
        with self.assertRaisesMessage(CommandError, "real Microsoft 365 accounts"):
            self.generate(*self.SMALL)
        self.assertFalse(Ticket.objects.exists())

    @override_settings(STRESS_TEST_MODE=True)
    def test_generates_only_fake_people_and_tickets(self):
        self.generate(*self.SMALL)

        people = User.objects.all()
        self.assertEqual(people.count(), 8)
        for person in people:
            self.assertTrue(person.username.startswith("stress-"))
            self.assertTrue(person.email.endswith("@example.invalid"))
            self.assertFalse(person.has_usable_password())
            self.assertIsNone(person.entra_oid)

        counts = self.counts()
        self.assertEqual(counts["tickets"], 40)
        self.assertEqual(counts["emails"], OutboundEmail.objects.count())
        self.assertEqual(Attachment.objects.count(), 3)
        self.assertEqual(len(self.stored_files()), 3)
        self.assertEqual(sum(p.stat().st_size for p in self.stored_files()),
                         sum(Attachment.objects.values_list("size", flat=True)))
        # The emails the app would have sent: all to fake addresses, all marked as sent, none queued.
        self.assertEqual(OutboundEmail.objects.filter(kind="received").count(), 40)
        self.assertFalse(OutboundEmail.objects.exclude(to__endswith="@example.invalid").exists())
        self.assertFalse(OutboundEmail.objects.exclude(status=OutboundEmail.Status.SENT).exists())
        self.assertEqual(InboundEmail.objects.filter(outcome=InboundEmail.Outcome.NEW_TICKET).count(),
                         Ticket.objects.filter(source=Ticket.Source.EMAIL).count())
        # Tickets are spread back in time, and the date fields work normally again afterwards.
        oldest = Ticket.objects.order_by("created_at").first()
        self.assertGreater((Ticket.objects.order_by("-created_at").first().created_at - oldest.created_at).days, 7)
        self.assertTrue(Ticket._meta.get_field("created_at").auto_now_add)
        self.assertTrue(Ticket._meta.get_field("updated_at").auto_now)

    @override_settings(STRESS_TEST_MODE=True)
    def test_runs_again_only_with_clear(self):
        self.generate(*self.SMALL)
        with self.assertRaisesMessage(CommandError, "--clear"):
            self.generate(*self.SMALL)

        self.generate(*self.SMALL, "--clear")
        counts = self.counts()
        self.assertEqual((counts["requesters"], counts["agents"], counts["tickets"]), (6, 2, 40))
        self.assertEqual(len(self.stored_files()), 3)  # the first run's files were removed

    @override_settings(STRESS_TEST_MODE=True)
    def test_tickets_follow_a_realistic_lifecycle(self):
        # A year at 200 tickets a month, without files (they don't affect this).
        self.generate("--requesters", "50", "--agents", "5", "--tickets", "2400", "--days", "365",
                      "--attachments", "0")
        now = timezone.now()
        open_count = Ticket.objects.open().count()
        # A team of five has a few dozen open tickets, not hundreds (about 30 expected here).
        self.assertGreaterEqual(open_count, 10)
        self.assertLessEqual(open_count, 60)
        # Resolved tickets close after AUTO_CLOSE_RESOLVED_DAYS, so the worker has nothing left over.
        stale = now - timedelta(days=settings.AUTO_CLOSE_RESOLVED_DAYS)
        self.assertFalse(Ticket.objects.filter(status=Ticket.Status.RESOLVED, resolved_at__lt=stale).exists())
        for ticket in Ticket.objects.filter(status=Ticket.Status.CLOSED)[:200]:
            self.assertEqual(ticket.closed_at - ticket.resolved_at, timedelta(days=settings.AUTO_CLOSE_RESOLVED_DAYS))
        # New tickets haven't been touched by IT yet.
        self.assertFalse(Ticket.objects.filter(status=Ticket.Status.NEW, assignee__isnull=False).exists())
        self.assertFalse(Comment.objects.filter(ticket__status=Ticket.Status.NEW).exists())
        # Nothing is dated in the future.
        self.assertFalse(Comment.objects.filter(created_at__gt=now).exists())
        self.assertFalse(OutboundEmail.objects.filter(created_at__gt=now).exists())

    @override_settings(STRESS_TEST_MODE=True)
    def test_prune_files_removes_only_files_no_ticket_uses(self):
        self.generate(*self.SMALL)
        kept = set(self.stored_files())
        stray = Path(self._media_dir) / "attachments" / "999999" / "uploaded-in-an-earlier-run.jpg"
        stray.parent.mkdir(parents=True)
        stray.write_bytes(b"x" * 1000)
        out = io.StringIO()
        call_command(stress_prune_files.Command(), stdout=out)
        self.assertIn("Removed 1 unused attachment files", out.getvalue())
        self.assertEqual(set(self.stored_files()), kept)
        self.assertFalse(stray.parent.exists())

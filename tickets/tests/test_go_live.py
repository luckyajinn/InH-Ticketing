"""v0.9.1, before go-live: spoofed IT emails, shared PCs, the archive, departments, department mailboxes, removal."""

import importlib
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.apps import apps as django_apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts import entra
from accounts.models import User
from core import departments
from inbound.models import InboundEmail
from inbound.processing import IncomingMessage, process, sender_confirmed
from notifications import graph
from notifications.backends import GraphEmailBackend
from notifications.models import OutboundEmail
from notifications.sender import send_pending
from tickets import services
from tickets.forms import agent_choices
from tickets.examples import CLEANING, MECHANICS, add_example_departments
from tickets.models import Category, Comment, Department, Ticket, TicketEvent
from tickets.tests.helpers import MediaTestCase, make_ticket, make_user, upload

Status = Ticket.Status
_ids = iter(range(1, 10_000))
MECH_BOX = {"mechanics": {"address": "mechanics@example.invalid", "folder": ""}}


def email(from_address, subject="Printer jammed", body="Tray 2 again.", headers=None, source="graph", **extra):
    return IncomingMessage(
        message_id=f"<go-live-{next(_ids)}@example.invalid>", from_address=from_address, subject=subject,
        body_text=body, headers=headers or {}, source=source, **extra,
    )


class GoLiveTestCase(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.admin = make_user("Ada Admin", User.Role.ADMIN)
        User.objects.filter(pk=self.admin.pk).update(is_staff=True, is_superuser=True)
        self.admin.refresh_from_db()
        examples = add_example_departments()
        self.mech_agent = self.make_agent("Mo Mechanic", MECHANICS)
        self.cs_agent = self.make_agent("Cleo Cleaner", CLEANING)
        self.mechanics, self.cleaning = examples[MECHANICS], examples[CLEANING]
        self.hardware = Category.objects.get(name="Hardware")

    def make_agent(self, name, department):
        agent = make_user(name, User.Role.AGENT)
        agent.department = department
        agent.save()
        return agent


# ---------------------------------------------------------------------------
# Emails that only claim to be from IT
# ---------------------------------------------------------------------------
@override_settings(INBOUND_ALLOWED_DOMAINS=["example.invalid"], HELPDESK_MAILBOX="helpdesk-test@example.invalid")
class SpoofingTests(GoLiveTestCase):
    def test_what_counts_as_confirmed(self):
        cases = [
            ({}, False),
            ({"Authentication-Results": "spf=pass; dkim=none; dmarc=fail action=none"}, False),
            ({"Authentication-Results": "spf=pass; dmarc=pass action=none header.from=example.invalid"}, True),
            ({"Authentication-Results": "spf=softfail; compauth=pass reason=105"}, True),
            ({"X-MS-Exchange-Organization-AuthAs": "Internal"}, True),
            ({"X-MS-Exchange-Organization-AuthAs": "Anonymous"}, False),
        ]
        for headers, confirmed in cases:
            with self.subTest(headers=headers):
                self.assertEqual(sender_confirmed(email(self.agent.email, headers=headers)), confirmed)
        self.assertTrue(sender_confirmed(email(self.agent.email, source="command")))
        with override_settings(INBOUND_VERIFY_IT_SENDERS=False):
            self.assertTrue(sender_confirmed(email(self.agent.email)))

    def test_an_unconfirmed_it_email_becomes_an_internal_note(self):
        ticket = make_ticket(self.requester)
        result = process(email(self.agent.email, subject=f"Re: [#{ticket.number}] Printer jammed",
                               body="Your new password is Hunter22!"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.NOTE)
        note = ticket.comments.get()
        self.assertTrue(note.is_internal)
        self.assertIn("couldn't confirm", note.body)
        self.assertFalse(OutboundEmail.objects.filter(kind="it_replied").exists())

    def test_a_confirmed_it_email_is_a_public_reply(self):
        ticket = make_ticket(self.requester)
        result = process(email(self.agent.email, subject=f"Re: [#{ticket.number}] Printer jammed",
                               headers={"X-MS-Exchange-Organization-AuthAs": "Internal"}))
        self.assertEqual(result.outcome, InboundEmail.Outcome.REPLY)
        self.assertFalse(ticket.comments.get().is_internal)


# ---------------------------------------------------------------------------
# Shared PCs, no deletes, start-up order, the manifest, the privacy page
# ---------------------------------------------------------------------------
class SafetyNetTests(GoLiveTestCase):
    def test_signed_in_pages_are_never_stored(self):
        ticket = make_ticket(self.requester, files=[upload()])
        self.client.force_login(self.requester)
        for url in (reverse("tickets:mine"), ticket.get_absolute_url()):
            with self.subTest(url=url):
                self.assertIn("no-store", self.client.get(url)["Cache-Control"])
        attachment = ticket.attachments.get()
        response = self.client.get(reverse("tickets:attachment", args=[attachment.pk, attachment.original_name]))
        self.assertIn("no-store", response["Cache-Control"])
        self.client.logout()
        self.assertNotIn("no-store", self.client.get(reverse("core:about")).get("Cache-Control", ""))

    def test_signing_in_ends_when_the_browser_closes(self):
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.client.force_login(self.requester)
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_tickets_cant_be_deleted_in_the_admin(self):
        ticket = make_ticket(self.requester)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(f"/admin/tickets/ticket/{ticket.pk}/delete/").status_code, 403)
        self.assertNotContains(self.client.get("/admin/tickets/ticket/"), "delete_selected")

    def test_the_worker_waits_for_the_web_container(self):
        compose = (Path(settings.BASE_DIR) / "compose.yaml").read_text(encoding="utf-8")
        worker = compose.split("  worker:", 1)[1]
        self.assertIn("web:\n        # Healthy", worker)
        self.assertIn("condition: service_healthy\n    command: python manage.py run_worker", worker)

    def test_the_worker_has_its_own_health_check(self):
        compose = (Path(settings.BASE_DIR) / "compose.yaml").read_text(encoding="utf-8")
        worker = compose.split("  worker:", 1)[1].split("\nvolumes:", 1)[0]
        self.assertIn('test: ["CMD", "python", "manage.py", "check_worker"]', worker)
        self.assertNotIn("disable: true", worker)

    def test_the_manifest_has_its_type(self):
        self.assertEqual(settings.WHITENOISE_MIMETYPES[".webmanifest"], "application/manifest+json")

    def test_privacy_page(self):
        page = self.client.get(reverse("core:about"))
        self.assertContains(page, "logged with its sender and subject only")
        self.assertContains(page, "A copy of each email it sends you")
        self.assertContains(page, "kept for two years")
        self.assertContains(page, "until you close the browser")


# ---------------------------------------------------------------------------
# The archive
# ---------------------------------------------------------------------------
@override_settings(INBOUND_ALLOWED_DOMAINS=["example.invalid"], HELPDESK_MAILBOX="helpdesk-test@example.invalid")
class ArchiveTests(GoLiveTestCase):
    def closed_ticket(self):
        ticket = make_ticket(self.requester)
        services.update_ticket(ticket=ticket, actor=self.agent, status=Status.CLOSED)
        return ticket

    def test_closing_archives_for_two_years(self):
        ticket = self.closed_ticket()
        self.assertIsNotNone(ticket.archived_at)
        self.assertEqual(ticket.keep_until, ticket.archived_at + timedelta(days=730))
        self.assertTrue(ticket.events.filter(kind=TicketEvent.Kind.ARCHIVE, new_value="Archived").exists())

    def test_auto_close_archives_too(self):
        ticket = make_ticket(self.requester)
        services.update_ticket(ticket=ticket, actor=self.agent, status=Status.RESOLVED)
        Ticket.objects.filter(pk=ticket.pk).update(resolved_at=timezone.now() - timedelta(days=8))
        self.assertEqual(services.close_resolved_tickets(), 1)
        self.assertIsNotNone(Ticket.objects.get(pk=ticket.pk).archived_at)

    def test_archived_tickets_are_read_only(self):
        ticket = self.closed_ticket()
        self.client.force_login(self.agent)
        page = self.client.get(ticket.get_absolute_url())
        self.assertContains(page, "Archived")
        self.assertNotContains(page, 'id="reply"')
        self.assertNotContains(page, 'data-autosubmit')
        self.client.post(reverse("tickets:reply", args=[ticket.number]), {"body": "Hello", "visibility": "public"})
        self.client.post(reverse("tickets:update", args=[ticket.number]),
                         {"status": Status.OPEN, "priority": 2, "category": ticket.category_id})
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.comments.count()), (Status.CLOSED, 0))

    def test_queue_archive_view(self):
        archived = self.closed_ticket()
        open_one = make_ticket(self.requester, subject="Still broken")
        self.client.force_login(self.agent)
        everything_open = self.client.get(reverse("tickets:queue"), {"view": "open"})
        self.assertContains(everything_open, open_one.subject)
        self.assertNotContains(everything_open, f"#{archived.number}<")
        self.assertContains(self.client.get(reverse("tickets:queue"), {"view": "archive"}), archived.subject)

    def test_only_admins_take_tickets_out_of_the_archive(self):
        ticket = self.closed_ticket()
        self.client.force_login(self.agent)
        self.assertEqual(self.client.post(reverse("tickets:unarchive", args=[ticket.number])).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(reverse("tickets:unarchive", args=[ticket.number]))
        ticket.refresh_from_db()
        self.assertIsNone(ticket.archived_at)
        self.assertEqual(ticket.status, Status.CLOSED)

    def test_emails_about_an_archived_ticket(self):
        ticket = self.closed_ticket()
        subject = f"Re: [#{ticket.number}] Printer jammed"
        follow_up = process(email(self.requester.email, subject=subject, source="command"))
        self.assertEqual(follow_up.outcome, InboundEmail.Outcome.NEW_TICKET)
        self.assertEqual(follow_up.ticket.follows_up, ticket)
        note = process(email(self.agent.email, subject=subject, source="command"))
        self.assertEqual(note.outcome, InboundEmail.Outcome.NOTE)
        self.assertTrue(ticket.comments.get().is_internal)

    def test_tickets_closed_before_the_upgrade_are_archived(self):
        ticket = make_ticket(self.requester)
        closed = timezone.now() - timedelta(days=30)
        Ticket.objects.filter(pk=ticket.pk).update(status=Status.CLOSED, closed_at=closed, archived_at=None)
        migration = importlib.import_module("tickets.migrations.0007_departments_and_archive")
        migration.fill_in(django_apps, None)
        self.assertEqual(Ticket.objects.get(pk=ticket.pk).archived_at, closed)


# ---------------------------------------------------------------------------
# Departments: Mechanics and C&S see and work their own tickets
# ---------------------------------------------------------------------------
class EntraRoleTests(GoLiveTestCase):
    def test_roles_and_departments(self):
        cases = [
            (["Agent"], User.Role.AGENT, departments.IT),
            (["Agent.Mechanics"], User.Role.AGENT, MECHANICS),
            (["Agent.Cleaning"], User.Role.AGENT, CLEANING),
            (["Agent.Mechanics", "Agent"], User.Role.AGENT, departments.IT),
            (["Admin", "Agent.Mechanics"], User.Role.ADMIN, ""),
            ([], User.Role.REQUESTER, ""),
        ]
        for roles, role, department in cases:
            with self.subTest(roles=roles):
                self.assertEqual(entra.role_from_claims(roles), role)
                self.assertEqual(entra.department_from_claims(roles), department)

    def test_categories_have_departments(self):
        self.assertEqual(self.mechanics.department, MECHANICS)
        self.assertEqual(self.cleaning.department, CLEANING)
        self.assertEqual(self.hardware.department, departments.IT)


class DepartmentAccessTests(GoLiveTestCase):
    def setUp(self):
        super().setUp()
        self.it_ticket = make_ticket(self.requester, subject="Laptop not charging", category=self.hardware)
        self.mech_ticket = make_ticket(self.requester, subject="Press is leaking", category=self.mechanics)
        self.cs_ticket = make_ticket(self.requester, subject="Spill in lab 2", category=self.cleaning)

    def test_each_department_sees_only_its_own_tickets(self):
        for user, mine, others in [
            (self.agent, self.it_ticket, [self.mech_ticket, self.cs_ticket]),
            (self.mech_agent, self.mech_ticket, [self.it_ticket, self.cs_ticket]),
            (self.cs_agent, self.cs_ticket, [self.it_ticket, self.mech_ticket]),
        ]:
            with self.subTest(user=str(user)):
                self.client.force_login(user)
                queue = self.client.get(reverse("tickets:queue"))
                self.assertContains(queue, mine.subject)
                self.assertContains(self.client.get(mine.get_absolute_url()), "Properties")
                for other in others:
                    self.assertNotContains(queue, other.subject)
                    self.assertEqual(self.client.get(other.get_absolute_url()).status_code, 404)

    def test_admins_see_every_department_and_can_filter(self):
        self.client.force_login(self.admin)
        queue = self.client.get(reverse("tickets:queue"))
        for ticket in (self.it_ticket, self.mech_ticket, self.cs_ticket):
            self.assertContains(queue, ticket.subject)
        only = self.client.get(reverse("tickets:queue"), {"dept": "mechanics"})
        self.assertContains(only, self.mech_ticket.subject)
        self.assertNotContains(only, self.it_ticket.subject)

    def test_department_staff_work_their_tickets(self):
        self.client.force_login(self.mech_agent)
        self.client.post(reverse("tickets:reply", args=[self.mech_ticket.number]),
                         {"body": "On our way.", "visibility": "public"})
        self.client.post(reverse("tickets:update", args=[self.mech_ticket.number]),
                         {"status": Status.IN_PROGRESS, "priority": 3, "category": self.mechanics.pk,
                          "assignee": self.mech_agent.pk})
        self.mech_ticket.refresh_from_db()
        self.assertEqual((self.mech_ticket.status, self.mech_ticket.assignee), (Status.IN_PROGRESS, self.mech_agent))
        self.assertTrue(OutboundEmail.objects.filter(kind="it_replied", to=self.requester.email).exists())

    def test_staff_cant_move_tickets_to_another_department(self):
        with self.assertRaises(PermissionDenied):
            services.update_ticket(ticket=self.mech_ticket, actor=self.mech_agent, category=self.hardware)
        self.client.force_login(self.mech_agent)
        response = self.client.post(reverse("tickets:update", args=[self.mech_ticket.number]),
                                    {"status": Status.NEW, "priority": 2, "category": self.hardware.pk})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Ticket.objects.get(pk=self.mech_ticket.pk).category, self.mechanics)

    def test_assignees_come_from_the_department(self):
        choices = set(agent_choices(self.mech_ticket))
        self.assertIn(self.mech_agent, choices)
        self.assertIn(self.admin, choices)
        self.assertNotIn(self.agent, choices)
        self.assertNotIn(self.cs_agent, choices)
        self.assertIn(self.agent, set(agent_choices(self.it_ticket)))

    def test_staff_see_their_own_requests_to_other_departments_as_requesters(self):
        mine = make_ticket(self.mech_agent, subject="My monitor flickers", category=self.hardware)
        services.add_comment(ticket=mine, author=self.agent, body="Checking the cable.", is_internal=True)
        self.client.force_login(self.mech_agent)
        page = self.client.get(mine.get_absolute_url())
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Checking the cable.")
        self.assertNotContains(page, "Properties")

    def test_new_request_alerts_go_to_the_department(self):
        Department.objects.filter(key=MECHANICS).update(alert_email="mech-team@example.invalid")
        with override_settings(IT_NOTIFY_EMAIL="it-team@example.invalid"):
            make_ticket(self.requester, subject="Belt squeaks", category=self.mechanics)
            make_ticket(self.requester, subject="VPN drops", category=self.hardware)
            make_ticket(self.requester, subject="Bins full", category=self.cleaning)
        alerts = dict(OutboundEmail.objects.filter(kind="new_ticket").values_list("subject", "to"))
        self.assertTrue(any(s.endswith("Belt squeaks") and to == "mech-team@example.invalid" for s, to in alerts.items()))
        self.assertTrue(any(s.endswith("VPN drops") and to == "it-team@example.invalid" for s, to in alerts.items()))
        # No address for C&S: each of its agents gets the alert.
        self.assertTrue(any(s.endswith("Bins full") and to == self.cs_agent.email for s, to in alerts.items()))


class MoveTests(GoLiveTestCase):
    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester, subject="Machine on line 3 stopped", category=self.hardware)
        services.update_ticket(ticket=self.ticket, actor=self.agent, assignee=self.agent)
        services.add_comment(ticket=self.ticket, author=self.agent, body="Not ours, it's mechanical.",
                             is_internal=True, share_on_move=True)
        services.add_comment(ticket=self.ticket, author=self.agent, body="IT-only remark.", is_internal=True)

    def test_staff_ask_an_admin_to_move_it(self):
        self.client.force_login(self.agent)
        self.client.post(reverse("tickets:ask_to_move", args=[self.ticket.number]),
                         {"department": "mechanics", "reason": "It's a mechanical fault"})
        event = self.ticket.events.get(kind=TicketEvent.Kind.MOVE_REQUEST)
        self.assertEqual((event.old_value, event.new_value), ("IT", "Mechanics"))
        self.assertTrue(OutboundEmail.objects.filter(kind="move_requested", to=self.admin.email).exists())
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.ticket.get_absolute_url()), "asked to move this to Mechanics")

    def test_only_admins_move_and_only_once_confirmed(self):
        self.client.force_login(self.agent)
        url = reverse("tickets:move", args=[self.ticket.number])
        self.assertEqual(self.client.post(url, {"category": self.mechanics.pk, "confirmed": "on"}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(url, {"category": self.mechanics.pk}).status_code, 400)
        self.client.post(url, {"category": self.mechanics.pk, "confirmed": "on"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.category, self.mechanics)
        self.assertIsNone(self.ticket.assignee)  # IT's agent doesn't work Mechanics tickets
        moved = self.ticket.events.get(kind=TicketEvent.Kind.DEPARTMENT)
        self.assertIn("1 internal note shared, 1 kept with IT", moved.note)

    def test_notes_stay_with_their_department_unless_shared(self):
        services.move_ticket(ticket=self.ticket, actor=self.admin, category=self.mechanics)
        self.client.force_login(self.mech_agent)
        page = self.client.get(self.ticket.get_absolute_url())
        self.assertContains(page, "Not ours, it&#x27;s mechanical.")
        self.assertNotContains(page, "IT-only remark.")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.ticket.get_absolute_url()), "IT-only remark.")
        self.assertEqual(self.client.get(self.ticket.get_absolute_url()).status_code, 200)
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(self.ticket.get_absolute_url()).status_code, 404)

    def test_notes_record_their_department(self):
        note = self.ticket.comments.filter(is_internal=True).first()
        self.assertEqual(note.department, departments.IT)


# ---------------------------------------------------------------------------
# A mailbox per department
# ---------------------------------------------------------------------------
class DepartmentMailboxSettingsTests(GoLiveTestCase):
    def test_parsing(self):
        from config.settings import env_departments

        with mock.patch.dict("os.environ", {"X": "mechanics=a@example.invalid; cleaning=b@example.invalid/Requests"}):
            self.assertEqual(env_departments("X"), {"mechanics": "a@example.invalid",
                                                     "cleaning": "b@example.invalid/Requests"})
        # Any department's key works (they're set in the admin site), but not IT's, a name, or no address.
        with mock.patch.dict("os.environ", {"X": "plumbing=d@example.invalid"}):
            self.assertEqual(env_departments("X"), {"plumbing": "d@example.invalid"})
        for bad in ("it=c@example.invalid", "Plumbing Team=d@example.invalid", "9lives=e@example.invalid", "mechanics="):
            with self.subTest(bad=bad), mock.patch.dict("os.environ", {"X": bad}):
                with self.assertRaises(ImproperlyConfigured):
                    env_departments("X")


@override_settings(INBOUND_ALLOWED_DOMAINS=["example.invalid"], HELPDESK_MAILBOX="helpdesk-test@example.invalid",
                   DEPARTMENT_MAILBOXES=MECH_BOX)
class DepartmentMailboxTests(GoLiveTestCase):
    def test_email_to_a_department_mailbox_is_that_departments_ticket(self):
        result = process(email(self.requester.email, subject="Press is leaking", source="command",
                               department="mechanics"))
        self.assertEqual(result.ticket.category.department, MECHANICS)

    def test_its_own_mailboxes_are_ignored(self):
        result = process(email("mechanics@example.invalid", source="command"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.IGNORED)

    def test_department_tickets_are_emailed_from_their_mailbox(self):
        make_ticket(self.requester, subject="Press is leaking", category=self.mechanics)
        make_ticket(self.requester, subject="VPN drops", category=self.hardware)
        with mock.patch.object(graph, "call") as call:
            with override_settings(EMAIL_BACKEND="notifications.backends.GraphEmailBackend"):
                send_pending()
        paths = {c.args[1] for c in call.call_args_list}
        self.assertIn("/users/mechanics@example.invalid/sendMail", paths)
        self.assertIn("/users/helpdesk-test@example.invalid/sendMail", paths)

    def test_the_backend_only_sends_from_our_mailboxes(self):
        from django.core.mail import EmailMessage

        with mock.patch.object(graph, "call") as call:
            GraphEmailBackend().send_messages([EmailMessage("s", "b", "someone@else.invalid", ["x@example.invalid"])])
        self.assertEqual(call.call_args.args[1], "/users/helpdesk-test@example.invalid/sendMail")

    @override_settings(INBOUND_EMAIL="graph",
                       DEPARTMENT_MAILBOXES={"cleaning": {"address": "cs@example.invalid", "folder": "Requests"}})
    def test_reading_a_folder_in_a_department_mailbox(self):
        from inbound import graph_inbox

        graph_inbox._folder_ids.clear()
        self.addCleanup(graph_inbox._folder_ids.clear)
        message = {
            "id": "M1", "subject": "Bins full", "receivedDateTime": "2026-11-10T09:00:00Z",
            "internetMessageId": "<cs-1@example.invalid>",
            "from": {"emailAddress": {"address": self.requester.email, "name": "Dana"}},
            "internetMessageHeaders": [{"name": "X-MS-Exchange-Organization-AuthAs", "value": "Internal"}],
            "hasAttachments": False, "body": {"content": "Lab 2"},
        }

        def fake(method, path, **kwargs):
            response = mock.Mock()
            response.json.return_value = {}
            if method == "GET" and path.endswith("/inbox/childFolders"):
                response.json.return_value = {"value": [{"id": "REQ"}]}
            elif method == "GET" and path.endswith("/mailFolders") and "Requests" in kwargs["params"]["$filter"]:
                response.json.return_value = {"value": []}
            elif method == "GET" and path == "/users/cs@example.invalid/mailFolders/REQ/messages":
                response.json.return_value = {"value": [message]}
            elif method == "GET" and path.endswith("/mailFolders"):
                response.json.return_value = {"value": [{"id": "PROCESSED"}]}
            elif method == "GET" and "/mailFolders/inbox/messages" in path:
                response.json.return_value = {"value": []}
            return response

        with mock.patch.object(graph, "call", side_effect=fake):
            self.assertEqual(graph_inbox.poll(), (1, 0))
        self.assertEqual(Ticket.objects.get(subject="Bins full").category.department, CLEANING)


# ---------------------------------------------------------------------------
# Removing a pasted password or a file
# ---------------------------------------------------------------------------
@override_settings(IT_NOTIFY_EMAIL="it-team@example.invalid")
class RemovalTests(GoLiveTestCase):
    SECRET = "Summer2024!xyz"

    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester, subject=f"VPN {self.SECRET}",
                                  description=f"It fails. My password is {self.SECRET} if needed.",
                                  files=[upload("passwords.txt", b"secret", "text/plain")])
        self.url = reverse("tickets:remove", args=[self.ticket.number])

    def test_admins_only(self):
        for user in (self.requester, self.agent):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url, {"part": "description"}).status_code, 403)

    def test_removing_text_from_the_request_and_its_email_copies(self):
        self.assertTrue(OutboundEmail.objects.filter(body_text__contains=self.SECRET).exists())
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url, {"part": "description"}), "Remove a password or file")
        response = self.client.post(self.url, {"part": "description", "text": self.SECRET})
        self.assertRedirects(response, self.ticket.get_absolute_url(), fetch_redirect_response=False)
        self.ticket.refresh_from_db()
        self.assertNotIn(self.SECRET, self.ticket.description)
        self.assertIn("[removed by IT]", self.ticket.description)
        for row in OutboundEmail.objects.all():
            self.assertNotIn(self.SECRET, row.body_text)
            self.assertNotIn(self.SECRET, row.body_html)
        event = self.ticket.events.get(kind=TicketEvent.Kind.REMOVED)
        self.assertEqual(event.actor, self.admin)
        self.assertNotIn(self.SECRET, event.new_value + event.note)

    def test_removing_from_the_subject(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, {"part": "subject", "text": self.SECRET})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.subject, "VPN [removed by IT]")
        self.assertFalse(OutboundEmail.objects.filter(subject__contains=self.SECRET).exists())

    def test_text_that_isnt_there(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {"part": "description", "text": "not in it"})
        self.assertContains(response, "That text isn", status_code=400)

    def test_removing_a_whole_reply_and_a_file(self):
        reply = services.add_comment(ticket=self.ticket, author=self.requester, body=f"Try {self.SECRET}",
                                     files=[upload("screenshot.png")])
        self.client.force_login(self.admin)
        attachment = reply.attachments.get()
        stored = Path(attachment.file.path)
        self.client.post(self.url, {"part": f"c{reply.pk}", "whole": "on", "remove_files": [str(attachment.pk)]})
        reply.refresh_from_db()
        self.assertEqual(reply.body, services.REMOVED_MESSAGE)
        self.assertFalse(reply.attachments.exists())
        self.assertFalse(stored.exists())
        self.assertIn("1 file", self.ticket.events.get(kind=TicketEvent.Kind.REMOVED).new_value)

    def test_removing_the_requests_file(self):
        attachment = self.ticket.attachments.get()
        self.client.force_login(self.admin)
        self.client.post(self.url, {"part": "description", "remove_files": [str(attachment.pk)]})
        self.assertFalse(self.ticket.attachments.exists())
        self.assertFalse(Comment.objects.exists())

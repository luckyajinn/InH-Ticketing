from django.test import override_settings
from django.urls import reverse

from tickets import services
from tickets.models import Category, Comment, Ticket
from tickets.tests.helpers import MediaTestCase, make_ticket, upload

Status = Ticket.Status
SECRET_NOTE = "Re-enrolment fixed both. Do not tell the requester yet."


class PrivacyTests(MediaTestCase):
    """The most important tests: what requesters must never see."""

    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester, subject="Outlook keeps prompting")
        services.add_comment(ticket=self.ticket, author=self.agent, body="Can you restart Outlook?")
        self.note = services.add_comment(
            ticket=self.ticket, author=self.agent, body=SECRET_NOTE, is_internal=True,
            files=[upload("internal-diagnostics.txt", b"secret", "text/plain")],
        )
        services.update_ticket(ticket=self.ticket, actor=self.agent, priority=Ticket.Priority.HIGH)
        self.url = self.ticket.get_absolute_url()

    def test_requester_sees_public_replies_only(self):
        self.client.force_login(self.requester)
        response = self.client.get(self.url)
        self.assertContains(response, "Can you restart Outlook?")
        self.assertNotContains(response, SECRET_NOTE)
        self.assertNotContains(response, "internal-diagnostics.txt")
        self.assertNotContains(response, "Internal note")
        self.assertNotContains(response, "History:")  # no events
        self.assertNotContains(response, "Priority")  # requesters never see priority

    def test_agent_sees_everything(self):
        self.client.force_login(self.agent)
        response = self.client.get(self.url)
        self.assertContains(response, SECRET_NOTE)
        self.assertContains(response, "Internal note: not visible to requester")
        self.assertContains(response, "internal-diagnostics.txt")
        self.assertContains(response, "History:")

    def test_other_requester_gets_404(self):
        self.client.force_login(self.other_requester)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_internal_attachment_is_404_for_requester(self):
        attachment = self.note.attachments.get()
        self.client.force_login(self.requester)
        self.assertEqual(self.client.get(attachment.get_absolute_url()).status_code, 404)
        self.client.force_login(self.agent)
        response = self.client.get(attachment.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response["Content-Disposition"])

    def test_public_attachment_download(self):
        ticket = make_ticket(self.requester, files=[upload("screen.png")])
        attachment = ticket.attachments.get()
        self.client.force_login(self.requester)
        response = self.client.get(attachment.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"fake image bytes")
        self.client.force_login(self.other_requester)
        self.assertEqual(self.client.get(attachment.get_absolute_url()).status_code, 404)

    def test_requester_list_ignores_internal_activity(self):
        older = make_ticket(self.requester, subject="Older ticket")
        Ticket.objects.filter(pk=older.pk).update(created_at=self.ticket.created_at.replace(year=2020))
        services.add_comment(ticket=older, author=self.agent, body="private", is_internal=True)
        self.client.force_login(self.requester)
        response = self.client.get(reverse("tickets:mine"))
        page = list(response.context["page"])
        # An internal note on the older ticket must not bump it to the top.
        self.assertEqual(page[0].pk, self.ticket.pk)

    def test_requester_cannot_reach_queue(self):
        self.client.force_login(self.requester)
        self.assertEqual(self.client.get(reverse("tickets:queue")).status_code, 403)

    def test_html_is_escaped(self):
        ticket = make_ticket(self.requester, subject="<script>alert(1)</script>")
        self.client.force_login(self.requester)
        response = self.client.get(ticket.get_absolute_url())
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")


class HomeTests(MediaTestCase):
    def test_agents_land_on_queue_requesters_on_their_tickets(self):
        self.client.force_login(self.agent)
        self.assertRedirects(self.client.get("/"), reverse("tickets:queue"))
        self.client.force_login(self.requester)
        self.assertRedirects(self.client.get("/"), reverse("tickets:mine"))


class NewTicketViewTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.requester)
        self.hardware = Category.objects.get(name="Hardware")

    def _post(self, **overrides):
        data = {"subject": "Monitor flickers", "category": self.hardware.pk,
                "description": "Flickers when cold.", **overrides}
        return self.client.post(reverse("tickets:new"), data)

    def test_creates_ticket_with_attachment(self):
        response = self._post(is_blocking="on", attachments=[upload("flicker.jpg")])
        ticket = Ticket.objects.get()
        self.assertRedirects(response, ticket.get_absolute_url())
        self.assertEqual(ticket.requester, self.requester)
        self.assertTrue(ticket.is_blocking)
        self.assertEqual(ticket.attachments.get().original_name, "flicker.jpg")

    def test_missing_fields(self):
        response = self._post(subject="", description="")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Enter a subject.", status_code=400)
        self.assertFalse(Ticket.objects.exists())

    def test_rejects_unsafe_file_types(self):
        response = self._post(attachments=[upload("setup.exe", b"MZ", "application/octet-stream")])
        self.assertContains(response, "isn&#x27;t a file type we accept", status_code=400)
        self.assertFalse(Ticket.objects.exists())

    @override_settings(ATTACHMENT_MAX_BYTES=10)
    def test_rejects_large_files(self):
        response = self._post(attachments=[upload("big.png", b"x" * 11)])
        self.assertContains(response, "The limit is", status_code=400)

    def test_retired_category_not_offered(self):
        Category.objects.filter(name="Other").update(is_active=False)
        response = self.client.get(reverse("tickets:new"))
        self.assertNotContains(response, "Other:")


class ReplyViewTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester)
        self.url = reverse("tickets:reply", args=[self.ticket.number])

    def test_requester_reply(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.WAITING)
        self.client.force_login(self.requester)
        response = self.client.post(self.url, {"body": "Done that", "visibility": "public"})
        self.assertRedirects(response, self.ticket.get_absolute_url())
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.OPEN)

    def test_requester_cannot_post_internal_note(self):
        self.client.force_login(self.requester)
        response = self.client.post(self.url, {"body": "sneaky", "visibility": "internal"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Comment.objects.exists())

    def test_agent_internal_note(self):
        self.client.force_login(self.agent)
        self.client.post(self.url, {"body": "Checked the logs", "visibility": "internal"})
        comment = Comment.objects.get()
        self.assertTrue(comment.is_internal)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.NEW)

    def test_empty_reply(self):
        self.client.force_login(self.agent)
        response = self.client.post(self.url, {"body": "  ", "visibility": "public"})
        self.assertContains(response, "Write a message first.", status_code=400)

    def test_send_and_set_waiting(self):
        self.client.force_login(self.agent)
        response = self.client.post(self.url, {"body": "Which printer?", "visibility": "public",
                                               "then_status": "waiting"})
        self.assertRedirects(response, self.ticket.get_absolute_url())
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.WAITING)

    def test_send_and_resolve(self):
        self.client.force_login(self.agent)
        self.client.post(self.url, {"body": "Fixed", "visibility": "public", "then_status": "resolved"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.RESOLVED)
        self.assertIsNotNone(self.ticket.resolved_at)

    def test_status_buttons_need_a_public_reply(self):
        self.client.force_login(self.agent)
        response = self.client.post(self.url, {"body": "note", "visibility": "internal",
                                               "then_status": "resolved"})
        self.assertEqual(response.status_code, 400)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.NEW)
        self.assertFalse(Comment.objects.exists())

    def test_requester_cannot_use_status_buttons(self):
        self.client.force_login(self.requester)
        response = self.client.post(self.url, {"body": "done", "then_status": "resolved"})
        self.assertEqual(response.status_code, 400)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.NEW)

    def test_status_buttons_shown_to_it(self):
        self.client.force_login(self.agent)
        response = self.client.get(self.ticket.get_absolute_url())
        self.assertContains(response, "Send and set Waiting on User")
        self.assertContains(response, "Send and resolve")

    def test_requester_cannot_reply_to_closed(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Status.CLOSED)
        self.client.force_login(self.requester)
        self.client.post(self.url, {"body": "Hello?"})
        self.assertFalse(Comment.objects.exists())


class PropertiesViewTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester)
        self.url = reverse("tickets:update", args=[self.ticket.number])
        self.data = {
            "status": Status.IN_PROGRESS, "priority": Ticket.Priority.HIGH,
            "assignee": self.agent2.pk, "category": self.ticket.category_id,
        }

    def test_agent_updates(self):
        self.client.force_login(self.agent)
        response = self.client.post(self.url, self.data)
        self.assertRedirects(response, self.ticket.get_absolute_url())
        self.ticket.refresh_from_db()
        self.assertEqual(
            (self.ticket.status, self.ticket.priority, self.ticket.assignee),
            (Status.IN_PROGRESS, Ticket.Priority.HIGH, self.agent2),
        )

    def test_requester_forbidden(self):
        self.client.force_login(self.requester)
        self.assertEqual(self.client.post(self.url, self.data).status_code, 403)

    def test_cannot_assign_to_a_requester(self):
        self.client.force_login(self.agent)
        response = self.client.post(self.url, {**self.data, "assignee": self.requester.pk})
        self.assertEqual(response.status_code, 400)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assignee)

    def test_assign_to_me(self):
        self.client.force_login(self.agent)
        self.client.post(reverse("tickets:assign_to_me", args=[self.ticket.number]))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assignee, self.agent)
        self.assertEqual(self.ticket.status, Status.OPEN)


class RequesterActionViewTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester)

    def test_resolve_and_reopen(self):
        self.client.force_login(self.requester)
        self.client.post(reverse("tickets:resolve", args=[self.ticket.number]))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.RESOLVED)
        response = self.client.get(self.ticket.get_absolute_url())
        self.assertContains(response, "This is still a problem")

        response = self.client.post(reverse("tickets:reopen", args=[self.ticket.number]))
        self.assertRedirects(
            response, self.ticket.get_absolute_url() + "?reopened=1#reply", fetch_redirect_response=False
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.OPEN)

    def test_other_requester_cannot_resolve(self):
        self.client.force_login(self.other_requester)
        response = self.client.post(reverse("tickets:resolve", args=[self.ticket.number]))
        self.assertEqual(response.status_code, 404)


class QueueViewTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.low = make_ticket(self.requester, subject="Mouse squeaks")
        services.update_ticket(ticket=self.low, actor=self.agent, priority=Ticket.Priority.LOW)
        self.urgent = make_ticket(self.other_requester, subject="Server room is hot")
        services.update_ticket(ticket=self.urgent, actor=self.agent, priority=Ticket.Priority.URGENT,
                               assignee=self.agent)
        self.waiting = make_ticket(self.requester, subject="Need approval",
                                   category=Category.objects.get(name="Access"))
        services.update_ticket(ticket=self.waiting, actor=self.agent, status=Status.WAITING)
        self.done = make_ticket(self.requester, subject="Old problem")
        services.update_ticket(ticket=self.done, actor=self.agent, status=Status.RESOLVED)
        self.client.force_login(self.agent)

    def _subjects(self, **params):
        response = self.client.get(reverse("tickets:queue"), params)
        self.assertEqual(response.status_code, 200)
        return [t.subject for t in response.context["page"]]

    def test_all_open_sorted_by_priority(self):
        self.assertEqual(self._subjects(), ["Server room is hot", "Need approval", "Mouse squeaks"])

    def test_views(self):
        self.assertEqual(self._subjects(view="mine"), ["Server room is hot"])
        self.assertEqual(set(self._subjects(view="unassigned")), {"Mouse squeaks", "Need approval"})
        self.assertEqual(self._subjects(view="waiting"), ["Need approval"])
        self.assertEqual(self._subjects(view="resolved"), ["Old problem"])

    def test_counts(self):
        response = self.client.get(reverse("tickets:queue"))
        counts = {v["id"]: v["count"] for v in response.context["views"]}
        self.assertEqual(counts, {"unassigned": 2, "mine": 1, "open": 3, "waiting": 1, "resolved": 1})

    def test_search_and_filters(self):
        self.assertEqual(self._subjects(q=f"#{self.urgent.number}"), ["Server room is hot"])
        self.assertEqual(self._subjects(q="tom reyes"), ["Server room is hot"])
        access = Category.objects.get(name="Access")
        self.assertEqual(self._subjects(category=access.pk), ["Need approval"])
        self.assertEqual(self._subjects(priority=Ticket.Priority.LOW), ["Mouse squeaks"])

    def test_bad_filter_values_are_ignored(self):
        self.assertEqual(len(self._subjects(view="nope", category="x", priority="'; DROP")), 3)

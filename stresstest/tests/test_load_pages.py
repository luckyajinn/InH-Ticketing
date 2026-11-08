"""
The load generator reads the app's pages (stress/pages.py) to find tickets,
categories, files and the IT side panel. These tests run those readers against
the real pages, and send the forms the way the load generator does, so a
template change breaks a test instead of quietly emptying the load test.
STRESS-TEST BRANCH ONLY.
"""

from tickets import services
from tickets.models import Category, Ticket
from tickets.tests.helpers import MediaTestCase, make_ticket, upload
from stresstest.tests.helpers import load_stress_module

pages = load_stress_module("pages")


class LoadGeneratorPageTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester, subject="Laptop fan is loud", files=[upload()])
        services.update_ticket(ticket=self.ticket, actor=self.agent, assignee=self.agent,
                               priority=Ticket.Priority.HIGH)
        self.number = str(self.ticket.number)

    def test_finds_tickets_in_the_queue_and_my_tickets(self):
        self.client.force_login(self.agent)
        self.assertIn(self.number, pages.ticket_numbers(self.client.get("/queue/?view=open").content.decode()))
        self.client.force_login(self.requester)
        self.assertEqual(pages.ticket_numbers(self.client.get("/tickets/").content.decode()), [self.number])

    def test_finds_the_categories_on_the_new_request_form(self):
        self.client.force_login(self.requester)
        html = self.client.get("/tickets/new/").content.decode()
        expected = [str(pk) for pk in Category.objects.filter(is_active=True).values_list("pk", flat=True)]
        self.assertEqual(sorted(pages.options(html, "category")), sorted(expected))

    def test_new_request_redirect_names_the_new_ticket(self):
        self.client.force_login(self.requester)
        category = Category.objects.filter(is_active=True).first()
        response = self.client.post("/tickets/new/", {
            "subject": "Stress test", "category": category.pk, "description": "Fake.", "is_blocking": "",
            "attachments": upload("photo-1234.jpg", b"\xff\xd8 fake jpeg", "image/jpeg"),
        })
        self.assertEqual(response.status_code, 302)
        number = pages.ticket_from_location(response["Location"])
        self.assertEqual(Ticket.objects.get(pk=Ticket.pk_from_number(int(number))).attachments.count(), 1)

    def test_finds_attachment_links_that_download(self):
        for user in (self.requester, self.agent):
            self.client.force_login(user)
            links = pages.attachment_links(self.client.get(f"/tickets/{self.number}/").content.decode())
            self.assertEqual(len(links), 1)
            self.assertEqual(self.client.get(links[0]).status_code, 200)

    def test_reads_the_side_panel_and_its_form_is_accepted(self):
        self.client.force_login(self.agent)
        html = self.client.get(f"/tickets/{self.number}/").content.decode()
        panel = pages.side_panel(html)
        self.assertEqual(panel, {
            "status": self.ticket.status, "priority": str(Ticket.Priority.HIGH),
            "assignee": str(self.agent.pk), "category": str(self.ticket.category_id),
        })
        panel["priority"] = str(Ticket.Priority.URGENT)
        response = self.client.post(f"/tickets/{self.number}/update/", panel)
        self.assertEqual(response.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.priority, Ticket.Priority.URGENT)
        self.assertEqual(self.ticket.assignee, self.agent)

    def test_side_panel_of_an_unassigned_ticket(self):
        unassigned = make_ticket(self.other_requester)
        self.client.force_login(self.agent)
        panel = pages.side_panel(self.client.get(unassigned.get_absolute_url()).content.decode())
        self.assertEqual(panel["assignee"], "")
        self.assertEqual(self.client.post(f"{unassigned.get_absolute_url()}update/", panel).status_code, 302)

    def test_requesters_have_no_side_panel(self):
        self.client.force_login(self.requester)
        self.assertIsNone(pages.side_panel(self.client.get(f"/tickets/{self.number}/").content.decode()))

    def test_the_forms_the_load_generator_sends_are_accepted(self):
        self.client.force_login(self.agent)
        for data in (
            {"body": "Reply", "visibility": "public", "then_status": ""},
            {"body": "Reply", "visibility": "public", "then_status": "waiting"},
            {"body": "Reply", "visibility": "public", "then_status": "resolved"},
            {"body": "Note", "visibility": "internal", "attachments": upload("log.pdf", b"%PDF", "application/pdf")},
        ):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(f"/tickets/{self.number}/reply/", data).status_code, 302)
        self.assertEqual(self.client.post(f"/tickets/{self.number}/assign-to-me/", {}).status_code, 302)

        self.client.force_login(self.requester)
        self.assertEqual(self.client.post(f"/tickets/{self.number}/reply/",
                                          {"body": "Still broken", "visibility": "public"}).status_code, 302)
        self.assertEqual(self.client.post(f"/tickets/{self.number}/resolve/", {}).status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.RESOLVED)

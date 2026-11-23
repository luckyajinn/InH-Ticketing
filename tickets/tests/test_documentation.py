"""
A ticket's documentation: the staff write-up (troubleshooting, steps taken,
solution, other problems found). Only staff working the ticket write it; the
requester never sees it, and it stays out of the timeline, history and emails.
"""

from django.core.exceptions import PermissionDenied
from django.urls import reverse

from accounts.models import User
from notifications.models import OutboundEmail
from tickets import services
from tickets.models import TEXT_MAX_CHARS, Category, Department, PasswordWarning, Ticket, TicketDocumentation, TicketEvent
from tickets.tests.helpers import MediaTestCase, make_ticket, make_user

SECRET_FIX = "Rebuilt the print spooler and cleared the stuck queue on PRN-04."


class DocumentationTestCase(MediaTestCase):
    def setUp(self):
        super().setUp()
        Department.objects.create(key="plumbing", name="Plumbing", entra_role="Agent.Plumbing")
        self.pipes = Category.objects.create(name="Pipes", department="plumbing")
        self.plumber = make_user("Pat Plumber", User.Role.AGENT)
        User.objects.filter(pk=self.plumber.pk).update(department="plumbing")
        self.plumber.refresh_from_db()
        self.admin = make_user("Ada Admin", User.Role.ADMIN)
        self.ticket = make_ticket(self.requester)  # Hardware: IT's
        self.url = reverse("tickets:documentation", args=[self.ticket.number])

    def post(self, user, ticket=None, **data):
        self.client.force_login(user)
        url = reverse("tickets:documentation", args=[ticket.number]) if ticket else self.url
        return self.client.post(url, data)


class SavingTests(DocumentationTestCase):
    def test_agent_creates_then_updates(self):
        response = self.post(self.agent, troubleshooting="Queue stuck.", solution=SECRET_FIX)
        self.assertRedirects(response, self.ticket.get_absolute_url() + "#documentation",
                             fetch_redirect_response=False)
        doc = TicketDocumentation.objects.get(ticket=self.ticket)
        self.assertEqual((doc.troubleshooting, doc.steps_taken, doc.solution, doc.other_problems),
                         ("Queue stuck.", "", SECRET_FIX, ""))
        self.assertEqual((doc.department, doc.created_by, doc.updated_by), ("it", self.agent, self.agent))

        self.post(self.agent2, troubleshooting="Queue stuck.", solution=SECRET_FIX,
                  steps_taken="Restarted the spooler.", other_problems="Toner low: replaced it.")
        doc.refresh_from_db()
        self.assertEqual(TicketDocumentation.objects.count(), 1)
        self.assertEqual(doc.steps_taken, "Restarted the spooler.")
        self.assertEqual(doc.other_problems, "Toner low: replaced it.")
        self.assertEqual((doc.created_by, doc.updated_by), (self.agent, self.agent2))

    def test_nothing_changed_writes_nothing(self):
        self.assertTrue(services.save_documentation(ticket=self.ticket, actor=self.agent, data={"solution": "Fixed."}))
        before = TicketDocumentation.objects.get().updated_at
        self.assertFalse(services.save_documentation(ticket=self.ticket, actor=self.agent2, data={"solution": " Fixed. "}))
        doc = TicketDocumentation.objects.get()
        self.assertEqual((doc.updated_at, doc.updated_by), (before, self.agent))

    def test_an_empty_form_creates_no_row(self):
        self.assertFalse(services.save_documentation(ticket=self.ticket, actor=self.agent, data={}))
        self.post(self.agent)
        self.assertFalse(TicketDocumentation.objects.exists())

    def test_admin_can_save_any_departments(self):
        pipes = make_ticket(self.requester, subject="Tap drips", category=self.pipes)
        self.post(self.admin, ticket=pipes, solution="New washer.")
        doc = TicketDocumentation.objects.get(ticket=pipes)
        self.assertEqual((doc.department, doc.updated_by), ("plumbing", self.admin))

    def test_department_follows_the_ticket(self):
        services.save_documentation(ticket=self.ticket, actor=self.agent, data={"solution": "Fixed."})
        services.move_ticket(ticket=self.ticket, actor=self.admin, category=self.pipes)
        services.save_documentation(ticket=self.ticket, actor=self.plumber, data={"solution": "Fixed again."})
        self.assertEqual(TicketDocumentation.objects.get().department, "plumbing")

    def test_too_long_is_a_400(self):
        response = self.post(self.agent, solution="x" * (TEXT_MAX_CHARS + 1))
        self.assertContains(response, "over the", status_code=400)
        self.assertFalse(TicketDocumentation.objects.exists())

    def test_get_is_not_allowed(self):
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(self.url).status_code, 405)


class WhoCanTests(DocumentationTestCase):
    def test_agent_of_another_department_cannot(self):
        response = self.post(self.plumber, solution=SECRET_FIX)
        self.assertIn(response.status_code, (403, 404))
        self.assertFalse(TicketDocumentation.objects.exists())
        with self.assertRaises(PermissionDenied):
            services.save_documentation(ticket=self.ticket, actor=self.plumber, data={"solution": SECRET_FIX})

    def test_requester_gets_403(self):
        self.assertEqual(self.post(self.requester, solution=SECRET_FIX).status_code, 403)
        self.assertFalse(TicketDocumentation.objects.exists())

    def test_requester_never_sees_it(self):
        services.save_documentation(ticket=self.ticket, actor=self.agent, data={"solution": SECRET_FIX})
        self.client.force_login(self.requester)
        page = self.client.get(self.ticket.get_absolute_url())
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, SECRET_FIX)
        self.assertNotContains(page, "Documentation")
        self.assertNotIn("documentation_form", page.context)

    def test_requester_who_is_an_agent_elsewhere(self):
        """An IT agent's own plumbing request: they see it as a requester, without the write-up."""
        pipes = make_ticket(self.agent, subject="Tap drips", category=self.pipes)
        services.save_documentation(ticket=pipes, actor=self.plumber, data={"solution": SECRET_FIX})
        self.client.force_login(self.agent)
        page = self.client.get(pipes.get_absolute_url())
        self.assertTemplateUsed(page, "tickets/detail_requester.html")
        self.assertNotContains(page, SECRET_FIX)
        self.assertNotContains(page, "Documentation")
        self.assertEqual(self.post(self.agent, ticket=pipes, solution="Mine now").status_code, 403)
        self.assertEqual(TicketDocumentation.objects.get().solution, SECRET_FIX)

    def test_archived_ticket_refuses(self):
        services.save_documentation(ticket=self.ticket, actor=self.agent, data={"solution": SECRET_FIX})
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Ticket.Status.CLOSED)
        response = self.post(self.agent, solution="Changed after closing")
        self.assertRedirects(response, self.ticket.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(TicketDocumentation.objects.get().solution, SECRET_FIX)
        with self.assertRaisesMessage(PermissionDenied, services.ARCHIVED):
            services.save_documentation(ticket=self.ticket, actor=self.agent, data={"solution": "x"})
        page = self.client.get(self.ticket.get_absolute_url())
        self.assertContains(page, SECRET_FIX)  # still readable
        self.assertContains(page, "Read-only: the ticket is archived.")
        self.assertNotContains(page, reverse("tickets:documentation", args=[self.ticket.number]))


class KeptOutTests(DocumentationTestCase):
    """Not in the timeline, the history or any email."""

    def test_no_history_line_and_no_email(self):
        events, emails = TicketEvent.objects.count(), OutboundEmail.objects.count()
        self.post(self.agent, troubleshooting=SECRET_FIX, solution=SECRET_FIX)
        self.assertEqual(TicketEvent.objects.count(), events)
        self.assertEqual(OutboundEmail.objects.count(), emails)
        # Later activity that does email people doesn't carry it either.
        services.add_comment(ticket=self.ticket, author=self.agent, body="Fixed now.", then_status="resolved")
        for email in OutboundEmail.objects.all():
            self.assertNotIn(SECRET_FIX, email.subject + email.body_text + email.body_html)
        self.assertFalse(TicketEvent.objects.filter(new_value__contains="Rebuilt").exists())

    def test_not_in_the_timeline(self):
        self.post(self.agent, solution=SECRET_FIX)
        self.client.force_login(self.agent)
        page = self.client.get(self.ticket.get_absolute_url())
        self.assertContains(page, SECRET_FIX, count=1)  # in its own box only
        for item in page.context["timeline"]:
            text = item.comment.body if item.comment else f"{item.event.old_value} {item.event.new_value} {item.event.note}"
            self.assertNotIn(SECRET_FIX, text)

    def test_html_is_escaped_on_the_ticket_page(self):
        xss = '<script>alert("doc")</script>'
        services.save_documentation(ticket=self.ticket, actor=self.agent, data={"solution": xss})
        services.update_ticket(ticket=self.ticket, actor=self.agent, status=Ticket.Status.CLOSED)
        unarchived = make_ticket(self.requester, subject="Second")
        services.save_documentation(ticket=unarchived, actor=self.agent, data={"steps_taken": xss})
        self.client.force_login(self.agent)
        for ticket in (self.ticket, unarchived):  # read-only and in the form
            with self.subTest(archived=ticket.is_archived):
                page = self.client.get(ticket.get_absolute_url())
                self.assertNotContains(page, xss)
                self.assertContains(page, "&lt;script&gt;")


class PageTests(DocumentationTestCase):
    def test_agent_sees_the_form_filled_in(self):
        self.client.force_login(self.agent)
        page = self.client.get(self.ticket.get_absolute_url())
        self.assertContains(page, "Not shown to the requester. Admins read it in Reports.")
        self.assertContains(page, "Nothing written yet")
        self.assertContains(page, 'id="password-ack"')
        self.assertContains(page, 'id="doc-password-ack"')
        services.save_documentation(ticket=self.ticket, actor=self.agent2, data={"solution": SECRET_FIX})
        page = self.client.get(self.ticket.get_absolute_url())
        self.assertContains(page, SECRET_FIX)
        self.assertContains(page, "Last updated by Alex Morgan")
        self.assertContains(page, '<details class="panel doc" id="documentation" open>')


class PasswordTests(DocumentationTestCase):
    def test_warned_then_sent_anyway(self):
        response = self.post(self.agent, steps_taken="Reset it. Temp password: ChangeMe!")
        self.assertContains(response, "This might include a password", status_code=400)
        self.assertContains(response, "In steps taken:", status_code=400)
        self.assertContains(response, '<details class="panel doc" id="documentation" open>', status_code=400)
        self.assertFalse(TicketDocumentation.objects.exists())

        self.post(self.agent, steps_taken="Reset it. Temp password: ChangeMe!", password_ack="on", password_warned="on")
        self.assertTrue(TicketDocumentation.objects.exists())
        warning = PasswordWarning.objects.get()
        self.assertEqual((warning.place, warning.outcome, warning.ticket, warning.fields),
                         (PasswordWarning.Place.DOCUMENTATION, PasswordWarning.Outcome.SENT_ANYWAY,
                          self.ticket, "steps_taken"))
        # The history notes where (never the text), as for a reply.
        event = TicketEvent.objects.get(kind=TicketEvent.Kind.PASSWORD)
        self.assertEqual(event.new_value, "the documentation")
        self.assertNotIn("ChangeMe", event.note)

    def test_warned_then_taken_out(self):
        self.post(self.agent, solution="Reset it and sent it by Teams.", password_warned="on")
        self.assertEqual(PasswordWarning.objects.get().outcome, PasswordWarning.Outcome.REMOVED)

    def test_the_browser_check_knows_the_boxes(self):
        self.client.force_login(self.agent)
        result = self.client.post(reverse("tickets:check_text"), {"other_problems": "pw: hunter2"}).json()
        self.assertTrue(result["found"])
        self.assertTrue(result["hints"][0].startswith("In other problems found:"))

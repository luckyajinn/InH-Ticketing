"""The Not found page's next steps, and opening a ticket by its number."""

from django.urls import reverse

from tickets.tests.helpers import MediaTestCase, make_ticket


class NotFoundPageTests(MediaTestCase):
    def get(self, user=None, path="/no-such-page/"):
        if user:
            self.client.force_login(user)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 404)
        return response

    def test_requester_gets_their_tickets_a_new_request_and_the_lookup(self):
        response = self.get(self.requester)
        self.assertContains(response, "We couldn't find that page", status_code=404)
        self.assertContains(response, f'href="{reverse("tickets:mine")}">Go to my tickets', status_code=404)
        self.assertContains(response, "New request", status_code=404)
        self.assertContains(response, f'action="{reverse("tickets:go")}"', status_code=404)
        self.assertNotContains(response, "Go to the queue", status_code=404)

    def test_it_gets_the_queue(self):
        response = self.get(self.agent)
        self.assertContains(response, f'href="{reverse("tickets:queue")}">Go to the queue', status_code=404)
        self.assertNotContains(response, "Go to my tickets", status_code=404)

    def test_signed_out_gets_sign_in_only(self):
        response = self.get()
        self.assertContains(response, reverse("accounts:signin"), status_code=404)
        self.assertNotContains(response, reverse("tickets:go"), status_code=404)

    def test_someone_elses_ticket_looks_the_same_as_a_missing_one(self):
        theirs = make_ticket(self.other_requester, subject="Payroll laptop for Tom")
        response = self.get(self.requester, theirs.get_absolute_url())
        self.assertContains(response, "We couldn't find that page", status_code=404)
        self.assertNotContains(response, "Payroll laptop", status_code=404)

    def test_title(self):
        self.assertContains(self.get(self.requester), "<title>Page not found · InH-Ticketing</title>", status_code=404)


class GoToTicketTests(MediaTestCase):
    url = reverse("tickets:go")

    def setUp(self):
        super().setUp()
        self.client.force_login(self.requester)

    def test_opens_the_number(self):
        for typed in ("1042", "#1042", "  # 1042 "):
            with self.subTest(typed=typed):
                response = self.client.get(self.url, {"number": typed})
                self.assertRedirects(response, "/tickets/1042/", fetch_redirect_response=False)

    def test_own_ticket_opens(self):
        ticket = make_ticket(self.requester)
        response = self.client.get(self.url, {"number": str(ticket.number)}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ticket.subject)

    def test_someone_elses_number_is_just_not_found(self):
        theirs = make_ticket(self.other_requester)
        response = self.client.get(self.url, {"number": str(theirs.number)}, follow=True)
        self.assertEqual(response.status_code, 404)

    def test_anything_else_says_what_to_type(self):
        for typed in ("", "abc", "10 42", "1234567890"):
            with self.subTest(typed=typed):
                response = self.client.get(self.url, {"number": typed}, follow=True)
                self.assertRedirects(response, reverse("tickets:mine"))
                self.assertContains(response, "Enter a ticket number, like 1042.")

    def test_needs_sign_in(self):
        self.client.logout()
        response = self.client.get(self.url, {"number": "1042"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:signin"), response["Location"])

    def test_get_only(self):
        self.assertEqual(self.client.post(self.url, {"number": "1042"}).status_code, 405)

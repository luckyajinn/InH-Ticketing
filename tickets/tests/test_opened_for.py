"""Staff opening a request for someone else, at the desk say (v0.10.6)."""

from django.core.exceptions import PermissionDenied
from django.test import override_settings
from django.urls import reverse

from accounts import people
from accounts.entra import sync_user
from accounts.models import User
from accounts.tests.helpers import claims
from notifications.models import OutboundEmail
from tickets import services
from tickets.examples import add_example_departments
from tickets.models import Category, Ticket, TicketEvent
from tickets.tests.helpers import MediaTestCase, make_ticket, make_user, upload


@override_settings(INBOUND_ALLOWED_DOMAINS=["example.invalid"], IT_NOTIFY_EMAIL="it-alerts@example.invalid")
class OpenForSomeoneElseTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("tickets:new")
        self.hardware = Category.objects.get(name="Hardware")
        self.admin = make_user("Ada Admin", User.Role.ADMIN)

    def post(self, **data):
        data.setdefault("subject", "Laptop won't charge")
        data.setdefault("description", "Came to the desk: the charger light stays off.")
        data.setdefault("category", self.hardware.pk)
        return self.client.post(self.url, data)

    def test_requesters_dont_get_the_choice(self):
        self.client.force_login(self.requester)
        self.assertNotContains(self.client.get(self.url), "Who is it for?")
        # Sending it anyway changes nothing: the request is theirs.
        self.post(for_whom="other", for_email=self.other_requester.email)
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.requester, self.requester)
        self.assertIsNone(ticket.opened_by)

    def test_staff_get_the_choice(self):
        self.client.force_login(self.agent)
        page = self.client.get(self.url)
        self.assertContains(page, "Who is it for?")
        self.assertContains(page, 'id="for-me" value="me" checked')

    def test_for_someone_the_app_knows(self):
        self.client.force_login(self.agent)
        response = self.client.post(self.url, {
            "subject": "Laptop won't charge", "description": "The charger light stays off.",
            "category": self.hardware.pk, "for_whom": "other", "for_email": self.requester.email.upper(),
            "attachments": [upload()],
        })
        ticket = Ticket.objects.get()
        self.assertRedirects(response, ticket.get_absolute_url())
        self.assertEqual(ticket.requester, self.requester)
        self.assertEqual(ticket.opened_by, self.agent)
        self.assertEqual(ticket.attachments.get().uploaded_by, self.agent)
        event = ticket.events.get(kind=TicketEvent.Kind.OPENED_FOR)
        self.assertEqual((event.actor, event.new_value), (self.agent, "Dana Whitfield"))

        receipt = OutboundEmail.objects.get(kind="received")
        self.assertEqual(receipt.to, self.requester.email)
        self.assertIn("Sam Patel opened request #", receipt.body_text)
        alert = OutboundEmail.objects.get(kind="new_ticket")
        self.assertIn("New request for Dana Whitfield", alert.body_text)
        self.assertIn("Opened by Sam Patel", alert.body_text)

        page = self.client.get(ticket.get_absolute_url())
        self.assertContains(page, "Opened by Sam Patel for Dana Whitfield")
        self.assertContains(page, "opened this</strong> for Dana Whitfield")

        # It's theirs: in My tickets, and their page says who opened it.
        self.client.force_login(self.requester)
        self.assertContains(self.client.get(reverse("tickets:mine")), "Laptop won&#x27;t charge")
        page = self.client.get(ticket.get_absolute_url())
        self.assertContains(page, "for you by Sam Patel")
        self.assertContains(page, "Opened for you by Sam Patel")

    def test_for_someone_new(self):
        self.client.force_login(self.agent)
        self.post(for_whom="other", for_email="Jo.Banks@Example.invalid", for_name="  Jo   Banks ")
        ticket = Ticket.objects.get()
        jo = ticket.requester
        self.assertEqual((jo.email, jo.display_name, jo.role), ("jo.banks@example.invalid", "Jo Banks", User.Role.REQUESTER))
        self.assertIsNone(jo.entra_oid)
        self.assertTrue(OutboundEmail.objects.filter(kind="received", to="jo.banks@example.invalid").exists())
        # Their first sign-in links the account, so the ticket follows them.
        signed_in = sync_user(claims(name="Jo Banks", preferred_username="jo.banks@example.invalid"))
        self.assertEqual(signed_in.pk, jo.pk)
        self.assertIsNotNone(User.objects.get(pk=jo.pk).entra_oid)

    def test_someone_new_needs_a_name(self):
        self.client.force_login(self.agent)
        response = self.post(for_whom="other", for_email="jo.banks@example.invalid")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Enter their name", status_code=400)
        self.assertFalse(Ticket.objects.exists())
        self.assertIsNone(people.by_email("jo.banks@example.invalid"))

    def test_only_work_addresses(self):
        self.client.force_login(self.agent)
        response = self.post(for_whom="other", for_email="jo@gmail.com", for_name="Jo Banks")
        self.assertContains(response, "Use their work email: an address ending in @example.invalid", status_code=400)
        self.assertFalse(Ticket.objects.exists())
        self.assertIsNone(people.by_email("jo@gmail.com"))

    def test_an_email_is_needed(self):
        self.client.force_login(self.agent)
        response = self.post(for_whom="other", for_email="  ")
        self.assertContains(response, "Enter their work email", status_code=400)
        self.assertFalse(Ticket.objects.exists())

    def test_not_for_a_turned_off_account(self):
        User.objects.filter(pk=self.requester.pk).update(is_active=False)
        self.client.force_login(self.agent)
        response = self.post(for_whom="other", for_email=self.requester.email)
        self.assertContains(response, "account is turned off", status_code=400)
        self.assertFalse(Ticket.objects.exists())

    def test_their_own_email_is_a_request_for_themselves(self):
        self.client.force_login(self.agent)
        self.post(for_whom="other", for_email=self.agent.email)
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.requester, self.agent)
        self.assertIsNone(ticket.opened_by)
        self.assertFalse(ticket.events.filter(kind=TicketEvent.Kind.OPENED_FOR).exists())

    def test_me_ignores_the_other_fields(self):
        self.client.force_login(self.agent)
        self.post(for_whom="me", for_email=self.requester.email)
        self.assertEqual(Ticket.objects.get().requester, self.agent)

    def test_staff_open_only_their_own_departments_for_someone(self):
        mechanics = add_example_departments()["mechanics"]
        self.client.force_login(self.agent)
        response = self.post(for_whom="other", for_email=self.requester.email, category=mechanics.pk)
        self.assertContains(response, "choose one of IT&#x27;s categories", status_code=400)
        self.assertFalse(Ticket.objects.exists())
        # For themselves, any team's, as before.
        self.post(category=mechanics.pk)
        self.assertEqual(Ticket.objects.get().requester, self.agent)

    def test_admins_open_any_departments_for_someone(self):
        mechanics = add_example_departments()["mechanics"]
        self.client.force_login(self.admin)
        self.post(for_whom="other", for_email=self.requester.email, category=mechanics.pk)
        ticket = Ticket.objects.get()
        self.assertEqual((ticket.requester, ticket.opened_by, ticket.category), (self.requester, self.admin, mechanics))

    def test_a_follow_up_is_for_the_same_person(self):
        original = make_ticket(self.requester)
        self.client.force_login(self.agent)
        page = self.client.get(self.url, {"follow_up": original.number})
        self.assertContains(page, 'id="for-other" value="other" checked')
        self.assertContains(page, f'value="{self.requester.email}"')

    def test_the_service_checks_too(self):
        with self.assertRaises(PermissionDenied):
            services.create_ticket(requester=self.requester, subject="x", description="y",
                                   category=self.hardware, opened_by=self.other_requester)
        mechanics = add_example_departments()["mechanics"]
        with self.assertRaises(PermissionDenied):
            services.create_ticket(requester=self.requester, subject="x", description="y",
                                   category=mechanics, opened_by=self.agent)
        self.assertFalse(Ticket.objects.exists())


class FindPeopleTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("tickets:find_people")

    def find(self, text):
        return self.client.get(self.url, {"q": text})

    def test_staff_only(self):
        self.client.force_login(self.requester)
        self.assertEqual(self.find("dana").status_code, 403)
        self.client.logout()
        self.assertEqual(self.find("dana").status_code, 302)

    def test_by_name_or_email_with_every_word(self):
        self.client.force_login(self.agent)
        self.assertEqual(self.find("dana").json(), {"people": [{"name": "Dana Whitfield", "email": self.requester.email}]})
        self.assertEqual([p["name"] for p in self.find("whit DAN").json()["people"]], ["Dana Whitfield"])
        self.assertEqual([p["name"] for p in self.find("tom.reyes@").json()["people"]], ["Tom Reyes"])
        self.assertEqual(self.find("dana tom").json()["people"], [])

    def test_never_everyone(self):
        self.client.force_login(self.agent)
        self.assertEqual(self.find("a").json()["people"], [])
        self.assertEqual(self.find("   ").json()["people"], [])
        for i in range(12):
            make_user(f"Casey Example{i}")
        self.assertEqual(len(self.find("casey").json()["people"]), people.SEARCH_LIMIT)

    def test_not_turned_off_accounts(self):
        User.objects.filter(pk=self.requester.pk).update(is_active=False)
        self.client.force_login(self.agent)
        self.assertEqual(self.find("dana").json()["people"], [])

    def test_not_cached(self):
        self.client.force_login(self.agent)
        self.assertIn("no-store", self.find("dana")["Cache-Control"])

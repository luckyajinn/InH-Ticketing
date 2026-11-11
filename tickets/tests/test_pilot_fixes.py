"""v0.8.3: fixes found in the pre-pilot review on 2026-11-10."""

from django.urls import reverse

from accounts.models import User
from tickets import services
from tickets.examples import add_example_departments
from tickets.models import Category, Ticket
from tickets.tests.helpers import MediaTestCase, make_ticket


class SidePanelTests(MediaTestCase):
    """The panel only applies fields the person changed, not what an old page still showed."""

    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester)  # New, Normal, Hardware, unassigned
        self.url = reverse("tickets:update", args=[self.ticket.number])
        self.hardware = Category.objects.get(name="Hardware")

    def shown(self, **values):
        """What a page loaded before any of the changes below would send back."""
        data = {
            "status": "new", "priority": 2, "assignee": "", "category": self.hardware.pk,
            "shown_status": "new", "shown_priority": "2", "shown_assignee": "", "shown_category": str(self.hardware.pk),
        }
        data.update(values)
        return data

    def test_an_old_page_doesnt_undo_someone_elses_assignment(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent2, assignee=self.agent2)  # now Open, Alex
        self.client.force_login(self.agent)
        self.client.post(self.url, self.shown(priority=3))  # Sam only changed the priority
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.priority, 3)
        self.assertEqual(self.ticket.assignee, self.agent2)
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)

    def test_an_old_page_doesnt_reopen_a_resolved_ticket(self):
        services.resolve_by_requester(ticket=self.ticket, user=self.requester)
        self.client.force_login(self.agent)
        self.client.post(self.url, self.shown(priority=3))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.RESOLVED)
        self.assertEqual(self.ticket.priority, 3)

    def test_a_field_changed_on_the_page_is_applied(self):
        services.update_ticket(ticket=self.ticket, actor=self.agent2, assignee=self.agent2)
        self.client.force_login(self.agent)
        self.client.post(self.url, self.shown(assignee=self.agent.pk))  # deliberately reassigned
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assignee, self.agent)

    def test_a_page_from_before_the_fix_still_saves(self):
        self.client.force_login(self.agent)
        self.client.post(self.url, {"status": "open", "priority": 4, "assignee": "", "category": self.hardware.pk})
        self.ticket.refresh_from_db()
        self.assertEqual((self.ticket.status, self.ticket.priority), (Ticket.Status.OPEN, 4))

    def test_the_page_sends_what_it_showed(self):
        self.client.force_login(self.agent)
        page = self.client.get(self.ticket.get_absolute_url())
        self.assertContains(page, 'name="shown_status" value="new"')
        self.assertContains(page, f'name="shown_category" value="{self.hardware.pk}"')


class OddCharacterTests(MediaTestCase):
    """Superscript digits ("²") pass isdigit() but not int(): they must never cause an error page."""

    def test_no_error_pages(self):
        self.client.force_login(self.agent)
        for path, params in [
            (reverse("tickets:go"), {"number": "²"}),
            (reverse("tickets:go"), {"number": "1²"}),
            (reverse("tickets:new"), {"follow_up": "²"}),
            (reverse("tickets:queue"), {"q": "²", "category": "²", "priority": "²"}),
        ]:
            with self.subTest(path=path, params=params):
                self.assertLess(self.client.get(path, params).status_code, 500)

    def test_quick_pick_with_odd_characters(self):
        self.client.force_login(self.requester)
        response = self.client.post(reverse("tickets:new"), {"subject_pick": "²:0", "description": "x"})
        self.assertContains(response, "Enter a subject.", status_code=400)


class SignInLinkTests(MediaTestCase):
    def test_signed_in_people_with_an_odd_next_link_go_home(self):
        self.client.force_login(self.requester)
        for value in ["dashboard", "' OR '1'='1", "tickets:mine", "//evil.example", "https://evil.example/"]:
            with self.subTest(value=value):
                response = self.client.get(reverse("accounts:signin"), {"next": value})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], reverse("core:home"))

    def test_a_real_path_is_kept(self):
        self.client.force_login(self.requester)
        response = self.client.get(reverse("accounts:signin"), {"next": "/tickets/"})
        self.assertEqual(response["Location"], "/tickets/")


class QuickPickCategoryTests(MediaTestCase):
    def test_a_category_chosen_after_the_pick_wins_within_its_department(self):
        # Another department's category gives way to the pick's (v0.10.1):
        # see test_category_lists.NewRequestTests.
        self.client.force_login(self.requester)
        hardware = Category.objects.get(name="Hardware")
        network = Category.objects.get(name="Network")
        self.client.post(reverse("tickets:new"), {
            "subject_pick": f"{hardware.pk}:0", "subject": hardware.subject_choices[0],
            "category": network.pk, "description": "The office printer drops off the network.",
        })
        self.assertEqual(Ticket.objects.get().category, network)


class WordingTests(MediaTestCase):
    def test_requester_pages_name_no_single_team(self):
        ticket = make_ticket(self.requester, category=add_example_departments()["mechanics"])
        self.client.force_login(self.requester)
        for url in [ticket.get_absolute_url(), reverse("tickets:mine")]:
            with self.subTest(url=url):
                page = self.client.get(url).content.decode()
                for phrase in ("Replies from IT", "Waiting for IT", "waiting on IT", "Tell IT", "IT is working"):
                    self.assertNotIn(phrase, page)

    def test_receipt_email_names_no_single_team(self):
        from notifications.models import OutboundEmail

        make_ticket(self.requester)
        receipt = OutboundEmail.objects.get(kind="received")
        self.assertNotIn("is with IT", receipt.body_text)
        self.assertIn("someone will pick it up soon", receipt.body_text)

    def test_assignee_fallback_reads_as_a_sentence(self):
        ticket = make_ticket(self.requester)
        services.update_ticket(ticket=ticket, actor=self.agent, status=Ticket.Status.WAITING)
        ticket.refresh_from_db()
        services.update_ticket(ticket=ticket, actor=self.agent, assignee=None)
        self.client.force_login(self.requester)
        self.assertContains(self.client.get(ticket.get_absolute_url()), "The team is waiting for your reply.")
        self.assertTrue(User.objects.filter(pk=self.agent.pk).exists())

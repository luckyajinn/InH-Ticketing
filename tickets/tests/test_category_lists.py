"""
Category lists follow the department: with one chosen (or implied by a common
request), only its categories are offered. The queue, the New request form and
the admin site's ticket list.
"""

import importlib
import re

from django.apps import apps as django_apps
from django.urls import reverse

from accounts.models import User
from tickets.examples import add_example_departments
from tickets.models import Category, Ticket
from tickets.tests.helpers import MediaTestCase, make_ticket, make_user

it_requests = importlib.import_module("tickets.migrations.0009_it_common_requests")


def options(page, select_id: str) -> list[str]:
    """The option labels of one <select> on the page, in order."""
    html = page.content.decode()
    select = re.search(rf'<select[^>]*id="{select_id}".*?</select>', html, re.S).group(0)
    return [label.strip() for label in re.findall(r"<option[^>]*>([^<]*)</option>", select)]


def optgroups(page, select_id: str) -> list[str]:
    html = page.content.decode()
    select = re.search(rf'<select[^>]*id="{select_id}".*?</select>', html, re.S).group(0)
    return re.findall(r'<optgroup label="([^"]*)"', select)


class QueueTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        examples = add_example_departments()
        self.mechanics, self.cleaning = examples["mechanics"], examples["cleaning"]
        self.admin = make_user("Ada Admin", User.Role.ADMIN)
        self.hardware = Category.objects.get(name="Hardware")
        make_ticket(self.requester, subject="Printer jammed")
        make_ticket(self.requester, subject="Line 2 stopped", category=self.mechanics)
        self.url = reverse("tickets:queue")

    def test_a_chosen_department_offers_only_its_categories(self):
        self.client.force_login(self.admin)
        for key, expected in [("mechanics", ["All categories", "Mechanics"]),
                              ("cleaning", ["All categories", "Cleaning &amp; sanitization"])]:
            with self.subTest(department=key):
                page = self.client.get(self.url, {"dept": key})
                self.assertEqual(options(page, "q-cat"), expected)
                self.assertEqual(optgroups(page, "q-cat"), [])

    def test_all_departments_groups_the_categories_by_department(self):
        self.client.force_login(self.admin)
        page = self.client.get(self.url)
        self.assertEqual(optgroups(page, "q-cat"), ["IT", "Mechanics", "Cleaning &amp; sanitization"])
        self.assertIn("Hardware", options(page, "q-cat"))

    def test_another_departments_category_is_ignored(self):
        # As when the department is changed with a category still chosen.
        self.client.force_login(self.admin)
        page = self.client.get(self.url, {"dept": "mechanics", "category": self.hardware.pk})
        self.assertContains(page, "Line 2 stopped")
        self.assertNotContains(page, f'value="{self.hardware.pk}" selected')
        self.assertContains(page, "1 ticket match")

    def test_changing_department_clears_the_category(self):
        self.client.force_login(self.admin)
        # v0.10.7: app.js does it (data-clears), as inline handlers break the Content-Security-Policy.
        self.assertContains(self.client.get(self.url), 'name="dept" class="select" data-submit-on-change data-clears="category"')

    def test_agents_see_only_their_departments_categories(self):
        mechanic = make_user("Mo Mechanic", User.Role.AGENT)
        User.objects.filter(pk=mechanic.pk).update(department="mechanics")
        for person, expected in [(self.agent, ["Hardware", "Software", "Access", "Network", "Other"]),
                                 (mechanic, ["Mechanics"])]:
            with self.subTest(person=person.display_name):
                self.client.force_login(person)
                page = self.client.get(self.url)
                self.assertEqual(options(page, "q-cat")[1:], expected)
                self.assertEqual(optgroups(page, "q-cat"), [])



class ITOnlyQueueTests(MediaTestCase):
    def test_it_only_has_no_groups(self):
        self.client.force_login(make_user("Ada Admin", User.Role.ADMIN))
        page = self.client.get(reverse("tickets:queue"))
        self.assertEqual(optgroups(page, "q-cat"), [])
        self.assertEqual(options(page, "q-cat")[1:], ["Hardware", "Software", "Access", "Network", "Other"])


class NewRequestTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        examples = add_example_departments()
        self.mechanics = examples["mechanics"]
        self.hardware = Category.objects.get(name="Hardware")
        self.network = Category.objects.get(name="Network")
        self.client.force_login(self.requester)
        self.url = reverse("tickets:new")

    def post(self, **data):
        data.setdefault("description", "Since this morning.")
        return self.client.post(self.url, data)

    def test_the_page_says_which_department_each_belongs_to(self):
        # app.js uses these to show only the picked request's department's categories.
        page = self.client.get(self.url)
        self.assertContains(page, f'data-category="{self.mechanics.pk}" data-department="mechanics"')
        self.assertContains(page, f'<option value="{self.hardware.pk}" data-department="it">')
        self.assertContains(page, "The category list then shows only that team's categories.")

    def test_another_category_of_the_picks_department_is_kept(self):
        self.post(subject_pick=f"{self.hardware.pk}:0", category=self.network.pk)
        ticket = Ticket.objects.get()
        self.assertEqual((ticket.subject, ticket.category), (self.hardware.subject_choices[0], self.network))

    def test_another_departments_category_gives_way_to_the_picks(self):
        self.post(subject_pick=f"{self.mechanics.pk}:0", category=self.hardware.pk)
        ticket = Ticket.objects.get()
        self.assertEqual((ticket.subject, ticket.category), (self.mechanics.subject_choices[0], self.mechanics))

    def test_without_a_pick_any_category_can_be_chosen(self):
        self.post(subject="Conveyor squeaks", category=self.mechanics.pk)
        self.assertEqual(Ticket.objects.get().category, self.mechanics)


class ITCommonRequestsTests(MediaTestCase):
    def test_a_new_install_has_them(self):
        found = {c.name: c.subject_choices for c in Category.objects.filter(department="it") if c.subject_choices}
        self.assertEqual(found, it_requests.IT_COMMON_REQUESTS)
        self.client.force_login(self.requester)
        page = self.client.get(reverse("tickets:new"))
        for label in ("Hardware", "Access", "Network"):
            self.assertContains(page, f'<optgroup label="{label}"')
        self.assertContains(page, "Can&#x27;t connect to the Wi-Fi")

    def test_an_admins_own_list_is_kept(self):
        Category.objects.filter(name="Access").update(subject_options="Badge doesn't open the door")
        Category.objects.filter(name="Network").update(subject_options="")
        it_requests.remove_requests(django_apps, None)
        self.assertEqual(Category.objects.get(name="Access").subject_options, "Badge doesn't open the door")
        self.assertEqual(Category.objects.get(name="Hardware").subject_options, "")
        it_requests.add_requests(django_apps, None)
        self.assertEqual(Category.objects.get(name="Access").subject_options, "Badge doesn't open the door")
        self.assertEqual(Category.objects.get(name="Network").subject_choices, it_requests.IT_COMMON_REQUESTS["Network"])

    def test_none_of_them_sets_off_the_password_check(self):
        from tickets import password_guard
        for subjects in it_requests.IT_COMMON_REQUESTS.values():
            for subject in subjects:
                with self.subTest(subject=subject):
                    self.assertEqual(password_guard.find(subject), [])


class AdminTicketListTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.mechanics = add_example_departments()["mechanics"]
        admin = make_user("Ada Admin", User.Role.ADMIN)
        User.objects.filter(pk=admin.pk).update(is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        self.url = reverse("admin:tickets_ticket_changelist")
        self.hardware = Category.objects.get(name="Hardware")
        make_ticket(self.requester, subject="Printer jammed")
        make_ticket(self.requester, subject="Line 2 stopped", category=self.mechanics)

    def test_the_category_filter_follows_the_department_filter(self):
        page = self.client.get(self.url, {"department": "mechanics"})
        self.assertContains(page, f"?category={self.mechanics.pk}&amp;department=mechanics")
        self.assertNotContains(page, f"category={self.hardware.pk}")
        everything = self.client.get(self.url)
        self.assertContains(everything, "IT: Hardware")
        self.assertContains(everything, "Mechanics: Mechanics")

    def test_another_departments_category_is_ignored(self):
        page = self.client.get(self.url, {"department": "mechanics", "category": self.hardware.pk})
        self.assertContains(page, "Line 2 stopped")
        self.assertNotContains(page, "Printer jammed")

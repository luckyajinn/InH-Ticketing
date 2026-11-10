"""Common requests ("quick picks") on the New request form, and the Mechanics and C&S categories."""

from django.test import SimpleTestCase
from django.urls import reverse

from tickets.models import Category, Ticket
from tickets.tests.helpers import MediaTestCase


class SubjectChoicesTests(SimpleTestCase):
    def test_blank_lines_and_spaces_are_dropped(self):
        category = Category(subject_options="  First  \n\n\nSecond\n   \n")
        self.assertEqual(category.subject_choices, ["First", "Second"])

    def test_capped(self):
        category = Category(subject_options="\n".join(f"Subject {i}" for i in range(50)))
        self.assertEqual(len(category.subject_choices), Category.MAX_SUBJECT_OPTIONS)

    def test_none(self):
        self.assertEqual(Category().subject_choices, [])


class NewCategoriesTests(MediaTestCase):
    def test_mechanics_and_cleaning_exist_with_three_requests_each(self):
        for name in ("Mechanics", "Cleaning & sanitization"):
            with self.subTest(name=name):
                category = Category.objects.get(name=name)
                self.assertTrue(category.is_active)
                self.assertEqual(len(category.subject_choices), 3)

    def test_they_sit_before_other(self):
        names = list(Category.objects.filter(is_active=True).values_list("name", flat=True))
        self.assertLess(names.index("Mechanics"), names.index("Other"))
        self.assertLess(names.index("Cleaning & sanitization"), names.index("Other"))


class QuickPickFormTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.requester)
        self.url = reverse("tickets:new")
        self.mechanics = Category.objects.get(name="Mechanics")
        self.cleaning = Category.objects.get(name="Cleaning & sanitization")

    def post(self, **data):
        data.setdefault("description", "Line 2 stopped after lunch.")
        return self.client.post(self.url, data)

    def test_page_lists_the_common_requests(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Common requests")
        self.assertContains(page, '<optgroup label="Mechanics"')
        self.assertContains(page, '<optgroup label="Cleaning &amp; sanitization"')
        for subject in self.mechanics.subject_choices + self.cleaning.subject_choices:
            self.assertContains(page, subject.replace("'", "&#x27;"))

    def test_no_picker_when_no_category_has_requests(self):
        Category.objects.update(subject_options="")
        self.assertNotContains(self.client.get(self.url), "Common requests")

    def test_inactive_categories_are_not_offered(self):
        self.mechanics.is_active = False
        self.mechanics.save()
        page = self.client.get(self.url)
        self.assertNotContains(page, '<optgroup label="Mechanics"')
        self.assertContains(page, '<optgroup label="Cleaning &amp; sanitization"')

    def test_pick_alone_fills_subject_and_category(self):
        # As without JavaScript: no subject typed, no category chosen.
        response = self.post(subject_pick=f"{self.mechanics.pk}:0")
        ticket = Ticket.objects.get()
        self.assertRedirects(response, ticket.get_absolute_url())
        self.assertEqual(ticket.subject, self.mechanics.subject_choices[0])
        self.assertEqual(ticket.category, self.mechanics)

    def test_pick_with_its_text_already_filled_in(self):
        # As with JavaScript: the page filled in both already.
        text = self.cleaning.subject_choices[2]
        self.post(subject_pick=f"{self.cleaning.pk}:2", subject=text, category=self.cleaning.pk)
        ticket = Ticket.objects.get()
        self.assertEqual((ticket.subject, ticket.category), (text, self.cleaning))

    def test_typed_subject_wins_over_the_pick(self):
        hardware = Category.objects.get(name="Hardware")
        self.post(subject_pick=f"{self.mechanics.pk}:0", subject="Monitor flickers", category=hardware.pk)
        ticket = Ticket.objects.get()
        self.assertEqual((ticket.subject, ticket.category), ("Monitor flickers", hardware))

    def test_made_up_picks_are_ignored(self):
        for value in ("abc", "999999:0", f"{self.mechanics.pk}:99", f"{self.mechanics.pk}:-1", ":"):
            with self.subTest(value=value):
                response = self.post(subject_pick=value)
                self.assertContains(response, "Enter a subject.", status_code=400)
        self.assertFalse(Ticket.objects.exists())

    def test_picks_from_inactive_categories_are_ignored(self):
        self.mechanics.is_active = False
        self.mechanics.save()
        response = self.post(subject_pick=f"{self.mechanics.pk}:0")
        self.assertContains(response, "Enter a subject.", status_code=400)

    def test_choice_is_kept_when_the_form_comes_back(self):
        value = f"{self.mechanics.pk}:1"
        response = self.post(subject_pick=value, description="")
        self.assertContains(response, f'<option value="{value}" selected>', status_code=400)

    def test_typing_a_subject_still_works_on_its_own(self):
        self.post(subject="Badge reader won't open", category=Category.objects.get(name="Access").pk)
        self.assertEqual(Ticket.objects.get().subject, "Badge reader won't open")

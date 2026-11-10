"""
The help contact, the usage and privacy page, robots.txt, the favicon, and the
"request sent" message: the basics a person needs when something goes wrong.
"""

from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from core.views import server_error
from tickets.models import Category
from tickets.tests.helpers import MediaTestCase

CONTACT = "Call IT on ext. 1234, or post in IT Help in Teams."


class HelpContactTests(MediaTestCase):
    @override_settings(HELP_CONTACT=CONTACT)
    def test_sign_in_page_says_who_to_contact(self):
        self.assertContains(self.client.get(reverse("accounts:signin")), f"Can't sign in? {CONTACT}")

    @override_settings(HELP_CONTACT="", HELPDESK_MAILBOX="helpdesk@example.invalid")
    def test_falls_back_to_the_help_desk_mailbox(self):
        self.assertContains(
            self.client.get(reverse("accounts:signin")),
            'Email IT at <a href="mailto:helpdesk@example.invalid">helpdesk@example.invalid</a>.',
        )

    @override_settings(HELP_CONTACT="", HELPDESK_MAILBOX="")
    def test_falls_back_to_contact_it(self):
        self.assertContains(self.client.get(reverse("accounts:signin")), "Can't sign in? Contact IT.")

    @override_settings(HELP_CONTACT=CONTACT)
    def test_no_access_and_not_found_pages_say_it_too(self):
        self.client.force_login(self.requester)
        self.assertContains(self.client.get(reverse("tickets:queue")), CONTACT, status_code=403)
        self.assertContains(self.client.get("/no-such-page/"), CONTACT, status_code=404)


class ServerErrorTests(SimpleTestCase):
    """SimpleTestCase has no database, so this also proves the page doesn't need one."""

    @override_settings(HELP_CONTACT=CONTACT)
    def test_says_who_to_contact(self):
        response = server_error(RequestFactory().get("/"))
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Something went wrong", status_code=500)
        self.assertContains(response, f"If it keeps happening: {CONTACT}", status_code=500)

    @override_settings(HELP_CONTACT="", HELPDESK_MAILBOX="helpdesk@example.invalid")
    def test_mailbox_link_is_a_plain_link(self):
        response = server_error(RequestFactory().get("/"))
        self.assertContains(response, 'href="mailto:helpdesk@example.invalid"', status_code=500)


class BasicsTests(MediaTestCase):
    def test_robots_txt_keeps_everything_out_of_search(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertEqual(response.content.decode(), "User-agent: *\nDisallow: /\n")

    def test_pages_say_noindex_and_have_icons(self):
        page = self.client.get(reverse("accounts:signin")).content.decode()
        self.assertIn('<meta name="robots" content="noindex, nofollow">', page)
        self.assertIn('rel="icon"', page)
        self.assertIn('rel="apple-touch-icon"', page)
        self.assertIn('rel="manifest"', page)

    def test_favicon_ico_points_at_the_icon(self):
        response = self.client.get("/favicon.ico")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("icons/icon-32.png"))

    def test_usage_and_privacy_page_is_open_to_everyone(self):
        page = self.client.get(reverse("core:about"))
        self.assertContains(page, "Usage and privacy")
        self.assertContains(page, "No tracking, no analytics.")
        self.assertContains(page, "never the text itself")

    @override_settings(AUTO_CLOSE_RESOLVED_DAYS=7)
    def test_usage_page_states_the_close_rule(self):
        self.assertContains(self.client.get(reverse("core:about")), "closes by itself after 7 days")

    def test_footer_links_to_it(self):
        self.client.force_login(self.requester)
        self.assertContains(self.client.get(reverse("tickets:mine")), f'href="{reverse("core:about")}">Usage and privacy')

    def test_request_sent_message_doesnt_name_one_team(self):
        self.client.force_login(self.requester)
        response = self.client.post(reverse("tickets:new"), {
            "subject": "Leak on line 2", "category": Category.objects.get(name="Mechanics").pk,
            "description": "Dripping under the filler.",
        }, follow=True)
        self.assertContains(response, "sent. You&#x27;ll get an email when there&#x27;s an update.")
        self.assertNotContains(response, "IT will pick it up")

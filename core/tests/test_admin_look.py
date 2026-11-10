"""The admin site in the app's own look (templates/admin/base_site.html, static/css/admin.css)."""

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from tickets.models import Category


class AdminLookTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create(
            username="admin-1", display_name="Ada Admin", email="ada@example.invalid",
            role=User.Role.ADMIN, is_staff=True, is_superuser=True,
        )
        self.client.force_login(self.admin)

    def test_admin_pages_use_the_app_look(self):
        category = Category.objects.create(name="Printers")
        for url in [
            "/admin/",
            "/admin/tickets/ticket/",
            "/admin/tickets/category/",
            f"/admin/tickets/category/{category.pk}/change/",
            "/admin/tickets/passwordwarning/",
            "/admin/accounts/user/",
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "css/admin.css")
                self.assertContains(response, 'class="inh-brand"')
                self.assertContains(response, "Usage and privacy")
                self.assertContains(response, 'content="noindex, nofollow"')

    def test_admin_stylesheet_exists(self):
        self.assertIsNotNone(finders.find("css/admin.css"))

    def test_signs_out_the_same_way_as_the_rest_of_the_app(self):
        response = self.client.get("/admin/")
        self.assertContains(response, f'action="{reverse("accounts:signout")}"')
        self.assertNotContains(response, f'action="{reverse("admin:logout")}"')
        self.assertContains(response, f'href="{reverse("core:home")}"')

    def test_follows_the_device_theme_without_a_switch(self):
        response = self.client.get("/admin/")
        self.assertNotContains(response, "theme-toggle")
        self.assertNotContains(response, "admin/js/theme.js")

    def test_no_sidebar_and_plain_section_names(self):
        self.assertNotContains(self.client.get("/admin/tickets/ticket/"), 'id="nav-sidebar"')
        response = self.client.get("/admin/")
        for name in ["People", "Email in", "Email out", "Tickets"]:
            self.assertContains(response, name)
        for old in ["Accounts", "Inbound", "Notifications"]:
            self.assertNotContains(response, f">{old}<")

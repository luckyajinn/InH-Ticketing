from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import entra
from accounts.tests.helpers import ENTRA_SETTINGS, claims
from config import __version__


@override_settings(**ENTRA_SETTINGS)
class HomeTests(TestCase):
    def test_requires_sign_in(self):
        response = self.client.get(reverse("core:home"))
        self.assertRedirects(
            response, reverse("accounts:signin") + "?next=/", fetch_redirect_response=False
        )

    def test_header_shows_name_role_and_version(self):
        self.client.force_login(entra.sync_user(claims(roles=["Agent"])))
        response = self.client.get(reverse("core:home"), follow=True)
        self.assertContains(response, "Dana Whitfield")
        self.assertContains(response, '<span class="role-tag role-it">')
        self.assertContains(response, f"v{__version__}")
        # Agents aren't admins, so no admin link.
        self.assertNotContains(response, 'href="/admin/"')

    def test_admin_sees_admin_link(self):
        self.client.force_login(entra.sync_user(claims(roles=["Admin"])))
        response = self.client.get(reverse("core:home"), follow=True)
        self.assertContains(response, 'href="/admin/"')


class HealthTests(TestCase):
    def test_healthz(self):
        response = self.client.get(reverse("core:healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

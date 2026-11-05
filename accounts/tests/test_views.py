from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import entra
from accounts.models import User
from accounts.tests.helpers import ENTRA_SETTINGS, NO_ENTRA_SETTINGS, claims
from accounts.views import FLOW_KEY, NEXT_KEY

AUTH_URI = "https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize?client_id=x"


def fake_msal(*, flow=None, result=None, raises=None):
    app = mock.Mock()
    app.initiate_auth_code_flow.return_value = flow or {"auth_uri": AUTH_URI, "state": "abc"}
    if raises:
        app.acquire_token_by_auth_code_flow.side_effect = raises
    else:
        app.acquire_token_by_auth_code_flow.return_value = result
    return mock.patch.object(entra, "build_msal_app", return_value=app)


@override_settings(**ENTRA_SETTINGS)
class SignInPageTests(TestCase):
    def test_renders_sign_in_button(self):
        response = self.client.get(reverse("accounts:signin"))
        self.assertContains(response, "Sign in with your Microsoft 365 work account")
        self.assertContains(response, "/auth/login?next=/")
        self.assertNotContains(response, "Setup needed")

    @override_settings(**NO_ENTRA_SETTINGS)
    def test_shows_setup_notice_when_not_configured(self):
        response = self.client.get(reverse("accounts:signin"))
        self.assertContains(response, "Setup needed")

    def test_signed_in_user_is_sent_on(self):
        self.client.force_login(User.objects.create(username="u1"))
        response = self.client.get(reverse("accounts:signin") + "?next=/somewhere/")
        self.assertRedirects(response, "/somewhere/", fetch_redirect_response=False)


@override_settings(**ENTRA_SETTINGS)
class LoginStartTests(TestCase):
    def test_redirects_to_microsoft_and_stores_flow(self):
        with fake_msal():
            response = self.client.get(reverse("accounts:login") + "?next=/after/")
        self.assertRedirects(response, AUTH_URI, fetch_redirect_response=False)
        self.assertEqual(self.client.session[FLOW_KEY]["state"], "abc")
        self.assertEqual(self.client.session[NEXT_KEY], "/after/")

    def test_external_next_is_ignored(self):
        with fake_msal():
            self.client.get(reverse("accounts:login") + "?next=https://evil.example/")
        self.assertEqual(self.client.session[NEXT_KEY], "/")

    @override_settings(ENTRA_REDIRECT_URI="http://localhost:8000/auth/callback")
    def test_moves_to_the_redirect_uri_host_first(self):
        response = self.client.get(reverse("accounts:login") + "?next=/x/")
        self.assertRedirects(
            response, "http://localhost:8000/auth/login?next=/x/", fetch_redirect_response=False
        )
        self.assertNotIn(FLOW_KEY, self.client.session)

    def test_unreachable_or_wrong_tenant_shows_clear_error(self):
        # This is what MSAL raises for a tenant ID that doesn't exist.
        bad_tenant = ValueError("Unable to get authority configuration")
        with mock.patch.object(entra, "build_msal_app", side_effect=bad_tenant):
            response = self.client.get(reverse("accounts:login"))
        self.assertContains(response, "check ENTRA_TENANT_ID", status_code=502)
        self.assertNotIn(FLOW_KEY, self.client.session)

    @override_settings(**NO_ENTRA_SETTINGS)
    def test_not_configured_goes_back_to_sign_in(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertRedirects(response, reverse("accounts:signin"), fetch_redirect_response=False)


@override_settings(**ENTRA_SETTINGS)
class CallbackTests(TestCase):
    def _start_flow(self, next_url="/after/"):
        session = self.client.session
        session[FLOW_KEY] = {"state": "abc", "auth_uri": AUTH_URI}
        session[NEXT_KEY] = next_url
        session.save()

    def _callback(self):
        return self.client.get(reverse("accounts:callback") + "?code=c&state=abc")

    def test_success_signs_in_and_redirects(self):
        self._start_flow()
        with fake_msal(result={"id_token_claims": claims(roles=["Agent"])}):
            response = self._callback()

        self.assertRedirects(response, "/after/", fetch_redirect_response=False)
        user = User.objects.get()
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertEqual(user.role, User.Role.AGENT)
        self.assertNotIn(FLOW_KEY, self.client.session)

    def test_without_a_started_flow(self):
        response = self._callback()
        self.assertContains(response, "session expired", status_code=400)
        self.assertFalse(User.objects.exists())

    def test_state_mismatch(self):
        self._start_flow()
        with fake_msal(raises=ValueError("state mismatch")):
            response = self._callback()
        self.assertContains(response, "expired or was already used", status_code=400)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_user_not_assigned_in_entra(self):
        self._start_flow()
        with fake_msal(result={"error": "access_denied", "error_description": "AADSTS50105: no"}):
            response = self._callback()
        self.assertContains(response, "given access", status_code=403)

    def test_locally_disabled_user_is_refused(self):
        entra.sync_user(claims())
        User.objects.update(is_active=False)
        self._start_flow()
        with fake_msal(result={"id_token_claims": claims()}):
            response = self._callback()
        self.assertContains(response, "disabled", status_code=403)
        self.assertNotIn("_auth_user_id", self.client.session)


@override_settings(**ENTRA_SETTINGS)
class SignOutTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create(username="u1"))

    def test_get_is_not_allowed(self):
        # Sign-out must be a POST so another site can't sign people out with a link.
        response = self.client.get(reverse("accounts:signout"))
        self.assertEqual(response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_post_signs_out(self):
        response = self.client.post(reverse("accounts:signout"))
        self.assertRedirects(response, reverse("accounts:signin"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)


@override_settings(**ENTRA_SETTINGS)
class AdminAccessTests(TestCase):
    def test_anonymous_is_sent_to_microsoft_sign_in(self):
        response = self.client.get("/admin/", follow=True)
        self.assertEqual(response.request["PATH_INFO"], reverse("accounts:signin"))
        self.assertNotContains(response, 'type="password"')

    def test_requester_is_forbidden(self):
        self.client.force_login(entra.sync_user(claims()))
        response = self.client.get("/admin/", follow=True)
        self.assertEqual(response.status_code, 403)

    def test_admin_gets_in(self):
        self.client.force_login(entra.sync_user(claims(roles=["Admin"])))
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "InH-Ticketing admin")

import uuid
from unittest import mock

from django.test import TestCase, override_settings

from accounts import entra
from accounts.models import User
from accounts.tests.helpers import ENTRA_SETTINGS, OID, OTHER_TENANT_ID, claims


@override_settings(**ENTRA_SETTINGS)
class RoleMappingTests(TestCase):
    def test_no_roles_is_requester(self):
        self.assertEqual(entra.role_from_claims(None), User.Role.REQUESTER)
        self.assertEqual(entra.role_from_claims([]), User.Role.REQUESTER)

    def test_requester_role_is_requester(self):
        self.assertEqual(entra.role_from_claims(["Requester"]), User.Role.REQUESTER)

    def test_agent(self):
        self.assertEqual(entra.role_from_claims(["Agent"]), User.Role.AGENT)

    def test_highest_role_wins(self):
        self.assertEqual(entra.role_from_claims(["Requester", "Agent", "Admin"]), User.Role.ADMIN)

    def test_role_values_are_case_sensitive(self):
        # Entra role values are exact strings; a typo must not grant access.
        self.assertEqual(entra.role_from_claims(["admin", "AGENT"]), User.Role.REQUESTER)

    @override_settings(ENTRA_ROLE_AGENT="HelpdeskAgent")
    def test_custom_role_values(self):
        self.assertEqual(entra.role_from_claims(["HelpdeskAgent"]), User.Role.AGENT)
        self.assertEqual(entra.role_from_claims(["Agent"]), User.Role.REQUESTER)


@override_settings(**ENTRA_SETTINGS)
class SyncUserTests(TestCase):
    def test_creates_user_on_first_sign_in(self):
        user = entra.sync_user(claims(roles=["Agent"]))

        self.assertEqual(user.entra_oid, uuid.UUID(OID))
        self.assertEqual(user.username, OID)
        self.assertEqual(user.display_name, "Dana Whitfield")
        self.assertEqual(user.email, "dana.whitfield@example.com")
        self.assertEqual(user.role, User.Role.AGENT)
        self.assertTrue(user.is_agent)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.has_usable_password())

    def test_updates_existing_user_and_revokes_admin(self):
        entra.sync_user(claims(roles=["Admin"]))
        admin = User.objects.get()
        self.assertTrue(admin.is_staff and admin.is_superuser)

        entra.sync_user(claims(name="Dana W. Whitfield", roles=None))

        self.assertEqual(User.objects.count(), 1)
        user = User.objects.get()
        self.assertEqual(user.display_name, "Dana W. Whitfield")
        self.assertEqual(user.role, User.Role.REQUESTER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_prefers_email_claim(self):
        user = entra.sync_user(claims(email="dana@example.com"))
        self.assertEqual(user.email, "dana@example.com")

    def test_name_falls_back_to_email(self):
        user = entra.sync_user(claims(name=None))
        self.assertEqual(user.display_name, "dana.whitfield@example.com")


@override_settings(**ENTRA_SETTINGS)
class FinishFlowTests(TestCase):
    def _finish(self, *, result=None, raises=None):
        app = mock.Mock()
        if raises:
            app.acquire_token_by_auth_code_flow.side_effect = raises
        else:
            app.acquire_token_by_auth_code_flow.return_value = result
        with mock.patch.object(entra, "build_msal_app", return_value=app):
            return entra.finish_flow({"state": "s"}, {"state": "s", "code": "c"})

    def test_success_returns_claims(self):
        result = self._finish(result={"id_token_claims": claims()})
        self.assertEqual(result["oid"], OID)

    def test_state_mismatch(self):
        with self.assertRaises(entra.EntraSignInError) as ctx:
            self._finish(raises=ValueError("state mismatch"))
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("expired", ctx.exception.message)

    def test_not_assigned_to_app(self):
        with self.assertRaises(entra.EntraSignInError) as ctx:
            self._finish(result={
                "error": "access_denied",
                "error_description": "AADSTS50105: The signed in user is not assigned to a role.",
            })
        self.assertEqual(ctx.exception.status, 403)
        self.assertIn("hasn't been given access", ctx.exception.message)

    def test_unknown_error_is_generic(self):
        with self.assertRaises(entra.EntraSignInError) as ctx:
            self._finish(result={"error": "server_error", "error_description": "AADSTS12345: Boom"})
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("couldn't complete", ctx.exception.message)

    def test_wrong_tenant_rejected(self):
        with self.assertRaises(entra.EntraSignInError) as ctx:
            self._finish(result={"id_token_claims": claims(tid=OTHER_TENANT_ID)})
        self.assertEqual(ctx.exception.status, 403)

    def test_missing_oid_rejected(self):
        with self.assertRaises(entra.EntraSignInError):
            self._finish(result={"id_token_claims": claims(oid=None)})


@override_settings(**ENTRA_SETTINGS)
class StartFlowTests(TestCase):
    def test_uses_query_response_mode_and_redirect_uri(self):
        app = mock.Mock()
        app.initiate_auth_code_flow.return_value = {"auth_uri": "https://login.example/authorize"}
        with mock.patch.object(entra, "build_msal_app", return_value=app):
            entra.start_flow()
        kwargs = app.initiate_auth_code_flow.call_args.kwargs
        self.assertEqual(kwargs["scopes"], [])
        self.assertEqual(kwargs["redirect_uri"], "http://testserver/auth/callback")
        self.assertEqual(kwargs["response_mode"], "query")

    def test_authority_is_tenant_specific(self):
        # A tenant-specific authority is what keeps other organisations out.
        # MSAL itself is patched out, so this makes no network calls.
        with mock.patch("msal.ConfidentialClientApplication") as cca:
            entra.build_msal_app()
        self.assertEqual(
            cca.call_args.kwargs["authority"],
            f"https://login.microsoftonline.com/{ENTRA_SETTINGS['ENTRA_TENANT_ID']}",
        )

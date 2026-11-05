"""
Microsoft 365 (Entra ID) sign-in helpers.

The flow (OpenID Connect authorization code flow with PKCE):

1. `login_start` asks MSAL for a Microsoft sign-in URL and keeps MSAL's
   "flow" (state, nonce, PKCE verifier) in the user's session.
2. Microsoft sends the browser back to `/auth/callback` with a one-time code.
3. MSAL swaps the code for an ID token, checking state, nonce, audience,
   issuer and expiry. The app never sees a password.
4. We read the person's details from the token and create or update them.
"""

from __future__ import annotations

import logging
import uuid

import msal
import requests
from django.conf import settings
from django.db import transaction

from accounts.models import User

logger = logging.getLogger(__name__)

# Some AADSTS error codes deserve a plain-English explanation.
FRIENDLY_ERRORS = {
    "AADSTS50105": (
        "Your account hasn't been given access to InH-Ticketing yet. "
        "Contact IT to be added."
    ),
    "AADSTS65004": "Sign-in was cancelled because consent was declined.",
    "AADSTS50011": (
        "The app's redirect address doesn't match its Entra registration. "
        "IT: check ENTRA_REDIRECT_URI against the app registration."
    ),
    "AADSTS7000215": "The app's client secret is wrong or has expired. IT: renew it.",
    "AADSTS7000222": "The app's client secret has expired. IT: renew it.",
    "AADSTS700016": (
        "The app registration wasn't found in this tenant. "
        "IT: check ENTRA_CLIENT_ID and ENTRA_TENANT_ID."
    ),
}


class EntraSignInError(Exception):
    """Sign-in failed in a way we should explain to the person."""

    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def is_configured() -> bool:
    return all(
        [settings.ENTRA_TENANT_ID, settings.ENTRA_CLIENT_ID, settings.ENTRA_CLIENT_SECRET]
    )


def authority() -> str:
    # A tenant-specific authority means only McKenna Labs accounts can sign in.
    return f"https://login.microsoftonline.com/{settings.ENTRA_TENANT_ID}"


def build_msal_app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=settings.ENTRA_CLIENT_ID,
        client_credential=settings.ENTRA_CLIENT_SECRET,
        authority=authority(),
    )


def _msal_app() -> msal.ConfidentialClientApplication:
    """Build the MSAL app, turning setup and network failures into a clear message."""
    try:
        # MSAL contacts Microsoft here to look up the tenant's sign-in endpoints.
        return build_msal_app()
    except (ValueError, requests.RequestException) as exc:
        logger.error("Couldn't reach Entra for tenant %s: %s", settings.ENTRA_TENANT_ID, exc)
        raise EntraSignInError(
            "Microsoft 365 sign-in is unavailable right now. "
            "IT: check ENTRA_TENANT_ID and the server's internet access.",
            status=502,
        ) from exc


def start_flow() -> dict:
    """Begin a sign-in. Returns MSAL's flow dict; send the browser to flow["auth_uri"]."""
    return _msal_app().initiate_auth_code_flow(
        # Empty: we only need the ID token. MSAL adds openid/profile/offline_access.
        scopes=[],
        redirect_uri=settings.ENTRA_REDIRECT_URI,
        # "query" (a GET back to us) rather than MSAL's suggested "form_post":
        # a cross-site POST from Microsoft wouldn't carry our SameSite=Lax session
        # cookie, so the flow would be lost. The code that comes back is useless
        # without our client secret and PKCE verifier, so this is still safe.
        response_mode="query",
    )


def finish_flow(flow: dict, auth_response: dict) -> dict:
    """Swap the code for tokens and return the ID token's claims."""
    app = _msal_app()
    try:
        result = app.acquire_token_by_auth_code_flow(flow, auth_response)
    except ValueError as exc:
        # State mismatch or a replayed/old callback. Usually a stale tab.
        logger.warning("Entra sign-in rejected: %s", exc)
        raise EntraSignInError(
            "That sign-in link has expired or was already used. Please sign in again."
        ) from exc

    if "error" in result:
        description = result.get("error_description", "") or ""
        logger.warning("Entra sign-in error %s: %s", result.get("error"), description)
        code = description.split(":", 1)[0].strip()
        message = FRIENDLY_ERRORS.get(code, "Microsoft couldn't complete the sign-in. Please try again.")
        status = 403 if code == "AADSTS50105" else 400
        raise EntraSignInError(message, status=status)

    claims = result.get("id_token_claims") or {}
    if not claims.get("oid"):
        raise EntraSignInError("Microsoft didn't return an account ID. Please try again.")
    if (claims.get("tid") or "").lower() != settings.ENTRA_TENANT_ID.lower():
        logger.warning("Entra sign-in from unexpected tenant %s", claims.get("tid"))
        raise EntraSignInError("That account isn't part of this organisation.", status=403)
    return claims


def role_from_claims(roles: list[str] | None) -> str:
    """Map Entra app role values to our roles. The highest one wins."""
    roles = set(roles or [])
    if settings.ENTRA_ROLE_ADMIN in roles:
        return User.Role.ADMIN
    if settings.ENTRA_ROLE_AGENT in roles:
        return User.Role.AGENT
    return User.Role.REQUESTER


@transaction.atomic
def sync_user(claims: dict) -> User:
    """Create or update the person described by an ID token."""
    oid = uuid.UUID(claims["oid"])
    email = (claims.get("email") or claims.get("preferred_username") or "").strip()
    name = (claims.get("name") or "").strip()
    role = role_from_claims(claims.get("roles"))

    user = User.objects.select_for_update().filter(entra_oid=oid).first()
    if user is None:
        user = User(entra_oid=oid, username=str(oid))
        user.set_unusable_password()  # Entra is the only way in.

    user.email = email
    user.display_name = name or email
    user.role = role
    # Admins get the Django admin site. Recomputed every sign-in, so removing
    # the Admin role in Entra removes admin access next time they sign in.
    user.is_staff = role == User.Role.ADMIN
    user.is_superuser = role == User.Role.ADMIN
    user.save()
    return user

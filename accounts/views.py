from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from accounts import entra

FLOW_KEY = "entra_flow"
NEXT_KEY = "entra_next"


def _safe_next(request, candidate: str | None) -> str:
    """Only allow redirects back into this site, never to another domain."""
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return reverse(settings.LOGIN_REDIRECT_URL)


@require_GET
def signin(request):
    """The sign-in page with the 'Sign in with Microsoft 365' button."""
    next_url = _safe_next(request, request.GET.get("next"))
    if request.user.is_authenticated:
        return redirect(next_url)
    return render(
        request,
        "accounts/signin.html",
        {"next": next_url, "entra_configured": entra.is_configured()},
    )


@require_GET
def login_start(request):
    """Send the browser to Microsoft's sign-in page."""
    if not entra.is_configured():
        messages.error(request, "Microsoft 365 sign-in isn't configured yet. See docs/entra-setup.md.")
        return redirect("accounts:signin")

    # The session cookie belongs to the host the browser is on. If that isn't
    # the host Microsoft will send people back to (e.g. 127.0.0.1 vs localhost),
    # the session would be lost mid-sign-in, so move to the right host first.
    callback = urlsplit(settings.ENTRA_REDIRECT_URI)
    if request.get_host() != callback.netloc:
        return redirect(f"{callback.scheme}://{callback.netloc}{request.get_full_path()}")

    try:
        flow = entra.start_flow()
    except entra.EntraSignInError as exc:
        return render(
            request, "accounts/signin_error.html", {"message": exc.message}, status=exc.status
        )
    request.session[FLOW_KEY] = flow
    request.session[NEXT_KEY] = _safe_next(request, request.GET.get("next"))
    return redirect(flow["auth_uri"])


@require_GET
def callback(request):
    """Microsoft sends the browser back here after sign-in."""
    flow = request.session.pop(FLOW_KEY, None)
    next_url = request.session.pop(NEXT_KEY, None) or reverse(settings.LOGIN_REDIRECT_URL)

    try:
        if flow is None:
            raise entra.EntraSignInError(
                "Your sign-in session expired before it finished. Please sign in again."
            )
        claims = entra.finish_flow(flow, request.GET.dict())
        user = entra.sync_user(claims)
        if not user.is_active:
            raise entra.EntraSignInError(
                "Your InH-Ticketing account has been disabled. Contact IT.", status=403
            )
    except entra.EntraSignInError as exc:
        return render(
            request, "accounts/signin_error.html", {"message": exc.message}, status=exc.status
        )

    # login() also gives the person a fresh session ID.
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect(next_url)


@require_POST
def signout(request):
    """
    Sign out of InH-Ticketing only. The person stays signed in to Microsoft 365,
    so Outlook and Teams in the same browser are not affected.
    """
    logout(request)
    messages.info(request, "You've signed out of InH-Ticketing.")
    return redirect("accounts:signin")


def admin_login(request, extra_context=None):
    """Replaces the Django admin's password form with Microsoft 365 sign-in."""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("admin:index")
        # Signed in, but not an Admin. Sending them back to sign-in would loop.
        raise PermissionDenied
    return redirect_to_login(
        request.GET.get("next", reverse("admin:index")), login_url=reverse("accounts:signin")
    )

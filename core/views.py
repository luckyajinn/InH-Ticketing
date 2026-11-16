from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseServerError
from django.middleware.csp import get_nonce
from django.shortcuts import redirect, render
from django.template import loader
from django.templatetags.static import static
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.http import require_GET

from core.context_processors import help_contact


@require_GET
def about(request):
    """Usage and privacy: what the app is for, what it keeps, and who sees it. Open to everyone."""
    return render(request, "core/about.html", {"auto_close_days": settings.AUTO_CLOSE_RESOLVED_DAYS})


@require_GET
@cache_control(max_age=86400)
def robots_txt(request):
    """An internal app: nothing here should ever be indexed."""
    return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")


@require_GET
@cache_control(max_age=86400)
def favicon(request):
    """Browsers ask for /favicon.ico on their own; send them to the real icon."""
    return redirect(static("icons/icon-32.png"), permanent=False)


def server_error(request):
    """
    The "Something went wrong" page, with who to contact. It reads settings
    only, never the database or the session, which may be what failed.
    """
    # Its styles are inline, so the page works without static files; the
    # Content-Security-Policy lets them in with this request's nonce.
    # (str() makes the nonce, so the header names it; without the middleware there's none.)
    nonce = get_nonce(request)
    context = {**help_contact(), "csp_nonce": str(nonce) if nonce is not None else ""}
    return HttpResponseServerError(loader.get_template("500.html").render(context))


@login_required
@require_GET
def home(request):
    """IT lands on the queue; everyone else on their own tickets."""
    return redirect("tickets:queue" if request.user.is_agent else "tickets:mine")


@never_cache
@require_GET
def healthz(request):
    """Liveness check for Docker / the reverse proxy. No auth, no database."""
    return HttpResponse("ok", content_type="text/plain")

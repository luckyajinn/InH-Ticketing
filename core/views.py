from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@login_required
@require_GET
def home(request):
    """Landing page after sign-in. Tickets arrive in milestone 2."""
    return render(request, "core/home.html")


@never_cache
@require_GET
def healthz(request):
    """Liveness check for Docker / the reverse proxy. No auth, no database."""
    return HttpResponse("ok", content_type="text/plain")

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


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

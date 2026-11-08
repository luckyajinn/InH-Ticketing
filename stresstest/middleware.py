"""
Automatic sign-in for stress tests. STRESS-TEST BRANCH ONLY: never merge into main.

Only installed when STRESS_TEST_MODE is on (see config/settings.py). A request
that isn't signed in is signed in as a generated fake user:

  * the one named in the X-Stress-User header (what the load generator sends),
  * otherwise the one in the "stress_user" cookie (set by ?as=<username>),
  * otherwise the first fake agent, so a person can just open the site.

Only accounts whose username starts with "stress-" can ever be used, so real
accounts can't be reached this way even if one exists in the database.
"""

from django.contrib.auth import get_user_model, login

from stresstest.guard import FAKE_USER_PREFIX

DEFAULT_USER = f"{FAKE_USER_PREFIX}agent-01"


class StressAutoLoginMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        chosen = request.GET.get("as", "")
        if chosen.startswith(FAKE_USER_PREFIX) and request.user.is_authenticated \
                and request.user.username != chosen:
            from django.contrib.auth import logout
            logout(request)  # switching to another fake user for a look around
        if not request.user.is_authenticated:
            username = (
                request.headers.get("X-Stress-User")
                or chosen
                or request.COOKIES.get("stress_user")
                or DEFAULT_USER
            )
            if username.startswith(FAKE_USER_PREFIX):
                user = get_user_model().objects.filter(username=username, is_active=True).first()
                if user is not None:
                    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        response = self.get_response(request)
        if chosen.startswith(FAKE_USER_PREFIX):
            response.set_cookie("stress_user", chosen, samesite="Lax", secure=request.is_secure())
        return response

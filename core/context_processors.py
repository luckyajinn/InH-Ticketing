from django.conf import settings


def app_info(request):
    """Values every template can use."""
    return {
        "APP_NAME": "InH-Ticketing",
        "APP_VERSION": settings.APP_VERSION,
        # Shown as "you can also email ..." only when email-in is switched on.
        "INBOUND_ADDRESS": settings.HELPDESK_MAILBOX if settings.INBOUND_EMAIL == "graph" else "",
        # Stress-test branch only: shows the "fake data" banner.
        "STRESS_TEST_MODE": getattr(settings, "STRESS_TEST_MODE", False),
    }

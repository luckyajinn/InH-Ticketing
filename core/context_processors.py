from django.conf import settings


def help_contact() -> dict:
    """Who to contact when the app can't help (see HELP_CONTACT in settings)."""
    return {"HELP_CONTACT": settings.HELP_CONTACT, "HELP_EMAIL": settings.HELPDESK_MAILBOX}


def app_info(request):
    """Values every template can use."""
    return {
        "APP_NAME": "InH-Ticketing",
        "APP_VERSION": settings.APP_VERSION,
        # Shown as "you can also email ..." only when email-in is switched on.
        "INBOUND_ADDRESS": settings.HELPDESK_MAILBOX if settings.INBOUND_EMAIL == "graph" else "",
        **help_contact(),
    }

from django.conf import settings
from django.utils.functional import lazy

from core import departments


def help_contact() -> dict:
    """Who to contact when the app can't help (see HELP_CONTACT in settings)."""
    return {"HELP_CONTACT": settings.HELP_CONTACT, "HELP_EMAIL": settings.HELPDESK_MAILBOX}


def app_info(request):
    """Values every template can use."""
    return {
        "APP_NAME": "InH-Ticketing",
        "APP_VERSION": settings.APP_VERSION,
        # "IT, Mechanics, or Cleaning & sanitization": looked up only on pages that say it.
        "DEPARTMENTS_OR": lazy(departments.names, str)("or"),
        "DEPARTMENTS_AND": lazy(departments.names, str)("and"),
        # Shown as "you can also email ..." only when email-in is switched on.
        "INBOUND_ADDRESS": settings.HELPDESK_MAILBOX if settings.INBOUND_EMAIL == "graph" else "",
        **help_contact(),
    }

from django.conf import settings


def app_info(request):
    """Values every template can use."""
    return {"APP_NAME": "InH-Ticketing", "APP_VERSION": settings.APP_VERSION}

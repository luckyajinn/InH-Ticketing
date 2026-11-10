from django.utils.cache import patch_cache_control


class PrivatePagesMiddleware:
    """
    Signed-in pages and file downloads are never kept by the browser or
    anything in between (Cache-Control: private, no-store). On a shared PC,
    the Back button after signing out can't bring someone's tickets back.
    Static files are served before this runs (WhiteNoise), so they still cache.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            patch_cache_control(response, private=True, no_store=True)
        return response

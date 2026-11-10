from django.contrib import admin
from django.urls import include, path

from accounts.views import admin_login

# The Django admin uses Microsoft 365 sign-in like the rest of the app.
admin.site.login = admin_login
admin.site.site_header = "InH-Ticketing admin"
admin.site.site_title = "InH-Ticketing admin"
admin.site.index_title = "Administration"
# Six lists don't need a sidebar: the admin home and breadcrumbs cover it, and
# the ticket list gets the full width.
admin.site.enable_nav_sidebar = False

handler500 = "core.views.server_error"

urlpatterns = [
    path("", include("core.urls")),
    path("", include("accounts.urls")),
    path("", include("tickets.urls")),
    path("admin/", admin.site.urls),
]

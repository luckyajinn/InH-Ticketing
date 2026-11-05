from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group

from accounts.models import User

# Roles come from Entra app roles, not Django groups, so hide Groups to avoid confusion.
admin.site.unregister(Group)


@admin.register(User)
class InHUserAdmin(UserAdmin):
    """People are managed in Entra. Here you can view them, or deactivate one locally."""

    list_display = ["__str__", "email", "role", "is_active", "last_login"]
    list_filter = ["role", "is_active"]
    search_fields = ["display_name", "email", "username"]
    ordering = ["display_name"]
    readonly_fields = [
        "entra_oid", "display_name", "email", "role", "is_staff", "is_superuser",
        "last_login", "date_joined",
    ]
    fieldsets = [
        (None, {"fields": ["display_name", "email", "role", "entra_oid"]}),
        (
            "Access",
            {
                "fields": ["is_active", "is_staff", "is_superuser"],
                "description": (
                    "Role and admin access come from Entra app roles and refresh on every "
                    "sign-in. Untick <b>Active</b> to block someone locally."
                ),
            },
        ),
        ("Activity", {"fields": ["last_login", "date_joined"]}),
    ]
    # People are created by signing in, never by hand.
    add_fieldsets = []

    def has_add_permission(self, request):
        return False

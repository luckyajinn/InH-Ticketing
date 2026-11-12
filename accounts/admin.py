from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group

from accounts.models import User
from core import departments
from core.admin import DepartmentListFilter, LoggedChanges

# Roles come from Entra app roles, not Django groups, so hide Groups to avoid confusion.
admin.site.unregister(Group)


@admin.register(User)
class InHUserAdmin(LoggedChanges, UserAdmin):
    """People are managed in Entra. Here you can view them, or deactivate one locally."""

    list_display = ["__str__", "email", "role", "department_name", "is_active", "last_login"]
    list_filter = ["role", DepartmentListFilter, "is_active"]
    search_fields = ["display_name", "email", "username"]
    ordering = ["display_name"]
    readonly_fields = [
        "entra_oid", "display_name", "email", "role", "department_name", "is_staff", "is_superuser",
        "last_login", "date_joined",
    ]
    fieldsets = [
        (None, {"fields": ["display_name", "email", "role", "department_name", "entra_oid"]}),
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

    def has_delete_permission(self, request, obj=None):
        # Deactivate instead: deleting someone would also delete their entries in the admin log.
        return False

    @admin.display(description="department", ordering="department")
    def department_name(self, obj):
        """An agent's department (IT if Entra gave none); blank for requesters and admins."""
        return departments.label(obj.department or (departments.IT if obj.role == User.Role.AGENT else ""))

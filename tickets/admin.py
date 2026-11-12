from django import forms
from django.conf import settings
from django.contrib import admin

from accounts.models import User
from core import departments
from core.admin import DepartmentListFilter, LoggedChanges, TicketDepartmentFilter
from tickets.models import Attachment, Category, Comment, Department, PasswordWarning, Ticket, TicketEvent

ADD_STEPS = (
    "<b>After you save it, for its staff to work its tickets:</b><ol>"
    "<li>In Entra, create an app role whose value is exactly the <b>Entra app role</b> below, and assign "
    "the team's group to it (docs/entra-setup.md, section 3). Never give them the plain "
    "<code>{agent_role}</code> role, which is IT's. It applies at their next sign-in.</li>"
    "<li>In <b>Categories</b>, add its categories with this department, and their common requests. "
    "Requesters see a department only through its categories.</li>"
    "<li>Optional: its own mailbox, in <code>DEPARTMENT_MAILBOXES</code> in .env with this department's "
    "key, and the Exchange steps in docs/email-setup.md, 4d.</li></ol>"
)
KEEP_NOTE = (
    "A department can be deleted only while nothing uses it: no categories, agents or internal notes. "
    "To stop using one, untick <b>Active</b> on its categories and remove its role in Entra."
)
IT_NOTE = (
    "IT is built in, and set in .env: its agents have the Entra app role in <code>ENTRA_ROLE_AGENT</code>, "
    "its alerts go to <code>IT_NOTIFY_EMAIL</code>, and its mailbox is <code>HELPDESK_MAILBOX</code>."
)


@admin.register(Department)
class DepartmentAdmin(LoggedChanges, admin.ModelAdmin):
    """The teams that work tickets. IT is built in; admins add the rest here."""

    list_display = ["name", "key", "role", "alerts", "colour_name", "categories", "agents"]

    def get_fieldsets(self, request, obj=None):
        if obj and obj.is_it:
            return [(None, {"fields": ["name", "key", "role", "alerts", "colour_name"], "description": IT_NOTE})]
        if obj:
            return [(None, {"fields": ["name", "key", "entra_role", "alert_email", "colour_name"],
                            "description": KEEP_NOTE})]
        steps = ADD_STEPS.replace("{agent_role}", settings.ENTRA_ROLE_AGENT)
        return [(None, {"fields": ["name", "key", "entra_role", "alert_email"], "description": steps})]

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.is_it:
            return ["name", "key", "role", "alerts", "colour_name"]
        return ["key", "colour_name"] if obj else []

    def get_prepopulated_fields(self, request, obj=None):
        return {} if obj else {"key": ["name"]}

    def has_delete_permission(self, request, obj=None):
        return bool(obj) and not obj.is_it and not self._in_use(obj)

    @staticmethod
    def _in_use(obj) -> bool:
        return (Category.objects.filter(department=obj.key).exists()
                or User.objects.filter(department=obj.key).exists()
                or Comment.objects.filter(department=obj.key).exists())

    @admin.display(description="Entra app role")
    def role(self, obj):
        return f"{settings.ENTRA_ROLE_AGENT} (ENTRA_ROLE_AGENT)" if obj.is_it else obj.entra_role

    @admin.display(description="alerts go to")
    def alerts(self, obj):
        if obj.is_it:
            return f"{settings.IT_NOTIFY_EMAIL or 'Nobody'} (IT_NOTIFY_EMAIL)"
        return obj.alert_email or "Each of its agents"

    @admin.display(description="colour in Reports", ordering="colour")
    def colour_name(self, obj):
        return obj.get_colour_display()

    @admin.display(description="active categories")
    def categories(self, obj):
        return Category.objects.filter(department=obj.key, is_active=True).count()

    @admin.display(description="agents")
    def agents(self, obj):
        people = User.objects.filter(role=User.Role.AGENT, is_active=True)
        return people.filter(department__in=[obj.key, ""] if obj.is_it else [obj.key]).count()


class CategoryForm(forms.ModelForm):
    department = forms.ChoiceField(help_text=Category._meta.get_field("department").help_text)

    class Meta:
        model = Category
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].choices = departments.choices()


@admin.register(Category)
class CategoryAdmin(LoggedChanges, admin.ModelAdmin):
    form = CategoryForm
    list_display = ["name", "department_name", "hint", "is_active", "sort_order"]
    list_editable = ["hint", "is_active", "sort_order"]
    list_filter = [DepartmentListFilter]
    ordering = ["sort_order", "name"]

    def has_delete_permission(self, request, obj=None):
        # Retire a category by unticking Active; deleting would break old tickets.
        return False

    @admin.display(description="department", ordering="department")
    def department_name(self, obj):
        return departments.label(obj.department)


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class CommentInline(ReadOnlyInline):
    model = Comment
    fields = ["created_at", "author", "is_internal", "body"]
    readonly_fields = fields


class EventInline(ReadOnlyInline):
    model = TicketEvent
    fields = ["created_at", "actor", "kind", "old_value", "new_value", "note"]
    readonly_fields = fields


class AttachmentInline(ReadOnlyInline):
    model = Attachment
    fields = ["created_at", "original_name", "size", "uploaded_by", "comment"]
    readonly_fields = fields


class TicketCategoryFilter(admin.SimpleListFilter):
    """
    Categories: only the chosen department's when the department filter is
    set, otherwise all, each with its department's name. A category left over
    from another department is ignored.
    """

    title = "category"
    parameter_name = "category"

    def lookups(self, request, model_admin):
        department = request.GET.get(TicketDepartmentFilter.parameter_name, "")
        if department:
            return [(str(c.pk), c.name) for c in Category.objects.filter(department=department)]
        names = dict(departments.choices())
        return [(str(c.pk), f"{names.get(c.department, c.department)}: {c.name}") for c in Category.objects.all()]

    def value(self):
        value = super().value()
        return value if value in {key for key, _ in self.lookup_choices} else None

    def queryset(self, request, queryset):
        return queryset.filter(category_id=int(self.value())) if self.value() else queryset


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    """
    A read-only record view for admins. Day-to-day work happens in the app,
    where every change is logged in the ticket's history.
    """

    list_display = ["number", "subject", "status", "priority", "requester", "assignee", "category", "created_at"]
    list_filter = ["status", TicketDepartmentFilter, "priority", TicketCategoryFilter, "source", "archived_at"]
    search_fields = ["subject", "requester__display_name", "requester__email"]
    list_select_related = ["requester", "assignee", "category"]
    date_hierarchy = "created_at"
    inlines = [CommentInline, EventInline, AttachmentInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # The usage rules: never delete a ticket. Closed tickets are archived instead.
        return False

    @admin.display(description="#", ordering="pk")
    def number(self, obj):
        return f"#{obj.number}"


@admin.register(PasswordWarning)
class PasswordWarningAdmin(admin.ModelAdmin):
    """
    The audit trail of the "this might include a password" check. Read-only,
    and rows can't be deleted here, so the record stays complete.
    """

    list_display = ["created_at", "outcome", "place", "ticket_number", "user", "fields", "rules"]
    list_filter = ["outcome", "place", "created_at"]
    search_fields = ["user__display_name", "user__email"]
    list_select_related = ["user", "ticket"]
    date_hierarchy = "created_at"
    fields = ["created_at", "outcome", "place", "ticket", "comment", "user", "fields", "rules"]
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Ticket", ordering="ticket")
    def ticket_number(self, obj):
        return f"#{obj.ticket.number}" if obj.ticket_id else "-"

from django.contrib import admin

from tickets.models import Attachment, Category, Comment, PasswordWarning, Ticket, TicketEvent


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "hint", "is_active", "sort_order"]
    list_editable = ["hint", "is_active", "sort_order"]
    ordering = ["sort_order", "name"]

    def has_delete_permission(self, request, obj=None):
        # Retire a category by unticking Active; deleting would break old tickets.
        return False


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


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    """
    A read-only record view for admins. Day-to-day work happens in the app,
    where every change is logged in the ticket's history.
    """

    list_display = ["number", "subject", "status", "priority", "requester", "assignee", "category", "created_at"]
    list_filter = ["status", "priority", "category", "source"]
    search_fields = ["subject", "requester__display_name", "requester__email"]
    list_select_related = ["requester", "assignee", "category"]
    date_hierarchy = "created_at"
    inlines = [CommentInline, EventInline, AttachmentInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
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

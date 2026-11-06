from django.contrib import admin

from inbound.models import InboundEmail


@admin.register(InboundEmail)
class InboundEmailAdmin(admin.ModelAdmin):
    """Every email that reached the help-desk mailbox, and what happened to it."""

    list_display = ["created_at", "from_address", "subject", "outcome", "ticket", "attempts"]
    list_filter = ["outcome", "source"]
    search_fields = ["from_address", "subject", "message_id"]
    readonly_fields = [
        "message_id", "source", "from_address", "from_name", "subject", "received_at",
        "outcome", "detail", "attempts", "ticket", "created_at", "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

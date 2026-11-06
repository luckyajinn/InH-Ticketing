from django.contrib import admin, messages
from django.utils import timezone

from notifications.models import OutboundEmail


@admin.register(OutboundEmail)
class OutboundEmailAdmin(admin.ModelAdmin):
    """See what was emailed, to whom, and why anything failed."""

    list_display = ["created_at", "kind", "to", "subject", "status", "attempts", "sent_at"]
    list_filter = ["status", "kind"]
    search_fields = ["to", "subject"]
    readonly_fields = [
        "ticket", "kind", "to", "subject", "status", "attempts", "last_error",
        "next_attempt_at", "created_at", "sent_at", "body_text",
    ]
    exclude = ["body_html"]
    actions = ["retry_now"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Retry selected emails now")
    def retry_now(self, request, queryset):
        count = queryset.exclude(status=OutboundEmail.Status.SENT).update(
            status=OutboundEmail.Status.PENDING, attempts=0, next_attempt_at=timezone.now()
        )
        self.message_user(request, f"{count} email(s) queued again.", messages.SUCCESS)

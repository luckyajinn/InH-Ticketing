from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, LogEntry
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
        emails = list(queryset.exclude(status=OutboundEmail.Status.SENT))
        count = OutboundEmail.objects.filter(pk__in=[e.pk for e in emails]).update(
            status=OutboundEmail.Status.PENDING, attempts=0, next_attempt_at=timezone.now()
        )
        if emails:
            LogEntry.objects.log_actions(
                user_id=request.user.pk, queryset=emails, action_flag=CHANGE,
                change_message="Queued to send again (Retry selected emails now).",
            )
        self.message_user(request, f"{count} email(s) queued again.", messages.SUCCESS)

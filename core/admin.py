from decimal import Decimal

from django import forms
from django.contrib import admin
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.html import format_html
from django.utils.text import capfirst

from core import departments


class DepartmentListFilter(admin.SimpleListFilter):
    """Filter by department, showing their names (the field stores the key)."""

    title = "department"
    parameter_name = "department"
    field = "department"

    def lookups(self, request, model_admin):
        return departments.choices()

    def queryset(self, request, queryset):
        return queryset.filter(**{self.field: self.value()}) if self.value() else queryset


class TicketDepartmentFilter(DepartmentListFilter):
    field = "category__department"


# ---------------------------------------------------------------------------
# The admin log: every change made in the admin site, with the values
# ---------------------------------------------------------------------------

VALUE_LIMIT = 200  # characters of a value kept in the log, e.g. of a long list of common requests


def _choice_label(field, value):
    for key, label in field.choices:
        if isinstance(label, (list, tuple)):  # a group of choices
            found = dict(label).get(value)
            if found is not None:
                return found
        elif key == value:
            return label
    return value


def _shown(field, value) -> str:
    """A value as the log shows it: on one line, cut at VALUE_LIMIT."""
    if isinstance(field, forms.ModelChoiceField):
        if value not in (None, "") and not isinstance(value, models.Model):
            value = field.queryset.filter(pk=value).first() or value
    elif isinstance(field, forms.ChoiceField):
        value = _choice_label(field, value)
    if value is None or value == "":
        return "blank"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    text = " / ".join(line.strip() for line in str(value).splitlines() if line.strip())
    if len(text) > VALUE_LIMIT:
        text = text[:VALUE_LIMIT] + "…"
    return f'"{text}"'


def _label(form, name) -> str:
    return str(form.fields[name].label or capfirst(name.replace("_", " ")))


def change_message(form, add=False) -> str:
    """'Changed Entra app role: "Agent.Mech" → "Agent.Mechanics".', or what an added item was given."""
    if add:
        given = [f"{_label(form, name)}: {_shown(field, form.cleaned_data.get(name))}"
                 for name, field in form.fields.items() if name in form.cleaned_data]
        return "Added" + (f" with {'; '.join(given)}." if given else ".")
    changes = [
        f"{_label(form, name)}: {_shown(form.fields[name], form[name].initial)} → "
        f"{_shown(form.fields[name], form.cleaned_data.get(name))}"
        for name in form.changed_data if name in form.fields
    ]
    return f"Changed {'; '.join(changes)}." if changes else "No fields changed."


class LoggedChanges:
    """
    For a ModelAdmin: its log entries say what each field was and became, not
    only which fields changed. For admins without editable inlines.
    """

    def construct_change_message(self, request, form, formsets, add=False):
        return change_message(form, add=add)


ACTIONS = {ADDITION: "Added", CHANGE: "Changed", DELETION: "Deleted"}


class ActionFilter(admin.SimpleListFilter):
    title = "action"
    parameter_name = "action"

    def lookups(self, request, model_admin):
        return [(str(flag), label) for flag, label in ACTIONS.items()]

    def queryset(self, request, queryset):
        return queryset.filter(action_flag=int(self.value())) if self.value() in {"1", "2", "3"} else queryset


class TypeFilter(admin.SimpleListFilter):
    """The kinds of thing that have entries: Department, Category, User…"""

    title = "type"
    parameter_name = "type"

    def lookups(self, request, model_admin):
        types = ContentType.objects.filter(
            pk__in=LogEntry.objects.exclude(content_type=None).values("content_type").distinct())
        return sorted(((str(t.pk), capfirst(t.name)) for t in types), key=lambda choice: choice[1])

    def queryset(self, request, queryset):
        return queryset.filter(content_type_id=int(self.value())) if (self.value() or "").isdigit() else queryset


@admin.register(LogEntry)
class AdminLogAdmin(admin.ModelAdmin):
    """
    Every change made in this admin site: who, when, what and the values.
    Read-only, and nothing can be deleted here. Changes to tickets are made in
    the app, and each ticket's history records them.
    """

    list_display = ["when", "who", "action", "kind", "item", "details"]
    list_display_links = ["when"]
    list_filter = [ActionFilter, ("user", admin.RelatedOnlyFieldListFilter), TypeFilter, "action_time"]
    search_fields = ["object_repr", "change_message"]
    list_select_related = ["user", "content_type"]
    date_hierarchy = "action_time"
    ordering = ["-action_time"]
    fields = ["when", "who", "action", "kind", "item", "details"]
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="when", ordering="action_time")
    def when(self, obj):
        return obj.action_time

    @admin.display(description="who", ordering="user__display_name")
    def who(self, obj):
        return obj.user

    @admin.display(description="action", ordering="action_flag")
    def action(self, obj):
        return ACTIONS.get(obj.action_flag, obj.get_action_flag_display())

    @admin.display(description="type", ordering="content_type__model")
    def kind(self, obj):
        return capfirst(obj.content_type.name) if obj.content_type else "-"

    @admin.display(description="item", ordering="object_repr")
    def item(self, obj):
        url = None if obj.is_deletion() else obj.get_admin_url()
        return format_html('<a href="{}">{}</a>', url, obj.object_repr) if url else obj.object_repr

    @admin.display(description="details")
    def details(self, obj):
        return obj.get_change_message() or ACTIONS.get(obj.action_flag, "")

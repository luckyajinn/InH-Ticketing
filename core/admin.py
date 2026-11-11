from django.contrib import admin

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

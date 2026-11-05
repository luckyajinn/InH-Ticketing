"""Add the starting categories. Admins can rename, reorder or retire them later."""

from django.db import migrations

CATEGORIES = [
    ("Hardware", "laptop, monitor, printer, phone"),
    ("Software", "apps, installs, updates"),
    ("Access", "accounts, sign-in, shared drives"),
    ("Network", "Wi-Fi, VPN, internet"),
    ("Other", "if nothing else fits, or not sure"),
]


def add_categories(apps, schema_editor):
    Category = apps.get_model("tickets", "Category")
    for order, (name, hint) in enumerate(CATEGORIES, start=1):
        Category.objects.get_or_create(name=name, defaults={"hint": hint, "sort_order": order * 10})


def remove_categories(apps, schema_editor):
    Category = apps.get_model("tickets", "Category")
    Category.objects.filter(name__in=[name for name, _ in CATEGORIES], tickets__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("tickets", "0001_initial")]

    operations = [migrations.RunPython(add_categories, remove_categories)]

"""
Common requests for IT: printers (Hardware), passwords (Access) and Wi-Fi
(Network).

Only an IT category with no common requests yet gets them, so a list an admin
has already set up is left as it is. Admins change them in Admin, Categories.
Undoing this migration takes them out again where they're still unchanged.
"""

from django.db import migrations

IT_COMMON_REQUESTS = {
    "Hardware": [
        "Printer won't print, is jammed or shows offline",
        "Printer needs toner or a new cartridge",
    ],
    "Access": [
        "Forgot my password or locked out of my account",
        "Password expired or needs changing",
    ],
    "Network": [
        "Can't connect to the Wi-Fi",
        "Wi-Fi is slow or keeps dropping",
    ],
}


def _it_categories(apps):
    Category = apps.get_model("tickets", "Category")
    return Category.objects.filter(department="it", name__in=IT_COMMON_REQUESTS)


def add_requests(apps, schema_editor):
    for category in _it_categories(apps):
        if not category.subject_options.strip():
            category.subject_options = "\n".join(IT_COMMON_REQUESTS[category.name])
            category.save(update_fields=["subject_options"])


def remove_requests(apps, schema_editor):
    for category in _it_categories(apps):
        if category.subject_options == "\n".join(IT_COMMON_REQUESTS[category.name]):
            category.subject_options = ""
            category.save(update_fields=["subject_options"])


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0008_department"),
    ]

    operations = [
        migrations.RunPython(add_requests, remove_requests),
    ]

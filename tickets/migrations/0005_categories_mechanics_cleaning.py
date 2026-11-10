"""
Quick-pick subjects for categories ("common requests"), and two categories for
other teams: Mechanics, and Cleaning & sanitization, with three common
requests each. Admins can edit the lists, add more, or untick Active.
"""

from django.db import migrations, models

NEW_CATEGORIES = [
    (
        "Mechanics", "machines, equipment, facility repairs", 44,
        [
            "Equipment down: a machine won't start or has stopped",
            "Leak, unusual noise or vibration on equipment",
            "Facility repair: door, lighting, plumbing or HVAC",
        ],
    ),
    (
        "Cleaning & sanitization", "spills, rooms, cleaning supplies", 46,
        [
            "Spill or mess that needs cleaning up",
            "Room or area needs cleaning and sanitizing",
            "Cleaning or sanitizing supplies running low",
        ],
    ),
]


def add_categories(apps, schema_editor):
    Category = apps.get_model("tickets", "Category")
    for name, hint, order, subjects in NEW_CATEGORIES:
        Category.objects.get_or_create(
            name=name,
            defaults={"hint": hint, "sort_order": order, "subject_options": "\n".join(subjects)},
        )


def remove_categories(apps, schema_editor):
    Category = apps.get_model("tickets", "Category")
    Category.objects.filter(name__in=[c[0] for c in NEW_CATEGORIES], tickets__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("tickets", "0004_password_warnings")]

    operations = [
        migrations.AddField(
            model_name="category",
            name="subject_options",
            field=models.TextField(
                blank=True,
                help_text="One subject per line. Shown as quick picks on the New request form, which fill "
                          "in the subject and this category; people can still type their own.",
                verbose_name="common requests",
            ),
        ),
        migrations.RunPython(add_categories, remove_categories),
    ]

"""
Quick-pick subjects for categories ("common requests").

Until v0.10.0 this also added two categories for other teams, Mechanics and
Cleaning & sanitization. Databases that ran it then keep them (0008 turns them
into departments). A new install starts with IT only, and an admin adds its own
departments; the demo data adds those two as examples (tickets/examples.py).
"""

from django.db import migrations, models


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
    ]

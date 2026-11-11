"""
Departments become a table that admins edit (Tickets > Departments), instead
of a fixed list of IT, Mechanics, and Cleaning & sanitization.

Every department already in use (by a category, a person or an internal note)
gets a row with the same key, so no ticket changes. Their Entra roles and alert
addresses are copied from the old settings (ENTRA_ROLE_AGENT_MECHANICS,
ENTRA_ROLE_AGENT_CLEANING, DEPARTMENT_NOTIFY_EMAILS), which are no longer read
after this. A new install gets IT only.
"""

import os

from django.db import migrations, models

import django.core.validators

NAMES = {"it": "IT", "mechanics": "Mechanics", "cleaning": "Cleaning & sanitization"}
OLD_ROLES = {"mechanics": ("ENTRA_ROLE_AGENT_MECHANICS", "Agent.Mechanics"),
             "cleaning": ("ENTRA_ROLE_AGENT_CLEANING", "Agent.Cleaning")}


def _old_alert_addresses() -> dict[str, str]:
    """DEPARTMENT_NOTIFY_EMAILS, "mechanics=a@example.com, cleaning=b@example.com", read leniently."""
    found = {}
    for part in os.environ.get("DEPARTMENT_NOTIFY_EMAILS", "").replace(";", ",").split(","):
        key, _, value = part.partition("=")
        if key.strip() and "@" in value:
            found[key.strip().lower()] = value.strip()
    return found


def add_departments(apps, schema_editor):
    Department = apps.get_model("tickets", "Department")
    Category = apps.get_model("tickets", "Category")
    Comment = apps.get_model("tickets", "Comment")
    User = apps.get_model("accounts", "User")
    used = {"it"}
    used |= set(Category.objects.values_list("department", flat=True))
    used |= set(User.objects.exclude(department="").values_list("department", flat=True))
    used |= set(Comment.objects.exclude(department="").values_list("department", flat=True))
    known = list(NAMES)
    alerts = _old_alert_addresses()
    for colour, key in enumerate(sorted(used, key=lambda k: (known.index(k) if k in known else len(known), k)), 1):
        name = NAMES.get(key) or key.replace("-", " ").capitalize()
        setting, default = OLD_ROLES.get(key, ("", f"Agent.{name.replace(' ', '')}"))
        Department.objects.create(
            key=key, name=name, colour=colour,
            entra_role="" if key == "it" else (os.environ.get(setting, "").strip() if setting else "") or default,
            alert_email="" if key == "it" else alerts.get(key, ""),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_user_department"),
        ("tickets", "0007_departments_and_archive"),
    ]

    operations = [
        migrations.CreateModel(
            name="Department",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(
                    help_text='A short name, e.g. "mechanics", used in settings such as DEPARTMENT_MAILBOXES. '
                              "It can't be changed later.",
                    max_length=16, unique=True,
                    validators=[django.core.validators.RegexValidator(
                        "^[a-z][a-z0-9-]*\\Z", "Lower-case letters, digits and hyphens, starting with a letter.")],
                )),
                ("name", models.CharField(help_text='As people see it, e.g. "Mechanics".', max_length=40, unique=True)),
                ("entra_role", models.CharField(
                    blank=True, max_length=100, verbose_name="Entra app role",
                    help_text='The value of the Entra app role that makes someone this department\'s agent, e.g. '
                              '"Agent.Mechanics". Create the role in Entra with exactly this value.',
                )),
                ("alert_email", models.EmailField(
                    blank=True, max_length=254, verbose_name="alert address",
                    help_text="Where its new-request and unassigned-reply alerts go: a team list, or a Teams "
                              "channel's email address. Blank: to each of its agents.",
                )),
                ("colour", models.PositiveSmallIntegerField(
                    choices=[(1, "Teal"), (2, "Orange"), (3, "Blue"), (4, "Yellow"), (5, "Pink"), (6, "Green"),
                             (7, "Violet"), (8, "Red")],
                    editable=False, unique=True,
                    help_text="Its colour in Reports, given in the order departments are added.",
                )),
            ],
            options={"ordering": ["colour"]},
        ),
        migrations.RunPython(add_departments, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="category",
            name="department",
            field=models.CharField(
                default="it", max_length=16,
                help_text="Which department works these requests. Only admins move a ticket to another department.",
            ),
        ),
        migrations.AlterField(
            model_name="comment",
            name="department",
            field=models.CharField(blank=True, max_length=16),
        ),
    ]

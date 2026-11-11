# Departments are a table now (tickets.Department), so the field lists no fixed choices.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_user_department")]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="department",
            field=models.CharField(
                blank=True, max_length=16,
                help_text="The department an agent works for, from their Entra app role. Admins work for all of them.",
            ),
        ),
    ]

"""
The departments that work tickets. Each category belongs to one; each agent
works for one (from their Entra app role); admins work for all of them.
"""

from django.db import models


class Department(models.TextChoices):
    IT = "it", "IT"
    MECHANICS = "mechanics", "Mechanics"
    CLEANING = "cleaning", "Cleaning & sanitization"

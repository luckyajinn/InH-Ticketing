from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    A person who uses InH-Ticketing.

    People are created automatically the first time they sign in with Microsoft
    365. Their name, email and role are refreshed from Entra on every sign-in,
    so Entra stays the single source of truth.
    """

    class Role(models.TextChoices):
        REQUESTER = "requester", "Requester"
        AGENT = "agent", "Agent"
        ADMIN = "admin", "Admin"

    # Entra's permanent ID for the person (the `oid` claim). Names and email
    # addresses can change; this never does, so it is what we match on.
    entra_oid = models.UUIDField(
        "Entra object ID", unique=True, null=True, blank=True, editable=False
    )
    display_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.REQUESTER,
        help_text="Managed in Entra (app roles). Refreshed on every sign-in.",
    )

    class Meta:
        ordering = ["display_name", "username"]

    def __str__(self) -> str:
        return self.display_name or self.get_full_name() or self.email or self.username

    @property
    def is_agent(self) -> bool:
        """Agents and admins both work tickets."""
        return self.role in {self.Role.AGENT, self.Role.ADMIN}

    @property
    def avatar_variant(self) -> int:
        """One of six avatar colours, stable per person."""
        return (self.pk or 0) % 6 + 1

    @property
    def initials(self) -> str:
        parts = str(self).replace(".", " ").split()
        return "".join(p[0] for p in parts[:2]).upper() or "?"

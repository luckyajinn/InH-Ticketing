"""
The departments that work tickets. IT is built in; an admin adds the others in
the admin site (Tickets > Departments). Each category belongs to one; each agent
works for one, from their Entra app role; admins work for all of them.

Tickets, notes and people store a department's key ("it", "mechanics"). These
helpers look up the rest from tickets.models.Department.
"""

from django.conf import settings

IT = "it"
IT_NAME = "IT"


def _model():
    from tickets.models import Department  # tickets.models imports this module

    return Department


def all_departments() -> list:
    """Every department, IT first, then in the order they were added."""
    return list(_model().objects.all())


def keys() -> list[str]:
    return list(_model().objects.values_list("key", flat=True))


def choices() -> list[tuple[str, str]]:
    """(key, name) pairs, for forms and filters."""
    return list(_model().objects.values_list("key", "name"))


def get(key: str):
    return _model().objects.filter(key=key).first() if key else None


def label(key: str) -> str:
    """A department's name ("" for no department)."""
    if not key:
        return ""
    name = _model().objects.filter(key=key).values_list("name", flat=True).first()
    return name or (IT_NAME if key == IT else key)


def names(conjunction: str = "and") -> str:
    """ "IT", "IT and Mechanics", "IT, Mechanics, and Cleaning & sanitization"."""
    found = [name for _, name in choices()] or [IT_NAME]
    if len(found) <= 2:
        return f" {conjunction} ".join(found)
    return f"{', '.join(found[:-1])}, {conjunction} {found[-1]}"


def agent_roles() -> list[tuple[str, str]]:
    """Entra role value -> department, in order of precedence: IT's (ENTRA_ROLE_AGENT) first."""
    others = _model().objects.exclude(key=IT).exclude(entra_role="").values_list("entra_role", "key")
    return [(settings.ENTRA_ROLE_AGENT, IT), *others]

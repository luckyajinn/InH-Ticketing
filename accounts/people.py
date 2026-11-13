"""
The people the app knows, and adding someone it doesn't know yet.

Everyone who signs in has an account (accounts/entra.py). Someone who emails
the help desk before ever signing in gets one too, as does someone staff open
a request for: username "email:<address>", with no Entra ID yet. The first
time they sign in, it's linked to their Microsoft 365 account (sync_user), so
their tickets follow them, and their name and email come from Entra from then on.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Q

from accounts.models import User

SEARCH_MIN_CHARS = 2
SEARCH_LIMIT = 8


def by_email(address: str) -> User | None:
    """The account with this email address, an active one first, or None."""
    address = (address or "").strip()
    if not address:
        return None
    return User.objects.filter(email__iexact=address).order_by("-is_active", "pk").first()


def add(address: str, name: str = "") -> User:
    """An account for someone the app hasn't seen yet (or theirs, if it was just made)."""
    address = address.strip().lower()
    user, _ = User.objects.get_or_create(
        username=f"email:{address}"[:150],
        defaults={
            "email": address,
            "display_name": (" ".join((name or "").split()) or address)[:255],
            "role": User.Role.REQUESTER,
        },
    )
    return user


def work_domains(fallback: User | None = None) -> list[str]:
    """
    The organisation's email domains: INBOUND_ALLOWED_DOMAINS (by default, the
    help-desk mailbox's domain). With neither set, as on a PC without a
    mailbox, the domain of the person asking.
    """
    if settings.INBOUND_ALLOWED_DOMAINS:
        return list(settings.INBOUND_ALLOWED_DOMAINS)
    if fallback is not None and "@" in (fallback.email or ""):
        return [fallback.email.rsplit("@", 1)[-1].lower()]
    return []


def search(text: str, limit: int = SEARCH_LIMIT):
    """
    Active people whose name or email contains every word typed, for staff
    picking who a request is for. Nothing for fewer than SEARCH_MIN_CHARS, so
    it never lists everyone.
    """
    words = " ".join((text or "").split())[:100].split()
    if len("".join(words)) < SEARCH_MIN_CHARS:
        return User.objects.none()
    query = Q()
    for word in words:
        query &= Q(display_name__icontains=word) | Q(email__icontains=word)
    return (
        User.objects.filter(query, is_active=True)
        .exclude(email="")
        .order_by("display_name", "pk")[:limit]
    )

from django import template
from django.utils import timezone
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def icon(name: str, extra_class: str = ""):
    """Inline an icon from the sprite in templates/partials/icons.html."""
    css = f"icon {extra_class}".strip()
    return format_html(
        '<svg class="{}" aria-hidden="true" focusable="false"><use href="#i-{}"/></svg>', css, name
    )


def _age_parts(value):
    seconds = max(0, int((timezone.now() - value).total_seconds()))
    minutes = seconds // 60
    if minutes < 60:
        return max(minutes, 1), "m", "minute"
    hours = minutes // 60
    if hours < 24:
        return hours, "h", "hour"
    days = hours // 24
    if days < 14:
        return days, "d", "day"
    return days // 7, "w", "week"


@register.filter
def short_age(value):
    """'14m', '4h', '2d', '3w' for the dense queue table."""
    if not value:
        return ""
    number, unit, _ = _age_parts(value)
    return f"{number}{unit}"


@register.filter
def ago(value):
    """'just now', '14 minutes ago', '2 days ago'."""
    if not value:
        return ""
    if (timezone.now() - value).total_seconds() < 60:
        return "just now"
    number, _, word = _age_parts(value)
    return f"{number} {word}{'' if number == 1 else 's'} ago"


@register.filter
def long_age(value):
    """'2 days old', for screen readers next to the short form."""
    if not value:
        return ""
    number, _, word = _age_parts(value)
    return f"{number} {word}{'' if number == 1 else 's'} old"

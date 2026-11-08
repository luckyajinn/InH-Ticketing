"""
Reading the app's pages, for the load generator. STRESS-TEST BRANCH ONLY.

Kept apart from locustfile.py, and free of Locust, so the Django tests
(stresstest/tests/test_load_pages.py) can check these patterns against the
real pages. If a template changes, a test fails instead of the load test
quietly skipping actions.
"""

from __future__ import annotations

import re

TICKET_LINK = re.compile(r'href="/tickets/(\d+)/"')
ATTACHMENT_LINK = re.compile(r'href="(/attachments/\d+/[^"]+)"')
TICKET_PATH = re.compile(r"/tickets/(\d+)/$")


def ticket_numbers(html: str) -> list[str]:
    """Ticket numbers linked from a page, in page order, without repeats."""
    return list(dict.fromkeys(TICKET_LINK.findall(html or "")))


def attachment_links(html: str) -> list[str]:
    """Download links for the attachments shown on a ticket page."""
    return list(dict.fromkeys(ATTACHMENT_LINK.findall(html or "")))


def _select(html: str, name: str) -> str | None:
    match = re.search(rf'<select\b[^>]*\sname="{re.escape(name)}"[^>]*>(.*?)</select>', html or "", re.S)
    return match.group(1) if match else None


def options(html: str, name: str) -> list[str]:
    """The non-empty option values of the <select> called `name`."""
    block = _select(html, name)
    return [v for v in re.findall(r'<option value="([^"]*)"', block or "") if v]


def selected(html: str, name: str) -> str | None:
    """The selected value of the <select> called `name` (None if there's no such select)."""
    block = _select(html, name)
    if block is None:
        return None
    match = re.search(r'<option value="([^"]*)"[^>]*\sselected\b', block)
    return match.group(1) if match else ""


def side_panel(html: str) -> dict[str, str] | None:
    """The IT side panel's current values (status, priority, assignee, category), or None if absent."""
    values = {name: selected(html, name) for name in ("status", "priority", "assignee", "category")}
    if any(values[name] in (None, "") for name in ("status", "priority", "category")):
        return None
    values["assignee"] = values["assignee"] or ""
    return values


def ticket_from_location(location: str) -> str | None:
    """The ticket number a form redirected to, e.g. '/tickets/1234/' -> '1234'."""
    match = TICKET_PATH.search(location or "")
    return match.group(1) if match else None

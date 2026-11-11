"""
Build the clickable mockup, mockups/ui-mockup.html, from the app's own pages.

    python manage.py seed_demo          # once, into a development database
    python manage.py build_mockup

Each screen is the real page as one of the fictional demo people sees it: a
requester, an IT agent, a Mechanics agent and an admin, plus the sign-in page.
Pages are rendered here (no server or browser needed) and packed into one
self-contained HTML file, with the app's stylesheet and script inside it.

In the mockup, a bar at the top switches who you're viewing as, the screen,
desktop or phone width, and light or dark. Links in the pages go to the
matching screen. Forms do nothing: nothing is sent or saved. Run it again
after a release to bring the mockup up to date.
"""

import base64
import mimetypes
import posixpath
import re
from collections import deque
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string
from django.test import Client
from django.utils import timezone

from accounts.models import User
from core.context_processors import app_info
from core import departments
from tickets.models import Ticket

APP_NAME = app_info(None)["APP_NAME"]
DEFAULT_OUT = Path(settings.BASE_DIR) / "mockups" / "ui-mockup.html"
MAX_PAGES = 60  # per person, so the file stays a few MB at most

# Who the mockup shows the app as: (id, menu label, demo username, how the bar describes them).
PEOPLE = [
    ("visitor", "Signed out", None, ""),
    ("requester", "Requester", "demo-dana", "a requester"),
    ("it", "IT agent", "demo-sam", "an IT agent"),
    ("mechanics", "Mechanics agent", "demo-mo", "a Mechanics agent"),
    ("admin", "Admin", "demo-riley", "an admin"),
]
STAFF = {"it", "mechanics", "admin"}
ADMIN_PAGES = ("/reports/", "/admin/", "/admin/tickets/department/", "/admin/tickets/department/add/")

TICKET_PAGE = re.compile(r"/tickets/(\d+)/")
REMOVE_PAGE = re.compile(r"/tickets/(\d+)/remove/")
LINK = re.compile(r'\b(?:href|data-href)="([^"]*)"')
ELSEWHERE = re.compile(r"[a-z][a-z0-9+.-]*:|//|#", re.IGNORECASE)  # another site, mailto:, or a place on the page
TAG = re.compile(r"<(link|script|img)\b([^>]*)>(?:</script>)?", re.IGNORECASE)
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""")


def normalize(url: str) -> str:
    """The path, then the query without empty values or "next", sorted (as the mockup's script does)."""
    parts = urlsplit(url)
    query = sorted((k, v) for k, v in parse_qsl(parts.query) if v and k != "next")
    return parts.path + ("?" + urlencode(query) if query else "")


class Command(BaseCommand):
    help = "Build the clickable mockup (mockups/ui-mockup.html) from the app's pages, using demo data."

    def add_arguments(self, parser):
        parser.add_argument("--out", default=str(DEFAULT_OUT), help="Where to write it (default: %(default)s)")

    def handle(self, *args, out, **options):
        if not settings.DEBUG:
            raise CommandError("The mockup is built from a development database (DEBUG=True).")
        users = {key: User.objects.filter(username=name).first() for key, _, name, _ in PEOPLE if name}
        tickets = self._tickets()
        if not all(users.values()) or not all(tickets.values()):
            raise CommandError("Demo data not found, or from an older version. "
                               "Run: python manage.py seed_demo --clear, then seed_demo")

        self.assets: dict[str, str] = {"mockup:frame": self._script(render_to_string("mockup/frame.js"))}
        self.icons = render_to_string("partials/icons.html")
        screens = self._screens(tickets)
        self.remove_ticket = tickets["outlook"].number

        pages, aliases, roles = {}, {}, []
        for role, label, username, described in PEOPLE:
            user = users.get(role)
            start = [s["url"] for s in screens[role]] + self._form_pages(role)
            crawled, redirects = self._crawl(role, user, start)
            missing = [s["url"] for s in screens[role] if self._resolve(s["url"], crawled, redirects) is None]
            if missing:
                raise CommandError(f"{label}: couldn't render {', '.join(missing)}")
            pages.update({f"{role} {url}": page for url, page in crawled.items()})
            aliases.update({f"{role} {url}": f"{role} {target}" for url, target in redirects.items()})
            roles.append({
                "id": role, "label": label, "screens": screens[role],
                "who": f"{user.display_name}, {described}" if user else "",
            })
            self.stdout.write(f"  {label}: {len(crawled)} pages")

        today = timezone.localdate()
        data = {
            "roles": roles, "pages": pages, "aliases": aliases, "assets": self.assets, "icons": self.icons,
            "footer": f"(Built from {APP_NAME} v{settings.APP_VERSION} on {today:%b} {today.day}, {today.year}, "
                      "with fictional demo data. Nothing is sent or saved.)",
        }
        icon = self._data_uri("icons/icon.svg")
        html = render_to_string("mockup/shell.html", {"data": data, "app_name": APP_NAME, "icon": icon})
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8", newline="\n")
        size = target.stat().st_size / 1_000_000
        self.stdout.write(self.style.SUCCESS(f"Wrote {target} ({len(pages)} pages, {size:.1f} MB)."))

    # ------------------------------------------------------------------
    # What to show
    # ------------------------------------------------------------------
    def _tickets(self) -> dict:
        demo = Ticket.objects.filter(requester__username__startswith="demo-")
        return {
            "outlook": demo.filter(subject="Outlook keeps prompting for my password").first(),
            "filler": demo.filter(category__name="Mechanics", assignee__username="demo-mo").first(),
            "conveyor": demo.filter(subject="Line 1 conveyor screen keeps freezing").first(),
            "archived": demo.filter(archived_at__isnull=False).order_by("-archived_at").first(),
        }

    def _screens(self, t: dict) -> dict[str, list[dict]]:
        """The screens listed in the bar for each person; links reach the rest."""
        def screen(label, url, note):
            return {"label": label, "url": normalize(url), "note": note}

        outlook, filler, conveyor, archived = (t[k].get_absolute_url() for k in ("outlook", "filler", "conveyor", "archived"))
        return {
            "visitor": [
                screen("Sign-in", "/signin/", "Everyone signs in with their Microsoft 365 work account. "
                       "Choose the button to continue as the demo requester."),
            ],
            "requester": [
                screen("My tickets", "/tickets/", "A requester sees only their own requests."),
                screen("New request", "/tickets/new/", "Common requests fill in the subject. Anything that "
                       "looks like a password gets a warning before it's sent: try typing one."),
                screen("A request", outlook, "The conversation with IT. Staff's internal notes never show here."),
                screen("Usage and privacy", "/about/", "What the app keeps, who sees it, and for how long."),
            ],
            "it": [
                screen("Queue", "/queue/", "IT's open tickets, most urgent first. Mechanics' and Cleaning "
                       "& sanitization's tickets aren't here."),
                screen("A ticket", outlook, "Replies, internal notes, the history and the ticket's details "
                       "on one page. Switch the composer to Internal note to see the difference."),
                screen("Archive", "/queue/?view=archive", "Closed tickets: read-only, and kept for two years."),
                screen("An archived ticket", archived, "Read-only. If the problem comes back, the requester "
                       "starts a follow-up."),
            ],
            "mechanics": [
                screen("Queue", "/queue/", "A Mechanics agent sees and works only Mechanics' tickets."),
                screen("A ticket", filler, "Internal notes stay with Mechanics, unless shared when an admin "
                       "moves the ticket. \"Wrong department?\" asks an admin to move it."),
            ],
            "admin": [
                screen("Queue", "/queue/", "Admins see every department's tickets, with a department filter."),
                screen("Move request", conveyor, "IT asked for this to go to Mechanics. Only an admin moves "
                       "it, once Mechanics has agreed."),
                screen("Remove a password", f"{outlook}remove/?part=description", "Admins take a pasted "
                       "password out of a ticket and the app's copies of its emails. The history says "
                       "something was removed, never what."),
                screen("Reports", "/reports/", "Totals for each team, never for one person."),
                screen("Departments", "/admin/tickets/department/", "Admins add the teams that work tickets: "
                       "IT is built in, and each other department has its own Entra role, categories and colour."),
                screen("Admin site", "/admin/", "Categories, people and settings, in the app's look."),
            ],
        }

    @staticmethod
    def _form_pages(role: str) -> list[str]:
        """Pages reached only through a form (the queue's department filter), so not found by following links."""
        return [normalize(f"/queue/?dept={key}") for key in departments.keys()] if role == "admin" else []

    def _allowed(self, role: str, url: str) -> bool:
        """Pages worth having in the mockup: no searches, downloads or side effects."""
        parts = urlsplit(url)
        path, keys = parts.path, {k for k, _ in parse_qsl(parts.query)}
        if role == "visitor":
            return path == "/signin/"
        if path == "/queue/":
            return role in STAFF and keys <= ({"view", "dept"} if role == "admin" else {"view"})
        if path == "/tickets/":
            return keys <= {"show"}
        if path == "/about/":
            return not keys
        if path == "/tickets/new/":
            return keys <= {"follow_up"}
        if path in ADMIN_PAGES:
            return role == "admin" and not keys
        if match := REMOVE_PAGE.fullmatch(path):
            return role == "admin" and int(match[1]) == self.remove_ticket and keys == {"part"}
        return bool(TICKET_PAGE.fullmatch(path)) and not keys

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _crawl(self, role: str, user, start: list[str]):
        """Render the starting screens, then the pages they link to, as this person."""
        client = Client(HTTP_HOST="localhost")
        if user:
            client.force_login(user)
        pages, redirects = {}, {}
        todo, seen = deque(start + ["/"]), set(start + ["/"])
        try:
            while todo and len(pages) < MAX_PAGES:
                url = todo.popleft()
                response = client.get(url)
                if response.status_code in (301, 302):
                    target = normalize(urljoin(url, response["Location"]))
                    redirects[url] = target
                    if target not in seen and self._allowed(role, target):
                        seen.add(target)
                        todo.appendleft(target)
                    continue
                if response.status_code != 200 or "text/html" not in response.get("Content-Type", ""):
                    continue
                html = response.content.decode("utf-8")
                pages[url] = self._pack(html)
                for href in LINK.findall(html):
                    href = unescape(href)
                    if not href or ELSEWHERE.match(href):
                        continue
                    link = normalize(urljoin(url, href))
                    if link not in seen and self._allowed(role, link):
                        seen.add(link)
                        todo.append(link)
        finally:
            client.logout()  # deletes the session it signed in with
        return pages, redirects

    @staticmethod
    def _resolve(url, pages, redirects):
        for _ in range(5):
            if url in pages:
                return url
            url = redirects.get(url)
        return None

    def _pack(self, html: str) -> dict:
        """One page, ready for the mockup: its files kept once, separately; nothing that would load from a server."""
        title = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
        # The demo server has no Entra values, so the sign-in page asks for them. Show it as configured.
        html = re.sub(r'\s*<p class="setup-warning"[\s\S]*?</p>', "", html)
        html = html.replace('aria-disabled="true" tabindex="-1"', "")
        if html.count(self.icons) == 1:
            html = html.replace(self.icons, "<!--mockup:icons-->")
        html = TAG.sub(self._tag, html)
        html = re.sub(r"<head>", '<head>\n<script data-mockup-asset="mockup:frame"></script>', html, count=1)
        return {"title": unescape(title[1]).strip() if title else "", "html": html}

    def _tag(self, match) -> str:
        kind, attrs = match[1].lower(), dict(ATTR.findall(match[2]))
        if kind == "link":
            href = attrs.get("href", "")
            if attrs.get("rel") == "stylesheet" and self._static(href):
                return f'<style data-mockup-asset="{self._asset(href, "css")}"></style>'
            return "" if attrs.get("rel") in ("icon", "apple-touch-icon", "manifest", "stylesheet") else match[0]
        if kind == "script":
            src = attrs.get("src")
            if not src:
                return match[0]  # an inline script: kept as it is
            name = self._static(src)
            # The admin site's own scripts (jQuery and the form helpers) do nothing useful in a
            # mockup and would double its size; its theme script is the one kept.
            if not name or (name.startswith("admin/js/") and name != "admin/js/theme.js"):
                return ""
            return f'<script data-mockup-asset="{self._asset(src, "js")}"></script>'
        src = attrs.get("src", "")
        return match[0].replace(f'src="{src}"', f'src="{self._data_uri(self._static(src))}"') if self._static(src) else match[0]

    @staticmethod
    def _static(url: str) -> str:
        """The static file a URL points to ("css/app.css"), or "" if it isn't one."""
        path = urlsplit(unescape(url)).path
        return path[len(settings.STATIC_URL):] if path.startswith(settings.STATIC_URL) else ""

    def _asset(self, url: str, kind: str) -> str:
        name = self._static(url)
        if name not in self.assets:
            text = self._read(name).decode("utf-8")
            self.assets[name] = self._inline_urls(text, name) if kind == "css" else self._script(text)
        return name

    @staticmethod
    def _script(text: str) -> str:
        return text.replace("</script", "<\\/script")

    def _inline_urls(self, css: str, name: str) -> str:
        """Images and fonts a stylesheet refers to, put inside it."""
        def inline(match):
            ref = match[2].strip()
            if ref.startswith(("data:", "#", "http:", "https:", "//")):
                return match[0]
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), urlsplit(ref).path))
            return f'url("{self._data_uri(target)}")'
        return CSS_URL.sub(inline, css)

    def _data_uri(self, name: str) -> str:
        kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return f"data:{kind};base64,{base64.b64encode(self._read(name)).decode('ascii')}"

    @staticmethod
    def _read(name: str) -> bytes:
        path = finders.find(name)
        if not path:
            raise CommandError(f"Static file not found: {name}")
        return Path(path).read_bytes()

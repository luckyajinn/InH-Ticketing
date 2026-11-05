"""
Take the screenshots for a version's release notes.

    python manage.py seed_demo                       # once, if not done yet
    python manage.py runserver                       # in another terminal
    python manage.py release_screenshots --out docs/releases/v0.2.0

Uses the Microsoft Edge already installed on this PC (through Playwright, a
development-only package in requirements-dev.txt). Pages are captured as the
fictional demo people, in light mode, at desktop and phone sizes. The
temporary sign-in sessions it creates are deleted when it finishes.
"""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from tickets.models import Ticket

DESKTOP = {"width": 1280, "height": 800}
PHONE = {"width": 390, "height": 844}
SAMPLE_SUBJECT = "Outlook keeps prompting for my password"


class Command(BaseCommand):
    help = "Capture release-note screenshots of the running dev server, using demo data."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="Folder for the PNG files, e.g. docs/releases/v0.2.0")
        parser.add_argument("--base-url", default="http://localhost:8000")

    def handle(self, *args, out, base_url, **options):
        if not settings.DEBUG:
            raise CommandError("Screenshots are taken from a development server (DEBUG=True).")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise CommandError("Install the dev tools first: pip install -r requirements-dev.txt") from exc

        requester = User.objects.filter(username="demo-dana").first()
        agent = User.objects.filter(username="demo-sam").first()
        sample = Ticket.objects.filter(subject=SAMPLE_SUBJECT, requester=requester).first()
        if not (requester and agent and sample):
            raise CommandError("Demo data not found. Run: python manage.py seed_demo")

        # Database work happens before and after the browser runs: Playwright's
        # sync API runs an event loop, and Django refuses ORM calls inside one.
        sessions = {"requester": self._session_for(requester), "agent": self._session_for(agent)}
        out_dir = Path(out)
        out_dir.mkdir(parents=True, exist_ok=True)
        base_url = base_url.rstrip("/")
        sample_url = sample.get_absolute_url()

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="msedge", headless=True)
                try:
                    shots = self._capture(browser, base_url, sessions, sample_url, out_dir)
                finally:
                    browser.close()
        finally:
            Session.objects.filter(session_key__in=sessions.values()).delete()

        for name in shots:
            self.stdout.write(f"  {out_dir / name}")
        self.stdout.write(self.style.SUCCESS(f"Saved {len(shots)} screenshots."))

    def _session_for(self, user) -> str:
        session = SessionStore()
        session[SESSION_KEY] = str(user.pk)
        session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
        session[HASH_SESSION_KEY] = user.get_session_auth_hash()
        session.create()
        return session.session_key

    def _capture(self, browser, base_url, sessions, sample_url, out_dir) -> list[str]:
        saved = []

        def page_for(who, viewport):
            context = browser.new_context(viewport=viewport, color_scheme="light", device_scale_factor=1)
            if who:
                context.add_cookies([{
                    "name": settings.SESSION_COOKIE_NAME, "value": sessions[who], "url": base_url,
                }])
            return context.new_page()

        def shoot(name, who, path, viewport=DESKTOP, full_page=False, prepare=None, element=None):
            page = page_for(who, viewport)
            response = page.goto(base_url + path, wait_until="load")
            if response is None or response.status >= 400:
                raise CommandError(f"{path} returned {response.status if response else 'nothing'}")
            if prepare:
                prepare(page)
            target = out_dir / name
            if element:
                page.locator(element).screenshot(path=str(target))
            else:
                page.screenshot(path=str(target), full_page=full_page)
            page.context.close()
            saved.append(name)

        def as_configured(page):
            # The dev server has no Entra values, so it shows a setup notice.
            # Show the page as staff will see it once Entra is configured.
            page.evaluate(
                "document.querySelector('.setup-warning')?.remove();"
                "document.querySelector('[aria-disabled]')?.removeAttribute('aria-disabled');"
            )

        def internal_mode(page):
            page.click("label[for=mode-internal]")
            page.fill("#composer-text", "Re-enrolment fixed the other two laptops. Booking 2:30 with Dana.")

        shoot("01-sign-in.png", None, "/signin/", prepare=as_configured)
        shoot("02-my-tickets.png", "requester", "/tickets/")
        shoot("03-new-request.png", "requester", "/tickets/new/", full_page=True)
        shoot("04-requester-ticket.png", "requester", sample_url, full_page=True)
        shoot("05-queue.png", "agent", "/queue/")
        shoot("06-agent-ticket.png", "agent", sample_url, full_page=True)
        shoot("07-internal-note-composer.png", "agent", sample_url, prepare=internal_mode, element=".composer")
        shoot("08-queue-phone.png", "agent", "/queue/", viewport=PHONE)
        shoot("09-requester-ticket-phone.png", "requester", sample_url, viewport=PHONE)
        return saved

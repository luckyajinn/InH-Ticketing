"""
Take the screenshots for a version's release notes.

    python manage.py seed_demo                       # once, if not done yet
    python manage.py runserver                       # in another terminal
    python manage.py release_screenshots --out docs/releases/v0.2.0
    python manage.py release_screenshots --out docs/releases/v0.3.0 --only 06,10,11,12

--only takes the numbers of the shots you want (the start of each file name),
so a version only stores screenshots of what changed.

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
from notifications.models import OutboundEmail
from tickets.models import Category, Ticket

DESKTOP = {"width": 1280, "height": 800}
PHONE = {"width": 390, "height": 844}
SAMPLE_SUBJECT = "Outlook keeps prompting for my password"


class Command(BaseCommand):
    help = "Capture release-note screenshots of the running dev server, using demo data."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="Folder for the PNG files, e.g. docs/releases/v0.2.0")
        parser.add_argument("--base-url", default="http://localhost:8000")
        parser.add_argument("--only", default="", help="Comma-separated shot numbers, e.g. 06,10")

    def handle(self, *args, out, base_url, only, **options):
        if not settings.DEBUG:
            raise CommandError("Screenshots are taken from a development server (DEBUG=True).")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise CommandError("Install the dev tools first: pip install -r requirements-dev.txt") from exc

        requester = User.objects.filter(username="demo-dana").first()
        agent = User.objects.filter(username="demo-sam").first()
        sample = Ticket.objects.filter(subject=SAMPLE_SUBJECT, requester=requester).first()
        # An Open ticket, where the composer shows both "Send and ..." buttons.
        open_ticket = Ticket.objects.filter(
            requester__username__startswith="demo-", status=Ticket.Status.OPEN
        ).first()
        # A ticket with an emailed approval from someone other than the requester.
        noted = Ticket.objects.filter(
            requester__username__startswith="demo-", comments__source="email", comments__is_internal=True
        ).first()
        # v0.5.0: a Resolved ticket of Dana's (shows the auto-close date), and a
        # Closed ticket with a follow-up linked to it (Aisha's).
        resolved = Ticket.objects.filter(requester=requester, status=Ticket.Status.RESOLVED).first()
        closed = Ticket.objects.filter(
            requester__username__startswith="demo-", status=Ticket.Status.CLOSED, follow_ups__isnull=False
        ).first()
        if not (requester and agent and sample and open_ticket and noted and resolved and closed):
            raise CommandError("Demo data not found. Run: python manage.py seed_demo --clear, then seed_demo")
        follow_up = closed.follow_ups.first()

        # Database work happens before and after the browser runs: Playwright's
        # sync API runs an event loop, and Django refuses ORM calls inside one.
        def latest_email(ticket, kind):
            return (OutboundEmail.objects.filter(ticket=ticket, kind=kind)
                    .order_by("created_at").values_list("body_html", flat=True).last())

        emails = {
            "received": latest_email(sample, "received"),
            "it_replied": latest_email(sample, "it_replied"),
            "resolved_reply": latest_email(resolved, "it_replied"),
        }
        sessions = {
            "requester": self._session_for(requester),
            "agent": self._session_for(agent),
            "closed_requester": self._session_for(closed.requester),
        }
        out_dir = Path(out)
        out_dir.mkdir(parents=True, exist_ok=True)
        base_url = base_url.rstrip("/")
        sample_url = sample.get_absolute_url()
        urls = {
            "sample": sample_url, "open": open_ticket.get_absolute_url(), "noted": noted.get_absolute_url(),
            "resolved": resolved.get_absolute_url(), "closed": closed.get_absolute_url(),
            "follow_up": follow_up.get_absolute_url(),
            "new_follow_up": f"/tickets/new/?follow_up={closed.number}",
        }
        # v0.8.0: the queue filtered to one of the new teams.
        mechanics = Category.objects.filter(name="Mechanics").values_list("pk", flat=True).first()
        urls["team_queue"] = f"/queue/?category={mechanics}" if mechanics else "/queue/"
        wanted = {p.strip() for p in only.split(",") if p.strip()}

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="msedge", headless=True)
                try:
                    shots = self._capture(browser, base_url, sessions, urls, out_dir, emails, wanted)
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

    def _capture(self, browser, base_url, sessions, urls, out_dir, emails, wanted) -> list[str]:
        saved = []
        sample_url = urls["sample"]

        def skip(name):
            return bool(wanted) and name.split("-", 1)[0] not in wanted

        def page_for(who, viewport):
            context = browser.new_context(
                viewport=viewport, color_scheme="light", device_scale_factor=1,
                # Animations play their end state at once, so shots never catch a fade halfway.
                reduced_motion="reduce",
            )
            if who:
                context.add_cookies([{
                    "name": settings.SESSION_COOKIE_NAME, "value": sessions[who], "url": base_url,
                }])
            return context.new_page()

        def shoot_email(name, html):
            if skip(name):
                return
            if not html:
                raise CommandError(f"No email found for {name}. Run: python manage.py seed_demo --clear, then seed_demo")
            page = page_for(None, {"width": 680, "height": 200})  # grows to fit the email
            page.set_content(html)
            page.screenshot(path=str(out_dir / name), full_page=True)
            page.context.close()
            saved.append(name)

        def shoot(name, who, path, viewport=DESKTOP, full_page=False, prepare=None, element=None):
            if skip(name):
                return
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

        # v0.7.0: the "this might include a password" warning. The page asks the
        # server before sending, so nothing is saved; only the warning appears.
        def password_in_request(page):
            page.fill("input[name=subject]", "VPN won't connect from home")
            page.select_option("select[name=category]", index=1)
            page.fill("textarea[name=description]", "It fails every morning. My password is Summer24 if you need it.")
            page.click("form[data-password-check] button[type=submit]")
            page.wait_for_selector("[data-password-warning]:not([hidden])")

        def password_in_composer(page):
            page.fill("#composer-text", "Your temporary password is ChangeMe! Please change it when you sign in.")
            page.click(".composer-send")
            page.wait_for_selector(".composer [data-password-warning]:not([hidden])")

        def open_signature(page):
            page.click("details.email-signature summary")

        # v0.8.0: pick a common request, which fills in the subject and category.
        def pick_common_request(page):
            page.select_option("select[data-subject-pick]", index=1)

        shoot("01-sign-in.png", None, "/signin/", prepare=as_configured)
        shoot("02-my-tickets.png", "requester", "/tickets/")
        shoot("03-new-request.png", "requester", "/tickets/new/", full_page=True)
        shoot("04-requester-ticket.png", "requester", sample_url, full_page=True)
        shoot("05-queue.png", "agent", "/queue/")
        shoot("06-agent-ticket.png", "agent", sample_url, full_page=True)
        shoot("07-internal-note-composer.png", "agent", sample_url, prepare=internal_mode, element=".composer")
        shoot("08-queue-phone.png", "agent", "/queue/", viewport=PHONE)
        shoot("09-requester-ticket-phone.png", "requester", sample_url, viewport=PHONE)
        shoot("10-composer-status-buttons.png", "agent", urls["open"], element=".composer")
        shoot_email("11-email-it-replied.png", emails["it_replied"])
        shoot_email("12-email-received.png", emails["received"])
        shoot("13-agent-ticket-email-note.png", "agent", urls["noted"], full_page=True)
        shoot("14-requester-resolved.png", "requester", urls["resolved"], full_page=True)
        shoot("15-requester-closed.png", "closed_requester", urls["closed"], full_page=True)
        shoot("16-new-request-follow-up.png", "closed_requester", urls["new_follow_up"], full_page=True)
        shoot("17-agent-linked-tickets.png", "agent", urls["follow_up"], full_page=True)
        shoot_email("18-email-resolved.png", emails["resolved_reply"])
        shoot("19-password-warning-request.png", "requester", "/tickets/new/",
              prepare=password_in_request, element="form[data-password-check]")
        shoot("20-password-warning-composer.png", "agent", sample_url, prepare=password_in_composer, element=".composer")
        shoot("21-email-signature-open.png", "agent", sample_url, prepare=open_signature,
              element=".tl-comment:has(details.email-signature)")
        shoot("22-common-requests.png", "requester", "/tickets/new/", prepare=pick_common_request,
              element="form[data-password-check]")
        shoot("23-queue-mechanics.png", "agent", urls["team_queue"])
        return saved

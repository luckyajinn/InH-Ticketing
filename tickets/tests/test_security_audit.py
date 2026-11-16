"""
Security audit, 2026-11-16: attacks on the app, one class per kind of weakness.

Everything runs against Django's throwaway test database and a temporary media
folder. Nothing is emailed: messages are only queued in the test database.
People sign in with force_login(), which stands in for Microsoft 365 sign-in.

Tests named test_observed_* record how the app behaves today where that is a
known gap the user may choose to close; they're explained in the audit report.
"""

import re
from unittest import mock

from django.conf import settings
from django.test import Client, override_settings
from django.urls import get_resolver, reverse

from accounts.models import User
from inbound.eml import html_to_text
from inbound.models import InboundEmail
from inbound.processing import IncomingAttachment, IncomingMessage, process
from notifications.models import OutboundEmail
from tickets import services
from tickets.examples import add_example_departments
from tickets.models import Attachment, Comment, Ticket, TicketEvent
from tickets.tests.helpers import MediaTestCase, make_ticket, make_user, upload

XSS = '<script>alert("x")</script><img src=x onerror=alert(1)>'
_ids = iter(range(1, 100_000))


class AuditBase(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.categories = add_example_departments()
        self.mech_agent = make_user("Mia Mechanic", User.Role.AGENT)
        self.mech_agent.department = "mechanics"
        self.mech_agent.save()
        self.admin = make_user("Ada Admin", User.Role.ADMIN)
        # As entra.sync_user sets them for the Admin role.
        self.admin.is_staff = self.admin.is_superuser = True
        self.admin.save()
        self.mine = make_ticket(self.requester, subject="Dana's own laptop")
        self.theirs = make_ticket(self.other_requester, subject="Tom's private salary question",
                                  files=[upload("tom.pdf", b"%PDF-1.4 tom")])
        self.mech_ticket = make_ticket(self.other_requester, subject="Press 4 hydraulic leak",
                                       category=self.categories["mechanics"])
        self.note = services.add_comment(ticket=self.mine, author=self.agent, body="Internal: check asset tag",
                                         is_internal=True, files=[upload("internal.png")])

    def as_(self, user, **client_kwargs) -> Client:
        client = Client(**client_kwargs)
        client.force_login(user)
        return client

    def url(self, name, ticket, **kwargs):
        return reverse(name, kwargs={"number": ticket.number, **kwargs})


# 1. Broken access control ---------------------------------------------------
class AccessControlTests(AuditBase):
    def test_changing_the_ticket_number_shows_nothing(self):
        client = self.as_(self.requester)
        self.assertEqual(client.get(self.url("tickets:detail", self.mine)).status_code, 200)
        other = client.get(self.url("tickets:detail", self.theirs))
        missing = client.get(reverse("tickets:detail", kwargs={"number": 999_999}))
        self.assertEqual(other.status_code, 404)
        self.assertEqual(missing.status_code, 404)
        self.assertNotContains(other, "salary", status_code=404)

    def test_every_ticket_action_checks_ownership(self):
        client = self.as_(self.requester)
        before = Comment.objects.count()
        for name in ("tickets:reply", "tickets:resolve", "tickets:reopen"):
            response = client.post(self.url(name, self.theirs), {"body": "hijack"})
            self.assertEqual(response.status_code, 404, name)
        self.assertEqual(Comment.objects.count(), before)

    def test_attachments_check_the_ticket_and_the_note(self):
        client = self.as_(self.requester)
        tom_file = self.theirs.attachments.get()
        internal = self.note.attachments.get()
        self.assertEqual(client.get(tom_file.get_absolute_url()).status_code, 404)
        self.assertEqual(client.get(reverse("tickets:attachment", args=[tom_file.pk, "anything.pdf"])).status_code, 404)
        self.assertEqual(client.get(internal.get_absolute_url()).status_code, 404)
        self.assertEqual(self.as_(self.other_requester).get(tom_file.get_absolute_url()).status_code, 200)

    def test_staff_pages_check_the_role_on_the_server(self):
        client = self.as_(self.requester)
        self.assertEqual(client.get(reverse("tickets:queue")).status_code, 403)
        self.assertEqual(client.get(reverse("tickets:find_people"), {"q": "tom"}).status_code, 403)
        for name in ("tickets:update", "tickets:assign_to_me", "tickets:ask_to_move"):
            self.assertEqual(client.post(self.url(name, self.mine), {"status": "resolved"}).status_code, 403, name)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, Ticket.Status.NEW)

    def test_admin_pages_check_the_role_on_the_server(self):
        for user in (self.requester, self.agent):
            client = self.as_(user)
            self.assertEqual(client.get(reverse("tickets:reports")).status_code, 403)
            self.assertEqual(client.get(reverse("tickets:reports_csv")).status_code, 403)
            self.assertEqual(client.get(self.url("tickets:remove", self.mine), {"part": "subject"}).status_code, 403)
            for name in ("tickets:move", "tickets:unarchive"):
                self.assertEqual(client.post(self.url(name, self.mine),
                                             {"category": self.categories["mechanics"].pk}).status_code, 403)
            self.assertNotEqual(client.get("/admin/").status_code, 200)
            self.assertNotEqual(client.get("/admin/accounts/user/").status_code, 200)
        self.assertEqual(self.as_(self.admin).get("/admin/").status_code, 200)

    def test_agents_only_see_their_own_department(self):
        it_agent = self.as_(self.agent)
        self.assertEqual(it_agent.get(self.url("tickets:detail", self.mech_ticket)).status_code, 404)
        self.assertEqual(it_agent.post(self.url("tickets:update", self.mech_ticket), {"status": "resolved"}).status_code, 404)
        self.assertNotContains(it_agent.get(reverse("tickets:queue")), "hydraulic")
        mech = self.as_(self.mech_agent)
        self.assertEqual(mech.get(self.url("tickets:detail", self.mine)).status_code, 404)
        self.assertEqual(mech.get(self.note.attachments.get().get_absolute_url()).status_code, 404)

    def test_requester_cannot_forge_staff_fields(self):
        client = self.as_(self.requester)
        response = client.post(self.url("tickets:reply", self.mine),
                               {"body": "sneaky", "visibility": "internal", "then_status": "resolved"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Comment.objects.filter(body="sneaky").exists())
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, Ticket.Status.NEW)

    def test_requester_cannot_open_a_request_in_someone_elses_name(self):
        client = self.as_(self.requester)
        client.post(reverse("tickets:new"), {
            "subject": "In Tom's name", "description": "x", "category": self.mine.category_id,
            "for_whom": "other", "for_email": self.other_requester.email,
        })
        ticket = Ticket.objects.get(subject="In Tom's name")
        self.assertEqual(ticket.requester, self.requester)
        self.assertIsNone(ticket.opened_by_id)

    def test_side_panel_cannot_move_a_ticket_or_assign_a_requester(self):
        client = self.as_(self.agent)
        response = client.post(self.url("tickets:update", self.mine), {
            "status": "open", "priority": 2, "category": self.categories["mechanics"].pk,
            "assignee": self.requester.pk,
        })
        self.assertEqual(response.status_code, 400)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.department, "it")
        self.assertIsNone(self.mine.assignee_id)

    def test_follow_up_link_does_not_leak_another_ticket(self):
        response = self.as_(self.requester).get(reverse("tickets:new"), {"follow_up": self.theirs.number})
        self.assertNotContains(response, "salary")

    def test_removal_is_limited_to_the_ticket_in_the_url(self):
        other_comment = services.add_comment(ticket=self.theirs, author=self.other_requester, body="Tom's reply")
        response = self.as_(self.admin).get(self.url("tickets:remove", self.mine), {"part": f"c{other_comment.pk}"})
        self.assertEqual(response.status_code, 404)

    def test_people_search_needs_two_characters_and_caps_results(self):
        for i in range(20):
            make_user(f"Pat Person{i}")
        client = self.as_(self.agent)
        self.assertEqual(client.get(reverse("tickets:find_people"), {"q": "p"}).json()["people"], [])
        self.assertLessEqual(len(client.get(reverse("tickets:find_people"), {"q": "pat"}).json()["people"]), 8)

    def test_sign_in_never_redirects_off_site(self):
        client = self.as_(self.requester)
        for target in ("//evil.example/", "https://evil.example/", "/\\evil.example", "\\\\evil.example",
                       "javascript:alert(1)", "/%2F%2Fevil.example"):
            response = client.get(reverse("accounts:signin"), {"next": target})
            location = response.headers.get("Location", "")
            self.assertFalse(location.startswith(("//", "http", "javascript", "/\\", "\\")), (target, location))


# 2 and 3. Secrets, debug and leftover development settings --------------------
class SecretsAndDebugTests(AuditBase):
    def test_pages_and_scripts_carry_no_secrets(self):
        client = self.as_(self.admin)
        pages = [reverse("tickets:queue"), self.url("tickets:detail", self.mine), reverse("tickets:new"),
                 reverse("tickets:reports"), reverse("core:about"), "/static/js/app.js"]
        secrets = [settings.SECRET_KEY, settings.ENTRA_CLIENT_SECRET]
        for page in pages:
            response = client.get(page)
            body = b"".join(response.streaming_content) if response.streaming else response.content
            for secret in filter(None, secrets):
                self.assertNotIn(secret.encode(), body, page)

    @override_settings(DEBUG=False)
    def test_a_crash_shows_no_traceback_or_settings(self):
        client = self.as_(self.requester, raise_request_exception=False)
        with mock.patch("tickets.views.selectors.timeline", side_effect=RuntimeError("boom at C:\\secret\\path")):
            response = client.get(self.url("tickets:detail", self.mine))
        self.assertEqual(response.status_code, 500)
        for leak in (b"Traceback", b"boom", b"SECRET_KEY", b"views.py", b"DATABASES"):
            self.assertNotIn(leak, response.content)

    @override_settings(DEBUG=False)
    def test_not_found_lists_no_urls(self):
        response = self.as_(self.requester).get("/definitely-not-a-page/")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"URLconf", response.content)
        self.assertNotIn(b"admin/", response.content)

    def test_no_password_sign_in_anywhere(self):
        client = Client()
        response = client.post("/admin/login/", {"username": "admin", "password": "admin"})
        self.assertIn(response.status_code, (302, 405))
        self.assertNotIn("_auth_user_id", client.session)
        self.assertFalse(User.objects.filter(password__startswith="pbkdf2").exclude(
            username__startswith="test-").exists())

    def test_no_debug_or_test_routes(self):
        routes = []

        def walk(patterns, prefix=""):
            for p in patterns:
                if hasattr(p, "url_patterns"):
                    walk(p.url_patterns, prefix + str(p.pattern))
                else:
                    routes.append(prefix + str(p.pattern))

        walk(get_resolver().url_patterns)
        risky = [r for r in routes if any(w in r.lower() for w in ("debug", "seed", "test", "mockup", "__", "shell"))]
        self.assertEqual(risky, [])


# 4. Injection -----------------------------------------------------------------
class InjectionTests(AuditBase):
    def test_sql_in_search_and_filters_is_just_text(self):
        client = self.as_(self.agent)
        for q in ("' OR '1'='1' --", "%", "_", "1; DROP TABLE tickets_ticket;--", "#1001 OR 1=1"):
            response = client.get(reverse("tickets:queue"), {"q": q, "view": "open", "category": "1 OR 1=1",
                                                              "priority": "1 OR 1=1"})
            self.assertEqual(response.status_code, 200, q)
            self.assertNotContains(response, "hydraulic")
        self.assertTrue(Ticket.objects.exists())
        self.assertEqual(client.get(reverse("tickets:go"), {"number": "1001 OR 1=1"}).status_code, 302)

    def test_html_is_escaped_on_every_page_that_shows_it(self):
        self.requester.display_name = XSS
        self.requester.save()
        ticket = make_ticket(self.requester, subject=XSS, description=XSS)
        services.add_comment(ticket=ticket, author=self.agent, body=XSS)
        services.add_comment(ticket=ticket, author=self.agent, body=XSS, is_internal=True)
        pages = [
            (self.requester, self.url("tickets:detail", ticket)),
            (self.requester, reverse("tickets:mine")),
            (self.agent, self.url("tickets:detail", ticket)),
            (self.agent, reverse("tickets:queue")),
            (self.admin, reverse("tickets:reports")),
            (self.admin, "/admin/tickets/ticket/"),
            (self.admin, "/admin/accounts/user/"),
        ]
        for user, page in pages:
            response = self.as_(user).get(page)
            self.assertEqual(response.status_code, 200, page)
            self.assertNotIn(b"<script>alert", response.content, page)
            self.assertNotIn(b"<img src=x onerror", response.content, page)
        # The people search is JSON (never rendered as a page); app.js puts it
        # on the page with textContent, which can't create HTML.
        response = self.as_(self.agent).get(reverse("tickets:find_people"), {"q": "script"})
        self.assertEqual(response["Content-Type"], "application/json")
        script = (settings.BASE_DIR / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("insertAdjacentHTML", script)

    def test_html_in_emails_is_escaped(self):
        self.requester.display_name = XSS
        self.requester.save()
        ticket = make_ticket(self.requester, subject=XSS, description=XSS)
        services.add_comment(ticket=ticket, author=self.agent, body=XSS)
        emails = OutboundEmail.objects.filter(ticket=ticket)
        self.assertTrue(emails.exists())
        for email in emails:
            self.assertNotIn("<script>alert", email.body_html)
            self.assertNotIn("<img src=x onerror", email.body_html)

    def test_csv_export_neutralises_formulas(self):
        make_ticket(self.requester, subject='=HYPERLINK("http://evil.example","click")')
        response = self.as_(self.admin).get(reverse("tickets:reports_csv"), {"period": "week"})
        self.assertIn("'=HYPERLINK", response.content.decode("utf-8-sig"))


# 5. File uploads ----------------------------------------------------------------
class UploadTests(AuditBase):
    def post_files(self, *files):
        return self.as_(self.requester).post(self.url("tickets:reply", self.mine),
                                             {"body": "see file", "attachments": list(files)})

    def test_dangerous_file_types_are_refused(self):
        names = ["page.html", "page.HTM", "image.svg", "run.exe", "script.js", "x.ps1", "x.bat", "x.php",
                 "photo.png.html", "noextension", "x.xhtml", "x.hta", "x.jar"]
        for name in names:
            response = self.post_files(upload(name, b"<script>alert(1)</script>", "text/html"))
            self.assertEqual(response.status_code, 400, name)
        self.assertFalse(Attachment.objects.filter(ticket=self.mine, comment__isnull=False,
                                                   comment__is_internal=False).exists())

    def test_tricky_file_names_cannot_escape_or_inject_headers(self):
        names = ["../../../../etc/evil.png", "..\\..\\windows\\evil.png", 'a"; filename="evil.html.png',
                 "name\r\nX-Injected: yes.png", "\x00null.png"]
        for name in names:
            self.post_files(upload(name, b"<html><script>alert(1)</script></html>", "text/html"))
        files = Attachment.objects.filter(ticket=self.mine, comment__is_internal=False)
        self.assertTrue(files.exists())
        for attachment in files:
            self.assertRegex(attachment.file.name, rf"^attachments/{self.mine.pk}/[0-9a-f]{{32}}\.png$")
            response = self.as_(self.requester).get(attachment.get_absolute_url())
            self.assertEqual(response.status_code, 200, attachment.original_name)
            self.assertTrue(response["Content-Disposition"].startswith("attachment"))
            self.assertNotIn("X-Injected", response.headers)
            self.assertNotIn("text/html", response["Content-Type"])
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_size_and_count_limits(self):
        too_big = upload("big.png", b"0" * (settings.ATTACHMENT_MAX_BYTES + 1))
        self.assertEqual(self.post_files(too_big).status_code, 400)
        six = [upload(f"s{i}.png") for i in range(settings.ATTACHMENT_MAX_FILES + 1)]
        self.assertEqual(self.post_files(*six).status_code, 400)

    def test_zip_files_are_refused(self):
        # v0.10.7: an archive can hide any file type, and nothing scans inside it.
        for name in ("invoice.zip", "LOGS.ZIP", "report.pdf.zip"):
            response = self.post_files(upload(name, b"PK\x03\x04 pretend archive", "application/zip"))
            self.assertContains(response, "Zip files aren", status_code=400)
        response = self.as_(self.requester).post(reverse("tickets:new"), {
            "subject": "Logs", "description": "attached", "category": self.mine.category_id,
            "attachments": [upload("logs.zip", b"PK\x03\x04", "application/zip")]})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Ticket.objects.filter(subject="Logs").exists())

    def test_observed_office_files_are_stored_unscanned(self):
        # Allowed on purpose (.docx, .xlsx, .eml, .msg ...). Nothing scans them for
        # malware; they're always downloaded, never opened by the browser.
        response = self.post_files(upload("invoice.docx", b"PK\x03\x04 pretend document"))
        self.assertEqual(response.status_code, 302)


# 6 and 7. Sign-in, CSRF, CORS, cookies, headers ---------------------------------
class SessionAndHeaderTests(AuditBase):
    def test_every_form_post_needs_a_csrf_token(self):
        client = self.as_(self.requester, enforce_csrf_checks=True)
        posts = [
            (self.url("tickets:reply", self.mine), {"body": "x"}),
            (reverse("tickets:new"), {"subject": "x", "description": "x", "category": self.mine.category_id}),
            (reverse("tickets:check_text"), {"body": "x"}),
            (self.url("tickets:resolve", self.mine), {}),
            (reverse("accounts:signout"), {}),
        ]
        for url, data in posts:
            self.assertEqual(client.post(url, data).status_code, 403, url)
        self.assertIn("_auth_user_id", client.session)  # signout without a token did nothing

    def test_sign_out_is_post_only(self):
        client = self.as_(self.requester)
        self.assertEqual(client.get(reverse("accounts:signout")).status_code, 405)

    def test_no_cross_origin_access(self):
        client = self.as_(self.agent)
        response = client.get(reverse("tickets:find_people"), {"q": "tom"}, HTTP_ORIGIN="https://evil.example")
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertNotIn("Access-Control-Allow-Credentials", response.headers)

    def test_security_headers_and_private_caching(self):
        response = self.as_(self.requester).get(self.url("tickets:detail", self.mine))
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])

    def test_session_cookie_flags(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertLessEqual(settings.SESSION_COOKIE_AGE, 12 * 3600)

    def test_content_security_policy_on_every_kind_of_page(self):
        # v0.10.7: only the app's own script and styles run.
        pages = [(None, reverse("accounts:signin")), (self.requester, self.url("tickets:detail", self.mine)),
                 (self.agent, reverse("tickets:queue")), (self.admin, reverse("tickets:reports")),
                 (self.admin, "/admin/"), (self.requester, "/no-such-page/")]
        for user, page in pages:
            client = self.as_(user) if user else Client()
            policy = client.get(page).headers.get("Content-Security-Policy", "")
            for part in ("default-src 'self'", "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
                         "form-action 'self'"):
                self.assertIn(part, policy, page)
            self.assertNotIn("unsafe-inline", policy, page)
            self.assertNotIn("unsafe-eval", policy, page)

    def test_app_pages_have_no_inline_code(self):
        # Nothing the policy would block: no inline <script> or <style>, no on...= handlers, no style=.
        ticket = make_ticket(self.requester, subject="Inline check")
        services.add_comment(ticket=ticket, author=self.agent, body="A reply")
        pages = [(None, reverse("accounts:signin")), (None, reverse("core:about")),
                 (self.requester, reverse("tickets:mine")), (self.requester, reverse("tickets:new")),
                 (self.requester, self.url("tickets:detail", ticket)), (self.agent, self.url("tickets:detail", ticket)),
                 (self.agent, reverse("tickets:queue")), (self.admin, reverse("tickets:queue")),
                 (self.admin, reverse("tickets:reports")), (self.admin, self.url("tickets:detail", ticket)),
                 (self.requester, self.url("tickets:detail", self.theirs)), (self.requester, reverse("tickets:reports"))]
        inline = re.compile(rb"<script(?![^>]*\bsrc=)[^>]*>|<style[^>]*>|\son[a-z]+=|\sstyle=", re.IGNORECASE)
        for user, page in pages:
            client = self.as_(user) if user else Client()
            response = client.get(page)
            self.assertEqual(inline.findall(response.content), [], page)

    @override_settings(DEBUG=False)
    def test_the_error_page_styles_carry_the_nonce(self):
        client = self.as_(self.requester, raise_request_exception=False)
        with mock.patch("tickets.views.selectors.timeline", side_effect=RuntimeError("boom")):
            response = client.get(self.url("tickets:detail", self.mine))
        nonce = re.search(r"'nonce-([^']+)'", response["Content-Security-Policy"]).group(1)
        self.assertIn(f'<style nonce="{nonce}">'.encode(), response.content)


# 9. Email-in: spoofing, HTML and attachments -------------------------------------
@override_settings(INBOUND_ALLOWED_DOMAINS=["example.invalid"], HELPDESK_MAILBOX="helpdesk-test@example.invalid",
                   INBOUND_VERIFY_IT_SENDERS=True)
class EmailInTests(AuditBase):
    INTERNAL = {"X-MS-Exchange-Organization-AuthAs": "Internal"}

    def email(self, from_address, subject, body="hello", **extra):
        return IncomingMessage(message_id=f"<audit-{next(_ids)}@example.invalid>", from_address=from_address,
                               subject=subject, body_text=body, source="graph", **extra)

    def internal_email(self, from_address, subject, body="hello", **extra):
        """Sent from inside the organisation: Exchange confirmed the sender."""
        return self.email(from_address, subject, body, headers=self.INTERNAL, **extra)

    def test_spoofed_it_sender_only_becomes_an_internal_note(self):
        result = process(self.email(self.agent.email, f"Re: [#{self.mine.number}] laptop",
                                    "Please send me your password"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.NOTE)
        self.assertTrue(Comment.objects.get(body__contains="send me your password").is_internal)

    def test_confirmed_it_sender_is_public(self):
        result = process(self.internal_email(self.agent.email, f"Re: [#{self.mine.number}] laptop", "fixed"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.REPLY)

    def test_spoofed_requester_reply_only_becomes_an_internal_note(self):
        # v0.10.7: the requester's email is checked against Exchange's headers too.
        result = process(self.email(self.requester.email, f"Re: [#{self.mine.number}] laptop", "spoofed reply"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.NOTE)
        comment = Comment.objects.get(body__contains="spoofed reply")
        self.assertTrue(comment.is_internal)
        self.assertIn("couldn't confirm", comment.body)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, Ticket.Status.NEW)

    def test_spoofed_reply_cannot_reopen_a_resolved_ticket(self):
        services.update_ticket(ticket=self.mine, actor=self.agent, status=Ticket.Status.RESOLVED)
        process(self.email(self.requester.email, f"Re: [#{self.mine.number}] laptop", "still broken"))
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, Ticket.Status.RESOLVED)

    def test_confirmed_requester_reply_is_public(self):
        result = process(self.internal_email(self.requester.email, f"Re: [#{self.mine.number}] laptop", "thanks"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.REPLY)
        self.assertFalse(Comment.objects.get(body__contains="thanks").is_internal)

    def test_spoofed_new_request_is_ignored_without_an_account(self):
        result = process(self.email("new.person@example.invalid", "Please reset my password"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.IGNORED)
        self.assertIn("wasn't confirmed", result.record.detail)
        self.assertFalse(Ticket.objects.filter(subject="Please reset my password").exists())
        self.assertFalse(User.objects.filter(email="new.person@example.invalid").exists())
        self.assertFalse(OutboundEmail.objects.filter(to="new.person@example.invalid").exists())

    def test_confirmed_new_request_becomes_a_ticket(self):
        result = process(self.internal_email(self.requester.email, "Monitor flickers"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.NEW_TICKET)

    def test_outsiders_are_ignored(self):
        result = process(self.email("attacker@evil.example", "Free money"))
        self.assertEqual(result.outcome, InboundEmail.Outcome.IGNORED)
        self.assertFalse(User.objects.filter(email="attacker@evil.example").exists())

    def test_dangerous_email_attachments_are_dropped(self):
        attachments = [IncomingAttachment(name, "application/octet-stream", b"MZ payload")
                       for name in ("invoice.exe", "page.html", "image.svg", "doc.pdf.js")]
        result = process(self.internal_email(self.requester.email, "Invoice", "see attached", attachments=attachments))
        self.assertFalse(result.ticket.attachments.exists())
        self.assertIn("file type not accepted", result.ticket.description)

    def test_html_email_is_stored_and_shown_as_text(self):
        text = html_to_text(f"<p>Hi</p>{XSS}<a href='javascript:alert(1)'>link</a>")
        result = process(self.internal_email(self.requester.email, "HTML mail", text))
        response = self.as_(self.agent).get(self.url("tickets:detail", result.ticket))
        self.assertNotIn(b"<script>alert", response.content)
        self.assertNotIn(b"href='javascript:", response.content)
        self.assertNotIn(b'href="javascript:', response.content)


# 10. Audit trail --------------------------------------------------------------
class AuditTrailTests(AuditBase):
    def test_staff_changes_record_who_and_what(self):
        client = self.as_(self.agent)
        client.post(self.url("tickets:update", self.mine), {"status": "open", "priority": 3,
                                                             "category": self.mine.category_id, "assignee": ""})
        event = TicketEvent.objects.filter(ticket=self.mine, actor=self.agent).last()
        self.assertIsNotNone(event)

    def test_removals_are_logged_without_the_removed_text(self):
        ticket = make_ticket(self.requester, description="my password is Hunter2Secret!")
        self.as_(self.admin).post(self.url("tickets:remove", ticket, ) + "?part=description",
                                  {"part": "description", "text": "Hunter2Secret!"})
        events = TicketEvent.objects.filter(ticket=ticket, actor=self.admin)
        self.assertTrue(events.exists())
        self.assertFalse(any("Hunter2Secret" in f"{e.old_value}{e.new_value}" for e in events))

    def test_observed_viewing_and_downloading_leave_no_record(self):
        before = TicketEvent.objects.count()
        client = self.as_(self.admin)
        client.get(self.url("tickets:detail", self.theirs))
        client.get(self.theirs.attachments.get().get_absolute_url())
        self.assertEqual(TicketEvent.objects.count(), before)

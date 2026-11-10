"""
The "this might include a password" check: what it catches, the warning on
the web forms, and the audit trail. It should rather warn too often than let
a password through, but must stay quiet on everyday IT requests.
"""

from django.contrib.admin.sites import site as admin_site
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from inbound.processing import IncomingMessage, process
from tickets import password_guard
from tickets.models import Category, PasswordWarning, Ticket, TicketEvent
from tickets.tests.helpers import MediaTestCase, make_ticket, upload

Outcome = PasswordWarning.Outcome
Place = PasswordWarning.Place

CAUGHT = [
    "my password is Summer24",
    "pw: hunter2",
    "Password: hunter2",
    "password = 1234",
    "the password for the VPN is Tr0ub4dor",
    "Password - hunter2",
    "pw hunter2",
    "my new password is Fall2025!",
    "Summer2024!",
    "xK9mQ2pL",
    "Password1",
    "P@ssw0rd",
    "welcome1",
    "it's Winter25",
    "the code is 482913",
    "verification code: 482913",
    "PIN 4821",
    "my PIN for the door is 4821",
    "pin: 4821",
    "pass: abc123",
    "pass hunter2",
    "login: jdoe / Summer24",
    "credentials: jdoe Hunter22",
    "passcode 7731",
    "temp password: ChangeMe!",
    "recovery key 123456-654321",
    "Tr0ub4dor&3",
    "token Xq7RfT2mN9pLw4ZsK8vB3cH6jD1gY5aE",
    "My password expired so I set it to Dana1987",
]

NOT_CAUGHT = [
    "Outlook keeps prompting for my password",
    "my password expired",
    "My password is not working",
    "password reset please",
    "I forgot my password!",
    "error code 1603 when installing",
    "Office365 won't open",
    "Windows11 update failed",
    "Correlation ID: 3f2a9c1e-8b7d-4e6f-9a0b-1c2d3e4f5a6b",
    "0x80070005 access denied",
    "AADSTS50126 error",
    "see https://example.com/Path?x=Y2",
    "email dana.whitfield@example.invalid",
    "Ticket #1001 is about the printer",
    "Can you pass this to Sam?",
    "login: jdoe",
    "my password is the same as before",
    "Please reset the password for Tom",
    "The printer on floor 2 jams",
    "Call me at 555-0123",
    "New phone: can't approve MFA sign-in requests",
    "Laptop LT-00423 has a cracked screen",
    "zip code 90210",
    "My password is expired and I'm locked out",
    "I changed my password yesterday and now Teams asks again",
    "the code stopped working",
]


class DetectionTests(SimpleTestCase):
    def test_catches_likely_passwords(self):
        for text in CAUGHT:
            with self.subTest(text=text):
                self.assertTrue(password_guard.find(text), "should be caught")

    def test_quiet_on_everyday_requests(self):
        for text in NOT_CAUGHT:
            with self.subTest(text=text):
                self.assertEqual(password_guard.find(text), [], "false alarm")

    def test_finds_the_password_itself(self):
        text = "Hi, my password is Summer24 thanks"
        [finding] = password_guard.find(text)
        self.assertEqual(text[finding.start:finding.end], "Summer24")
        self.assertEqual(finding.rule, "labelled")

    def test_hint_never_shows_the_password(self):
        [finding] = password_guard.find("Hi, my password is Summer24 thanks")
        self.assertNotIn("Summer24", finding.hint)
        self.assertNotIn("ummer", finding.hint)
        self.assertIn("my password is S•••••••", finding.hint)

    def test_mask_length_is_fixed(self):
        short = password_guard.find("pw: abc1")[0].hint
        long = password_guard.find("pw: abcdefghijklmnop1")[0].hint
        self.assertEqual(short.count("•"), long.count("•"))

    def test_overlapping_matches_count_once(self):
        # "Summer24" is both a labelled value and a password-looking word.
        self.assertEqual(len(password_guard.find("password: Summer2024!")), 1)

    def test_empty_text(self):
        self.assertEqual(password_guard.find(""), [])


class NewRequestWarningTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.requester)
        self.url = reverse("tickets:new")
        self.category = Category.objects.get(name="Software")

    def post(self, **extra):
        data = {"subject": "VPN won't connect", "category": self.category.pk,
                "description": "My password is Summer24 and it still fails."}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_warns_and_does_not_send(self):
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "This might include a password", status_code=400)
        self.assertContains(response, "In the description:", status_code=400)
        self.assertFalse(Ticket.objects.exists())
        self.assertFalse(PasswordWarning.objects.exists())

    def test_warning_page_never_repeats_the_password_in_the_hint(self):
        response = self.post()
        hints = response.context["form"].password_hints
        self.assertTrue(hints)
        self.assertFalse(any("Summer24" in hint for hint in hints))

    def test_warning_marks_the_form_as_warned(self):
        response = self.post()
        self.assertContains(response, 'name="password_warned" value="on"', status_code=400)

    def test_says_to_attach_files_again(self):
        response = self.client.post(self.url, {
            "subject": "VPN", "category": self.category.pk, "description": "pw: hunter2", "attachments": [upload()],
        })
        self.assertContains(response, "Attach your files again", status_code=400)

    def test_send_anyway_is_recorded(self):
        response = self.post(password_ack="on", password_warned="on")
        ticket = Ticket.objects.get()
        self.assertRedirects(response, ticket.get_absolute_url())
        warning = PasswordWarning.objects.get()
        self.assertEqual(warning.outcome, Outcome.SENT_ANYWAY)
        self.assertEqual(warning.place, Place.NEW_REQUEST)
        self.assertEqual(warning.ticket, ticket)
        self.assertEqual(warning.user, self.requester)
        self.assertEqual(warning.fields, "description")
        self.assertEqual(warning.rules, "labelled")
        event = ticket.events.get(kind=TicketEvent.Kind.PASSWORD)
        self.assertEqual(event.actor, self.requester)
        self.assertEqual(event.new_value, "the request")
        self.assertEqual(event.note, "sent anyway after a warning")

    def test_audit_trail_never_stores_the_text(self):
        self.post(password_ack="on")
        warning = PasswordWarning.objects.get()
        stored = " ".join(str(getattr(warning, f.attname)) for f in PasswordWarning._meta.fields)
        self.assertNotIn("Summer24", stored)
        event = TicketEvent.objects.get(kind=TicketEvent.Kind.PASSWORD)
        self.assertNotIn("Summer24", f"{event.old_value} {event.new_value} {event.note}")

    def test_taking_it_out_after_a_warning_is_recorded(self):
        self.post(description="I reset it and VPN still fails.", password_warned="on")
        ticket = Ticket.objects.get()
        warning = PasswordWarning.objects.get()
        self.assertEqual(warning.outcome, Outcome.REMOVED)
        self.assertEqual(warning.ticket, ticket)
        # Nothing for IT to check, so no history line.
        self.assertFalse(ticket.events.filter(kind=TicketEvent.Kind.PASSWORD).exists())

    def test_clean_request_records_nothing(self):
        self.post(description="VPN fails with error 809.")
        self.assertTrue(Ticket.objects.exists())
        self.assertFalse(PasswordWarning.objects.exists())

    def test_subject_is_checked_too(self):
        response = self.post(subject="pw: hunter2", description="Help")
        self.assertContains(response, "In the subject:", status_code=400)


class ReplyWarningTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.ticket = make_ticket(self.requester)
        self.url = reverse("tickets:reply", args=[self.ticket.number])

    def test_requester_reply_warns(self):
        self.client.force_login(self.requester)
        response = self.client.post(self.url, {"body": "my new password is Fall2025!"})
        self.assertContains(response, "This might include a password", status_code=400)
        self.assertEqual(self.ticket.comments.count(), 0)

    def test_requester_reply_sent_anyway_links_the_comment(self):
        self.client.force_login(self.requester)
        self.client.post(self.url, {"body": "my new password is Fall2025!", "password_ack": "on"})
        comment = self.ticket.comments.get()
        warning = PasswordWarning.objects.get()
        self.assertEqual((warning.place, warning.outcome, warning.comment), (Place.REPLY, Outcome.SENT_ANYWAY, comment))

    def test_requester_never_sees_the_history_line(self):
        self.client.force_login(self.requester)
        self.client.post(self.url, {"body": "pw: hunter2", "password_ack": "on"})
        page = self.client.get(self.ticket.get_absolute_url())
        self.assertNotContains(page, "Possible password")

    def test_it_sees_the_history_line(self):
        self.client.force_login(self.requester)
        self.client.post(self.url, {"body": "pw: hunter2", "password_ack": "on"})
        self.client.force_login(self.agent)
        page = self.client.get(self.ticket.get_absolute_url())
        self.assertContains(page, "<strong>Possible password</strong> in a reply from Dana Whitfield")
        self.assertContains(page, "sent anyway after a warning")

    def test_internal_notes_are_checked(self):
        self.client.force_login(self.agent)
        response = self.client.post(self.url, {"body": "Temp password: ChangeMe!", "visibility": "internal"})
        self.assertContains(response, "This might include a password", status_code=400)
        self.client.post(self.url, {"body": "Temp password: ChangeMe!", "visibility": "internal", "password_ack": "on"})
        self.assertEqual(PasswordWarning.objects.get().place, Place.INTERNAL_NOTE)

    def test_send_anyway_keeps_the_send_and_resolve_choice(self):
        self.client.force_login(self.agent)
        self.client.post(self.url, {"body": "Your temp password is ChangeMe!", "then_status": "resolved", "password_ack": "on"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.RESOLVED)
        self.assertEqual(PasswordWarning.objects.get().outcome, Outcome.SENT_ANYWAY)


class CheckTextEndpointTests(MediaTestCase):
    url = reverse("tickets:check_text")

    def test_needs_sign_in(self):
        response = self.client.post(self.url, {"body": "pw: hunter2"})
        self.assertEqual(response.status_code, 302)

    def test_post_only(self):
        self.client.force_login(self.requester)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_reports_findings_without_the_password(self):
        self.client.force_login(self.requester)
        result = self.client.post(self.url, {"description": "my password is Summer24"}).json()
        self.assertTrue(result["found"])
        self.assertEqual(len(result["hints"]), 1)
        self.assertNotIn("Summer24", result["hints"][0])
        self.assertTrue(result["hints"][0].startswith("In the description:"))

    def test_clean_text(self):
        self.client.force_login(self.requester)
        result = self.client.post(self.url, {"subject": "Printer", "description": "Tray 2 jams"}).json()
        self.assertEqual(result, {"found": False, "hints": []})

    def test_stores_nothing(self):
        self.client.force_login(self.requester)
        self.client.post(self.url, {"body": "pw: hunter2"})
        self.assertFalse(PasswordWarning.objects.exists())


@override_settings(INBOUND_ALLOWED_DOMAINS=["example.invalid"], HELPDESK_MAILBOX="helpdesk-test@example.invalid")
class EmailTests(MediaTestCase):
    def message(self, subject, body):
        return IncomingMessage(
            message_id=f"<pw-{subject}-{body}@example.invalid>", from_address="dana.whitfield@example.invalid",
            subject=subject, body_text=body, source="command",
        )

    def test_new_ticket_by_email_is_flagged_for_it(self):
        result = process(self.message("VPN", "My password is Summer24"))
        warning = PasswordWarning.objects.get()
        self.assertEqual((warning.place, warning.outcome), (Place.EMAIL, Outcome.EMAILED))
        self.assertEqual(warning.ticket, result.ticket)
        self.assertEqual(warning.user, self.requester)
        event = result.ticket.events.get(kind=TicketEvent.Kind.PASSWORD)
        self.assertEqual(event.new_value, "an email")
        self.assertIn("arrived by email", event.note)

    def test_email_reply_is_flagged_with_its_comment(self):
        ticket = make_ticket(self.requester)
        process(self.message(f"RE: [#{ticket.number}] Printer", "pw: hunter2"))
        comment = ticket.comments.get()
        self.assertEqual(PasswordWarning.objects.get().comment, comment)

    def test_clean_email_records_nothing(self):
        process(self.message("Printer", "Tray 2 jams again."))
        self.assertFalse(PasswordWarning.objects.exists())


class AdminTests(MediaTestCase):
    def test_audit_trail_is_read_only(self):
        model_admin = admin_site._registry[PasswordWarning]
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))

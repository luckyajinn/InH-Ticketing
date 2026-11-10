"""Email signatures are folded on tickets, but only when we're sure it's a signature."""

from django.test import SimpleTestCase, override_settings

from inbound.processing import IncomingMessage, process
from inbound.text import split_signature
from tickets.models import Category, PasswordWarning, Ticket
from tickets.tests.helpers import MediaTestCase

# Shaped like the CodeTwo signature on McKenna Labs mail (fictional details).
CODETWO = """Dana Whitfield
Quality Analyst | McKenna Labs
1234 Example Way, Suite 100, Anytown, CA 90000
T: +1 (555) 010-0100 | F: +1 (555) 010-0101
www.example.com
[cid:image001.png@01DB2A3B.4C5D6E70]

Please consider the environment before printing this email.

CONFIDENTIALITY NOTICE: This email and any attachments are confidential and
intended solely for the use of the addressee. If you have received this email
in error, please notify the sender and delete it."""


class SplitSignatureTests(SimpleTestCase):
    def test_codetwo_signature_after_a_sign_off(self):
        text = f"Hi IT,\n\nThe label printer in the lab keeps jamming.\n\nThanks,\n{CODETWO}"
        message, signature = split_signature(text)
        self.assertEqual(message, "Hi IT,\n\nThe label printer in the lab keeps jamming.\n\nThanks,")
        self.assertTrue(signature.startswith("Dana Whitfield"))
        self.assertIn("CONFIDENTIALITY NOTICE", signature)

    def test_signature_without_a_sign_off(self):
        message, signature = split_signature("Printer jammed again.\nDana Whitfield\nT: 555 010 0100\nF: 555 010 0101")
        self.assertEqual(message, "Printer jammed again.")
        self.assertEqual(signature, "Dana Whitfield\nT: 555 010 0100\nF: 555 010 0101")

    def test_standard_delimiter(self):
        message, signature = split_signature("VPN is down.\n-- \nTom Reyes\nFacilities")
        self.assertEqual((message, signature), ("VPN is down.", "-- \nTom Reyes\nFacilities"))

    def test_mobile_footer(self):
        message, signature = split_signature("Screen is cracked.\n\nSent from my iPhone\nT: 555 010 0100")
        self.assertEqual(message, "Screen is cracked.")
        self.assertIn("Sent from my iPhone", signature)

    def test_keeps_the_message_when_unsure(self):
        for text in [
            "Printer on floor 2 is jammed",
            "Please see https://example.com/error and call me at 555-0123",
            "Can you call me back?\nMobile: 555 010 0100",          # one sign only
            "The error says:\nwww.example.com is not reachable",
            "Thanks,\nDana",
            # v0.8.3: two contact-looking lines that are the request itself.
            "Please clean these:\nRestroom on floor 2\nBreak room in Unit 4",
            "Can these two have access?\njane.doe@example.com\njohn.roe@example.com",
            "Both crash on start:\nOffice 2019 on PC-12\nOffice 365 on PC-14",
            "The two links:\nhttps://example.sharepoint.com/a\nhttps://example.sharepoint.com/b",
            "Printer status page:\n--\n" + "\n".join(f"Tray {i}: OK" for i in range(1, 20)),
        ]:
            with self.subTest(text=text):
                self.assertEqual(split_signature(text), (text, ""))

    def test_contact_lines_after_a_sign_off_still_fold(self):
        message, signature = split_signature("Line 2 is down.\n\nThanks,\nT: 555 010 0100\nF: 555 010 0101")
        self.assertEqual(message, "Line 2 is down.\n\nThanks,")
        self.assertEqual(signature, "T: 555 010 0100\nF: 555 010 0101")

    def test_never_folds_everything(self):
        self.assertEqual(split_signature(CODETWO), (CODETWO, ""))

    def test_message_lines_above_the_name_stay(self):
        text = "Badge reader at the lab door won't open\nAisha Kamara\nT: 555 010 0102\nwww.example.com"
        message, signature = split_signature(text)
        self.assertEqual(message, "Badge reader at the lab door won't open")
        self.assertTrue(signature.startswith("Aisha Kamara"))

    def test_empty(self):
        self.assertEqual(split_signature(""), ("", ""))


@override_settings(INBOUND_ALLOWED_DOMAINS=["example.invalid"], HELPDESK_MAILBOX="helpdesk-test@example.invalid")
class TicketPageTests(MediaTestCase):
    def emailed_ticket(self):
        result = process(IncomingMessage(
            message_id="<sig-1@example.invalid>", from_address="dana.whitfield@example.invalid",
            subject="Label printer", body_text=f"The label printer keeps jamming.\n\nThanks,\n{CODETWO}",
            source="command",
        ))
        return result.ticket

    def test_it_sees_the_signature_folded(self):
        ticket = self.emailed_ticket()
        self.client.force_login(self.agent)
        page = self.client.get(ticket.get_absolute_url())
        self.assertContains(page, '<details class="email-signature">')
        self.assertContains(page, "Show email signature")
        body = page.content.decode()
        self.assertLess(body.index("The label printer keeps jamming."), body.index("Show email signature"))

    def test_the_full_email_is_still_stored(self):
        ticket = self.emailed_ticket()
        self.assertIn("CONFIDENTIALITY NOTICE", ticket.description)

    def test_signature_is_not_a_possible_password(self):
        # The logo placeholder used to look like a password to the token check.
        self.emailed_ticket()
        self.assertFalse(PasswordWarning.objects.exists())

    def test_web_requests_are_never_folded(self):
        self.client.force_login(self.requester)
        self.client.post("/tickets/new/", {
            "subject": "Printer", "category": Category.objects.first().pk,
            "description": f"Jammed.\n\nThanks,\n{CODETWO}",
        })
        ticket = Ticket.objects.get()
        page = self.client.get(ticket.get_absolute_url())
        self.assertNotContains(page, "Show email signature")

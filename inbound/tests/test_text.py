from django.test import SimpleTestCase

from inbound.text import clean_subject, find_ticket_number, is_automatic, strip_quoted


class SubjectTests(SimpleTestCase):
    def test_ticket_number(self):
        self.assertEqual(find_ticket_number("RE: [#1028] Outlook keeps prompting"), 1028)
        self.assertIsNone(find_ticket_number("Printer #1028 jammed"))  # needs the brackets

    def test_clean_subject(self):
        self.assertEqual(clean_subject("RE: [#1028] Outlook keeps prompting"), "Outlook keeps prompting")
        self.assertEqual(clean_subject("Fwd: FW: RE: VPN drops"), "VPN drops")
        self.assertEqual(clean_subject("Automatic reply: [#1001] Printer"), "Printer")
        self.assertEqual(clean_subject("   "), "(no subject)")


class QuotedReplyTests(SimpleTestCase):
    def test_gmail_style(self):
        text = "Still broken after the restart.\n\nOn Tue, 5 Nov 2026 at 10:01, IT <it@x.com> wrote:\n> Try a restart"
        self.assertEqual(strip_quoted(text), "Still broken after the restart.")

    def test_outlook_style(self):
        text = ("Yes, 2:30 works.\r\n\r\nFrom: InH-Ticketing <helpdesk@x.com>\r\nSent: Tuesday\r\n"
                "To: Dana\r\nSubject: [#1028] Outlook\r\n\r\nSam replied...")
        self.assertEqual(strip_quoted(text), "Yes, 2:30 works.")

    def test_original_message_separator(self):
        text = "Thanks!\n-----Original Message-----\nFrom: someone"
        self.assertEqual(strip_quoted(text), "Thanks!")

    def test_quote_markers_removed(self):
        self.assertEqual(strip_quoted("> old\nNew line\n> older"), "New line")

    def test_falls_back_to_everything(self):
        self.assertEqual(strip_quoted("> only quoted"), "> only quoted")


class AutomaticEmailTests(SimpleTestCase):
    def test_person(self):
        self.assertEqual(is_automatic({"Auto-Submitted": "no"}, "dana@x.com"), "")
        self.assertEqual(is_automatic({}, "dana@x.com"), "")

    def test_out_of_office(self):
        self.assertIn("Auto-Submitted", is_automatic({"Auto-Submitted": "auto-replied"}, "dana@x.com"))

    def test_bulk_and_lists(self):
        self.assertTrue(is_automatic({"Precedence": "bulk"}, "news@x.com"))
        self.assertTrue(is_automatic({"List-Id": "<team.x.com>"}, "team@x.com"))

    def test_automatic_subjects_without_headers(self):
        self.assertTrue(is_automatic({}, "dana@x.com", "Automatic reply: [#1001] Printer"))
        self.assertTrue(is_automatic({}, "dana@x.com", "Out of Office: back Monday"))
        self.assertTrue(is_automatic({}, "dana@x.com", "Undeliverable: [#1001] Printer"))
        self.assertEqual(is_automatic({}, "dana@x.com", "RE: [#1001] Out of paper again"), "")

    def test_bounces(self):
        self.assertTrue(is_automatic({}, "MAILER-DAEMON@x.com"))
        self.assertTrue(is_automatic({}, "postmaster@x.com"))

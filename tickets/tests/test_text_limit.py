"""Descriptions and replies stop at TEXT_MAX_CHARS, on the web and by email."""

from django.urls import reverse

from inbound import processing
from tickets.models import TEXT_MAX_CHARS, Category, Comment, Ticket
from tickets.tests.helpers import MediaTestCase, make_ticket

TOO_LONG = "a" * (TEXT_MAX_CHARS + 1)
MESSAGE = "That&#x27;s 20,001 characters, over the 20,000 limit. Attach a long log or list as a file instead."


class TextLimitTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.hardware = Category.objects.get(name="Hardware")

    def new_request(self, description):
        self.client.force_login(self.requester)
        return self.client.post(reverse("tickets:new"), {
            "subject": "Monitor flickers", "category": self.hardware.pk, "description": description,
        })

    def test_the_limit_is_20000_characters_as_for_email(self):
        self.assertEqual(TEXT_MAX_CHARS, 20_000)
        self.assertEqual(processing.MAX_BODY, TEXT_MAX_CHARS)

    def test_a_description_at_the_limit_is_kept_whole(self):
        self.new_request("a" * TEXT_MAX_CHARS)
        self.assertEqual(len(Ticket.objects.get().description), TEXT_MAX_CHARS)

    def test_a_longer_description_gets_a_clear_message(self):
        response = self.new_request(TOO_LONG)
        self.assertContains(response, MESSAGE, status_code=400)
        self.assertContains(response, TOO_LONG, status_code=400)  # still in the box
        self.assertFalse(Ticket.objects.exists())

    def test_a_longer_reply_gets_a_clear_message(self):
        ticket = make_ticket(self.requester)
        self.client.force_login(self.requester)
        response = self.client.post(reverse("tickets:reply", args=[ticket.number]),
                                    {"body": TOO_LONG, "visibility": "public"})
        self.assertContains(response, MESSAGE, status_code=400)
        self.assertContains(response, TOO_LONG, status_code=400)
        self.assertFalse(Comment.objects.filter(ticket=ticket).exists())

    def test_a_longer_internal_note_too(self):
        ticket = make_ticket(self.requester)
        self.client.force_login(self.agent)
        response = self.client.post(reverse("tickets:reply", args=[ticket.number]),
                                    {"body": TOO_LONG, "visibility": "internal"})
        self.assertContains(response, MESSAGE, status_code=400)
        self.assertFalse(Comment.objects.filter(ticket=ticket).exists())

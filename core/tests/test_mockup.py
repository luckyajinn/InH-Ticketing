"""The clickable mockup is built from the app's own pages, with the demo data."""

import io
import json
import re
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from core.management.commands.build_mockup import normalize
from tickets.models import Ticket


@override_settings(DEBUG=True)
class BuildMockupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "mockup.html"
            call_command("build_mockup", out=str(out), stdout=io.StringIO())
            html = out.read_text(encoding="utf-8")
        found = re.search(r'<script id="mockup-data" type="application/json">(.*?)</script>', html, re.S)
        cls.data = json.loads(found[1])
        cls.pages = cls.data["pages"]

    def page(self, key):
        return self.pages[key]["html"]

    def test_every_listed_screen_is_in_it(self):
        roles = [role["id"] for role in self.data["roles"]]
        self.assertEqual(roles, ["visitor", "requester", "it", "mechanics", "admin"])
        for role in self.data["roles"]:
            for screen in role["screens"]:
                key = f"{role['id']} {screen['url']}"
                self.assertIn(self.data["aliases"].get(key, key), self.pages, key)

    def test_each_person_sees_their_own_view(self):
        outlook = Ticket.objects.get(subject="Outlook keeps prompting for my password").get_absolute_url()
        conveyor = Ticket.objects.get(subject="Line 1 conveyor screen keeps freezing").get_absolute_url()
        self.assertIn("Mo Okafor", self.page("mechanics /queue/"))
        self.assertNotIn("VPN drops every 10 minutes", self.page("mechanics /queue/"))
        self.assertIn("Move to another department", self.page(f"admin {conveyor}"))
        self.assertNotIn("Move to another department", self.page(f"it {conveyor}"))
        self.assertIn("admin /reports/", self.pages)
        self.assertNotIn("it /reports/", self.pages)
        # Sam's internal note on the Outlook ticket: staff see it, the requester doesn't.
        self.assertIn("Re-enrolment fixed both", self.page(f"it {outlook}"))
        self.assertNotIn("Re-enrolment fixed both", self.page(f"requester {outlook}"))

    def test_nothing_loads_from_a_server(self):
        for key, page in self.pages.items():
            self.assertNotRegex(page["html"], r'(?:src|href)="/static/', key)
            self.assertNotIn("setup-warning", page["html"], key)
            self.assertIn('data-mockup-asset="mockup:frame"', page["html"], key)
        self.assertIn("css/app.css", self.data["assets"])
        self.assertNotIn("url(../", "".join(self.data["assets"].values()))

    def test_only_pages_without_side_effects(self):
        for key in self.pages:
            self.assertNotRegex(key, r"signout|attachments|\.csv|check-text|/update/|/reply/|/move/")

    def test_query_order_and_empty_values_dont_matter(self):
        self.assertEqual(normalize("/queue/?view=open&dept=&next=/x&q="), "/queue/?view=open")
        self.assertEqual(normalize("/queue/?view=open&dept=it"), normalize("/queue/?dept=it&view=open"))


class BuildMockupRefusesTests(TestCase):
    @override_settings(DEBUG=False)
    def test_only_in_development(self):
        with self.assertRaisesMessage(CommandError, "DEBUG=True"):
            call_command("build_mockup", out="unused.html")

    @override_settings(DEBUG=True)
    def test_needs_the_demo_data(self):
        with self.assertRaisesMessage(CommandError, "seed_demo"):
            call_command("build_mockup", out="unused.html")

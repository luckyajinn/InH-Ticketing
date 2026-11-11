"""Departments are a table admins edit: IT is built in, and an admin adds the others."""

import importlib
import os
from unittest import mock

from django.apps import apps as django_apps
from django.core.checks import run_checks
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from accounts import entra
from accounts.models import User
from core import departments
from tickets import reports
from tickets.examples import add_example_departments
from tickets.models import Category, Comment, Department, Ticket
from tickets.tests.helpers import MediaTestCase, make_ticket, make_user

upgrade = importlib.import_module("tickets.migrations.0008_department")


def add_department(key="plumbing", name="Plumbing", role="Agent.Plumbing", **extra) -> Department:
    department = Department(key=key, name=name, entra_role=role, **extra)
    department.full_clean()
    department.save()
    return department


class UpgradeTests(MediaTestCase):
    """What migration 0008 does to an existing install's data."""

    def run_upgrade(self, env=None):
        Department.objects.all().delete()
        with mock.patch.dict(os.environ, env or {}, clear=False):
            upgrade.add_departments(django_apps, None)
        return {d.key: d for d in Department.objects.all()}

    def test_a_new_install_gets_it_only(self):
        found = self.run_upgrade()
        self.assertEqual(list(found), ["it"])
        self.assertEqual((found["it"].name, found["it"].entra_role, found["it"].colour), ("IT", "", 1))

    def test_the_departments_in_use_keep_their_keys_colours_and_old_settings(self):
        Category.objects.create(name="Mechanics", department="mechanics")
        User.objects.filter(pk=self.agent.pk).update(department="cleaning")
        found = self.run_upgrade({
            "ENTRA_ROLE_AGENT_CLEANING": "Agent.CS",
            "DEPARTMENT_NOTIFY_EMAILS": "mechanics=mech-team@example.invalid",
        })
        self.assertEqual([(k, d.name, d.colour) for k, d in found.items()],
                         [("it", "IT", 1), ("mechanics", "Mechanics", 2), ("cleaning", "Cleaning & sanitization", 3)])
        self.assertEqual(found["mechanics"].entra_role, "Agent.Mechanics")  # the old default
        self.assertEqual(found["cleaning"].entra_role, "Agent.CS")  # from the old setting
        self.assertEqual(found["mechanics"].alert_email, "mech-team@example.invalid")
        self.assertEqual(found["cleaning"].alert_email, "")

    def test_an_internal_note_keeps_its_department_too(self):
        ticket = make_ticket(self.requester)
        Comment.objects.create(ticket=ticket, author=self.agent, body="x", is_internal=True, department="cleaning")
        self.assertIn("cleaning", self.run_upgrade())


class ValidationTests(MediaTestCase):
    def test_colours_go_in_order_and_are_reused(self):
        a, b = add_department(), add_department("roads", "Roads", "Agent.Roads")
        self.assertEqual((a.colour, b.colour), (2, 3))
        a.delete()
        self.assertEqual(add_department("grounds", "Grounds", "Agent.Grounds").colour, 2)

    def test_up_to_eight(self):
        for n in range(7):
            add_department(f"team-{n}", f"Team {n}", f"Agent.Team{n}")
        with self.assertRaisesMessage(ValidationError, "up to 8 departments"):
            add_department("one-more", "One more", "Agent.OneMore")

    def test_each_needs_its_own_entra_role(self):
        add_department()
        for role, message in [("", "needs its own Entra app role"), ("Agent", "Give this department its own"),
                              ("admin", "Give this department its own"), ("agent.plumbing", "already uses that role")]:
            with self.subTest(role=role), self.assertRaises(ValidationError) as caught:
                add_department("roads", "Roads", role)
            self.assertIn(message, " ".join(caught.exception.messages))

    def test_key(self):
        for key in ("Plumbing", "9lives", "plumbing team", "a" * 17):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                add_department(key)
        with self.assertRaises(ValidationError):
            add_department("it", "IT again")

    @override_settings(INBOUND_ALLOWED_DOMAINS=["example.invalid"], HELPDESK_MAILBOX="helpdesk@example.invalid",
                       DEPARTMENT_MAILBOXES={"plumbing": {"address": "plumbing@example.invalid", "folder": ""}})
    def test_alert_address(self):
        for address, message in [("helpdesk@example.invalid", "own mailboxes"),
                                 ("plumbing@example.invalid", "own mailboxes"),
                                 ("team@gmail.com", "in the organisation")]:
            with self.subTest(address=address), self.assertRaisesMessage(ValidationError, message):
                add_department(alert_email=address)
        self.assertEqual(add_department(alert_email="plumbers@example.invalid").alert_email, "plumbers@example.invalid")


class WorkingTests(MediaTestCase):
    """A department an admin adds works like the others."""

    def setUp(self):
        super().setUp()
        self.plumbing = add_department()
        self.pipes = Category.objects.create(name="Pipes", department="plumbing", subject_options="Leaking tap")
        self.plumber = make_user("Pat Plumber", User.Role.AGENT)
        User.objects.filter(pk=self.plumber.pk).update(department="plumbing")
        self.plumber.refresh_from_db()

    def test_its_entra_role_makes_an_agent_of_it(self):
        self.assertEqual(entra.role_from_claims(["Agent.Plumbing"]), User.Role.AGENT)
        self.assertEqual(entra.department_from_claims(["Agent.Plumbing"]), "plumbing")
        self.assertEqual(entra.department_from_claims(["Agent.Plumbing", "Agent"]), "it")  # IT comes first

    def test_its_agents_work_only_its_tickets(self):
        pipes = make_ticket(self.requester, subject="Tap drips", category=self.pipes)
        printer = make_ticket(self.requester)
        self.assertTrue(self.plumber.works_on(pipes))
        self.assertFalse(self.plumber.works_on(printer))
        self.assertFalse(self.agent.works_on(pipes))
        self.client.force_login(self.plumber)
        queue = self.client.get(reverse("tickets:queue"))
        self.assertContains(queue, "Tap drips")
        self.assertNotContains(queue, "Printer jammed")
        self.assertContains(queue, "Plumbing agent")

    def test_admins_filter_by_it_and_move_tickets_to_it(self):
        admin = make_user("Ada Admin", User.Role.ADMIN)
        ticket = make_ticket(self.requester)
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("tickets:queue")), '<option value="plumbing"')
        self.assertContains(self.client.get(ticket.get_absolute_url()), "Plumbing: Pipes")

    def test_no_move_boxes_with_nowhere_to_move_to(self):
        ticket = make_ticket(self.requester)
        admin = make_user("Ada Admin", User.Role.ADMIN)
        Category.objects.filter(department="plumbing").update(is_active=False)
        for person in (self.agent, admin):
            with self.subTest(person=person.display_name):
                self.client.force_login(person)
                page = self.client.get(ticket.get_absolute_url())
                self.assertNotContains(page, "Wrong department?")
                self.assertNotContains(page, "Move to another department")
        Category.objects.filter(department="plumbing").update(is_active=True)
        Department.objects.create(key="roads", name="Roads", entra_role="Agent.Roads")  # no categories yet
        self.client.force_login(self.agent)
        page = self.client.get(ticket.get_absolute_url())
        self.assertContains(page, "Wrong department?")
        self.assertContains(page, '<option value="plumbing">Plumbing</option>')
        self.assertNotContains(page, '<option value="roads">')

    def test_pages_name_the_departments_there_are(self):
        self.assertContains(self.client.get(reverse("accounts:signin")), "Ask IT or Plumbing for help")
        Department.objects.filter(key="plumbing").delete()
        self.assertContains(self.client.get(reverse("accounts:signin")), "Ask IT for help")
        add_example_departments()
        self.client.force_login(self.requester)
        self.assertContains(self.client.get(reverse("tickets:new")),
                            "For IT, Mechanics, and Cleaning &amp; sanitization requests only.")

    def test_reports_give_it_its_own_colour(self):
        make_ticket(self.requester, subject="Tap drips", category=self.pipes)
        data = reports.build("30")
        self.assertEqual([(r["key"], r["slot"]) for r in data["team_rows"]], [("it", 1), ("plumbing", 2)])
        only = reports.build("30", team="plumbing")
        self.assertEqual(only["series"], [("plumbing", "Plumbing", 2)])


class AdminTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.admin = make_user("Ada Admin", User.Role.ADMIN)
        User.objects.filter(pk=self.admin.pk).update(is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)
        self.it = Department.objects.get(key="it")

    def test_the_list_and_the_add_page(self):
        page = self.client.get(reverse("admin:tickets_department_changelist"))
        self.assertContains(page, "ENTRA_ROLE_AGENT")
        add = self.client.get(reverse("admin:tickets_department_add"))
        self.assertContains(add, "create an app role whose value is exactly")

    def test_adding_one(self):
        response = self.client.post(reverse("admin:tickets_department_add"), {
            "name": "Plumbing", "key": "plumbing", "entra_role": "Agent.Plumbing", "alert_email": "",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Department.objects.get(key="plumbing").colour, 2)
        form = self.client.get(reverse("admin:tickets_category_add"))
        self.assertContains(form, '<option value="plumbing">Plumbing</option>')

    def test_it_cant_be_changed_or_deleted(self):
        url = reverse("admin:tickets_department_change", args=[self.it.pk])
        self.client.post(url, {"name": "Help desk", "key": "helpdesk"})
        self.it.refresh_from_db()
        self.assertEqual((self.it.key, self.it.name), ("it", "IT"))
        self.assertEqual(self.client.get(reverse("admin:tickets_department_delete", args=[self.it.pk])).status_code, 403)

    def test_a_department_in_use_cant_be_deleted(self):
        plumbing = add_department()
        url = reverse("admin:tickets_department_delete", args=[plumbing.pk])
        Category.objects.create(name="Pipes", department="plumbing")
        self.assertEqual(self.client.get(url).status_code, 403)
        Category.objects.filter(name="Pipes").delete()
        self.client.post(url, {"post": "yes"})
        self.assertFalse(Department.objects.filter(key="plumbing").exists())

    def test_the_key_is_fixed_once_made(self):
        plumbing = add_department()
        self.client.post(reverse("admin:tickets_department_change", args=[plumbing.pk]), {
            "name": "Plumbing & heating", "key": "heating", "entra_role": "Agent.Plumbing", "alert_email": "",
        })
        plumbing.refresh_from_db()
        self.assertEqual((plumbing.key, plumbing.name), ("plumbing", "Plumbing & heating"))


class RetiredSettingsTests(MediaTestCase):
    def test_old_settings_are_flagged(self):
        with mock.patch.dict(os.environ, {"ENTRA_ROLE_AGENT_MECHANICS": "Agent.Mechanics"}):
            warnings = [w for w in run_checks() if w.id == "core.W001"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("ENTRA_ROLE_AGENT_MECHANICS", warnings[0].msg)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ENTRA_ROLE_AGENT_MECHANICS", None)
            self.assertFalse([w for w in run_checks() if w.id == "core.W001"])

    def test_labels_for_keys_that_arent_there(self):
        self.assertEqual(departments.label(""), "")
        self.assertEqual(departments.label("it"), "IT")
        self.assertEqual(departments.label("gone"), "gone")
        self.assertEqual(Ticket.objects.count(), 0)

"""The admin log: every change made in the admin site, with the values, read-only."""

from django.contrib.admin.models import CHANGE, DELETION, LogEntry
from django.urls import reverse

from accounts.models import User
from core.admin import VALUE_LIMIT
from notifications.models import OutboundEmail
from tickets.examples import add_example_departments
from tickets.models import Category, Department
from tickets.tests.helpers import MediaTestCase, make_user

LOG = reverse("admin:admin_logentry_changelist")


class AdminLogTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.admin = make_user("Ada Admin", User.Role.ADMIN)
        User.objects.filter(pk=self.admin.pk).update(is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)

    def latest(self) -> LogEntry:
        return LogEntry.objects.order_by("-pk").first()

    def add_plumbing(self):
        self.client.post(reverse("admin:tickets_department_add"), {
            "name": "Plumbing", "key": "plumbing", "entra_role": "Agent.Plumbing", "alert_email": "",
        })
        return Department.objects.get(key="plumbing")

    def test_adding_a_department_logs_what_it_was_given(self):
        self.add_plumbing()
        self.assertEqual(self.latest().change_message,
                         'Added with Name: "Plumbing"; Key: "plumbing"; Entra app role: "Agent.Plumbing"; '
                         'Alert address: blank.')

    def test_changing_a_department_logs_old_and_new(self):
        plumbing = self.add_plumbing()
        self.client.post(reverse("admin:tickets_department_change", args=[plumbing.pk]), {
            "name": "Plumbing", "entra_role": "Agent.Pipes", "alert_email": "pipes@example.invalid",
        })
        entry = self.latest()
        self.assertEqual((entry.action_flag, entry.user, entry.object_repr), (CHANGE, self.admin, "Plumbing"))
        self.assertEqual(entry.change_message,
                         'Changed Entra app role: "Agent.Plumbing" → "Agent.Pipes"; '
                         'Alert address: blank → "pipes@example.invalid".')

    def test_saving_without_changes(self):
        plumbing = self.add_plumbing()
        self.client.post(reverse("admin:tickets_department_change", args=[plumbing.pk]), {
            "name": "Plumbing", "entra_role": "Agent.Plumbing", "alert_email": "",
        })
        self.assertEqual(self.latest().change_message, "No fields changed.")

    def test_a_category_shows_department_names_and_its_list_on_one_line(self):
        add_example_departments()
        Category.objects.filter(name="Hardware").update(subject_options="")
        hardware = Category.objects.get(name="Hardware")
        self.client.post(reverse("admin:tickets_category_change", args=[hardware.pk]), {
            "name": "Hardware", "hint": hardware.hint, "sort_order": hardware.sort_order,
            "department": "mechanics", "subject_options": "Monitor flickers\r\nNo power",
        })  # Active unticked
        self.assertEqual(self.latest().change_message,
                         'Changed Is active: yes → no; Department: "IT" → "Mechanics"; '
                         'Common requests: blank → "Monitor flickers / No power".')

    def test_long_values_are_cut(self):
        hardware = Category.objects.get(name="Hardware")
        self.client.post(reverse("admin:tickets_category_change", args=[hardware.pk]), {
            "name": "Hardware", "hint": hardware.hint, "is_active": "on", "sort_order": hardware.sort_order,
            "department": "it", "subject_options": "\n".join(f"Request {n:02} " + "x" * 20 for n in range(20)),
        })
        message = self.latest().change_message
        new = message.split(" → ")[1]
        self.assertEqual(len(new), VALUE_LIMIT + 4)  # the quotes, the cut text, "…" and the full stop
        self.assertTrue(new.endswith('…".'))

    def test_deactivating_someone_is_logged_and_nobody_can_be_deleted(self):
        url = reverse("admin:accounts_user_change", args=[self.requester.pk])
        self.client.post(url, {})  # Active unticked
        self.requester.refresh_from_db()
        self.assertFalse(self.requester.is_active)
        self.assertEqual(self.latest().change_message, "Changed Active: yes → no.")
        delete = reverse("admin:accounts_user_delete", args=[self.requester.pk])
        self.assertEqual(self.client.get(delete).status_code, 403)
        self.assertNotContains(self.client.get(reverse("admin:accounts_user_changelist")), "delete_selected")

    def test_retrying_emails_is_logged(self):
        failed = OutboundEmail.objects.create(kind="test", to="dana@example.invalid", subject="Hello",
                                              body_text="Hi", body_html="<p>Hi</p>", status="failed")
        sent = OutboundEmail.objects.create(kind="test", to="tom@example.invalid", subject="Hello",
                                            body_text="Hi", body_html="<p>Hi</p>", status="sent")
        self.client.post(reverse("admin:notifications_outboundemail_changelist"), {
            "action": "retry_now", "_selected_action": [failed.pk, sent.pk],
        })
        entries = LogEntry.objects.filter(object_id=str(failed.pk), content_type__model="outboundemail")
        self.assertEqual([e.change_message for e in entries], ["Queued to send again (Retry selected emails now)."])
        self.assertFalse(LogEntry.objects.filter(object_id=str(sent.pk), content_type__model="outboundemail"))

    def test_the_log_page(self):
        plumbing = self.add_plumbing()
        page = self.client.get(LOG)
        self.assertContains(page, "Ada Admin")
        self.assertContains(page, "Entra app role: &quot;Agent.Plumbing&quot;")
        self.assertContains(page, reverse("admin:tickets_department_change", args=[plumbing.pk]))
        self.assertContains(self.client.get(reverse("admin:index")), "Log entries")
        self.assertContains(page, ">Department</a>")  # the Type filter
        self.assertContains(page, ">Added</a>")  # the Action filter

    def test_a_deleted_item_isnt_linked(self):
        plumbing = self.add_plumbing()
        self.client.post(reverse("admin:tickets_department_delete", args=[plumbing.pk]), {"post": "yes"})
        entry = self.latest()
        self.assertEqual((entry.action_flag, entry.object_repr), (DELETION, "Plumbing"))
        page = self.client.get(LOG)
        self.assertContains(page, '<td class="field-action">Deleted</td><td class="field-kind">Department</td>'
                                  '<td class="field-item">Plumbing</td>', html=False)

    def test_nothing_in_it_can_be_added_changed_or_deleted(self):
        self.add_plumbing()
        entry = self.latest()
        view = self.client.get(reverse("admin:admin_logentry_change", args=[entry.pk]))
        self.assertContains(view, "Agent.Plumbing")
        self.assertNotContains(view, 'name="_save"')
        self.assertEqual(self.client.get(reverse("admin:admin_logentry_add")).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:admin_logentry_delete", args=[entry.pk]),
                                          {"post": "yes"}).status_code, 403)
        self.assertTrue(LogEntry.objects.filter(pk=entry.pk).exists())

    def test_only_admins_see_it(self):
        self.client.force_login(self.agent)
        response = self.client.get(LOG)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

import datetime as dt
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from inbound import graph_inbox
from notifications import graph, heartbeat
from notifications.models import WorkerHeartbeat
from tickets.tests.helpers import MediaTestCase

INBOX_ON = dict(INBOUND_EMAIL="graph", HELPDESK_MAILBOX="helpdesk-test@example.invalid", DEPARTMENT_MAILBOXES={})


def run_once():
    call_command("run_worker", "--once", stdout=StringIO(), stderr=StringIO())
    return heartbeat.latest()


class WorkerRecordsTests(MediaTestCase):
    def test_a_round_records_start_round_and_auto_close(self):
        beat = run_once()
        for field in ("started_at", "round_at", "auto_close_at"):
            self.assertIsNotNone(getattr(beat, field), field)
        self.assertEqual((beat.auto_close_closed, beat.auto_close_error), (0, ""))
        self.assertIsNone(beat.inbox_at)  # email-in is off
        self.assertEqual(WorkerHeartbeat.objects.count(), 1)
        run_once()
        self.assertEqual(WorkerHeartbeat.objects.count(), 1)  # always the same row

    def test_a_failed_auto_close_is_recorded_and_the_round_still_finishes(self):
        with mock.patch("notifications.management.commands.run_worker.close_resolved_tickets",
                        side_effect=RuntimeError("database locked")):
            beat = run_once()
        self.assertEqual(beat.auto_close_error, "RuntimeError: database locked")
        self.assertIsNotNone(beat.round_at)
        beat = run_once()
        self.assertEqual(beat.auto_close_error, "")  # cleared by the next good run

    @override_settings(**INBOX_ON)
    def test_a_good_inbox_read(self):
        with mock.patch.object(graph_inbox, "poll_mailbox", return_value=(0, 0)):
            beat = run_once()
        self.assertIsNotNone(beat.inbox_ok_at)
        self.assertEqual(beat.inbox_at, beat.inbox_ok_at)
        self.assertEqual(beat.inbox_error, "")

    @override_settings(**INBOX_ON)
    def test_an_unreadable_mailbox_is_named_once(self):
        with mock.patch.object(graph_inbox, "poll_mailbox", side_effect=graph.GraphError("Graph GET returned 403")):
            beat = run_once()
        self.assertEqual(beat.inbox_error, "helpdesk-test@example.invalid: Graph GET returned 403")
        self.assertIsNotNone(beat.inbox_at)
        self.assertIsNone(beat.inbox_ok_at)

    @override_settings(INBOUND_EMAIL="graph", HELPDESK_MAILBOX="helpdesk-test@example.invalid",
                       DEPARTMENT_MAILBOXES={"mechanics": {"address": "mech-test@example.invalid", "folder": ""}})
    def test_one_mailbox_failing_while_the_others_are_read(self):
        def fake(department, address, folder, limit):
            if address == "mech-test@example.invalid":
                raise graph.GraphError("Graph GET returned 404: no such folder")
            return 0, 0

        with mock.patch.object(graph_inbox, "poll_mailbox", side_effect=fake):
            beat = run_once()
        self.assertEqual(beat.inbox_error, "mech-test@example.invalid: Graph GET returned 404: no such folder")
        self.assertIsNone(beat.inbox_ok_at)  # not every mailbox could be read

    @override_settings(**INBOX_ON)
    def test_any_other_inbox_failure_and_recovery(self):
        with mock.patch.object(graph_inbox, "poll_mailbox", side_effect=ConnectionError("network down")):
            beat = run_once()
        self.assertEqual(beat.inbox_error, "ConnectionError: network down")
        with mock.patch.object(graph_inbox, "poll_mailbox", return_value=(0, 0)):
            beat = run_once()
        self.assertEqual(beat.inbox_error, "")
        self.assertIsNotNone(beat.inbox_ok_at)

    def test_a_long_error_is_cut_short(self):
        heartbeat.inbox_read(["x" * 2000])
        self.assertEqual(len(heartbeat.latest().inbox_error), heartbeat.ERROR_LENGTH)

    def test_recording_never_stops_the_worker(self):
        with mock.patch.object(WorkerHeartbeat.objects, "filter", side_effect=RuntimeError("no database")):
            with self.assertLogs("notifications.heartbeat", "ERROR"):
                heartbeat.round_done()  # no exception


class StateTests(TestCase):
    def beat(self, seconds_ago):
        return WorkerHeartbeat(round_at=timezone.now() - dt.timedelta(seconds=seconds_ago))

    def test_states(self):
        self.assertEqual(heartbeat.state(None), "never")
        self.assertEqual(heartbeat.state(WorkerHeartbeat()), "never")
        self.assertEqual(heartbeat.state(self.beat(20)), "ok")
        self.assertEqual(heartbeat.state(self.beat(4 * 60)), "ok")
        self.assertEqual(heartbeat.state(self.beat(6 * 60)), "late")

    @override_settings(WORKER_INTERVAL_SECONDS=600)
    def test_a_slow_worker_gets_three_rounds(self):
        self.assertEqual(heartbeat.state(self.beat(20 * 60)), "ok")
        self.assertEqual(heartbeat.state(self.beat(31 * 60)), "late")


class CheckWorkerTests(TestCase):
    def test_never(self):
        with self.assertRaisesMessage(CommandError, "hasn't finished a round yet"):
            call_command("check_worker", stdout=StringIO())

    def test_running(self):
        heartbeat.round_done()
        out = StringIO()
        call_command("check_worker", stdout=out)
        self.assertIn("The worker is running", out.getvalue())

    def test_stopped(self):
        heartbeat.record(round_at=timezone.now() - dt.timedelta(hours=2))
        with self.assertRaisesMessage(CommandError, "may have stopped"):
            call_command("check_worker", stdout=StringIO())

"""
Tests for stress/make_report.py, the report each stress-test run produces.
Each test writes a run folder in the formats stress/run.sh collects (Locust's
CSVs, `docker stats` samples, the proxy log) and checks the verdict and numbers.
STRESS-TEST BRANCH ONLY.
"""

import contextlib
import csv
import io
import json
import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from stresstest.tests.helpers import load_stress_module

report = load_stress_module("make_report")

PERCENTILES = ["50%", "66%", "75%", "80%", "90%", "95%", "98%", "99%", "99.9%", "99.99%", "100%"]
T0 = 1_762_711_200
PARTS = ("web", "db", "worker", "proxy")


def write_run(folder: Path, *, scenario="expected", avg=86, p95=300, p99=600, failures=0,
              cpu=(60.0, 20.0, 5.0, 10.0), memory=(600, 300, 100, 40), meta=None, history=None):
    """A run folder: totals, per-second history, resource samples and a proxy log."""
    stats_head = ["Type", "Name", "Request Count", "Failure Count", "Median Response Time",
                  "Average Response Time", "Min Response Time", "Max Response Time", "Average Content Size",
                  "Requests/s", "Failures/s"] + PERCENTILES
    with open(folder / "locust_stats.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(stats_head)
        w.writerow(["GET", "/queue/?view=[view]", 1000, 0, 40, 120, 10, 900, 20000, 2, 0]
                   + [40, 50, 60, 70, 100, p95, 500, p99, 900, 900, 900])
        w.writerow(["", "Aggregated", 10000, failures, 30, avg, 5, 900, 15000, 16, 0]
                   + [30, 40, 50, 60, 100, p95, 500, p99, 900, 900, 900])
    with open(folder / "locust_stats_history.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Timestamp", "User Count", "Type", "Name", "Requests/s", "Failures/s"] + PERCENTILES)
        for t, users, rps, fps, h95, h99 in history or [(s, 35, 16, 0, p95, p99) for s in range(0, 600, 10)]:
            w.writerow([T0 + t, users, "", "Aggregated", rps, fps] + [h95] * 5 + [h95, h95, h99, h99, h99, h99])
    with open(folder / "resources.log", "w") as f:
        for t in range(0, 600, 2):
            for part, c, m in zip(PARTS, cpu, memory):
                f.write(f"{T0 + t} " + json.dumps({"Name": f"inh-stress-{part}-1", "CPUPerc": f"{c}%",
                                                    "MemUsage": f"{m}MiB / 1.5GiB"}) + "\n")
            # The load generator's own container must never count as the app.
            f.write(f"{T0 + t} " + json.dumps({"Name": "inh-stress-loadgen-run-0a1b2c", "CPUPerc": "180%",
                                                "MemUsage": "900MiB / 10GiB"}) + "\n")
    with open(folder / "caddy-access.log", "w") as f:
        for i in range(100):
            f.write(json.dumps({"logger": "http.log.access.log0", "duration": 0.010 + i / 10_000,
                                "status": 200}) + "\n")
    base = {
        "scenario": scenario, "scale": 1, "started_utc": "2026-11-09T18:00:00Z", "fresh_data": True,
        "server": {"cpus": 6, "memory_mb": 10_000, "cpu_model": "Test CPU"},
        "cpus": {"app": "0,1", "app_count": 2, "loadgen": "2,3"},
        "limits": {"web": {"memory": "1536m"}, "db": {"memory": "1536m"},
                   "worker": {"memory": "512m"}, "proxy": {"memory": "256m"}},
        "data": {"requesters": 300, "agents": 5, "tickets": 12000, "open_tickets": 28, "comments": 30114,
                 "emails": 48088, "attachments": 1500, "attachments_mb": 2250, "years": 5.0},
    }
    base.update(meta or {})
    (folder / "meta.json").write_text(json.dumps(base))


class ReportTests(SimpleTestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="inh-stress-report-"))
        self.addCleanup(shutil.rmtree, self.folder, True)

    def make(self) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(report.main(self.folder), 0)
        self.html = (self.folder / "report.html").read_text(encoding="utf-8")
        return json.loads((self.folder / "summary.json").read_text(encoding="utf-8"))

    def test_passes_when_staff_hardly_ever_wait(self):
        write_run(self.folder)
        summary = self.make()
        self.assertEqual(summary["overall"], "PASS")
        self.assertIn("met all 4 targets", self.html)

    def test_a_typical_page_taking_tens_of_milliseconds_is_fine(self):
        # The first trial averaged 86 ms and failed the old "average under 20 ms" target.
        write_run(self.folder, avg=86, p95=340, p99=560)
        self.assertEqual(self.make()["overall"], "PASS")

    def test_fails_when_too_many_responses_are_slow(self):
        write_run(self.folder, p95=700, p99=900)
        summary = self.make()
        self.assertEqual(summary["overall"], "FAIL")
        self.assertFalse(summary["checks"]["95% of responses within"])
        self.assertTrue(summary["checks"]["99% of responses within"])

    def test_fails_when_requests_fail(self):
        write_run(self.folder, failures=200)  # 2% of 10,000
        self.assertFalse(self.make()["checks"]["Failed requests"])

    def test_cpu_is_a_share_of_the_cpus_the_app_shares(self):
        write_run(self.folder, cpu=(60.0, 21.0, 5.0, 10.0))  # 96% of one CPU in total
        summary = self.make()
        self.assertEqual(summary["app_cpus"], 2)
        self.assertEqual(summary["app_cpu_avg_pct"], 48.0)
        self.assertIn("48% busy on average", self.html.replace("<strong>", "").replace("</strong>", ""))
        self.assertIn("plenty of room to spare", self.html)

    def test_busy_cpus_are_called_out(self):
        write_run(self.folder, cpu=(120.0, 30.0, 5.0, 10.0))  # 82.5% of 2 CPUs
        self.make()
        self.assertIn("little room to spare", self.html)

    def test_memory_is_added_up_and_checked_against_the_server(self):
        write_run(self.folder, memory=(600, 300, 100, 40))
        summary = self.make()
        self.assertEqual(summary["app_memory_peak_mb"], 1040)  # the load generator's 900 MiB isn't counted
        self.assertTrue(summary["checks"]["Memory, all parts together (peak)"])

        write_run(self.folder, memory=(1500, 1500, 500, 200))  # 3.6 GB: more than a 4 GB server leaves
        summary = self.make()
        self.assertEqual(summary["overall"], "FAIL")
        self.assertFalse(summary["checks"]["Memory, all parts together (peak)"])

    def test_stress_run_reports_the_capacity_it_found(self):
        history = []
        for minute in range(16):
            users = 25 * (minute + 1)
            p95 = 200 if users <= 200 else 800  # past 200 people, 1 in 20 clicks waits too long
            history += [(minute * 60 + s, users, users / 4, 0, p95, 700) for s in range(0, 60, 10)]
        write_run(self.folder, scenario="stress", history=history)
        summary = self.make()
        self.assertEqual(summary["overall"], "INFO")
        self.assertEqual(summary["capacity_users"], 200)
        self.assertIn("up to <strong>200 people active at the same time</strong>", self.html)

    def test_proxy_timings(self):
        write_run(self.folder)
        summary = self.make()
        self.assertAlmostEqual(summary["proxy_avg_ms"], 14.95, places=1)

    def test_reports_from_before_the_cpus_were_shared_still_work(self):
        write_run(self.folder, meta={"cpus": None, "limits": {
            "web": {"cpus": "1.0", "memory": "1536m"}, "db": {"cpus": "0.6", "memory": "1536m"},
            "worker": {"cpus": "0.15", "memory": "512m"}, "proxy": {"cpus": "0.25", "memory": "256m"}}})
        self.assertEqual(self.make()["app_cpus"], 2)

    def test_a_trial_without_a_size_cap_says_so(self):
        write_run(self.folder, meta={"cpus": None, "limits": None, "scale": 0.1})
        (self.folder / "resources.log").unlink()
        summary = self.make()
        self.assertIsNone(summary["app_cpus"])
        self.assertIn("none recorded (trial run, results not representative)", self.html)
        self.assertIn("shortened trial run", self.html)

    def test_says_when_the_data_wasnt_reset(self):
        write_run(self.folder, meta={"fresh_data": False})
        self.make()
        self.assertIn("didn't reset the data first", self.html)

    def test_no_results_is_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(report.main(self.folder), 1)

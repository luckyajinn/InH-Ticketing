"""
Load scenarios for InH-Ticketing. STRESS-TEST BRANCH ONLY.

Run by stress/run.sh inside the `loadgen` container; see stress/README.md.
Each simulated person signs in automatically as a fake user (X-Stress-User
header; stress-test mode only) and clicks through the app with pauses
("think time") between actions, like a real person:

  Staff     check their open and past tickets, open one, download a file,
            raise a request (some with a photo or document attached),
            reply (sometimes with a file), and mark a ticket resolved.
  IT        work the queue: views, search, open tickets, download files,
            public replies (some "Send and set Waiting on User" or "Send and
            resolve"), internal notes (some with a file), side-panel changes
            to status and priority, and "Assign to me".

Every page and form is checked: a page that doesn't load as the fake user,
or a form the app doesn't accept, counts as a failure.

Environment:
  STRESS_SCENARIO         expected | peak | stress | soak   (default expected)
  STRESS_DURATION_SCALE   multiply every stage's length, e.g. 0.1 for a quick try
  STRESS_REQUESTERS       how many fake requester accounts exist (default 300)
  STRESS_AGENTS           how many fake agents exist (default 5)
"""

import math
import os
import random
import sys
from pathlib import Path

from locust import HttpUser, LoadTestShape, between, task

sys.path.insert(0, str(Path(__file__).resolve().parent))  # pages.py sits next to this file
import pages  # noqa: E402

SCENARIO = os.getenv("STRESS_SCENARIO", "expected")
SCALE = float(os.getenv("STRESS_DURATION_SCALE", "1"))
N_REQUESTERS = int(os.getenv("STRESS_REQUESTERS", "300"))
N_AGENTS = int(os.getenv("STRESS_AGENTS", "5"))

# name: (think time in seconds (min, max), stages [(stage length in s, users), ...], description)
SCENARIOS = {
    "expected": ((5, 15), [(60, 35), (600, 35)],
                 "A normal busy period: 30 staff and all 5 IT agents active at once, for 10 minutes."),
    "peak": ((2, 5), [(120, 100), (600, 100)],
             "A very busy period (for example a company-wide outage): 100 people at once, "
             "acting about three times faster than normal, for 10 minutes."),
    "stress": ((1, 3), [(60, 25 * step) for step in range(1, 17)],
               "Find the limit: start at 25 people and add 25 every minute up to 400, "
               "acting very quickly, until something gives."),
    "soak": ((5, 15), [(120, 35), (7200, 35)],
             "Endurance: a normal busy period held for 2 hours, to catch slow leaks."),
}
if SCENARIO not in SCENARIOS:
    raise SystemExit(f"Unknown STRESS_SCENARIO {SCENARIO!r}; use one of {', '.join(SCENARIOS)}")
THINK, STAGES, _ = SCENARIOS[SCENARIO]

SEARCH_WORDS = ["printer", "vpn", "outlook", "slow", "password", "monitor", "teams", "1023", "error"]
QUEUE_VIEWS = ["open", "unassigned", "mine", "waiting", "resolved"]
UPLOAD_KINDS = [("photo", ".jpg", "image/jpeg"), ("screenshot", ".png", "image/png"),
                ("document", ".pdf", "application/pdf")]


def maybe_file(share: float):
    """With probability `share`, one file to upload, sized like real attachments (median ~800 KB)."""
    if random.random() >= share:
        return None
    stem, ext, content_type = random.choice(UPLOAD_KINDS)
    size = int(min(max(random.lognormvariate(math.log(800_000), 1.1), 5_000), 10_000_000))
    return {"attachments": (f"{stem}-{random.randint(1000, 9999)}{ext}", os.urandom(size), content_type)}


class StressUser(HttpUser):
    abstract = True
    wait_time = between(*THINK)

    def username(self) -> str:
        raise NotImplementedError

    def on_start(self):
        self.client.verify = False  # the test server uses a self-signed certificate
        self.client.headers["X-Stress-User"] = self.username()
        self.tickets: list[str] = []
        self.files: list[str] = []
        self.page("/", "/ (sign in and land)")

    def page(self, url: str, name: str, check=None):
        """
        GET a page. It counts as failed unless it loads (200) as the signed-in
        fake user; `check(response)` may return a reason to fail it as well.
        """
        with self.client.get(url, name=name, catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
            elif "/signin" in response.url:
                response.failure("sent to the sign-in page")
            elif check and (reason := check(response)):
                response.failure(reason)
        return response

    def post_form(self, url: str, data: dict, name: str, files=None):
        """
        POST a form the way the browser does. The app answers an accepted form
        with a redirect; a rejected one is shown again (400) or refused (403).
        Anything but a redirect back into the app counts as failed.
        """
        headers = {"X-CSRFToken": self.client.cookies.get("csrftoken", ""), "Referer": self.host + url}
        with self.client.post(url, data=data, files=files, name=name, headers=headers,
                              allow_redirects=False, catch_response=True) as response:
            location = response.headers.get("Location", "")
            if response.status_code != 302:
                response.failure(f"HTTP {response.status_code}: the form wasn't accepted")
            elif "/signin" in location:
                response.failure("sent to the sign-in page")
        return response

    def open_ticket(self, name: str):
        """Open one of the remembered tickets, and remember its attachment links."""
        if not self.tickets:
            self.refresh()
        if not self.tickets:
            return None
        number = random.choice(self.tickets)
        response = self.page(f"/tickets/{number}/", name)
        self.files = pages.attachment_links(response.text) or self.files
        return number, response

    def download(self):
        if not self.files:
            self.open_ticket(self.detail_name)
        if self.files:
            self.page(random.choice(self.files), "/attachments/[file] (download)")

    def refresh(self):
        raise NotImplementedError


class Requester(StressUser):
    """Staff member: checks their tickets, sometimes raises or answers one."""

    weight = 1
    detail_name = "/tickets/[n]/ (requester)"

    def username(self):
        return f"stress-req-{random.randint(1, N_REQUESTERS):04d}"

    def on_start(self):
        self.open: list[str] = []  # their open tickets (can reply, mark resolved)
        self.past: list[str] = []  # resolved and closed ones (can view)
        super().on_start()

    def refresh(self):
        self.my_tickets()
        if not self.tickets:
            self.my_past_tickets()

    @task(10)
    def my_tickets(self):
        response = self.page("/tickets/", "/tickets/ (my tickets)")
        self.open = pages.ticket_numbers(response.text)
        self.tickets = self.open + self.past

    @task(3)
    def my_past_tickets(self):
        response = self.page("/tickets/?show=closed", "/tickets/?show=closed")
        self.past = pages.ticket_numbers(response.text)
        self.tickets = self.open + self.past

    @task(8)
    def view_ticket(self):
        self.open_ticket(self.detail_name)

    @task(1)
    def download_file(self):
        self.download()

    @task(1)
    def new_request(self):
        form = self.page("/tickets/new/", "/tickets/new/",
                         check=lambda r: None if pages.options(r.text, "category") else "no categories on the form")
        categories = pages.options(form.text, "category")
        if not categories:
            return
        response = self.post_form("/tickets/new/", {
            "subject": f"Stress test: {random.choice(SEARCH_WORDS)} problem",
            "category": random.choice(categories),
            "description": "Generated by the stress test. Fake data.",
            "is_blocking": "on" if random.random() < 0.15 else "",
        }, name="POST /tickets/new/", files=maybe_file(0.3))
        number = pages.ticket_from_location(response.headers.get("Location", ""))
        if number:
            self.open = [number] + self.open
            self.tickets = [number] + self.tickets

    @task(2)
    def reply(self):
        if self.open:
            number = random.choice(self.open)
            self.post_form(f"/tickets/{number}/reply/", {"body": "Stress test reply. Fake data.",
                                                         "visibility": "public"},
                           name="POST /tickets/[n]/reply/ (requester)", files=maybe_file(0.1))

    @task(1)
    def mark_resolved(self):
        if self.open:
            number = random.choice(self.open)
            self.post_form(f"/tickets/{number}/resolve/", {}, name="POST /tickets/[n]/resolve/ (requester)")
            self.open = [n for n in self.open if n != number]


class Agent(StressUser):
    """IT agent: works the queue all day."""

    fixed_count = N_AGENTS  # always exactly as many agents as the real team
    detail_name = "/tickets/[n]/ (agent)"

    def username(self):
        return f"stress-agent-{random.randint(1, N_AGENTS):02d}"

    def refresh(self):
        self.queue()

    @task(6)
    def queue(self):
        view = random.choice(QUEUE_VIEWS)
        response = self.page(f"/queue/?view={view}", "/queue/?view=[view]")
        self.tickets = pages.ticket_numbers(response.text) or self.tickets

    @task(2)
    def search(self):
        self.page(f"/queue/?q={random.choice(SEARCH_WORDS)}", "/queue/?q=[search]")

    @task(1)
    def queue_page_two(self):
        self.page("/queue/?view=resolved&page=2", "/queue/ page 2")

    @task(6)
    def view_ticket(self):
        self.open_ticket(self.detail_name)

    @task(1)
    def download_file(self):
        self.download()

    @task(3)
    def public_reply(self):
        if self.tickets:
            number = random.choice(self.tickets)
            then = random.choices(["", "waiting", "resolved"], [5, 2, 3])[0]
            self.post_form(f"/tickets/{number}/reply/", {"body": "Stress test reply from IT. Fake data.",
                                                         "visibility": "public", "then_status": then},
                           name="POST /tickets/[n]/reply/ (agent public)", files=maybe_file(0.05))

    @task(1)
    def internal_note(self):
        if self.tickets:
            number = random.choice(self.tickets)
            self.post_form(f"/tickets/{number}/reply/", {"body": "Stress test note. Fake data.",
                                                         "visibility": "internal"},
                           name="POST /tickets/[n]/reply/ (agent note)", files=maybe_file(0.15))

    @task(2)
    def change_properties(self):
        """Open a ticket, then change its priority or status in the side panel."""
        if not self.tickets:
            self.refresh()
        if not self.tickets:
            return
        number = random.choice(self.tickets)
        response = self.page(f"/tickets/{number}/", self.detail_name,
                             check=lambda r: None if pages.side_panel(r.text) else "no IT side panel on the page")
        panel = pages.side_panel(response.text)
        if panel is None:
            return
        if random.random() < 0.6:
            panel["priority"] = random.choice([p for p in "1234" if p != panel["priority"]])
        else:
            panel["status"] = random.choice([s for s in ("open", "in_progress", "waiting") if s != panel["status"]])
        self.post_form(f"/tickets/{number}/update/", panel, name="POST /tickets/[n]/update/ (side panel)")

    @task(1)
    def assign_to_me(self):
        if self.tickets:
            number = random.choice(self.tickets)
            self.post_form(f"/tickets/{number}/assign-to-me/", {}, name="POST /tickets/[n]/assign-to-me/")


class ScenarioShape(LoadTestShape):
    """Runs the stages of STRESS_SCENARIO, then stops."""

    def tick(self):
        elapsed = self.get_run_time()
        end = 0.0
        for length, users in STAGES:
            end += length * SCALE
            if elapsed < end:
                spawn_rate = max(users / max(length * SCALE, 1), 1)
                return users, spawn_rate
        return None

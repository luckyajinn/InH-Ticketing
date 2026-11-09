# Roadmap

Where InH-Ticketing is heading, version by version, with target dates.
Written 2026-11-06; update it whenever a date moves. FDA review done (Ruben Martinez) and internal setup approved (Michael Rocovitz), 2026-11-06. Item-level detail
lives in [backlog.md](backlog.md), and what actually shipped is in
[releases/](releases/README.md).

## How to read the dates

- **Build time is short:** about a day per milestone, including tests, release
  notes and screenshots.
- **The pace is set by things outside the code:** Exchange setup, the server,
  DNS and certificate, and above all **pilot feedback**. Each row lists what
  it's waiting on.
- **Holidays:** dates avoid US Thanksgiving week (Nov 23–27) and a year-end
  change freeze (Dec 21 – Jan 1).
- **Version numbers:** each milestone is the next `0.x.0`, fixes are `0.x.1`,
  `0.x.2` and so on, and **1.0.0 means live for everyone**.

## Timeline (recommended path)

| When | Version | What | Waiting on |
|---|---|---|---|
| ✅ Nov 5 | v0.1.0 | Microsoft 365 sign-in, roles | — |
| ✅ Nov 5 | v0.2.0 | Tickets, IT queue, internal notes, history, attachments | — |
| ✅ Nov 6 | v0.3.0 | Email notifications, "Send and resolve" buttons | — |
| ✅ Nov 6 | v0.4.0 | Email in: emails become tickets and replies | — |
| ✅ Nov 6 | v0.5.0 | Automations: auto-close, follow-ups and linked tickets, "IT issues only" notice and usage rules. Reminders deferred to the backlog | — |
| ✅ Nov 9 | v0.6.0 | Deployment package: Docker Compose with an HTTPS proxy for the internal-CA certificate, nightly local backups and restores, server requirements and deployment guide. Released before the server exists, after a load test of the same setup on a test VM | — |
| Nov 9–20 | v0.6.x | Fixes from testing on your PC with your test user and real email | Your testing (below) |
| **When the server is ready** (target week of Nov 16) | v0.6.x | First install on the server, fixes from it, and the restore drill | Server, DNS and certificate |
| Nov 23–27 | — | Thanksgiving week: buffer for deployment fixes, no new features | — |
| **Nov 30 – Dec 11** | v0.6.x | **Pilot:** IT plus 10–20 staff use it for real, on their own computers, with the test mailbox | v0.6.0 live on the server |
| **Week of Dec 14** | **v0.7.0** | Pilot feedback: the header redesign and the top pilot requests | Pilot feedback |
| Dec 21 – Jan 1 | — | Change freeze | — |
| **Week of Jan 11, 2027** | **v1.0.0** | **Go-live for all ~300 staff:** switch to the live help-desk mailbox, assign all staff in Entra, tell everyone | Sign-off on the pilot |
| 2027 | v1.x | Improvements, chosen from pilot and live use (see below) | — |

## Your side, by date

| By | Task | Unlocks |
|---|---|---|
| Nov 13 | Create the test shared mailbox; run the Exchange steps for sending and reading ([email-setup.md](email-setup.md) 3c and 4b); set `IT_NOTIFY_EMAIL` | Real email on your PC |
| Nov 13 | Test on your PC with your test user and real email; note anything that feels wrong | v0.5.x fixes |
| Nov 13 | Check DMARC is enforced on `mckennalabs.com` | Trusting email-in |
| **Nov 16** | Linux VM ready: 2 vCPU, 4 GB RAM, ~80 GB disk, Docker installed, outbound HTTPS to Microsoft allowed | v0.6.0 |
| **Nov 16** | DNS record for `helpdesk.mckennalabs.com`; certificate issued by the internal CA | v0.6.0 |
| Nov 27 | Choose the pilot group (10–20 staff); add them to the Entra test group; assign IT as Agent | Pilot start |
| Dec 18 | Pilot sign-off: go / no-go for January | v1.0.0 |
| Jan 8 | Decide the live mailbox cut-over; draft the all-staff announcement | Go-live |

## Variations

**A. Recommended: automations, then deploy, then pilot.** As above.
v0.5.0 can be fully built and tested on your PC now, so nothing waits. The
pilot starts once the server is live.

**B. Deploy first.** Swap v0.5.0 and v0.6.0. Testers get onto their own
computers about a week sooner, **but only if the server is ready on Nov 9**.
The trade-off: the Docker and HTTPS setup can't be tested on your PC, so the
first deploy is more likely to need fixes. Automations follow a week later.

**C. Leaner pilot.** Skip the optional reminders in v0.5.0, or pilot without
v0.5.0 at all. The pilot doesn't strictly need automations; IT can close
resolved tickets by hand. This saves about a day, but resolved tickets pile up.

**D. Slip.** If the server or certificate isn't ready by Nov 16, everything
from v0.6.0 onward moves by the same amount. Thanksgiving and the year-end
freeze make **go-live in January** the realistic floor, and a server slip
past about Dec 1 pushes go-live into **late January or February**.

## After 1.0: candidate improvements (v1.x)

To be prioritised from pilot and live feedback:

- **Reply templates:** saved answers for common requests (password resets, new starters).
- **Response targets (SLA):** how long tickets wait, by priority, with overdue highlighting.
- **Reporting:** tickets per week, time to resolve, busiest categories.
- **Merging duplicate tickets.**
- **Teams notifications** for IT, alongside or instead of email.
- **Backups copied off the server** (a network share or a second machine).
- **Admin screens** beyond the Django admin, if IT outgrows it.

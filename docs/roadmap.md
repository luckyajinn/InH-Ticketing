# Roadmap

Where InH-Ticketing is heading, version by version, with target dates.
Written 2026-11-06; **rewritten 2026-11-09**: the server went live a week early,
so the plan now aims to have **everything finalized by Friday 2026-11-20**.
Update it whenever a date moves. FDA review done (Ruben Martinez) and internal
setup approved (Michael Rocovitz), 2026-11-06; the risk assessment passed.
Item-level detail lives in [backlog.md](backlog.md), and what actually shipped
is in [releases/](releases/README.md).

## How to read the dates

- **Build time is short:** a day or less per release, including tests,
  release notes and screenshots.
- **The pace is set by things outside the code:** what the pilot finds,
  server and Microsoft 365 tasks, and sign-off. Each row lists what it's
  waiting on.
- **Holidays:** US Thanksgiving week (Nov 23–27) and a year-end change freeze
  (Dec 21 – Jan 1) still apply to go-live.
- **Version numbers:** each milestone is the next `0.x.0`, fixes are `0.x.1`,
  `0.x.2` and so on, and **1.0.0 means ready for everyone**.

## Timeline: finalized by Friday Nov 20

| When | Version | What | Waiting on |
|---|---|---|---|
| ✅ Nov 5–6 | v0.1.0–v0.5.0 | Sign-in and roles, tickets and the IT queue, email out and in, automations and the FDA usage controls | — |
| ✅ Nov 9 | v0.6.0 | Deployment package: HTTPS proxy, nightly backups and restores, server guides | — |
| ✅ Nov 9 | Server | Live on the internal server (16 cores, 32 GB RAM) and tested | — |
| ✅ Nov 9 | **v0.7.0** | The new look, the password check with its audit trail, folded email signatures | — |
| **Tue Nov 10** | Demo, pilot starts | Demo of v0.7.0. Pilot with one other tester, trying to break it ([pilot-testing.md](pilot-testing.md)) | v0.7.0 installed on the server |
| Nov 10–17 | v0.7.x | Fixes as the pilot finds them, released as small updates | Pilot findings |
| **Wed Nov 18** | **v0.8.0** | Pilot fixes, the pasted-password removal tool (a before-go-live compliance item), the closed-ticket decision | Pilot findings, decisions |
| Thu Nov 19 | v1.0.0 candidate | Final checks on the server: restore drill, off-server backup, everything below ticked | Your side (below) |
| **Fri Nov 20** | **v1.0.0** | **Everything finalized:** go / no-go, go-live date set, docs and release done | Sign-off |
| Go-live (date set on Nov 20) | v1.0.0 live | Switch to the live help-desk mailbox, assign all ~300 staff in Entra, tell everyone. Earliest Mon Nov 30, after Thanksgiving week; not during the Dec 21 – Jan 1 freeze | Go / no-go |
| 2027 | v1.x | Improvements, chosen from pilot and live use (see below) | — |

## Your side, by date

| By | Task | Unlocks |
|---|---|---|
| **Tue Nov 10, morning** | Install v0.7.0 on the server ([deployment.md](deployment.md), updating to a new version; it needs `migrate`). Check ticket #1071's signature is folded | Demo, pilot |
| Tue Nov 10 | Start the pilot with one tester; report findings as tickets with "Pilot:" in the subject | v0.7.x fixes |
| Fri Nov 13 | Restore drill on the server, recorded ([deployment.md](deployment.md) section 9) | v1.0.0 |
| Fri Nov 13 | Entra: confirm the server's redirect URI, and give the server its own client secret or certificate | v1.0.0 |
| Fri Nov 13 | File the `Test-ServicePrincipalAuthorization` output with the risk assessment; check DMARC on `mckennalabs.com` | v1.0.0 |
| Tue Nov 17 | Pilot ends; decide what happens to closed tickets, and whether the removal tool is in v0.8.0 | v0.8.0 |
| Wed Nov 18 | Off-server backup copy (a network share or a second machine) and one tested restore from it | v1.0.0 |
| **Fri Nov 20** | Go / no-go; set the go-live date and the live-mailbox cut-over; draft the all-staff announcement | Go-live |

## If things slip

- **The pilot finds something big:** v0.8.0 moves, and Nov 20 becomes the
  go / no-go for a later date instead of the finish line.
- **The removal tool isn't ready by Nov 18:** it's a before-go-live compliance
  item, so go-live waits for it, unless Ruben Martinez agrees a manual
  procedure in the meantime.
- **Go-live can't fit before Dec 21:** the change freeze moves it to the week
  of Jan 11, 2027, as in the original plan.

## After 1.0: candidate improvements (v1.x)

To be prioritised from pilot and live feedback:

- **Reply templates:** saved answers for common requests (password resets, new starters).
- **Response targets (SLA):** how long tickets wait, by priority, with overdue highlighting.
- **Reporting:** tickets per week, time to resolve, busiest categories.
- **Merging duplicate tickets.**
- **Teams notifications** for IT, alongside or instead of email.
- **Admin screens** beyond the Django admin, if IT outgrows it.

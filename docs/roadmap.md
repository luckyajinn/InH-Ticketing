# Roadmap

Where InH-Ticketing is heading, version by version, with target dates.
Written 2026-11-06; **rewritten 2026-11-09**: the server went live a week early,
so the plan now aims to have **everything finalized by Friday 2026-11-20**,
with v1.0.0 by the end of this week and v1.1.0 and v1.2.0 as stretch goals
before the 20th. Update it whenever a date moves. FDA review done (the compliance lead) and internal setup approved (management), 2026-11-06; the risk
assessment passed. Item-level detail lives in [backlog.md](backlog.md), and
what actually shipped is in [releases/](releases/README.md).

## How to read the dates

- **Build time is short:** a day or less per release, including tests,
  release notes and screenshots.
- **The pace is set by things outside the code:** what the pilot finds,
  server and Microsoft 365 tasks, and sign-off. Each row lists what it's
  waiting on.
- **Stretch** releases happen only if the pilot fixes and v1.0.0 are done
  first; anything they don't fit moves to after go-live.
- **Holidays:** US Thanksgiving week (Nov 23–27) and a year-end change freeze
  (Dec 21 – Jan 1) still apply to go-live.
- **Version numbers:** each milestone is the next `0.x.0` or `1.x.0`, fixes
  are `x.y.1`, `x.y.2` and so on, and **1.0.0 means ready for everyone**.

## Timeline: finalized by Friday Nov 20

Nov 9 is a Monday.

| When | Version | What | Waiting on |
|---|---|---|---|
| ✅ Nov 5–6 | v0.1.0–v0.5.0 | Sign-in and roles, tickets and the IT queue, email out and in, automations and the FDA usage controls | — |
| ✅ Mon Nov 9 | v0.6.0 | Deployment package: HTTPS proxy, nightly backups and restores, server guides | — |
| ✅ Mon Nov 9 | Server | Live on the internal server (16 cores, 32 GB RAM) and tested | — |
| ✅ Mon Nov 9 | **v0.7.0** | The new look, the password check with its audit trail, folded email signatures | — |
| ✅ Mon Nov 9 | **v0.8.0** | Mechanics and Cleaning & sanitization requests, with common requests | — |
| ✅ Mon Nov 9 | **v0.8.2** | The site basics (below): new Not found page, help contact, no double-sent requests, wording for every team, usage and privacy page, favicon, kept out of search engines | — |
| ✅ Tue Nov 10 | **v0.8.3** | Fixes from the pre-pilot review (three reviews and an attack test): side panel, unsent replies, password check false alarms, signature folding, odd characters | — |
| ✅ Tue Nov 10 | **v0.8.4** | The admin site in the app's look; a chosen common request is always the subject | — |
| ✅ Tue Nov 10 | **v0.9.0** | Reports for admins, built early from v1.1.0: requests, response and resolve times, open tickets by age and email health, per team, never per person; CSV download | — |
| ✅ Wed Nov 11 | **v0.10.0** | Admins set up the departments in the admin site: IT built in, each other team with its own Entra role, alert address and Reports colour, up to 8. A new install has IT only. The clickable mockup is built from the app's pages | — |
| ✅ Tue Nov 10 | **v0.9.1** | Before go-live: Mechanics and C&S see and work their own tickets (v1.2.0's queues, built early), closed tickets archived for two years, the pasted-password removal tool, fake "IT" emails, shared PCs, no ticket deletes; department mailboxes ready to switch on | — |
| **Tue Nov 10** | Demo, pilot starts | CFO demo of v0.8.3. Pilot with one other tester, trying to break it ([pilot-testing.md](pilot-testing.md)). Risk assessment for the new teams with the compliance lead | v0.8.3 installed on the server |
| **After the pilot's testing** | **v0.9.x** | Paused until the pilot's testing is done. Then: pilot fixes | Pilot findings |
| **Fri Nov 13** (or Mon Nov 16) | **v1.0.0** | **Everything for IT finalized,** plus **a mailbox per department**: email to Mechanics' or C&S's mailbox becomes a ticket for that department, answered from the same mailbox. Final checks on the server, docs and release done | Your side (below); the mailbox decision |
| Mon–Tue Nov 16–17 | v1.1.0 (stretch) | IT improvements: reply templates, response targets, Teams alerts (reporting shipped early, in v0.9.0) | A Teams webhook or permission for the alerts |
| Wed–Thu Nov 18–19 | v1.2.0 (stretch) | More common requests and a self-fill option for Mechanics and C&S (their own queues and roles shipped early, in v0.9.1) | The common requests from the teams |
| **Fri Nov 20** | Final | **Go / no-go**, go-live date set, last docs and release | Sign-off |
| Go-live (date set on Nov 20) | Live | Switch to the live help-desk mailbox, assign all ~300 staff in Entra, set `REPORTS_FROM` to the go-live date, tell everyone. Earliest Mon Nov 30, after Thanksgiving week; not during the Dec 21 – Jan 1 freeze | Go / no-go |
| 2027 | v1.x | Improvements, chosen from pilot and live use (see below) | — |

## Your side, by date

| By | Task | Unlocks |
|---|---|---|
| **Tue Nov 10, morning** | Install v0.8.3 on the server ([deployment.md](deployment.md), section 10; the migrations run when it starts). Set `HELP_CONTACT` in `.env` first. Check ticket #1071's signature is folded, and that Mechanics and Cleaning & sanitization are on the New request form | Demo, pilot |
| Tue Nov 10 | Start the pilot with one tester; report findings as tickets with "Pilot:" in the subject | v0.9.x fixes |
| Tue Nov 10 | Risk assessment for Mechanics and Cleaning & sanitization with the compliance lead; then update [usage-rules.md](usage-rules.md) | v1.2.0 |
| ✅ Tue Nov 10 | Closed tickets: archived for two years, then deleted (archiving built in v0.9.1) | v0.9.1 |
| **Before installing v0.9.1** | In Entra, create the `Agent.Mechanics` and `Agent.Cleaning` app roles and assign each team's group to its own (never plain `Agent`) | v0.9.1 |
| Thu Nov 12 | Department mailboxes (no confirmation yet of a shared mailbox for each, Nov 10): decide new request-only mailboxes or a "Requests" folder in the existing ones (see [backlog.md](backlog.md), v1.0.0); send the addresses; in Exchange, allow the app to send as and read each one, set internal senders only, and record `Test-ServicePrincipalAuthorization` for each | v1.0.0 |
| Fri Nov 13 | Restore drill on the server, recorded ([deployment.md](deployment.md) section 9) | v1.0.0 |
| Fri Nov 13 | Entra: confirm the server's redirect URI, and give the server its own client secret or certificate | v1.0.0 |
| Fri Nov 13 | File the `Test-ServicePrincipalAuthorization` output with the risk assessment; check DMARC on `example.com` | v1.0.0 |
| Fri Nov 13 | Off-server backup copy (a network share or a second machine) and one tested restore from it | v1.0.0 |
| Mon Nov 16 | Teams: a webhook or permission for IT alerts | v1.1.0 |
| ✅ Tue Nov 10 | Entra groups for the Mechanics and Cleaning & sanitization teams are live. Still to do: assign each group its app role, `Agent.Mechanics` or `Agent.Cleaning` (safe before v1.2.0; never the plain `Agent` role) | v1.2.0 |
| Mon Nov 16 | The common requests you're gathering from Mechanics and Cleaning & sanitization | v1.2.0 |
| **Fri Nov 20** | Go / no-go; set the go-live date and the live-mailbox cut-over; draft the all-staff announcement | Go-live |

## Site basics (checklist, 2026-11-09)

From a review of common website basics against what an internal, sign-in-only
app needs. The ones it needed and didn't have all shipped in v0.8.2, most
important first:

| Priority | Item | Why it matters | Status |
|---|---|---|---|
| 1 | **Help contact** | Someone who can't sign in, or hits an error, had only "Contact IT", with no way to do it | ✅ v0.8.2 (`HELP_CONTACT`) |
| 2 | **Sending state, no double sends** | A double click could create two tickets or two replies | ✅ v0.8.2 |
| 3 | **Wording for every team** | "IT will pick it up soon" told Mechanics and C&S requesters the wrong team | ✅ v0.8.2 |
| 4 | **Usage and privacy page** | Says what's kept and who sees it; needed before go-live, and a fuller notice before licensing | ✅ v0.8.2 (`/about/`) |
| 5 | **Favicon set** | Find the tab among many; an icon on phone home screens | ✅ v0.8.2 |
| 6 | **robots.txt and noindex** | Insurance in case the server is ever reachable from outside | ✅ v0.8.2 |

Already in place: CTA above the fold, a title per page, alt text (the app has
no content images), mobile layouts, form error states. Decided against, as
bloat for an internal app: per-page meta descriptions, Open Graph images, a
sitemap, a sticky mobile CTA, a separate thank-you page, a terms page (the
usage rules are the terms), a cookie banner (only necessary cookies), and
third-party analytics (v1.1.0's reporting answers the same questions).

## If things slip

- **The pilot finds something big:** the pilot fixes and v1.0.0 move, the stretch
  releases wait until after go-live, and Nov 20 becomes the go / no-go for a
  later date instead of the finish line.
- **The removal tool isn't ready before v1.0.0:** it's a before-go-live
  compliance item, so go-live waits for it, unless the compliance lead agrees a
  manual procedure in the meantime.
- **v1.1.0 or v1.2.0 doesn't fit by Nov 19:** it ships after go-live instead.
  Until v1.2.0, Mechanics and Cleaning & sanitization tickets are worked from
  the IT queue.
- **Go-live can't fit before Dec 21:** the change freeze moves it to the week
  of Jan 11, 2027, as in the original plan.

## After 1.0: candidate improvements (v1.x)

To be prioritised from pilot and live feedback. Reply templates, response
targets, reporting and Teams alerts are planned for v1.1.0 (above).

- **Merging duplicate tickets.**
- **Admin screens** beyond the Django admin, if IT outgrows it.

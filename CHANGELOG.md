# Changelog

All notable changes to InH-Ticketing. Versions follow [Semantic Versioning](https://semver.org).
Each version also has illustrated release notes in [docs/releases](docs/releases/README.md).

## [0.9.0] - 2026-11-10

Reports for admins, built early from v1.1.0. [Release notes](docs/releases/v0.9.0.md).

### Added
- **Reports** (`/reports/`, admins only; agents and requesters get a 403;
  never cached), linked in the header and the admin site. Per team, never
  per person, from records the app already keeps:
  - **headline numbers** against the period before: new requests, first
    response, time to resolve (not counting waiting on the requester) and
    the blocking share
  - **requests over time**, stacked by team, with a hover readout and a table
  - **a by-team table**
  - **open requests** by age, with the five oldest
  - **the most common categories and common requests**
  - **email and safety checks**: email out and in, a stopped worker, the
    password check, auto-close
  - **a CSV download**: no descriptions or names, formula cells made safe
- Charts drawn on the server as SVG, no library, in team colours checked
  for colour-blind separation and contrast in light and dark.
- `REPORTS_FROM`: count tickets from a date (the go-live date). "Pilot:"
  tickets are always left out.

### Changed
- Usage and privacy page: admins see reports per team, never per person.
- Roadmap: the pilot fixes, the removal tool and the closed-ticket decision
  wait for the pilot's testing (v0.9.x).

### Upgrading
- No database changes. Optionally set `REPORTS_FROM` in `.env`.

## [0.8.4] - 2026-11-10

The admin site in the app's look, and a chosen common request is always the
subject. [Release notes](docs/releases/v0.8.4.md).

### Changed
- **The admin site looks like the rest of the app:** the app's header (with
  "Back to InH-Ticketing" and the app's own Sign out), warm background,
  rounded cards, pill buttons and queue-style tables, in light and dark
  (`templates/admin/base_site.html`, `static/css/admin.css`). No sidebar, so
  lists get the full width; sections renamed People, Email in, Email out and
  Tickets; light or dark follows the device, so no theme switch.
- **A chosen common request is the subject,** over anything typed. The
  subject box greys out (keeping what was typed) with a note that it won't
  be used; "None, I'll type my own subject" brings it back. The category
  still fills in, and a category chosen afterwards still wins. The password
  check skips the greyed-out subject, since it isn't sent.

### Upgrading
- One migration, `tickets` 0006: the admin's help text for common requests.
  Nothing changes in the database. Rolling back to v0.8.3 needs no restore.

## [0.8.3] - 2026-11-10

Fixes from the pre-pilot review: three independent reviews of v0.8.2
(security and privacy, feature logic, deployment) and an attack test.
[Release notes](docs/releases/v0.8.3.md).

### Fixed
- **The side panel no longer puts back old values.** It also sends what it
  showed when the page loaded, and saving applies only the fields the person
  changed. Before, a page left open could undo someone else's assignment, or
  reopen a ticket the requester had just resolved.
- **A reply being typed survives the side panel saving** (and "Assign to me"):
  it's set aside before the page reloads and put back afterwards.
- **Fewer false alarms from the password check** on everyday Mechanics and
  Cleaning & sanitization wording: "the pin is bent", "my pass is broken"
  (after "pin" or "pass" the value now needs a digit or symbol), lot, batch,
  cost, part and order codes, and the timestamps in pasted sign-in errors.
  It now also catches lock combinations ("combination is 12-34-56", "lock
  combo 2580").
- **Signatures fold only when they look like one:** two contact-looking lines
  at the end (rooms, units, links, a list of emails) no longer fold unless
  there's also a name, a sign-off or mail-app boilerplate. A `--` line only
  starts a signature near the end of an email.
- **No error pages from odd characters:** superscript digits ("²") in the
  ticket-number box, the queue search and filters, `?follow_up=` and common
  requests used to cause an error page (six places).
- **Sign-in:** a signed-in person opening the sign-in page with an odd `next=`
  link got an error page; now they go home. Only real page paths are followed.
- **Wording for every team:** "Replies will appear below", "Waiting for
  someone to pick it up", "Thanks for letting us know", and the receipt email.
- **Common requests:** a category the person chooses after picking a common
  request now wins over the pick's own category.

### Added
- An attack test (`tickets/tests/test_injection.py`): SQL injection, shell
  command and template injection strings in every input (forms, replies,
  notes, search, filters, the side panel, the ticket-number box, sign-in
  links, file names, emails coming in). All are stored and shown as plain
  text; nothing runs, the database stays intact, nothing errors.

### Docs
- deployment.md: `HELP_CONTACT` in the `.env` template and settings table
  (quote it if it contains `#`); a rollback that keeps tickets made since
  v0.7.0 (`migrate tickets 0003` first); the status banner.
- `scripts/restore.sh` now prints the start command with `--build`, so a
  restore can't start the newer version's images on the restored database.
- pilot-testing.md: updated for v0.8.x, with checks for the new features.

### Upgrading
- No database changes since v0.8.0. From v0.6.0 or v0.7.0, migrations
  `tickets` 0004 and 0005 run when the `web` container starts.
- Set `HELP_CONTACT` in `.env` first.

## [0.8.2] - 2026-11-09

The basics: a new Not found page, who to contact when the app can't help,
no more double-sent requests, wording for every team, a usage and privacy
page, a favicon, and staying out of search engines.
[Release notes](docs/releases/v0.8.2.md). (v0.8.1 was skipped: the Not found
page was going to be v0.8.1 on its own.)

### Added
- **Help contact** (`HELP_CONTACT` in `.env`): shown under "Can't sign in?"
  and on the sign-in problem, No access, Not found and Something went wrong
  pages. Blank falls back to "Email IT at" the help-desk mailbox, then to
  "Contact IT.". The Something went wrong page now has its own handler, which
  reads settings only, never the database.
- **Usage and privacy** page (`/about/`, open to everyone, linked from the
  footer and the sign-in page): what the app is for, what it keeps, who can
  see it, how long it's kept, and its cookies.
- **Favicon set**: the app's ticket mark for browser tabs, phone home screens
  and a web manifest; `/favicon.ico` points at it.
- **Kept out of search engines**: `/robots.txt` disallows everything, and
  every page says `noindex, nofollow`.
- **Sending state**: the pressed button shows a small spinner, and a double
  click no longer sends a request or reply twice.

### Changed
- New **Not found** page: next steps first. Staff get "Go to my tickets", IT
  gets "Go to the queue", both get "New request", and a "Have a ticket
  number?" box opens a ticket by its number (`/tickets/go/`). Signed out, it
  offers "Sign in". The wording never says whether a ticket exists, as the
  page also shows for tickets that aren't yours.
- Wording for every team, not just IT: "Request #1042 sent. You'll get an
  email when there's an update.", the tracker's "Being worked on" step, "Someone
  will pick it up soon", the sign-in page, My tickets, and the password warning.

### Fixed
- The hidden "Skip to content" link's shadow no longer peeks in at the top of
  signed-out pages.

### Upgrading
- No database changes. Optional: set `HELP_CONTACT` in `.env` (see
  `.env.example`), then rebuild so the new setting is picked up.

## [0.8.0] - 2026-11-09

Requests for two more teams, Mechanics and Cleaning & sanitization, with
common requests that fill in the subject. [Release notes](docs/releases/v0.8.0.md).

### Added
- Mechanics and Cleaning & sanitization categories, each with three common
  requests.
- **Common requests** on the New request form: picking one fills in the
  subject and its category, and people can still type their own. Admins set
  them per category in Admin, Categories (one per line). It works without
  JavaScript too, and only subjects an admin set up can be picked.

### Changed
- The New request page's notice and intro now name IT, mechanics, and
  cleaning and sanitization.
- The queue's Category column wraps long names ("Cleaning & sanitization")
  instead of widening the table.
- The demo data has a Mechanics ticket and a Cleaning & sanitization ticket.

### Upgrading
- Run `python manage.py migrate` (tickets 0005 adds the common requests and
  the two categories). The `web` container does this when it starts.

## [0.7.0] - 2026-11-09

The new look, the password check with its audit trail, and folded email
signatures. Released for the pilot, which starts 2026-11-10.
[Release notes](docs/releases/v0.7.0.md).

### Added
- Email signatures (the CodeTwo block: name, address, phone and fax, logo
  placeholder, "consider the environment", confidentiality notice) are folded
  under **Show email signature** on tickets and replies that arrive by email
  (`inbound/text.py`). The full email is still stored; it only folds when it
  finds at least two signs of a signature, and never on web requests. Works on
  tickets that arrived before this version too.
- Password check: the New request form, replies and internal notes warn before
  sending when the text might include a password, code or PIN
  (`tickets/password_guard.py`). It leans towards false alarms; people take it
  out or tick "send anyway". The page checks before sending, so attached files
  stay attached, and the server checks again when the form arrives.
- Password audit trail (`PasswordWarning`, read-only in Admin): who, where,
  which check, and whether it was sent anyway, taken out, or arrived by email.
  The text itself is never stored. A *Possible password* line in the ticket's
  history tells IT (requesters never see history).
- Emails that look like they contain a password are logged the same way.

### Changed
- New look ("Friendly Soft"): warm neutrals, one teal accent, rounded cards,
  chat-style conversations, and a progress tracker on the requester's ticket
  page. Gentle motion that switches off with "reduce motion". Queue subjects
  stay on one line on wider screens.
- Release screenshots are taken with reduced motion, so animations never show halfway.
- The demo data's emailed reply now carries a fictional signature, to show the fold.

### Fixed
- The password check no longer flags file names (`Report_Q3-2024v2.xlsx`) or
  the logo placeholders mail apps leave in signatures (`[cid:image001.png@...]`),
  which would have flagged nearly every emailed ticket.

### Upgrading
- Run `python manage.py migrate` (adds the password audit trail, tickets 0004).

## [0.6.0] - 2026-11-09

Milestone 6: the deployment package for the internal server. [Release notes](docs/releases/v0.6.0.md).
Released before the server exists. The same Docker setup has run on a test VM
for a load test; the first install on the real server is the next step.

### Added
- HTTPS reverse proxy: Caddy 2.11.9 (`compose.prod.yaml`, `deploy/caddy/Caddyfile`)
  with the internal-CA certificate, HTTP-to-HTTPS redirect, HSTS, 60 MB uploads
  buffered at the proxy, and log rotation. The web app's port 8000 is no longer
  published; only the proxy publishes 80 and 443.
- Production security settings: HTTPS redirect and HSTS (one year) on whenever
  `DEBUG` is off, with `/healthz` exempt so Docker's health check works.
  `manage.py check --deploy` is clean. New tests load the real production settings.
- Nightly backups (`scripts/backup.sh`, run by host cron): a database dump plus
  an attachments snapshot that hard-links unchanged files, so 14 days of backups
  cost about one copy of the attachments. Every backup is read back and checksummed.
- Restores (`scripts/restore.sh`): checks the checksums, takes a safety backup,
  restores into a new database and swaps it in only if that worked, then
  compares the attachments file by file.
- `docs/server-requirements.md` (for whoever builds the server) and
  `docs/deployment.md` (install, certificate, Entra, `.env`, first start,
  backups, restore drill, updating, rolling back, troubleshooting).
- `.gitattributes`: scripts and Docker files keep Linux line endings on Windows checkouts.
- `LICENSE`: proprietary, all rights reserved. The software is the sole property
  of Christian Jones (GitHub: luckyajinn), and may be used, deployed or licensed
  only with the owner's express written permission.

## [0.5.0] - 2026-11-06

Milestone 5: automations, follow-ups and FDA usage controls. [Release notes with screenshots](docs/releases/v0.5.0.md).

### Added
- Resolved tickets close automatically after `AUTO_CLOSE_RESOLVED_DAYS` (default
  7; 0 = off). Requesters see the close date on the ticket and in the email;
  the history records it as automatic. It runs in the worker hourly, or on
  demand with `manage.py close_resolved`.
- Follow-ups: "Start a follow-up" on closed tickets opens a linked new
  request. Email replies to closed tickets create the same link. A Linked
  tickets / Linked requests panel shows the links, limited to tickets the viewer may see.
- An "IT issues only" notice on the New request page (an FDA risk-assessment control).
- `docs/usage-rules.md` (staff and IT usage rules) and `docs/roadmap.md`.
- docs/email-setup.md: making the help-desk mailbox accept internal senders only.

### Fixed
- The attachment drop area's layout on the New request page (broken since v0.2.0).

## [0.4.0] - 2026-11-06

Milestone 4: email in. [Release notes with screenshots](docs/releases/v0.4.0.md).

### Added
- Email-in: the worker reads the test shared mailbox through Microsoft Graph
  (`INBOUND_EMAIL=graph`) and turns emails into tickets and replies.
  - `[#1028]` in the subject adds a reply to that ticket, keeping only the new
    text (Graph's `uniqueBody`, or quote-stripping for other sources).
  - Replies from someone other than the requester or IT become internal notes,
    and the assignee is alerted.
  - Replies to a closed ticket start a linked follow-up ticket; anything else
    creates a new ticket.
  - Processed emails are marked read and moved to "Processed by InH-Ticketing".
- Colleagues who email before ever signing in get an account, linked to their
  Microsoft 365 account on first sign-in.
- Attachments from email follow the web rules. Pictures inside signatures are
  skipped, and anything not attached is listed in the message.
- `manage.py ingest_email` puts a `.eml` file, or an email typed with
  `--from/--subject/--body`, through the same rules for local testing.
- Admin: an Inbound emails list recording every email and what happened to it.
- "You can also email …" hints for requesters when email-in is on.
- Email footers say what replying does. IT emails warn that replying sends a
  public reply.

### Security
- Out-of-office replies, bounces and mailing-list email are ignored (headers
  and subject), and outgoing email asks Exchange to suppress automatic replies.
- Only accepted domains are processed. Unknown senders get no reply, which
  avoids sending mail to forged addresses.
- Only plain text is requested and stored; nothing from outside is rendered as HTML.
- Each email is processed once (by Message-ID). Failures are retried 3 times,
  then left for a person.

### Changed
- Sending and reading share one Microsoft Graph client (`notifications/graph.py`).

## [0.3.0] - 2026-11-06

Milestone 3: outbound email. [Release notes with screenshots](docs/releases/v0.3.0.md).

### Added
- Email notifications: request received, IT replied, requester replied,
  ticket assigned, resolved and reopened. Internal notes never send one or
  appear in one, and nobody is emailed about their own action.
- An email queue (outbox) in the database, sent by a background worker
  (`manage.py run_worker`) with automatic retries. A failing mail server
  never blocks saving a ticket.
- Microsoft Graph sending from the test shared mailbox (`EMAIL_BACKEND=graph`),
  limited to that one mailbox by Exchange RBAC for Applications.
- Local email testing without sending anything (`EMAIL_BACKEND=file`, writes
  to `tmp/emails/`).
- Admin: an Outbound emails list showing status and errors, with a "Retry now" action.
- Composer buttons "Send and set Waiting on User" and "Send and resolve", so
  IT doesn't have to find the Status dropdown. *(Backlog item from testing.)*
- Docker Compose: a `worker` container.
- `docs/email-setup.md` and `docs/backlog.md`.

## [0.2.0] - 2026-11-05

Milestone 2: tickets. [Release notes with screenshots](docs/releases/v0.2.0.md).

### Added
- Requesters can submit a request (subject, category, description, "blocking my
  work", attachments), see their own tickets under Open and Closed, reply, mark
  a ticket resolved, and reopen it with "This is still a problem".
- An IT queue with views (Unassigned, Assigned to me, All open, Waiting on
  user, Recently resolved), search, filters, and sorting by priority and then age.
- An IT ticket page with a timeline of replies, internal notes and history,
  a Public reply / Internal note composer, and a side panel for status,
  priority, assignee and category that saves on change.
- Status rules: New moves to Open when IT replies or assigns the ticket;
  Waiting on User and Resolved move to Open when the requester replies.
- Every property change is logged with who changed it and when.
- Attachments up to 10 MB each (5 per message) from an allowlist of file
  types. They are stored under random names and only downloadable by people
  who may see them; files on internal notes are IT-only.
- Categories are editable in the admin site, with a read-only ticket record view there.
- `python manage.py seed_demo` loads fictional demo people and tickets for
  local testing, and `--clear` removes them.

### Changed
- `/` now sends IT to the queue and everyone else to their tickets.
- The header has navigation links and a role tag, matching the mockup.

### Security
- Requesters are only ever sent public replies: internal notes, their
  attachments and the history log are filtered out on the server.
- Ticket changes save only the fields that changed, so two people editing
  the same ticket don't overwrite each other's changes.

## [0.1.0] - 2026-11-05

Milestone 1: skeleton and Microsoft 365 sign-in. [Release notes with screenshots](docs/releases/v0.1.0.md).

### Added
- Django 6.1 project with settings from environment variables (`.env`).
- Sign-in with Microsoft 365 (Entra ID) using MSAL: OpenID Connect
  authorization code flow with PKCE. No passwords are handled.
- A custom User model keyed on the Entra object ID. Name, email and role
  sync from Entra on every sign-in.
- Roles from Entra app roles: Requester (default), Agent and Admin. Admins get
  the Django admin site, which also signs in with Microsoft 365.
- Friendly sign-in error pages for common Entra errors.
- Sign-in, home and error pages styled from the UI mockup, with light and dark mode.
- `/healthz` endpoint, Dockerfile and Docker Compose with PostgreSQL 17.
- Entra setup guide (`docs/entra-setup.md`) and the UI mockup (`mockups/`).

[0.9.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.9.0
[0.8.4]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.8.4
[0.8.3]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.8.3
[0.8.2]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.8.2
[0.8.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.8.0
[0.7.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.7.0
[0.6.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.6.0
[0.5.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.5.0
[0.4.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.4.0
[0.3.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.3.0
[0.2.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.2.0
[0.1.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.1.0

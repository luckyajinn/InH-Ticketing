# Changelog

All notable changes to InH-Ticketing. Versions follow [Semantic Versioning](https://semver.org).
Each version also has illustrated release notes in [docs/releases](docs/releases/README.md).

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

[0.6.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.6.0
[0.5.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.5.0
[0.4.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.4.0
[0.3.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.3.0
[0.2.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.2.0
[0.1.0]: https://github.com/luckyajinn/InH-Ticketing/releases/tag/v0.1.0

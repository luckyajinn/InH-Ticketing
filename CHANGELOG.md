# Changelog

All notable changes to InH-Ticketing. Versions follow [Semantic Versioning](https://semver.org).
Each version also has illustrated release notes in [docs/releases](docs/releases/README.md).

## [0.3.0] (unreleased)

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

## [0.2.0] (unreleased)

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

## [0.1.0] (unreleased)

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

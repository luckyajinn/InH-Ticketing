# InH-Ticketing

An in-house IT help desk for McKenna Labs. Staff send IT a request; IT works
it through to resolution. People sign in with their Microsoft 365 work account.

**Status:** v0.8.3: fixes from the pre-pilot review, on top of v0.8.2's basics (a new Not found page, a help contact, no double-sent requests, a usage and privacy page, a favicon), v0.8.0's Mechanics and Cleaning & sanitization requests and v0.7.0's new look, password check and folded email signatures. Live on the internal server; the pilot starts 2026-11-10, and the target is to have everything finalized by Friday 2026-11-20 (see [docs/roadmap.md](docs/roadmap.md)). This is a test build, approved for internal setup.
See the [release notes with screenshots](docs/releases/README.md) for how it looks and what changed in each version.

## What works today

- **Sign-in** with Microsoft 365 (Entra ID). No passwords are stored or seen.
  Roles come from Entra app roles: **Requester** (default), **Agent**, **Admin**.
- **Requesters** submit requests with attachments, follow their own tickets,
  reply, mark tickets resolved, or reopen them.
- **IT (Agents and Admins)** work from a queue with views, search and filters.
  On a ticket they see the full timeline, write public replies or **internal
  notes**, and set status, priority, assignee and category.
- **Email:** people are emailed when something happens on their ticket
  (received, IT replied, assigned, resolved and so on). Emails are queued and
  sent by a background worker. See [docs/email-setup.md](docs/email-setup.md).
- **Email in:** emails to the help-desk mailbox become tickets, and replies
  to our emails (with `[#1001]` in the subject) are added to the right ticket.
- **History:** every change is logged with who made it and when.
- **Password check:** requests, replies and notes are checked before sending;
  anything that might be a password gets a warning, with "send anyway" for
  false alarms. Each warning outcome is kept in an audit trail (never the
  text), and IT sees a *Possible password* line in the ticket's history. See
  `tickets/password_guard.py`.
- **Privacy:** requesters are never sent internal notes, files on internal
  notes, or the history log. This is filtered on the server, not hidden in the browser.
- **Other teams:** Mechanics and Cleaning & sanitization requests use the same
  form. Their tickets land in the IT queue for now (filter by category).
- **Common requests:** quick picks on the New request form that fill in the
  subject and category; people can still type their own.
- **Admins** manage categories and their common requests at `/admin/`.

### Ticket rules

| When | Status becomes |
|---|---|
| Someone submits a request | New |
| IT replies publicly, or assigns the ticket | New → Open |
| The requester replies to a Waiting on User or Resolved ticket | → Open |
| The requester clicks "Mark as resolved" | → Resolved |
| The requester clicks "This is still a problem" | Resolved → Open |
| IT clicks "Send and set Waiting on User" / "Send and resolve" | → Waiting on User / Resolved |
| Anything else | Set by IT in the side panel |

Requesters can't reply to Closed tickets; they start a new request instead.

## Run it on your PC (Windows)

You need Python 3.13. From the project folder in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # then fill it in; see below
python manage.py migrate
python manage.py runserver
```

Open **<http://localhost:8000>**. Use `localhost`, not `127.0.0.1`; Microsoft
sends you back to `localhost` after sign-in.

In `.env`:
- Generate `DJANGO_SECRET_KEY` with the command written above that line.
- Fill in the `ENTRA_*` values by following [docs/entra-setup.md](docs/entra-setup.md).
  Until they're set, the sign-in page shows a "Setup needed" notice.
- Leave `DATABASE_URL` blank to use a local SQLite file.

### Run the email worker

Emails are sent by a second process. In another PowerShell window, also in the project folder:

```powershell
.\.venv\Scripts\python.exe manage.py run_worker
```

By default nothing is really sent; emails appear as files in `tmp/emails/`.
To try email-in without Microsoft 365, feed it an email:

```powershell
.\.venv\Scripts\python.exe manage.py ingest_email --from dana.whitfield@example.invalid --subject "Laptop fan is loud" --body "Sounds like a jet"
```

### Try it with demo data

```powershell
python manage.py seed_demo          # 8 fictional people and 8 tickets
python manage.py seed_demo --clear  # remove them again
```

Demo people can't sign in. Sign in yourself with the **Agent** or **Admin**
role to see their tickets in the queue.

### Run the tests

```powershell
python manage.py test
```

The tests fake Microsoft's responses, so they don't need Entra or the internet.

## Run it with Docker

The server setup is Docker Compose: the web app, the email worker and PostgreSQL.

```bash
docker compose up --build
```

This needs `POSTGRES_PASSWORD` set in `.env`. The database and uploaded
attachments live in Docker volumes (`pgdata` and `media`), so they survive
restarts. Back up both.

On the server, production adds an HTTPS proxy and nightly backups:
[docs/server-requirements.md](docs/server-requirements.md) says what the server
needs, and [docs/deployment.md](docs/deployment.md) is the install guide.

## How it's put together

```
config/            Settings, URLs, version number (config/__init__.py)
accounts/          The User model and Microsoft 365 sign-in
  entra.py         The sign-in logic (MSAL), role mapping, user sync
  views.py         /signin/, /auth/login, /auth/callback, /signout/
core/              Home redirect, /healthz, shared template values
tickets/           Tickets, replies, notes, history, attachments
  models.py        The data: Category, Ticket, Comment, TicketEvent, Attachment
  services.py      The ticket rules; every change goes through here
  selectors.py     Who may see what (requesters never get internal notes)
  views.py         Queue, my tickets, new request, ticket page, actions
notifications/     Email out: who gets what (notify.py), the queue, the worker, Graph client
inbound/           Email in: processing rules (processing.py), Graph inbox reader, ingest_email
templates/         Server-rendered HTML pages (emails in templates/emails/)
static/css/app.css The one stylesheet; colours and spacing live in :root
static/js/app.js   Small extras (auto-save side panel, clickable rows); pages work without it
deploy/caddy/      The HTTPS proxy's configuration (production, with compose.prod.yaml)
scripts/           backup.sh and restore.sh for the server; release_body.py
docs/              Setup and deployment guides, and backlog.md (the to-do list)
docs/releases/     Release notes and screenshots for every version
mockups/           The clickable UI mockup the design is based on
```

Built with Django 6.1, MSAL (Microsoft's auth library), PostgreSQL and WhiteNoise.

## Roadmap

Dates, dependencies and alternative paths are in [docs/roadmap.md](docs/roadmap.md);
item-level detail is in [docs/backlog.md](docs/backlog.md).

| Milestone | Scope | Status |
|---|---|---|
| 1 | Skeleton, Microsoft 365 sign-in, roles | ✅ v0.1.0 |
| 2 | Tickets: submit, my tickets, agent queue, public replies vs internal notes, history, attachments | ✅ v0.2.0 |
| 3 | Outbound email notifications (files locally, Microsoft Graph for real) | ✅ v0.3.0 |
| 4 | Inbound email-to-ticket from a test shared mailbox | ✅ v0.4.0 |
| 5 | Automations: auto-close resolved tickets, follow-ups, usage controls | ✅ v0.5.0 |
| 6 | Deployment package: HTTPS proxy, backups, server guides | ✅ v0.6.0 (first install waits on the server) |

## License

Proprietary: all rights reserved. InH-Ticketing is the sole property of Christian
Jones ([luckyajinn](https://github.com/luckyajinn) on GitHub). It may be used,
copied, deployed or licensed only with the owner's express written permission. See
[LICENSE](LICENSE).

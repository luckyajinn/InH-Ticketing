# InH-Ticketing

An in-house IT help desk for McKenna Labs. Staff send IT a request; IT works
it through to resolution. People sign in with their Microsoft 365 work account.

**Status:** v0.3.0, milestone 3 (outbound email). This is a test build.
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
- **History:** every change is logged with who made it and when.
- **Privacy:** requesters are never sent internal notes, files on internal
  notes, or the history log. This is filtered on the server, not hidden in the browser.
- **Admins** manage categories at `/admin/`.

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
notifications/     Email: who gets what (notify.py), the queue, the worker, Graph sending
templates/         Server-rendered HTML pages (emails in templates/emails/)
static/css/app.css The one stylesheet; colours and spacing live in :root
static/js/app.js   Small extras (auto-save side panel, clickable rows); pages work without it
docs/              Setup guides, and backlog.md (the to-do list)
docs/releases/     Release notes and screenshots for every version
mockups/           The clickable UI mockup the design is based on
```

Built with Django 6.1, MSAL (Microsoft's auth library), PostgreSQL and WhiteNoise.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| 1 | Skeleton, Microsoft 365 sign-in, roles | ✅ v0.1.0 |
| 2 | Tickets: submit, my tickets, agent queue, public replies vs internal notes, history, attachments | ✅ v0.2.0 |
| 3 | Outbound email notifications (files locally, Microsoft Graph for real) | ✅ v0.3.0 |
| 4 | Inbound email-to-ticket from a test shared mailbox | Next |
| 5 | Automations: auto-close resolved tickets, reopen rules | |
| 6 | Deploy to the internal server with HTTPS and backups | |

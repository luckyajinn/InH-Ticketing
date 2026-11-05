# InH-Ticketing

An in-house IT help desk for McKenna Labs. Staff send IT a request; IT works
it through to resolution. People sign in with their Microsoft 365 work account.

**Status:** v0.1.0, milestone 1 (skeleton + sign-in). This is a test build.

## What works today

- Sign in with Microsoft 365 (Entra ID). No passwords are stored or seen.
- People are created on first sign-in, and their name, email and role are
  refreshed from Entra on every sign-in.
- Roles come from Entra app roles: **Requester** (default), **Agent**, **Admin**.
- Admins can open the Django admin site at `/admin/`, which also uses
  Microsoft 365 sign-in.

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

### Run the tests

```powershell
python manage.py test
```

The tests fake Microsoft's responses, so they don't need Entra or the internet.

## Run it with Docker

The server setup is Docker Compose: the web app plus PostgreSQL.

```bash
docker compose up --build
```

This needs `POSTGRES_PASSWORD` set in `.env`. The database lives in a Docker
volume, so it survives restarts.

## How it's put together

```
config/            Settings, URLs, version number (config/__init__.py)
accounts/          The User model and Microsoft 365 sign-in
  entra.py         The sign-in logic (MSAL), role mapping, user sync
  views.py         /signin/, /auth/login, /auth/callback, /signout/
core/              Home page, /healthz, shared template values
templates/         Server-rendered HTML pages
static/css/app.css The one stylesheet; colours and spacing live in :root
docs/              Setup guides
mockups/           The clickable UI mockup the design is based on
```

Built with Django 6.1, MSAL (Microsoft's auth library), PostgreSQL and WhiteNoise.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| 1 | Skeleton, Microsoft 365 sign-in, roles | ✅ v0.1.0 |
| 2 | Tickets: submit, my tickets, agent queue, public replies vs internal notes, history, attachments | Next |
| 3 | Outbound email notifications (Mailpit locally, then Microsoft Graph) | |
| 4 | Inbound email-to-ticket from a test shared mailbox | |
| 5 | Automations: auto-close resolved tickets, reopen rules | |
| 6 | Deploy to the internal server with HTTPS and backups | |

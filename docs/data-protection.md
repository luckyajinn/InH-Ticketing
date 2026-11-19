# Data protection

What sensitive data, secrets and personal information InH-Ticketing holds,
where each one lives, and how each is protected, or isn't. For IT admins, the
owner and the compliance lead. Written on 2026-11-19, for v0.10.7, from the
code and configuration in the repository.

Related: who can see what is in [access-control.md](access-control.md); what
could go wrong is in [threat-model.md](threat-model.md); what to do when it
does is in [incident-response.md](incident-response.md); the rules people
follow are in [security-policy.md](security-policy.md).

## 1. What the app holds

All of it sits on the one internal server. "Database" means the PostgreSQL
database in the Docker volume `inh-ticketing_pgdata`; "media" means the
attachments volume `inh-ticketing_media`.

| Data | What it is | Where | Who can read it in the app | How long it's kept |
|---|---|---|---|---|
| People | Name, work email, Entra object ID (a permanent ID), role, department, last sign-in, date joined. Copied from Entra at every sign-in. Someone who emailed the help desk, or had a request opened for them by staff, has a record before they sign in, with the name and email from the email or typed by staff | Database (`accounts_user`) | Staff see names and emails on tickets; admins see the list in the admin site | For ever. People can't be deleted in the admin site, only made inactive |
| Tickets | Subject, description, requester, assignee, category, status, priority, "blocking work", dates | Database (`tickets_ticket`) | The requester, the department's staff, admins | For ever in practice (section 7) |
| Replies and internal notes | The text, who wrote it, when, and for notes, their department | Database (`tickets_comment`) | Replies: as the ticket. Notes: the department's staff and admins only | As the ticket |
| History | Who changed status, priority, assignee, category or department, as display text. Also move requests with the reason typed, "Opened for", removals (never what was removed) | Database (`tickets_ticketevent`) | Staff and admins, never the requester | As the ticket |
| Attachments | The file, its original name, size, the type the browser claimed, who uploaded it. Up to 10 MB each, 5 per message | The file: media, at `attachments/<ticket>/<random name>`. The rest: database (`tickets_attachment`) | As the ticket, or as the note it's on | As the ticket |
| Copies of emails sent | One row per recipient: address, subject, plain-text and HTML body (ticket subject, the message text, names, a link), status, any error | Database (`notifications_outboundemail`) | Admins, in the admin site | For ever. Nothing deletes them; an admin can delete rows in the admin site |
| Emails received | One row per email: sender address and name, subject, Message-ID, when, what the app did and why. The body and files go into the ticket (as a ticket, reply or note), not this row. Ignored emails (out-of-office, outsiders, unconfirmed senders) get a row too | Database (`inbound_inboundemail`). The original email stays in the mailbox | Admins, in the admin site | For ever. Nothing deletes them; an admin can delete rows in the admin site |
| The emails themselves | Every email sent (in **Sent Items**) and every email read (moved to **Processed by InH-Ticketing**) | The help-desk and department shared mailboxes, in Exchange Online | Whoever has access to those mailboxes | Up to Exchange (below) |
| Password-warning audit trail | When the "this might include a password" warning appeared, who, which ticket, where (request, reply, note, email), the outcome, and which checks matched. **Never the text** | Database (`tickets_passwordwarning`) | Admins, in the admin site; read-only | For ever; can't be deleted there |
| Admin log | Every change made in the admin site: who, when, what, the old and new values (cut at 200 characters) | Database (`django_admin_log`) | Admins; read-only | For ever; can't be deleted there |
| Sessions | Who is signed in: the person's ID and a check value. During sign-in only, MSAL's one-time values (state, nonce, PKCE verifier) | Database (`django_session`) | Nobody in the app | 12 hours at most. Expired rows aren't cleared (nothing runs `clearsessions`), but they no longer work |
| Worker heartbeat | When the worker last ran, and the text of its last inbox or auto-close error | Database, one row | Admins (Reports) | Overwritten each round |
| Reports | Counts and times per team, worked out from the tickets each time an admin opens `/reports/`. Nothing is stored. The CSV export has one row per ticket: number, dates, team, category, priority, status, times **and the subject**; no names, no descriptions | Not stored on the server. A downloaded CSV is on the admin's PC | Admins only | The CSV: outside the app's control |
| Logs | Section 9 | Docker's log files | IT admins on the server | Section 9 |
| Backups | Everything in the database and media | `/srv/inh-ticketing/backups` | IT admins on the server | Section 6 |

The table shows who can read each thing *in the app*. Anyone with `sudo` or
membership of the `docker` group on the server can read all of it, and so can
anyone who has the backups. The roles are in [access-control.md](access-control.md).

> **To fill in:** how long Exchange keeps the shared mailboxes' Sent Items and
> *Processed by InH-Ticketing* folders (any retention policy), and who has
> full access to those mailboxes. The Microsoft 365 admin would know.

## 2. What it doesn't hold

| Not held | Why |
|---|---|
| Passwords at sign-in | There is no password form anywhere, the admin login included. Microsoft's page takes the password; the app gets an ID token. No account has a password the app could check |
| Microsoft tokens after sign-in | The ID token is read once and dropped. The sign-in MSAL object, and anything it cached, lives only for that request. The worker's Graph token (about an hour) is kept in memory only, never on disk |
| The text of a suspected password | The audit trail stores where and which check matched, never the text. (If someone sends it anyway, it is in the ticket until an admin removes it: section 7) |
| Phone numbers, addresses, dates of birth, photos, managers, job titles | Not requested from Entra and not stored. Only name, email, object ID, tenant ID (checked, not stored) and roles are read from the token |
| Who viewed a ticket or downloaded a file | Not recorded in v0.10.7 (a test checks this). Access logging is planned for v0.11.0 ([backlog.md](backlog.md)) |
| Card or bank details, government IDs | Nothing asks for them. Nothing stops someone typing them into a ticket, though |

## 3. Secrets

| Secret | What it protects | Where it lives | Who can read it | How it's changed | In the repository? |
|---|---|---|---|---|---|
| Django secret key (`DJANGO_SECRET_KEY`) | Signs session and message cookies | `.env` on the server (mode 600, the server's admin account), and the environment of the `web` and `worker` containers | The admin account, root, the `docker` group (`docker inspect`) | New value in `.env`, then `docker compose ... up -d`. Everyone is signed out. No fallback key is set, so there is no overlap | No. The Dockerfile uses a throwaway value during the build only |
| Database password (`POSTGRES_PASSWORD`) | The database account | `.env`; the `db` container's environment; inside `DATABASE_URL` in `web` and `worker` | As above | Changing `.env` alone breaks the connection: the database's own password must be changed to match ([deployment.md](deployment.md), section 12) | No |
| Entra client secret (`ENTRA_CLIENT_SECRET`) | Sign-in, **and** Graph: sending from and reading the shared mailboxes | `.env`; the `web` and `worker` environment. Entra shows it once | As above, plus Entra admins (who can make a new one) | Expires after 12 months. Make a new one in Entra, put it in `.env`, delete the old one. Each machine has its own ([deployment.md](deployment.md), section 4) | No |
| Certificate private key | The HTTPS certificate | `/srv/inh-ticketing/certs/privkey.pem`, root only (600), folder 750; mounted read-only into `proxy` | Root | Made on the server, never sent anywhere. A new key with each certificate (section 3.4 there). The current one is temporary, to 2026-12-17 | No (`*.pem`, `*.key` are ignored by git and Docker) |
| Deploy key | Read-only access to the private repository | The admin account's `~/.ssh/` | The admin account, root | Only the owner adds or removes it on GitHub ([deployment.md](deployment.md), section 2) | No |
| Session cookies | Being signed in | A random ID in the browser; the session row in the database | The person's browser; the database | A new ID at every sign-in; the row is deleted at sign-out; 12 hours at most | No |

`.env` is not in the backups. Its values are meant to be kept in IT's password
vault. `.env.example` holds names and comments only, no values. `.gitignore`
and `.dockerignore` keep `.env`, `*.pem`, `*.key` and `*.csr` out of git and
out of the image, and a test checks that no page or script carries a secret.

The Entra client secret is the most powerful one: with it and the client ID,
anyone can send email as the help-desk mailboxes and read them. Exchange
limits it to those mailboxes ([email-setup.md](email-setup.md), 3c and 4b).

> **To fill in:** where IT's password vault entry for `.env` is, and who can
> open it. Also whether the Django secret key and the database password are
> ever changed on a schedule (the repository sets none). IT admins would know.

## 4. In transit

| Path | Protected? | How |
|---|---|---|
| Browser to the server | Yes | HTTPS on port 443 (Caddy), HTTP/1.1 and HTTP/2, the certificate from `/srv/inh-ticketing/certs`. TLS versions and ciphers are Caddy's defaults |
| Plain HTTP | Redirected | Port 80 only sends a permanent redirect to `https://helpdesk.example.com`. Django redirects as well, as a second line |
| HSTS | Yes | One year, with subdomains, sent by Caddy and Django. Not preloaded (the name is internal). Browsers ignore it while the certificate is the temporary one they warn about |
| Proxy to app | **Not encrypted** | Plain HTTP from `proxy` to `web:8000` on Docker's internal network. Port 8000 isn't published in production, so this never leaves the server |
| App to database | **Not encrypted** | Plain PostgreSQL connection on Docker's internal network; no TLS is configured. Password-checked. Port 5432 isn't published, so this never leaves the server |
| Server to Microsoft | Yes | HTTPS to `login.microsoftonline.com` (sign-in, tokens) and `graph.microsoft.com` (email), with certificate checks |
| Email | Within Microsoft 365 | Sent through Graph, so it leaves from Exchange Online. How it travels to each inbox is Exchange's job, not the app's. Recipients are company addresses: people added by staff or by email, and department alert addresses, must be in the company's domains (`IT_NOTIFY_EMAIL` isn't checked) |

## 5. At rest

| Store | Encrypted by the app? | Notes |
|---|---|---|
| Database volume | No | PostgreSQL's files in a Docker volume on the server's disk. Neither PostgreSQL nor Docker encrypts it |
| Media volume | No | Attachments as ordinary files in a Docker volume |
| Backups folder | No | Plain `db.dump` and copies of every attachment |
| Docker logs | No | Plain JSON files under Docker's data folder |

> **To fill in:** whether the server's virtual disk is encrypted (the install
> guide says "the whole disk with LVM", with no mention of encryption), and
> who can read the VM's disk or snapshots on the host. Whoever runs the
> virtualisation platform would know.

What the app does do for files:

- **Random names on disk.** Each file is saved as a random 32-character name
  plus its extension. What someone typed never becomes part of a path; the
  original name is kept in the database.
- **Always a download.** Every file is sent as an attachment through a view
  that checks the person may see it (404 if not), never shown in the browser.
  The type sent is guessed from the file name, with `nosniff`, so a browser
  won't treat a file as a page.
- **Allowed types only.** An extension list (images, office documents, PDF,
  text, email files); no `.zip`. Files are **not virus-scanned**.
- Files are written once and never changed.

## 6. Backups

`scripts/backup.sh` makes one folder per backup in `/srv/inh-ticketing/backups`.

| | |
|---|---|
| In them | The whole database (`db.dump`), so every ticket, note, email copy, log and person; every attachment (`media/`); a manifest; checksums |
| Not in them | `.env`, the certificate's key, Docker's logs, the images, the mailboxes |
| Where | The same server as the data |
| How long | 14 days (`KEEP_DAYS`). Labelled ones made by hand (before an update) are deleted after 14 days too |
| Who can read them | The folder is mode 700, files 600 (`umask 077`), owned by the server's admin account. Root can read them |
| Encrypted | No |
| Copy off the server | **None.** Undecided as of 2026-11-11 ([deployment.md](deployment.md), section 8) |

Attachment snapshots share unchanged files with the previous backup (hard
links). A file removed from a ticket stays in older backups until the last
one holding it is more than 14 days old.

> **To fill in:** the nightly cron line isn't on the server yet
> ([deployment.md](deployment.md), item 5), so no nightly backups are being
> made. Fill in the date it was added. Also, once decided: where the
> off-server copy goes, whether it is encrypted, and who can read it. The
> owner and IT admins would know.

## 7. Keeping and deleting

| What | What happens |
|---|---|
| Resolved tickets | Close by themselves after 7 days without a reply (`AUTO_CLOSE_RESOLVED_DAYS`) |
| Closed tickets | Archived: read-only, out of the working views. The ticket page shows a "kept until" date 730 days later (`ARCHIVE_KEEP_DAYS`) |
| After that | **Nothing.** Automatic deletion isn't built yet ([backlog.md](backlog.md)), so tickets, their files and history are kept for ever |
| Deleting a ticket | Not possible, in the app or the admin site. People can't be deleted either |
| Email copies, inbound records | No automatic clean-up. Admins can delete rows in the admin site |

> **To fill in:** whether two years meets the company's own retention rules
> for personal data in tickets, and what should happen to people's records
> when they leave. The compliance lead would know.

**The removal tool** (admins only, **Remove…** on a ticket) takes out a
pasted password, a whole message, or files.

| It removes | It leaves |
|---|---|
| The exact text, everywhere it appears in that subject, request or message, replaced with "[removed by IT]". Or the whole message | The backups, for up to 14 days |
| The same text in the app's copies of emails sent about the ticket (subject, text and HTML), and in received emails' subjects | The emails in people's inboxes, in alert lists or Teams channels, and in the shared mailbox (Sent Items and the Processed folder). The tool says so after a removal |
| Files: the file on disk and its database row | Copies people downloaded; the original email the file came with |
| | Copies in the app that aren't exact matches (text re-wrapped in an email, say) |
| | A move request's reason in the history, and item names in the admin log (a retried email is logged as "subject -> address") |
| | Attachment file names in the proxy's and web's access logs (section 9); CSV exports already downloaded (they hold subjects) |
| | Old versions of the changed rows inside PostgreSQL's files, until it reuses the space |

The history records who removed what kind of thing and when, never what it was.
The usage rules say the password must also be reset ([usage-rules.md](usage-rules.md)).

## 8. In the browser

| Cookie | What for | Flags (on the server) | Lifetime |
|---|---|---|---|
| `sessionid` | Signed in | HttpOnly, Secure, SameSite=Lax | Until the browser closes; 12 hours at most on the server |
| `csrftoken` | Stops other sites sending forms | Secure, SameSite=Lax. Not HttpOnly (Django's default) | One year (Django's default). A random value, nothing personal |
| `messages` | Carries a notice such as "Request sent" to the next page | Same flags as `sessionid`. Signed, not encrypted | Until the notice is shown |

Other protections:

- **No caching of signed-in pages.** Every response to a signed-in person,
  downloads included, is `Cache-Control: private, no-store`.
- **Content-Security-Policy** on every page: scripts, styles, images, fonts
  and connections from the app itself only; no plugins; no framing. The
  admin site's few inline scripts carry a per-request nonce.
- `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `nosniff`;
  `robots.txt` tells search engines to stay away.
- **Reply drafts in `sessionStorage`.** When the side panel on a ticket saves
  (which reloads the page), the reply being typed and its Public/Internal
  choice are set aside under `inh-draft:<page>`, then read back and deleted
  on the next load. If the page never reloads, the draft stays in that tab
  until the tab closes. Signing out doesn't clear it.
- Nothing else is stored in the browser: no `localStorage`, no other cookies,
  no tracking.

Downloaded files land in the person's Downloads folder, outside the app's control.

## 9. Logs

Every container logs to the console, which Docker keeps.

| Container | What it logs | Personal or ticket data in it |
|---|---|---|
| `proxy` | Every request: client address, method, full URL, status, browser. Caddy hides cookie and authorisation values | **Yes:** URLs carry attachment file names (`/attachments/<id>/<name>`), search text (`?q=`), people-search text (names), and the one-time sign-in code |
| `web` | gunicorn's access log (the same URLs, seen from the proxy's address); Django warnings and errors, with tracebacks; sign-in failures with Microsoft's error text | Yes, the URLs as above. Ticket text isn't logged |
| `worker` | Rounds and counts; each email read: mailbox, **sender address**, outcome; each failed send: **recipient address** and the error | Email addresses |
| `db` | PostgreSQL's start-up, errors and the SQL statement that failed | Rarely: a failed statement can include values |

In production each container's log is cut at 20 MB, keeping 5 files (about
100 MB per container), so how long that lasts depends on traffic. Logs go
when a container is recreated (every update). They are readable by root and
the `docker` group, aren't in the backups, and aren't sent anywhere. On a PC
(`compose.yaml` alone) logs aren't rotated.

## 10. What leaves the server

| To | What | When |
|---|---|---|
| Microsoft Entra (`login.microsoftonline.com`) | The client ID and secret, the one-time sign-in code and PKCE verifier; app-only token requests for Graph | Each sign-in; about hourly while the worker sends or reads mail |
| Microsoft Graph (`graph.microsoft.com`) | Each email sent: recipient, subject, body (ticket subject, the request or reply text, names, a link). No attachments, and never internal notes. Reading mail: the app fetches emails and their files, marks them read and moves them | Every 15 seconds (send) and 60 seconds (read), when switched on |
| PyPI (`pypi.org`) and GitHub's API | `scripts/check_updates.py`: package names and installed versions, and a request for Caddy's latest release. User agent "InH-Ticketing update check". No ticket or personal data | Only when an IT admin runs it (monthly) |

Nothing else. No analytics, no error-reporting service, no fonts or scripts
from other sites (the Content-Security-Policy would block them). Docker
image pulls and system updates go out too, but they are the server's
maintenance, not the app's ([deployment.md](deployment.md), sections 1 and 11).

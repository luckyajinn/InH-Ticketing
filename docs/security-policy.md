# Security policy

The security rules for InH-Ticketing, who is responsible for what, and the
standards the app and its server are held to. For the owner, IT admins, the
compliance lead and management. Written 2026-11-19, for v0.10.7.

This is the front page of the security set. The detail is in
[threat-model.md](threat-model.md) (attackers and residual risks),
[access-control.md](access-control.md) (sign-in, roles, the permission matrix),
[data-protection.md](data-protection.md) (data, secrets, backups, logs) and
[incident-response.md](incident-response.md) (what to do when something goes wrong).

## 1. Scope

This policy covers the app at `https://helpdesk.example.com`, the one internal
server it runs on, the help-desk mailbox (and each department mailbox once
added), its Entra app registration, and its code, releases and the company's
copy of the repository. It doesn't cover the company's wider IT policies
(Microsoft 365, PCs, the network, passwords). Where those are stricter, they win.

What staff may put in a ticket is in [usage-rules.md](usage-rules.md), not here.

## 2. Principles

1. **Least access.** A person sees only their own tickets, their department's, or (admins) all of them; nothing else.
2. **The server decides, never the page.** Every check runs on the server; the browser only shows or hides buttons.
3. **Microsoft 365 is the only way in.** The app has no password form and stores no passwords; roles come from Entra at every sign-in.
4. **Tickets are never deleted.** No ticket, history line or user can be deleted, in the app or the admin site. An admin can blank a pasted password, a message or a file; the history records who did.
5. **Every change leaves a record.** Ticket changes go in the ticket's history; admin-site changes go in the read-only admin log.
6. **No secrets in the repository.** Secrets live only in the server's `.env` (and IT's password vault); git and Docker ignore `.env` and key files.
7. **Only tagged releases run on the server.** Never a branch, never an edit made on the server.

## 3. Responsibilities

| Role | Responsible for |
|---|---|
| **The owner** (developer) | The code, the repository, the company's copy and its deploy key; releases with tests and release notes; fixing reported flaws and vulnerable packages; keeping these documents and deployment.md current in the same commit as each change |
| **IT admins** (server) | The server, `.env`, containers, backups and logs; patching and the monthly routine checks; installing releases; the certificate; first response to an incident |
| **IT admins** (Entra and Exchange) | Who is assigned which role; MFA; the client secret and its expiry; the mailbox's internal-senders-only setting and the Exchange scope that limits the app to its mailboxes |
| **Admins in the app** | Removing pasted passwords and files; unticking *Active* for leavers; departments and categories in the admin site, a new department only after the compliance lead's review |
| **Department agents** | Working only their own department's tickets; following the staff rules in [usage-rules.md](usage-rules.md); telling IT at once about a pasted password |
| **Every user** | Using the help desk only for what it's for; never putting a password, PIN, recovery code or secret in a ticket, email or chat; reporting anything suspicious to IT, never in a ticket |
| **The compliance lead** | Reviewing any new use or department before it starts; the yearly review of the usage rules; deciding in an incident whether personal data or regulated records are involved and who outside must be told |
| **Management** | Deciding what staff and outsiders are told in an incident, and whether the help desk stays closed |

> **To fill in:** who the incident lead is by default, who owns the
> certificate's renewal, and who accepts the known exceptions in section 5
> where none is named. Management and IT would decide.

## 4. Standards

| Area | Requirement | Checked or enforced by |
|---|---|---|
| Sign-in | Staff must sign in with their company Microsoft 365 account; tokens from other tenants are refused | `accounts/entra.py`; `test_no_password_sign_in_anywhere` |
| Sign-in | Only people assigned in Entra may sign in (*Assignment required*) | Entra; not yet confirmed (section 5) |
| MFA | MFA must be required for the app by Entra | Entra Conditional Access or security defaults; not yet confirmed (section 5) |
| Roles | Agent and Admin come only from Entra app roles; nobody can set them in the app | `accounts/admin.py` (read-only fields) |
| Roles | A leaver must be disabled in Entra and unticked *Active* in the admin site, which ends any open session | Entra admins and an app admin ([access-control.md](access-control.md) section 7) |
| Secrets | Secrets must live only in the server's `.env` (mode 600) and IT's password vault, never in a ticket, email, chat or the repository | `.gitignore`, `.dockerignore`; `test_pages_and_scripts_carry_no_secrets` |
| Secrets | Each machine must have its own Entra client secret, made with a 12-month expiry and in the calendar | deployment.md section 4; the monthly check (section 11) |
| Secrets | A leaked secret must be rotated at once | [incident-response.md](incident-response.md) 5.3, 5.4 |
| HTTPS | All traffic must be HTTPS, with HSTS; plain HTTP only redirects; debug mode must never run under the real name | Caddy, `config/settings.py`; `core/tests/test_security.py`; post-install checks 3 to 6 |
| Certificates | The certificate must come from the company's internal CA, and its expiry must be in the calendar | deployment.md section 3; post-install checks 6 and 17; the monthly check |
| Patching | Debian security updates must install automatically, with a reboot when one is needed | unattended-upgrades (deployment.md 1.3); the monthly check |
| Patching | Docker, the PostgreSQL and Python images, and the app's packages must be checked and refreshed monthly | deployment.md section 11; `scripts/check_updates.py` |
| Patching | A package with a known security issue must be fixed by a release | The owner ([incident-response.md](incident-response.md) 5.9) |
| Releases | Each release must pass the full test suite and have release notes and screenshots (demo data only) in the same commit | [docs/releases/README.md](releases/README.md); the notes' *Tests* section |
| Releases | Each release must be an annotated tag, sent to the company's copy with `scripts/publish_copy.py` after its forbidden-words check | [company-copies.md](company-copies.md) |
| Releases | IT must take a backup before every update, and read the release notes of every version installed or skipped | deployment.md section 10 |
| Backups | The database and attachments must be backed up nightly, checked and kept 14 days | `scripts/backup.sh`, cron; `backup.log` weekly and monthly (deployment.md sections 8, 11) |
| Logging | Ticket changes, admin-site changes and password warnings must be recorded and must not be deletable | The history, the admin log, the password audit trail |
| Logging | No log or data may be sent outside the server, except to Microsoft for sign-in and email | [data-protection.md](data-protection.md) section 10 |
| Attachments | Only the allowed file types, up to 10 MB each and 5 per message, no `.zip`; always downloaded, never opened in the browser | `ATTACHMENT_EXTENSIONS` in `config/settings.py`; `test_dangerous_file_types_are_refused` |
| Email in | The mailbox must accept internal senders only, and only one copy of the app may read it | Exchange (email-setup.md 3a); post-install check 18 |
| Email in | Only the company's domains are read; an unconfirmed sender never gives a public reply or a new ticket | `INBOUND_ALLOWED_DOMAINS`; `inbound/processing.py`; [threat-model.md](threat-model.md) 4.4 |
| Email out | The app's mail permissions must be scoped in Exchange to its own mailboxes, never granted in Entra | email-setup.md 3b, 3c |
| Admin settings | A new department, or any new use, must be reviewed with the compliance lead before it's added | [usage-rules.md](usage-rules.md); the admin log shows who added it |
| Admin settings | A department's Entra role must be its own, never `Agent`, `Admin` or `Requester` | `Department.clean()` refuses `Agent` and `Admin` only (section 5) |
| Server settings | A change to `.env`, the crontab, DNS, the certificate, Entra or the deploy key must be written into deployment.md in the same commit | deployment.md, *Still to fill in or add* |
| Development | Tests and screenshots must use fictional demo data and fake Microsoft's responses | `seed_demo`; the test suite |
| Development | A PC must never read the live mailbox once the server does; a restore drill only on a separate VM with email off | deployment.md sections 5, 7 (check 18) and 9 |

> **To fill in:** whether real ticket data may ever be on a developer PC
> (no document says). The owner and the compliance lead would decide.

## 5. Known exceptions

Where today's setup doesn't meet the standards above, or where no standard is set yet.

| Exception | Risk | Who decides | Plan |
|---|---|---|---|
| MFA for the app not confirmed in Entra | A stolen password may be enough; an admin's opens every ticket | IT admins (Entra) | Open in backlog.md, v0.10.7 |
| *Assignment required* not confirmed on the production app | Any company account may sign in | IT admins (Entra) | Undecided |
| No record of sign-ins (only the last), downloads or ticket views | Misuse by an agent or admin can't be seen | The owner, after the compliance lead's review | v0.11.0 logs sign-ins and downloads; views never (decided 2026-11-16) |
| The nightly backup isn't scheduled on the server | No backups are being made | IT admins | Before go-live (deployment.md item 5) |
| Backups stay on the same server | Losing the server loses the tickets | The owner and IT admins | After v1.0.0; where is undecided |
| No restore test | A backup may not restore | The compliance lead, to confirm | Not planned (decided 2026-11-11) |
| Nothing encrypted at rest by the app (database, files, backups, logs); disk encryption unknown | A copied disk or backup is readable | Not assigned | Undecided |
| A temporary certificate, expiring 2026-12-17 | Browsers warn; HSTS doesn't apply | Not assigned (who owns renewal) | The real one before 2026-12-17 |
| The network firewall for ports 80 and 443 not confirmed; ufw doesn't cover them | The guest Wi-Fi may reach the app | Whoever runs the network | Post-install check 20, before go-live |
| SSH settings (key-only, root login) not confirmed | Weaker server access | IT admins | Undecided |
| Sign-out leaves Microsoft 365 signed in | The next person at a shared PC may get in as the last one | The owner | Not planned yet |
| Email confirmation trusts a header the sender could write; DMARC not confirmed; the spoofed-email test not run | A forged reply could pass as confirmed | The owner; the Exchange admin to confirm | Not planned yet; DMARC under "Later" |
| An unconfirmed email to a real ticket number creates an account | Unknown company addresses get accounts | The owner | Not planned yet |
| Uploaded files aren't virus-scanned; `.eml` and `.msg` can carry any file | A harmful file reaches staff | The owner | No scanner (decided 2026-11-16) |
| One client secret does sign-in and mail; PCs hold secrets for the same registration | A leaked secret reads and sends as the mailbox | The owner and the Entra admin | A certificate credential later (entra-setup.md) |
| No rotation schedule for the Django secret key or the database password | Old secrets stay valid | IT admins | Undecided |
| Unsigned tags, no lock file, images by tag, no automated build or review; GitHub access and two-factor not confirmed | A bad release or package could reach the server | The owner | Monthly checks only |
| A removed role or account keeps an open session up to 12 hours | Brief access after removal | IT admins | Untick *Active* for an immediate stop |
| A department's Entra role can be set to `Requester` | Everyone becomes that department's agent | The owner | Not planned yet |
| No scheduled review of who holds roles | Access outlives its need | The compliance lead | Not needed (decided 2026-11-09, backlog.md) |
| Nobody reviews the admin log or Entra's sign-in logs | Misuse goes unnoticed | Not assigned | Undecided |
| Admins can delete the app's records of emails received and sent, in the admin site | Evidence of what arrived or was sent can be removed; the admin log shows who did | The owner | Not planned yet |
| Archived tickets are never deleted | Kept beyond the two years decided | The owner | Automatic deletion in backlog.md |
| `Test-ServicePrincipalAuthorization` results not filed | No record of the Exchange scope | Not assigned | Open in backlog.md, Compliance |

## 6. Reporting a problem

Report a suspected breach or security flaw to IT, or to the owner, privately: never as a help-desk ticket.
What happens next is in [incident-response.md](incident-response.md); the channel for reporting a flaw is still to fill in there (5.10).

## 7. Review

This policy and the four documents must be reviewed together. The usage rules
are reviewed once a year and whenever the use changes ([usage-rules.md](usage-rules.md)).

> **To fill in:** how often this policy and the four documents are reviewed,
> and by whom. The compliance lead would decide.

Review sooner after:

- a release that changes sign-in, roles, email-in, uploads, what data is kept, or the server setup;
- an incident ([incident-response.md](incident-response.md) section 9);
- a change of use, such as a new department.

| Date | Version | Change | Reviewer |
|---|---|---|---|
| 2026-11-19 | v0.10.7 | First version; not yet reviewed | *To fill in* |

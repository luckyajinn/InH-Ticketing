# Threat model

Who might attack InH-Ticketing, what they could go after, how, what stops
them today, and what risk is left. For the owner, IT admins and the
compliance lead. Written 2026-11-19, for v0.10.7.

Related documents: roles and the permission matrix are in
[access-control.md](access-control.md); where data and secrets are kept, and
how, in [data-protection.md](data-protection.md); what to do when something
goes wrong in [incident-response.md](incident-response.md); the rules in
[security-policy.md](security-policy.md).

Test names below are in `tickets/tests/test_security_audit.py` unless another
file is named.

## 1. What's being protected

Ranked by the harm if it were read, changed or lost.

| # | Asset | Why it matters | Where it lives |
|---|---|---|---|
| 1 | **Ticket contents:** requests, replies, internal notes, attachments | Personal details, problems people would rather keep private, and sometimes a password pasted by mistake | The database and the `media` volume; copies of sent emails in the database and in mailboxes |
| 2 | **The app's Microsoft credential** (the Entra client secret) | With the tenant and client IDs, it can send as, and read, the help-desk mailbox (and each department mailbox once added) | The server's `.env`; each developer PC's `.env` for the same app registration |
| 3 | **The Admin role** | An admin sees every department's tickets and notes, runs Reports and the admin site | Entra app role assignments |
| 4 | **The help-desk mailbox's good name** | About 300 staff trust email from it. A fake or misused one is a ready-made phishing channel | Exchange Online |
| 5 | **The record itself:** ticket history, the admin log, "nothing deleted" | The usage rules rely on it (complaints redirected to QA, never deleted) | The database |
| 6 | **Backups** | A full copy of 1, so the same value to an attacker | `/srv/inh-ticketing/backups` on the same server |
| 7 | **The code and the release path** | Whoever can change what the server runs can take all of the above | The owner's GitHub repository, the company's copy, PyPI, Docker Hub |
| 8 | **Availability** | Staff fall back to email and hallway requests | The one server |

## 2. Who might attack

| Actor | Starts with | Might want | How likely |
|---|---|---|---|
| Curious or malicious **requester** | A normal account | Someone else's ticket or file; to look like staff | The most common case: 300 people |
| **Agent of another department** | The Agent role for one department | Another department's tickets or notes | Low: a handful of people |
| **Admin** misusing access | Everything in the app | To read tickets with no reason, or to hide a change | Low, but nothing would show the reading (see risk 2) |
| Next person at a **shared PC** | The browser the last person used | That person's tickets | Medium: shared PCs exist on site |
| Someone **on the LAN or VPN without an account** | Network access to ports 80 and 443 | Anything reachable signed out; to slow the app down | Low |
| **Outside email sender** | Any email address, including a forged one | To post into a ticket as someone else, or open tickets in their name | Medium: spoofing is cheap |
| Someone with a **stolen Microsoft 365 account** | A staff password (and MFA, if MFA isn't enforced) | That person's tickets; everything, if it's an admin | Medium: the usual way in for attackers |
| Someone with **server or repository access** | SSH to the server, or push access to GitHub | Everything | Low, but total impact |
| A **compromised dependency** | Code in a package or image the app installs | Everything the app can reach | Low |

## 3. Where the app can be reached

| Entry point | Who can reach it | What checks the caller |
|---|---|---|
| Web pages, `https://helpdesk.example.com` | LAN and VPN (the network firewall, see below) | Entra sign-in; role and ticket checks on the server, in `tickets/views.py` and `tickets/selectors.py` |
| Signed-out pages: sign-in, about and privacy, `/healthz`, static files | Anyone on the network | None needed: no ticket data on them |
| Admin site, `/admin/` | Admins only | `is_staff`, set from the Admin role at each sign-in (`accounts/entra.py`); no password form |
| The help-desk mailbox (email-in) | Anyone who can email it; outside senders bounce if the mailbox accepts internal senders only | `inbound/processing.py`: domain, sender confirmation, the ticket's parties |
| The Entra app registration | Entra and Exchange admins | Microsoft's own admin roles |
| The server's SSH | The admin subnet only (ufw, `docs/deployment.md` 1.4) | SSH keys or passwords (see the To fill in below) |
| Backups and `.env` on the server's disk | Anyone with a shell on the server as the admin user, or root | File permissions (700 and 600) |
| Code supply: GitHub, PyPI, Docker Hub | The owner (GitHub); the package and image publishers | A read-only deploy key on the server; version pins in `requirements.txt`; tags in the compose files |

Trust boundaries: the browser and Caddy (HTTPS); Caddy and the app (Caddy
sets `X-Forwarded-Proto` itself); the app and Microsoft (Entra tokens, Graph
calls with the client secret); Exchange and the app (email headers); the
server and GitHub (release tags).

Port 8000 is not published in production (`compose.prod.yaml`: `ports: !reset
[]`), and the database publishes no port. ufw does **not** filter Docker's
ports 80 and 443: only the network firewall in front of the server does.

> **To fill in:** whether the network firewall limits ports 80 and 443 to
> the LAN and VPN ranges and blocks the guest Wi-Fi (post-install check 20
> isn't done yet). Whoever runs the company's network would know.

> **To fill in:** how SSH is secured on the server: key-only or passwords
> allowed, root login off, and who holds an account. IT admins would know.

## 4. Threats, by area

### 4.1 Reaching tickets you shouldn't

| Threat | How it would work | What stops it today | What's left |
|---|---|---|---|
| Read another person's ticket | Change the number in `/tickets/1042/` | `Ticket.objects.visible_to()` in every lookup; "Not found", not "Forbidden" (`test_changing_the_ticket_number_shows_nothing`) | Nothing known |
| Reply, resolve or reopen someone else's ticket | Post to its action URLs | The same lookup (`test_every_ticket_action_checks_ownership`) | Nothing known |
| Download a file off someone else's ticket or an internal note | Guess the attachment URL | `selectors.can_download()` checks the ticket and the note (`test_attachments_check_the_ticket_and_the_note`) | Nothing known |
| Use staff or admin pages as a requester | Open the queue, Reports, removal, move | `agent_required` and `admin_required` on the server (`test_staff_pages_check_the_role_on_the_server`, `test_admin_pages_check_the_role_on_the_server`) | Nothing known |
| An agent reads another department's tickets | Open them by number, or through files | `works_on()` compares departments (`test_agents_only_see_their_own_department`) | Nothing known |
| A requester sets staff-only fields | Add `visibility=internal` or a status to a reply | The form refuses them (`test_requester_cannot_forge_staff_fields`) | Nothing known |
| Learn about a ticket through a link | `?follow_up=<their number>` | `_follow_up_target()` ignores tickets you can't see (`test_follow_up_link_does_not_leak_another_ticket`) | Nothing known |
| List all staff | The people search | Agents only, 2 characters at least, 8 results (`test_people_search_needs_two_characters_and_caps_results`) | An agent can still look up names and emails, a few at a time |

### 4.2 Injection, files and the browser

| Threat | How it would work | What stops it today | What's left |
|---|---|---|---|
| SQL injection | Quotes and SQL in search and filters | Django's query building (`test_sql_in_search_and_filters_is_just_text`) | Nothing known |
| Script in a ticket (cross-site scripting) | `<script>` in a subject, name or reply | Templates escape everything; `app.js` has no `innerHTML`; a strict Content-Security-Policy (`config/settings.py`, `test_html_is_escaped_on_every_page_that_shows_it`, `test_content_security_policy_on_every_kind_of_page`) | Nothing known |
| Script in an email the app sends | The same text, in a notification | Escaped (`test_html_in_emails_is_escaped`) | Nothing known |
| A formula in the CSV export | A subject starting `=HYPERLINK(` | Prefixed with `'` (`test_csv_export_neutralises_formulas`) | Nothing known |
| Upload a web page or program | `.html`, `.svg`, `.exe`, double extensions | An allow-list of extensions (`ATTACHMENT_EXTENSIONS`); `.zip` refused since v0.10.7 (`test_dangerous_file_types_are_refused`, `test_zip_files_are_refused`) | See the next row |
| A harmful document | A `.doc` or `.xls` with macros; a `.eml` or `.msg` that carries any file inside it | Files are always downloaded, never opened by the browser, with `nosniff`. Exchange scans email attachments; staff PCs' antivirus scans downloads | **Nothing scans files uploaded on the web** (`test_observed_office_files_are_stored_unscanned`). A `.eml` or `.msg` can hide any file type, the same reason `.zip` was refused (risk 7) |
| A file name that escapes the folder or adds headers | `../../evil.png`, a newline in the name | Random names on disk; a safe download header (`test_tricky_file_names_cannot_escape_or_inject_headers`) | Nothing known |
| Cross-site request forgery | A page elsewhere posts a form to the app | CSRF tokens on every form; `SameSite=Lax` cookies; sign-out is POST only (`test_every_form_post_needs_a_csrf_token`, `test_sign_out_is_post_only`) | Nothing known |
| Framing, other sites reading data | Clickjacking; cross-origin requests | `X-Frame-Options: DENY`, `frame-ancestors 'none'`, no CORS headers (`test_no_cross_origin_access`, `test_security_headers_and_private_caching`) | Nothing known |
| Error pages leak the inner workings | Cause a crash; visit a missing page | Debug mode can't run under a real name (`core/tests/test_security.py`, `DebugGuardTests`); `test_a_crash_shows_no_traceback_or_settings`, `test_not_found_lists_no_urls` | Nothing known |

### 4.3 Sign-in and sessions

| Threat | How it would work | What stops it today | What's left |
|---|---|---|---|
| Guess or reuse a password in the app | A password form | There is none: Entra only, the admin login redirects (`test_no_password_sign_in_anywhere`) | Password strength and MFA are Entra's job: see the To fill in below |
| A stolen Microsoft 365 account | Phishing, password reuse | Entra's own protections; "Assignment required" on the enterprise app | If MFA isn't enforced, a password alone is enough (risk 1) |
| An account from another tenant | Sign in with an outside account | Tenant-specific authority, and the token's `tid` is checked (`accounts/entra.py`) | Nothing known |
| Tamper with the sign-in reply | Replay a code, change `state` | MSAL checks state, nonce and PKCE; the code is useless without the client secret | Nothing known |
| Redirect to a fake site after sign-in | `?next=//evil.example/` | `_safe_next()` (`test_sign_in_never_redirects_off_site`) | Nothing known |
| The next person at a shared PC | Press Back, or reuse the open session | `Cache-Control: private, no-store`; the session ends when the browser closes, 12 hours at most (`core/middleware.py`, `test_session_cookie_flags`) | **Signing out leaves Microsoft 365 signed in** (`accounts/views.py`). If the browser stays open, the next person who presses Sign in may be let straight back in as the previous person (risk 5) |
| Keep access after losing a role | A role or account removed in Entra | Roles are read from Entra at every sign-in | Up to 12 hours on an open session. Unticking **Active** in the admin site blocks at once (risk 10) |
| Plain HTTP or a fake certificate | Network interception | HTTPS only, HSTS for a year, secure cookies (`core/tests/test_security.py`) | The temporary certificate, until the real one is in place (deployment.md item 2) |

> **To fill in:** whether MFA is required for this app in Entra (Conditional
> Access or security defaults). Open in backlog.md under v0.10.7. The Entra
> admin would know.

### 4.4 Email in

| Threat | How it would work | What stops it today | What's left |
|---|---|---|---|
| Fake reply "from IT" | Forge an agent's address on `[#1042]` | Only a confirmed sender gives a public reply; otherwise an internal note (`test_spoofed_it_sender_only_becomes_an_internal_note`) | See the last row |
| Fake reply "from the requester" | Forge the requester's address | The same, since v0.10.7; it can't reopen the ticket (`test_spoofed_requester_reply_only_becomes_an_internal_note`, `test_spoofed_reply_cannot_reopen_a_resolved_ticket`) | See the last row |
| A ticket in someone else's name | Forge a colleague's address with no ticket number | Ignored without confirmation: no ticket, account or receipt (`test_spoofed_new_request_is_ignored_without_an_account`) | An unconfirmed email **with** a real ticket number still creates an account for an unknown company address (risk 13) |
| Outsiders | Any other domain | `INBOUND_ALLOWED_DOMAINS`; the mailbox accepts internal senders only (email-setup.md 3a) (`test_outsiders_are_ignored`) | Department mailboxes need the same setting when they're added |
| Harmful attachments or HTML | `.exe`, `.html`, scripts in the body | The same allow-list as the web; text only (`test_dangerous_email_attachments_are_dropped`, `test_html_email_is_stored_and_shown_as_text`) | As in 4.2 |
| Mail loops, floods | Auto-replies; many emails | Automatic emails ignored; each Message-ID handled once | No limit on how many emails one sender can turn into tickets |
| Forge the confirmation itself | Write `Authentication-Results: dmarc=pass` into the email | `sender_confirmed()` reads every `Authentication-Results` header and accepts `dmarc=pass` or `compauth=pass` anywhere in them | **It can't tell Exchange's header from one the sender wrote**, and doesn't check which domain passed. Safe only while the mailbox refuses outside senders (risk 6) |

> **To fill in:** whether DMARC is enforced on the company domain (backlog
> "Later"), and whether Exchange Online removes `Authentication-Results`
> headers a sender wrote. The Exchange admin would know; one test email from
> outside would show it (the spoofed test email in backlog.md is still open).

### 4.5 Email out and the Microsoft credential

| Threat | How it would work | What stops it today | What's left |
|---|---|---|---|
| The client secret leaks | Copied from `.env`, a backup of a PC, a screen share | `.env` is 600, not in git or backups; never shown on a page (`test_pages_and_scripts_carry_no_secrets`) | A secret, not a certificate; PCs hold their own secret for the same registration (risk 8) |
| A leaked secret reads or sends company email | Graph calls with the secret | Exchange RBAC scopes Mail.Send and Mail.ReadWrite to the help-desk mailbox only; no Entra mail permissions (email-setup.md 3b, 3c) | That mailbox's whole contents, and sending as it. The `Test-ServicePrincipalAuthorization` record isn't filed yet |
| The app used to send phishing | Text in a ticket reaches IT's alert emails; staff open a request "for someone else" with any wording | Text is escaped; requesters can't open requests for others (`test_requester_cannot_open_a_request_in_someone_elses_name`) | An agent can make the help-desk mailbox send a receipt with their own words to any company address |

### 4.6 The admin site and admins

| Threat | How it would work | What stops it today | What's left |
|---|---|---|---|
| Delete or rewrite the record | The admin site | Tickets, users and categories can't be deleted; comments and history are read-only there; every admin-site change is in the admin log | Admins can still read everything, with no record of it (risk 2) |
| Give themselves or others more access | Edit a user's role | Role, staff and superuser are read-only, recomputed from Entra (`accounts/admin.py`) | A department's Entra role can be set to `Requester`: everyone would become that department's agent at next sign-in. `Department.clean()` refuses `Agent` and `Admin` only (risk 12) |
| Remove content to hide something | The removal tool | Logged in the history, without the removed text (`test_removals_are_logged_without_the_removed_text`) | Nothing known |

### 4.7 The server, secrets and backups

Details of storage are in [data-protection.md](data-protection.md).

| Threat | How it would work | What stops it today | What's left |
|---|---|---|---|
| Take the server over | SSH | SSH from the admin subnet only; automatic security updates | The admin user is in the `docker` group, which is the same as root |
| Read everything off the disk | A shell, the hypervisor, a stolen disk | `.env` 600; backups 700 and `umask 077`; containers run as a non-root user | Backups and `.env` aren't encrypted at rest by the app |
| Lose the data | Disk failure, ransomware on the server | Nightly backups, checked and checksummed (`scripts/backup.sh`) | The backup cron line isn't on the server yet; backups stay on the same server; no restore test (risk 3) |

> **To fill in:** whether the server's disk (or the VM's storage) is
> encrypted, and who can reach the hypervisor or console. IT admins would know.

### 4.8 Code supply

| Threat | How it would work | What stops it today | What's left |
|---|---|---|---|
| A malicious release | Someone pushes to the repository or the company's copy | Private repository; the server's deploy key is read-only; only release tags run on the server | Tags aren't signed or checked; no automated build or review (risk 9) |
| A bad package | A compromised or vulnerable PyPI package | `~=` pins; `scripts/check_updates.py` monthly, with indirect packages since v0.10.7 | No hashes or lock file: indirect packages float at each build |
| A bad image | `python:3.13-slim`, `postgres:17`, `caddy:2.11.9-alpine` | Official images; Caddy pinned; monthly refresh (deployment.md 11) | Tags, not digests; `check_updates.py` doesn't scan the images |

> **To fill in:** who has push access to the repository and the company's
> copy, whether two-factor sign-in is on for those GitHub accounts, and
> whether tags or `main` are protected. The owner would know.

## 5. Residual risks, ranked

| # | Risk | Impact | Owner | Fix planned? |
|---|---|---|---|---|
| 1 | MFA for the app not confirmed in Entra: a stolen password may be enough, and an admin's opens every ticket | High | IT admins (Entra) | Yes: open in backlog.md, v0.10.7 |
| 2 | No record of who viewed a ticket or downloaded a file, so misuse by an agent or admin can't be seen | High | The owner, after the compliance lead's review | Partly: v0.11.0 logs sign-ins and downloads; page views won't be logged (decided 2026-11-16) |
| 3 | No nightly backup on the server yet; backups never leave the server; no restore test | High | IT admins | Cron before go-live; the off-server copy after v1.0.0, place undecided; restore test not planned (to confirm with the compliance lead) |
| 4 | The network firewall for ports 80 and 443 isn't confirmed; ufw doesn't cover them | Medium | Whoever runs the network | Yes: post-install check 20, before go-live |
| 5 | Sign-out leaves Microsoft 365 signed in, so on a shared PC the next person may get in as the previous one | Medium | The owner | **Not recorded until now**; no fix planned |
| 6 | Email confirmation accepts a `dmarc=pass` or `compauth=pass` the sender could write themselves; relies on the mailbox refusing outside senders | Medium | The owner; the Exchange admin to confirm | **Not recorded until now**; no fix planned |
| 7 | Web uploads aren't scanned; `.eml`, `.msg` and old Office files can carry other files or macros | Medium | The owner | Recorded as "unscanned" (v0.10.7); the container point isn't; no fix planned |
| 8 | One client secret does sign-in and mail; secrets in plain `.env`; PCs hold secrets for the same registration | Medium | The owner, the Entra admin | A certificate credential is a "later improvement" (entra-setup.md) |
| 9 | Code supply: unsigned tags, no lock file or hashes, images by tag | Medium | The owner | Monthly checks only |
| 10 | A role or account removed in Entra keeps an open session for up to 12 hours | Low | IT admins | No: unticking Active in the admin site is the immediate step |
| 11 | No rate limits; Caddy holds up to 60 MB per request in memory before the app sees it; three web workers | Low | The owner | No: LAN and VPN only; load-tested at 400 people (2026-11-09) |
| 12 | A department's Entra role can be set to `Requester` | Low | The owner | **Not recorded until now**; no fix planned. The admin log would show who did it |
| 13 | An unconfirmed email to a real ticket number creates an account for an unknown company address | Low | The owner | **Not recorded until now**; no fix planned |
| 14 | The spoofed-email check has never been tried against the real mailbox | Low | IT admins | Yes: open in backlog.md (v0.8.3 section) |

## 6. What was tested and when

| Date | What | Result |
|---|---|---|
| 2026-11-10 | Three reviews of v0.8.2 and an attack test (SQL, shell and template injection in every input) | Fixed in v0.8.3 and v0.9.1 (fake IT emails, shared PCs, no deletes) |
| 2026-11-16 | **Security audit** against ten common weaknesses: access control, secrets, debug settings, injection, uploads, sign-in, CSRF and cookies, dependencies, email-in, the audit trail. 41 attacks against a throwaway database, a read of the code, and 32 pages opened as each role in Edge | No ticket or file of someone else's could be reached. Fixed in v0.10.7: the debug-mode guard, every sender checked, the Content-Security-Policy, no `.zip`, indirect packages in the update check. Two gaps kept as `test_observed_*` tests: unscanned office files, and no record of viewing or downloading |
| 2026-11-11 | `check_updates.py` | No known security issues. Next check mid-December |

The audit's attacks are kept in `tickets/tests/test_security_audit.py` (48
tests) and the production settings in `core/tests/test_security.py`, so
every change runs against them. To run just those:

```powershell
.\.venv\Scripts\python.exe manage.py test tickets.tests.test_security_audit core.tests.test_security
```

Not tested so far:

- an outside penetration test, or any test from the network against the
  real server;
- a spoofed email to the real mailbox, and a forged `Authentication-Results`
  header;
- the shared-PC case with Microsoft 365 still signed in;
- MFA, the network firewall and SSH settings (the To fill in notes above);
- a restore from backup.

This document should be reviewed with each release that changes sign-in,
email-in, uploads or the server setup.

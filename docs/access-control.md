# Access control

Who can get into InH-Ticketing, and what each person or system can do once
they're in. For IT admins, the compliance lead and anyone reviewing access.
Written 2026-11-19 for v0.10.7, from the code; where the code and another
document disagree, this one follows the code.

Related: attackers and residual risks are in [threat-model.md](threat-model.md);
where data and secrets are kept, in [data-protection.md](data-protection.md);
what to do when access goes wrong, in [incident-response.md](incident-response.md);
the rules people must follow, in [security-policy.md](security-policy.md).

## 1. Signing in

**Microsoft 365 only.** People sign in on Microsoft's own page (Entra ID,
OpenID Connect with PKCE, through the MSAL library). There is no password
form anywhere in the app, the admin site's included: its login page sends
people to the same Microsoft sign-in.

| The app sees | The app never sees |
|---|---|
| The person's Entra ID (`oid`, which never changes), name, work email, the tenant they belong to, and their app roles | Their password, their MFA method, or any Microsoft token after sign-in (the app keeps only the details above) |

**Only this company's accounts.** The app asks the company's own tenant to
sign people in, and refuses a token from any other tenant ("That account
isn't part of this organisation").

**Who may sign in at all** is decided in Entra, on the enterprise
application: with **Assignment required** set to *Yes*, only people (or
direct members of groups) assigned to the app get in; anyone else sees
"you haven't been given access" (`AADSTS50105`). The steps are in
[entra-setup.md](entra-setup.md#5-limit-who-can-sign-in).

> **To fill in:** whether *Assignment required* is set to *Yes* on the
> production enterprise application, and which groups are assigned which
> role. From the Entra admins.

**MFA** is not the app's decision. Entra decides it (Conditional Access or
security defaults) before sending the person back to the app.

> **To fill in:** whether MFA is required for this app, and by which policy.
> Still open in [backlog.md](backlog.md) under v0.10.7. From the Entra admins.

**How a sign-in becomes an account** (`accounts/entra.py`, `sync_user`):

| Situation | What happens |
|---|---|
| First sign-in | An account is created, matched on the Entra ID. It has no usable password |
| An account already exists from email-in, or from staff opening a request "for someone else" (username `email:<address>`, no Entra ID yet) | The first sign-in with the same email links it to the Entra ID, so their earlier tickets follow them |
| Every later sign-in | Name, email, role and department are copied from Entra again. Entra is the source of truth |
| No agent or admin role in the token | The person is a **Requester** |
| The account is turned off in the admin site (*Active* unticked) | Sign-in is refused: "Your InH-Ticketing account has been disabled" |

**Sessions** (`config/settings.py`):

- A sign-in lasts until the browser closes, and 12 hours at most.
- Signing in gives a fresh session ID. The cookie is HTTPS-only on the server,
  hidden from scripts (`HttpOnly`) and not sent by other sites' forms
  (`SameSite=Lax`).
- **Sign out** (a button, POST only) ends the session in the app. The person
  stays signed in to Microsoft 365, so Outlook and Teams aren't affected.
- Signed-in pages are sent with `Cache-Control: private, no-store`, so the
  Back button on a shared PC can't bring them back after sign-out.

**What ends access, and when:**

| Change | Takes effect |
|---|---|
| *Active* unticked in the admin site | At the person's next click: their open session stops working at once |
| Role changed or removed in Entra | At their next sign-in only. An open session keeps the old role for up to 12 hours |
| Account disabled or unassigned in Entra | At their next sign-in. An open session keeps working for up to 12 hours |

The app has no button to end another person's session. Unticking *Active*
does it, and so does a command on the server that leaves the account usable
([incident-response.md](incident-response.md), 5.2).

## 2. Roles

| Role | Who | Comes from |
|---|---|---|
| **Requester** | Any staff member (about 300) | No agent or admin role in Entra (the `Requester` app role, or *Default Access*) |
| **Agent** | A department's staff | An Entra app role: `Agent` (set by `ENTRA_ROLE_AGENT`) for IT; each other department's own role, typed in the admin site under **Tickets → Departments** |
| **Admin** | A few IT admins | The Entra app role `Admin` (set by `ENTRA_ROLE_ADMIN`). Also gives the admin site |

- **The highest role wins.** Admin beats any agent role. Someone with two
  agent roles works for IT if one is `Agent`, otherwise for the department
  added first.
- **An agent works for one department.** Admins work for all of them.
- **Adding a department** and its role: [entra-setup.md](entra-setup.md#3-define-the-app-roles).
- **A role change applies at the next sign-in**, whether it was made in
  Entra or by changing a department's role value in the admin site.

## 3. The permission matrix

"Own department" means tickets whose category belongs to the agent's
department. Agents and admins can also do everything a requester can on
their own requests. Archived means Closed: a closed ticket is archived at
once and is read-only for everyone until an admin takes it out.

| Action | Requester | Agent | Admin |
|---|---|---|---|
| See own tickets and their public replies | Yes | Yes | Yes |
| See a department's queue | No (403) | Own department only | Every department, with a filter |
| See another department's tickets | No | No (404), except their own requests, shown as a requester sees them | Yes |
| Open a request for someone else | No (it's opened in their own name) | Own department's categories only | Any category |
| Find people by name or email (for "someone else") | No (403) | Yes, active people, 2 characters minimum, 8 at a time | Yes |
| Start a follow-up from a ticket | Own tickets | Tickets they can see | Any |
| Reply publicly | Own tickets, unless closed | Own department | Any |
| Add an internal note | No | Own department | Any |
| Read internal notes | Never | Own department's, plus notes shared on a move | All |
| Read a ticket's history | Never | Own department | Any |
| Write or edit a ticket's documentation | Never | Own department, on its ticket page, unless archived | Any, unless archived |
| Read documentation across tickets | Never | No (403): only on the ticket page of their own department's tickets | Yes, in Reports (`/reports/documentation/`) |
| Change status, priority, assignee, category | No (403) | Own department; category within the department only; assignee from that department's agents and the admins | Any |
| Move a ticket to another department | No | No: can ask an admin ("Ask to move") | Yes |
| Resolve | Own open tickets ("Mark as resolved") | Own department (status, or "Send and resolve") | Any |
| Reopen | Own Resolved tickets ("This is still a problem", or by replying) | Own department, by status, unless archived | Any, by status, unless archived |
| Close | No (it closes by itself 7 days after Resolved) | Own department, by status | Any |
| Unarchive | No | No | Yes (it stays Closed; reopen from Status) |
| Download an attachment | On own tickets, not on internal notes | Own department, including notes they can read | Any |
| Remove a pasted password, a message or a file | No | No | Yes, any ticket, archived ones too |
| Reports and its CSV | No (403) | No (403) | Yes |
| The admin site | No (403) | No (403) | Yes (below) |

Reports show counts and times per team. Its CSV has one row per request
(number, team, category, status, times, subject and whether it has
documentation), with no names and none of the documentation text.

**The admin site** (admins only):

| Section | Admins can |
|---|---|
| Departments | Add one; edit its name, Entra role and alert address. IT's page is read-only. Delete one only while nothing uses it |
| Categories | Add and edit, including their department and common requests. No delete |
| Users | View; untick or tick *Active*. Role, email and admin access are read-only (from Entra). No add, no delete |
| Tickets | View only, with replies, notes, history and file names. No change, no delete |
| Password warnings, Admin log | View only. No change, no delete |
| Outbound emails | View; "Retry selected emails now". **Delete is possible** (Django's default) |
| Inbound emails | View. **Delete is possible** (Django's default) |

**Deleting.** Nobody can delete a ticket, a reply, a note, a history line or
a user, in the app or the admin site. What can be deleted: an attachment (by
an admin's removal, which logs that it happened, not what), an unused
department, and outbound and inbound email records in the admin site (each
deletion is in the admin log).

## 4. How the server enforces it

- **Every check runs on the server.** The browser only shows or hides
  buttons; a forged form is refused (`tickets/tests/test_security_audit.py`,
  class `AccessControlTests`).
- **One place decides what a person sees.** `Ticket.objects.visible_to(user)`
  (in `tickets/models.py`) gives admins everything, agents their department's
  tickets plus their own requests, and requesters their own.
  `tickets/selectors.py` does the same for notes, attachments, history and
  linked tickets. `User.works_on(ticket)` decides who may work a ticket.
- **Role checks** wrap each staff and admin page (`agent_required`,
  `admin_required` in `tickets/views.py`), and the rules are checked again in
  `tickets/services.py`, where every change is made and logged.
- **"Not found", not "Forbidden".** A ticket, attachment or message you may
  not see answers 404, the same as one that doesn't exist, so nobody can
  probe ticket numbers. A page that needs a role you don't have (the queue,
  Reports, the admin site, an admin-only action) answers 403 whatever the
  ticket number, so that doesn't reveal anything either.

## 5. Email as a way in

When email-in is on, the help-desk mailbox (and each department's) is
another way to act on tickets. Only senders from the company's domains
(`INBOUND_ALLOWED_DOMAINS`) are read; anyone else, and automatic mail, is
ignored without a reply. "Confirmed" means Exchange vouched for the sender.

| Sender | Confirmed | Not confirmed |
|---|---|---|
| New email, no ticket number | A new ticket in their name (an account is made if needed) | Ignored: no ticket, no account |
| The requester, `[#number]` in the subject | A public reply (a follow-up ticket if it's closed) | An internal note marked unconfirmed |
| Staff working that ticket | A public reply, never a note (an internal note if the ticket is archived) | An internal note marked unconfirmed |
| Anyone else in the company | An internal note; the assignee is alerted | The same |
| A disabled account | Ignored | Ignored |

Two things the table implies: an email can never write an internal note
that looks like staff's own, and an email to an existing ticket number from
someone the app doesn't know creates an account for that address (a
Requester with no access until they sign in). Details:
[email-setup.md](email-setup.md#4-email-in-emails-become-tickets-and-replies).

## 6. Access that isn't a person

| What | Its access | Limited by |
|---|---|---|
| **The Entra app registration**, signing people in | Delegated *User.Read* only, for sign-in. The app asks for no Graph data as the person | Entra |
| **The same registration**, for email | Application *Mail.Send* and *Mail.ReadWrite*, granted in Exchange to the help-desk mailbox (and department mailboxes) only, never in Entra's API permissions | An Exchange management scope ([email-setup.md](email-setup.md), 3b, 3c, 4b) |
| **The worker** container | Sends queued email, reads the mailbox, closes resolved tickets. Uses the same database login and client secret as the web app. Publishes no port | Docker |
| **The database** (PostgreSQL) | One login, used by the web app and the worker: the one the PostgreSQL image creates, which is a database superuser. Publishes no port: only those two containers reach it | Docker's network |
| **The server** | SSH from the IT admins' range only (whether it's keys only is a To fill in in [threat-model.md](threat-model.md)); one admin account with sudo, in the `docker` group (which is equal to root, and so can read the database and `.env`) | The firewall ([deployment.md](deployment.md#14-firewall)) |
| **The code** | The server fetches it with a read-only deploy key, for one repository. Only the owner can push releases or add and remove keys and readers | GitHub ([deployment.md](deployment.md#2-get-the-code)) |
| **`ingest_email`** on the server | Puts an email through email-in without the sender check | Whoever can run commands in the containers |

> **To fill in:** who holds the sudo account on the server, who has SSH keys
> for it, and the admin range allowed in the firewall. From the IT admins.

> **To fill in:** who the Entra admins (Application Administrator or Cloud
> Application Administrator) and Exchange admins are for this app. From the
> IT admins.

How these secrets are stored and rotated is in [data-protection.md](data-protection.md).

## 7. Granting, changing and removing access

| Event | Who | Where | Notes |
|---|---|---|---|
| New staff member (Requester) | Entra admins | Entra: add them to the group assigned *Requester* | Direct group members only; nested groups don't count |
| New agent | Entra admins | Entra: assign the department's agent role | Never the plain `Agent` role for a team other than IT |
| New department | An app admin, then Entra admins | Admin site → Departments, then the role in Entra | [entra-setup.md](entra-setup.md#3-define-the-app-roles) |
| New admin | Entra admins | Entra: assign *Admin* | Also gives the admin site |
| Changing department or role | Entra admins | Entra | Applies at their next sign-in. Reassign their open tickets: an assignee who no longer works the department keeps the tickets but can't see them |
| Leaver | Entra admins, and an app admin | Disable in Entra; untick *Active* in the admin site to end any open session now | Their tickets and history stay. Reassign their open tickets |
| Server or code access | IT admins; the owner | The server's SSH keys and `docker` group; GitHub | See [security-policy.md](security-policy.md) |

> **To fill in:** how IT learns of joiners, movers and leavers (HR process or
> ticket). From the IT admins.

There is no scheduled review of who holds the Agent and Admin roles: a
quarterly one was judged not needed (decided 2026-11-09,
[backlog.md](backlog.md), Compliance).

## 8. What's logged about access

| Recorded today | Where |
|---|---|
| Every change to a ticket: who, what, when (status, priority, assignee, category, moves, removals, opened for someone) | The ticket's history |
| Every change in the admin site, with old and new values | Admin site → Admin log (read-only) |
| Each password warning and what the person chose | Admin site → Password warnings (read-only) |
| Every email that reached the mailbox, and what happened to it | Admin site → Inbound emails |
| Each person's **last** sign-in time | Admin site → Users (`last_login`) |
| Failed sign-ins, with Entra's error code | The web container's log only, as warnings |

**Not recorded today:** a history of sign-ins (only the last one), sign-outs,
who viewed a ticket, and who downloaded a file (an audit test confirms
viewing and downloading leave no record). Entra keeps its own sign-in log
for the app.

Entra keeps those logs about 7 days without an Entra ID P1 or P2 licence and
30 days with one ([incident-response.md](incident-response.md), section 6).

> **To fill in:** which licence the company has, and who reviews Entra's
> sign-in logs for the app. From the Entra admins.

**Planned for v0.11.0** ([backlog.md](backlog.md#v0110-access-logging-after-the-compliance-leads-review)):
record every sign-in (success and failure) and every file download, kept as
long as tickets (2 years), read-only for admins. Ticket page views stay
unlogged (decided 2026-11-16).

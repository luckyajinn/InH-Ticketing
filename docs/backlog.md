# Backlog

Open items, grouped by the version they're planned for. Tick an item when
it's done and mention it in that version's release notes. Target dates for
each version are in [roadmap.md](roadmap.md).

## v0.3.0 (milestone 3: outbound email)

- [x] Email notifications: request received, IT replied, requester replied,
      assigned to you, resolved, reopened.
- [x] Email outbox and background worker, with retries.
- [x] Microsoft Graph sending from the test shared mailbox. *(Code done; needs
      the Exchange setup in docs/email-setup.md before it can be tried for real.)*
- [x] **Composer "send and set status" buttons.** IT could only resolve or
      close a ticket from the Status dropdown, which was easy to miss. Added
      "Send and set Waiting on User" and "Send and resolve" next to the reply
      button. *(Raised in testing, 2026-11-06.)*

## v0.4.0 (milestone 4: email in)

- [x] Inbound email-to-ticket from the test shared mailbox, with replies
      matched by `[#1001]`. *(Code done; reading the real mailbox needs the
      Exchange permission in docs/email-setup.md section 4b.)*
- [x] A reply to a closed ticket by email opens a linked follow-up ticket
      (brought forward from milestone 5).

## Compliance (from the intended-use and risk assessment, 2026-11-06)

McKenna Labs is FDA-regulated (cosmetics). The draft assessment proposes
InH-Ticketing as **non-GxP**: internal IT support only, holding no
FDA-required records. Ruben Martinez reviewed it, and the risk assessment
passed (reported 2026-11-09).

Before the pilot (by 2026-11-30):
- [x] One page of usage rules: [usage-rules.md](usage-rules.md) (intended
      use, the *not used for* list, "forward complaints to QA the same day,
      never delete", "no passwords in tickets", and IT's handling steps).
- [x] Show a short "IT issues only" notice on the New request page (v0.5.0).
- [x] Document how to make the help-desk mailbox accept internal senders only
      (docs/email-setup.md, section 3a).
- [x] **Actually set it** on the test mailbox (2026-11-09: `RequireSenderAuthenticationEnabled` is True).
- [x] Set it on the live help-desk mailbox before go-live. *(Live, reported 2026-11-09.)*
- [x] Record Ruben Martinez's review (the date and his decision) in the risk
      assessment, version 0.2. *(The risk assessment passed, reported 2026-11-09.)*
- [ ] File the `Test-ServicePrincipalAuthorization` results. *(Run 2026-11-09:
      Mail.Send and Mail.ReadWrite in scope for the test mailbox only. Save
      the output with the risk assessment.)*

Before go-live (by 2027-01-11):
- [x] Admin tool to remove a pasted password or file from a ticket, with the
      removal itself logged. *(v0.9.1.)*
- [x] Decide how long tickets are kept. *Decided 2026-11-09: a resolved ticket
      closes automatically after 7 days (already built in v0.5.0,
      `AUTO_CLOSE_RESOLVED_DAYS=7`).*
- [x] What happens to closed tickets after that. *Decided 2026-11-10:
      archived (read-only, out of the working views) for two years, then
      deleted. Archiving is built (v0.9.1).*
  - [ ] Delete archived tickets when their two years are up (`ARCHIVE_KEEP_DAYS`).
        Reports' trends lose them then: keep monthly totals first.
- [x] ~~Quarterly review of who holds the Agent and Admin roles.~~ *Not needed (decided 2026-11-09).*
- [ ] Monthly check of dependencies for security updates.
- [ ] Off-server backup copy and one tested restore (also under v0.6.0).

## v0.5.0 (milestone 5: automations)

- [x] Auto-close resolved tickets after N days (default 7). Show the close
      date in the resolved email and on the ticket.
- [x] "Start a follow-up" on closed tickets on the web, and a Linked tickets
      panel on both tickets.
- [ ] *(To decide)* Reminder when a ticket has been Waiting on User for N days.

## v0.6.0 (milestone 6: deploy)

Decided 2026-11-06:

| | |
|---|---|
| Server | Linux VM with Docker. 2 vCPU, 4 GB RAM, ~80 GB disk is plenty for the scale below. **Actual server (2026-11-09): 16 cores, 32 GB RAM**, so there is plenty of room for more features |
| Scale | Fewer than 5 IT agents; up to ~300 requesters |
| Address | `https://helpdesk.mckennalabs.com` (internal DNS record pointing at the server) |
| HTTPS | Certificate from the McKenna Labs **private internal CA**, served by a reverse proxy in Docker Compose. Staff PCs must trust that CA (usually already done through Group Policy) |
| Backups | Stored locally on the server: nightly database dump plus attachments, kept 14 days |
| Network | The server needs outbound HTTPS to `login.microsoftonline.com` and `graph.microsoft.com` |

- [x] Production Compose setup: reverse proxy with the internal-CA
      certificate, HSTS and an HTTP-to-HTTPS redirect (clears the two
      `check --deploy` warnings).
- [x] Nightly local backups with 14-day retention, and a restore procedure.
- [ ] The restore drill on the real server, recorded (docs/deployment.md section 9).
- [ ] Entra: add the redirect URI `https://helpdesk.mckennalabs.com/auth/callback`,
      and use a separate client secret (or a certificate) for the server.
- [x] A deployment guide covering first install, updating to a new version, and restoring.
- [x] The first install on the server, following the guide and fixing it as needed.
      *(Live on the internal server and tested, 2026-11-09.)*

## v0.7.0 (released 2026-11-09, for the pilot)

- [x] **Email signatures on email-in tickets.** Staff emails carry the company
      signature added by CodeTwo: name, address, phone and fax, a logo
      placeholder, the "consider the environment" line and the
      confidentiality notice. It now folds under **Show email signature** on
      tickets and replies that arrive by email; the full email is still
      stored. *(Raised in testing, 2026-11-09, on ticket #1071. Check #1071
      on the server once v0.7.0 is installed.)*
- [x] **Warn before a password is sent.** The New request form, replies and
      internal notes check the text before it's sent and warn if it might
      include a password, leaning towards false alarms rather than misses.
      People take it out, or tick "send anyway".
- [x] **Audit trail for the password warning.** Every "sent anyway", every
      password taken out after a warning, and every email that looks like it
      has one is recorded: who, where and which check, never the text.
      Read-only in Admin, under *Password warnings*. IT also sees a *Possible
      password* line in the ticket's history.
- [x] **The new look** ("Friendly Soft"), chosen from three renditions, with
      queue subjects on one line.

## v0.8.0 (released 2026-11-09, for the CFO demo)

- [x] **Mechanics and Cleaning & sanitization requests.** Two new categories,
      each with three **common requests** that fill in the subject and the
      category when picked; people can still type their own. Admins edit the
      lists in Admin, Categories (one per line, up to 20). *(Ruben Martinez
      said it needn't go through the FDA rules, as no customer data is
      involved; a risk assessment to confirm that is planned for 2026-11-10.)*
- [ ] Update `usage-rules.md` and the risk assessment for Mechanics and C&S,
      after the 2026-11-10 review. The New request page's notice already
      names them.

## v0.8.2 (released 2026-11-09: the site basics)

Priorities and reasons are in [roadmap.md](roadmap.md), Site basics.

- [x] New Not found page: next steps first, and open a ticket by its number.
- [x] Help contact (`HELP_CONTACT`) under "Can't sign in?" and on the error pages.
- [x] Sending state, and no double sends from a double click.
- [x] Wording for every team, not just IT.
- [x] Usage and privacy page (`/about/`), linked from the footer and sign-in.
- [x] Favicon set and web manifest.
- [x] robots.txt and noindex on every page.
- [ ] Set `HELP_CONTACT` on the server (`.env`), e.g. IT's extension and Teams channel.
- [ ] A fuller privacy notice before licensing to other companies.

## v0.8.3 (released 2026-11-10: pre-pilot review fixes)

From three reviews of v0.8.2 (security and privacy, feature logic,
deployment) and an attack test, all on 2026-11-10.

- [x] Side panel applies only the fields the person changed (an old page
      could undo someone else's assignment or reopen a resolved ticket).
- [x] A reply being typed survives the side panel saving.
- [x] Password check: no false alarms on "pin is bent", "pass is broken",
      lot / batch / cost / part codes, or pasted timestamps; catches lock
      combinations.
- [x] Signatures fold only with a name, a sign-off or boilerplate.
- [x] No error pages from superscript digits (six places) or odd sign-in links.
- [x] The last "IT"-only wording staff of other teams saw.
- [x] Attack test: SQL, shell and template injection in every input.
- [x] Docs: `HELP_CONTACT` in deployment.md, a rollback that keeps tickets,
      `restore.sh` start command, pilot checklist for v0.8.x.

Still from the review, before v1.0.0:

- [x] **Email spoofing:** an email that only *claims* to be from IT becomes
      a public IT reply. *(v0.9.1: it needs `AuthAs: Internal`, `dmarc=pass`
      or `compauth=pass`, or it's kept as an internal note.)*
  - [ ] Send one spoofed test email to the pilot mailbox to confirm Exchange
        junks it, and check one genuine IT reply by email still arrives as a reply.
- [x] **Shared PCs:** signed-in pages and downloads `Cache-Control: private,
      no-store`, and the sign-in ends when the browser closes. *(v0.9.1.)*
- [x] **Start-up order:** the worker waits for the web container
      (`condition: service_healthy`). *(v0.9.1.)*
- [x] The web manifest's content type (`application/manifest+json`). *(v0.9.1.)*
- [ ] *(Later)* A Content-Security-Policy header; password hints that never
      show an earlier password; matching first sign-ins on
      `preferred_username`; a length limit on descriptions and replies;
      rolling back 0005 shouldn't delete an admin's own "Mechanics" category.

## v0.8.4 (released 2026-11-10: admin look, common requests)

- [x] The admin site in the app's look: header, cards, buttons, tables, light
      and dark; no sidebar; plainer section names; the app's own sign-out.
- [x] A chosen common request is the subject: the typed subject greys out,
      with a note that it won't be used.

## v0.9.0 (released 2026-11-10: Reports)

- [x] Reports for admins (`/reports/`), built early from v1.1.0: see v1.1.0's
      Reporting item below and [releases/v0.9.0.md](releases/v0.9.0.md).

## v0.9.1 (released 2026-11-10: before go-live)

- [x] Departments: Mechanics and C&S see and work their own tickets; only
      admins move tickets between departments; notes stay with their department.
- [x] Closed tickets are archived for two years.
- [x] The removal tool for a pasted password or file.
- [x] Fake "IT" emails, shared PCs, no ticket deletes, the start-up order,
      the manifest type, the privacy page.
- [x] A mailbox per department, ready to switch on.

## v0.9.x (pilot fixes, after the pilot's testing)

Paused until the pilot's testing is done (2026-11-10).

Filled from the pilot, which starts 2026-11-10. Report what you find as a
ticket, subject starting "Pilot:", so it's tracked in the app itself.

- [ ] Fixes for everything the pilot breaks (see [pilot-testing.md](pilot-testing.md)).
- [x] **Remove a pasted password or file from a ticket.** *(v0.9.1.)* An admin tool to take
      out a password someone pasted into a message, or a file they attached.
      The removal itself is recorded in the ticket's history (who, when, and
      what kind of thing was removed, never the removed content). *(A
      compliance item, needed before go-live. The audit trail already links
      each warning to its message, so it can start there.)*
- [x] What happens to closed tickets: archived for two years (see Compliance above). *(v0.9.1.)*

## v1.0.0 (everything for IT finalized, by 2026-11-13 or 11-16)

- [x] **A mailbox per department** *(built in v0.9.1, `DEPARTMENT_MAILBOXES`;
      switched on once the addresses are decided. Required before v1.0.0, decided
      2026-11-09)*. Mechanics and Cleaning & sanitization already have shared
      mailboxes; IT uses the help-desk mailbox. Email to a department's
      mailbox becomes a ticket in that department's category (no admin move
      needed), and that ticket's emails are sent from the same mailbox, so
      replies come back to the right team. Set as a list of mailbox and
      department pairs in `.env`. *(2026-11-10: no confirmation yet of a
      shared mailbox for each department; waiting on the CFO meeting.)*
  - [ ] Set `DEPARTMENT_MAILBOXES` and do the Exchange steps (email-setup.md, 4d)
        once the CFO decides.
  - **Watch out:** email-in takes over a mailbox's Inbox. It turns every
    unread email into a ticket, sends the sender a receipt, marks it read and
    moves it to "Processed by InH-Ticketing". On a mailbox a department
    already reads every day, its emails would vanish from their Inbox, and
    any email someone opens first would be skipped. *(To decide)* Either a
    new request-only mailbox per department, or the existing mailbox with a
    rule that files requests into a "Requests" folder the app reads instead
    of the Inbox.
  - Exchange, per mailbox: allow the app to send as it and read it
    ([email-setup.md](email-setup.md) 3c and 4b), set internal senders only,
    and record `Test-ServicePrincipalAuthorization` for it.
- [ ] From the reports research (2026-11-10):
  - [x] Admins can hard-delete a ticket and its history in the admin site,
        against the usage rules ("never delete it"). *(Turned off in v0.9.1.)*
  - [x] The closed-ticket decision keeps a closed ticket's row and history
        (archived), so Reports keeps its trends. *(v0.9.1.)*
  - [ ] A worker heartbeat (last round, last inbox read, last auto-close),
        so Reports can say for sure that the worker is running. Today it
        infers it from emails waiting to be sent.
  - [x] Usage and privacy page: ignored emails are logged with their sender
        and subject, and the emails the app sends are kept. *(v0.9.1.)*
- [ ] Everything in v0.9.x, plus the server and Microsoft 365 tasks in the
      roadmap's "Your side" list (restore drill, the server's own Entra
      secret, the permission-check record, DMARC, an off-server backup).

## v1.1.0 (stretch: IT improvements, by 2026-11-17)

- [ ] **Reply templates:** saved answers for common requests (password resets, new starters).
- [ ] **Response targets:** how long tickets wait, by priority, with overdue highlighting.
- [x] **Reporting:** tickets per week, time to resolve, busiest categories.
      *(Built early, in v0.9.0 (2026-11-10): the Reports page at `/reports/`, admins only.
      Per team, never per person: new requests, first response, time to
      resolve not counting waiting on the requester, blocking share, requests
      over time, open tickets by age, top categories and common requests,
      email and password-check health, and a CSV download. Chosen from three
      research passes: IT operations, compliance and privacy, management.)*
  - [ ] Later: response targets per priority (the "% within target" tile),
        requests by the requester's own department (needs Entra's
        `department` claim stored), and a monthly summary email.
- [ ] **Teams alerts** for IT, alongside email. *(Needs a Teams webhook or permission.)*

## v1.2.0 (stretch: the other teams, by 2026-11-19)

- [x] **Own queue and role for Mechanics and for Cleaning & sanitization.**
      *(Built early, in v0.9.1, as decided below.)*
      Today their tickets land in the IT queue (filter by category) and only
      IT can reply. Each team gets its own queue and an Entra app role, and
      doesn't see IT's tickets or internal notes.

  Decided 2026-11-09:

  | | |
  |---|---|
  | Departments | IT, Mechanics, Cleaning & sanitization. Each category belongs to one |
  | Entra app roles | **IT Agent** (value `Agent`, unchanged), **Mechanics Agent** (`Agent.Mechanics`), **C&S Agent** (`Agent.Cleaning`), **Admin** (`Admin`, unchanged). Values come from settings, so another company can use its own |
  | Agents | See and work **only their own department's** tickets, including search, "other tickets from this requester" and linked tickets. IT agents see only IT tickets |
  | Admins | One Admin role oversees **every** department, with a department filter on the queue. No per-department admins |
  | Wrong department | **Only an admin can move a ticket** to another department. The department that got it asks an admin to move it from the ticket ("Ask an admin to move this"), which notifies the admins. The admin confirms with the receiving department **outside the app**, then moves it; the history records who asked, who moved it, from and to, and that it was confirmed |
  | Agents and categories | Agents can change the category only within their own department, so they can't move a ticket out themselves |
  | Internal notes | **Department-specific: they don't transfer** when a ticket moves. Each internal note has a toggle, *Share with the new department if this ticket moves*, **off by default**. On a move, only the notes with it on go to the receiving department; the rest stay with the original department and are never deleted. Admins always see every note. The history records which notes were shared |

  Email-in: each department gets its own mailbox before v1.0.0 (see above),
  so emailed requests land in the right department without an admin move.

  Entra, 2026-11-10: the **Mechanics and C&S groups are live**. In the app
  registration, create the two app roles (`Agent.Mechanics`, `Agent.Cleaning`)
  if they aren't there yet, and assign each group its role. That's safe to do
  before v1.2.0: sign-in only gives agent access for the exact value `Agent`
  (or `Admin`), so until v1.2.0 those people sign in as requesters. **Don't
  give these groups the plain `Agent` role**: that's IT's, and would show them
  every ticket and internal note.
- [ ] More in-depth common requests for Mechanics and C&S, and a self-fill
      option *(the owner is gathering them)*.

## Licensing to other companies (after v1.0.0)

The plan: finish the app for McKenna Labs, then license it to other companies,
each with its own logo, look and needs. *(Raised 2026-11-09.)*

- [ ] *(To decide)* How each company's version is kept. Suggested: one
      codebase, plus a **brand pack** and an `.env` per company, chosen by a
      setting such as `BRAND=mckenna`. A branch per company also works, but
      every fix then has to be merged into, and tested on, every branch.
- [ ] Brand pack contents: logo, favicon and app icons, colours (the `:root`
      variables in `static/css/app.css`), company and app name, and the
      email header image.
- [ ] Move the McKenna-only parts out of the code and into the McKenna pack
      or settings:
  - the "IT issues only, complaints go to QA" notice on the New request page
    (an FDA control, in `templates/tickets/new.html`)
  - the app name, typed in `core/context_processors.py`,
    `notifications/notify.py`, `templates/500.html` and
    `INBOUND_PROCESSED_FOLDER` in `config/settings.py`
  - the default hostname `helpdesk.mckennalabs.com` in `compose.prod.yaml`
- [ ] McKenna Labs as the first brand pack, from the branding kit received
      2026-11-09 (logos, icons, email header, `mckenna-theme.css`). Before
      using it beyond internal tools, get the official logo vector (the kit's
      logo is traced from the website) and sign-off on the "M" mark icon.
- [ ] Split the docs: a general install guide, with McKenna's server, mailbox
      and FDA details kept with the McKenna pack.
- [ ] Keep brand packs out of the shared code, so one company's branding is
      never shipped to another.
- [ ] Each company sets up its own Microsoft 365 (Entra) app registration
      and mailbox. This already works through `.env`; the setup guides need
      the McKenna names taken out.

## Later

- [ ] Confirm DMARC is enforced on the company domain before relying on
      email-in for anything sensitive.
- [ ] Copy backups off the server (a network share or a second machine).
      Local-only backups don't survive losing the server or its disk.
- [x] Tag released versions in git and publish them as GitHub releases (v0.1.0-v0.3.0, 2026-11-06).
- [ ] Revisit the app header ("top row") design.

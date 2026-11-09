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
FDA-required records. It is awaiting review by Ruben Martinez.

Before the pilot (by 2026-11-30):
- [x] One page of usage rules: [usage-rules.md](usage-rules.md) (intended
      use, the *not used for* list, "forward complaints to QA the same day,
      never delete", "no passwords in tickets", and IT's handling steps).
- [x] Show a short "IT issues only" notice on the New request page (v0.5.0).
- [x] Document how to make the help-desk mailbox accept internal senders only
      (docs/email-setup.md, section 3a).
- [ ] **Actually set it** on the test mailbox (and later the live one). *Owner: IT (Exchange admin)*
- [ ] Record Ruben Martinez's review (the date and his decision) in the risk
      assessment, version 0.2.
- [ ] File the `Test-ServicePrincipalAuthorization` results.

Before go-live (by 2027-01-11):
- [ ] Admin tool to remove a pasted password or file from a ticket, with the
      removal itself logged (v0.7.0).
- [ ] Decide how long tickets are kept; add automatic clean-up if needed.
- [ ] Quarterly review of who holds the Agent and Admin roles.
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
| Server | Linux VM with Docker. 2 vCPU, 4 GB RAM, ~80 GB disk is plenty for the scale below |
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
- [ ] The first install on the server, following the guide and fixing it as needed.

## Later

- [ ] Confirm DMARC is enforced on the company domain before relying on
      email-in for anything sensitive.
- [ ] Copy backups off the server (a network share or a second machine).
      Local-only backups don't survive losing the server or its disk.
- [x] Tag released versions in git and publish them as GitHub releases (v0.1.0-v0.3.0, 2026-11-06).
- [ ] Revisit the app header ("top row") design.

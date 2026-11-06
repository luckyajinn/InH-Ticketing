# Backlog

Open items, grouped by the version they're planned for. Tick an item when
it's done and mention it in that version's release notes.

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

## Later

- [ ] Inbound email-to-ticket from the test shared mailbox (milestone 4).
- [ ] Auto-close resolved tickets after N days; a reply to a closed ticket
      opens a linked new ticket (milestone 5).
- [ ] Deploy to the internal server with HTTPS, so testers can use their own
      computers (milestone 6).
- [ ] Size the server once staff and IT headcounts are known (milestone 6).
- [ ] Tag released versions in git (`v0.1.0`, `v0.2.0`, ...).
- [ ] Revisit the app header ("top row") design.

# Pilot testing: try to break it

From **2026-11-10**, two testers try to break InH-Ticketing before everything
is finalized on **2026-11-20** (see [roadmap.md](roadmap.md)). Fixes ship as
small v0.7.x updates during the week, and as v0.8.0 on Nov 18.

**Report each finding as a ticket in the app**, subject starting `Pilot:`,
category Other. Say what you did, what you expected, what happened, and on
which device and browser, with a screenshot if it helps. Mark it:

- **Blocker:** someone sees what they shouldn't, data is lost, or sign-in fails
- **Major:** a wrong status or email, or a page that doesn't work on a phone
- **Minor:** looks wrong, or the wording is confusing

**Never use a real password, even to test the password check.** Make them up.

Work as two roles: one tester as a **Requester** and one as **IT** (Agent),
then swap. Use the test shared mailbox for email.

## 1. Privacy and access (most important)

- [ ] As a requester, open someone else's ticket by changing the number in the address bar. It must say not found.
- [ ] As a requester, try an attachment link from someone else's ticket, or from an internal note (copy it from IT's view). Not found.
- [ ] A requester never sees internal notes, files on notes, history lines or *Possible password* lines: on the page **and** in their emails.
- [ ] A requester can't open `/queue/` or `/admin/`.
- [ ] Sign out, then press Back: no ticket content shows.
- [ ] Reply to a closed ticket as the requester: it should offer a follow-up instead.

## 2. The password check

- [ ] Made-up passwords in every place: subject, description, reply, internal note ("my password is ...", "pw: ...", a PIN, a 6-digit code, "Summer2024!"). Each should warn.
- [ ] Ordinary IT wording should **not** warn ("my password expired", "error code 1603", "Office365 won't open"). Report every false alarm and every miss.
- [ ] Tick "send anyway": IT sees *Possible password* in the history, and Admin, *Password warnings* has a row. The requester sees neither.
- [ ] Take the password out after a warning and send: the row says *Removed before sending*.
- [ ] Attach a file, trigger the warning, then send: the file is still attached.
- [ ] Email the test mailbox with a made-up password: the ticket gets a *Possible password* line.

## 3. Email in and out

- [ ] Email a new request; reply to a notification (keep `[#1234]` in the subject); reply from a colleague who isn't the requester (it becomes an internal note); reply to a closed ticket (a linked follow-up).
- [ ] An out-of-office reply is ignored, with no email loop.
- [ ] The CodeTwo signature folds under *Show email signature* (check #1071 too), and nothing you needed is folded away.
- [ ] A file over 10 MB, a `.exe`, and more than 5 files each get a clear message.
- [ ] An email arrives for each step: received, IT replied, assigned, waiting, resolved (with the close date).

## 4. Ticket rules

- [ ] Walk one ticket through everything: New, Open, Waiting on User, the requester replies (back to Open), "Send and resolve", "This is still a problem", Resolved again, then closed automatically. To close now instead of waiting 7 days: `docker compose -f compose.yaml -f compose.prod.yaml exec web python manage.py close_resolved` (only closes tickets resolved over 7 days ago).
- [ ] Two IT people change the same ticket at once, in two browsers.
- [ ] Assign, unassign, "Assign to me", priority, category.
- [ ] "Start a follow-up" from a closed ticket links both tickets.

## 5. Odd input

- [ ] A 200-character subject, a very long message, emoji, another language.
- [ ] Text like `<script>alert(1)</script>` or `<b>bold</b>`: it shows as plain text and never runs.
- [ ] An empty form, only spaces, and double-clicking Send (does it make two?).
- [ ] File names with spaces, accents or symbols.

## 6. Devices and display

- [ ] A phone, a tablet and a small laptop; Edge and Chrome.
- [ ] Dark mode, 200% zoom, keyboard only (Tab through every form), "reduce motion" turned on.
- [ ] A slow connection (a phone hotspot).

## 7. Sign-in and roles

- [ ] Someone who isn't assigned to the app in Entra can't get in, and is told why.
- [ ] Change a person's role in Entra (Requester to Agent and back): it applies at their next sign-in.
- [ ] Signed in on two devices at once.

## 8. Server and recovery (IT)

- [ ] `https://helpdesk.mckennalabs.com/healthz` answers.
- [ ] Restart the app mid-use (`docker compose -f compose.yaml -f compose.prod.yaml restart`): nothing is lost, and queued emails still go out.
- [ ] Last night's backup exists, and the restore drill works ([deployment.md](deployment.md) section 9).

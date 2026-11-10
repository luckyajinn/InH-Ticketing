# InH-Ticketing: overview

What the system is, where it stands, and how each feature and system works.
Written 2026-11-10 for v0.9.1. Each section is meant to work as one slide.

## 1. In one paragraph

InH-Ticketing is McKenna Labs' in-house help desk. Staff sign in with their
Microsoft 365 work account and send a request to IT, Mechanics, or Cleaning
and sanitization; the team works it through to resolution, and the person is
kept up to date by email. It replaces ad-hoc emails and hallway requests with
one tracked record per request: who asked, what was done, by whom and when.
It runs on McKenna Labs' own server, inside the company network.

## 2. Where it stands

| | |
|---|---|
| Version | **v0.9.1**, released 2026-11-10 |
| Built | v0.1.0 to v0.9.1 between 2026-11-05 and 2026-11-10, each release tested and documented with screenshots |
| Server | Live on the internal server (16 cores, 32 GB RAM) at `helpdesk.mckennalabs.com` |
| Pilot | Starts 2026-11-10 with one other tester, trying to break it |
| Compliance | Intended-use and risk assessment passed (Ruben Martinez); internal setup approved (Michael Rocovitz). A risk assessment for the Mechanics and C&S use is on 2026-11-10 |
| Target | Everything finalized by **Friday 2026-11-20**; go-live date set then (earliest Monday 2026-11-30) |
| Quality | 356 automated tests, all passing, including an attack test (SQL, shell and template injection in every input) |

## 3. Who uses it

| Role | Who | What they can do |
|---|---|---|
| **Requester** | Any staff member (~300) | Send requests, follow their own, reply, mark resolved, reopen, start a follow-up |
| **Agent** | IT, Mechanics or C&S staff (Entra roles `Agent`, `Agent.Mechanics`, `Agent.Cleaning`) | Everything a requester can, plus their own department's queue and tickets: internal notes, history, and setting status, priority, assignee and category within the department |
| **Admin** | IT admins | Every department's tickets, moving a ticket between departments, removing a pasted password or file, Reports and the admin site (categories, common requests, the password audit trail) |

Roles come from Microsoft 365 (Entra app roles), checked at every sign-in.
An agent never sees another department's tickets or internal notes. Staff ask
an admin to move a ticket that's in the wrong department; the admin checks
with the other team first.

## 4. A request, start to finish

1. **Ask.** Staff open *New request*, pick a common request or type a subject,
   choose a category, describe the problem and attach files, or simply email
   the help-desk mailbox.
2. **Receipt.** They land on their new ticket (#1042) and get an email
   receipt. IT gets a "new request" alert.
3. **Triage.** IT sees it in the queue, sorted by priority then age; sets
   priority, category and assignee. Assigning moves it from New to Open.
4. **Work.** IT replies publicly (emailed to the person) or writes internal
   notes (IT only). "Send and set Waiting on User" pauses it for an answer.
5. **Answer.** The person replies on the page or straight from the email;
   their reply lands on the ticket and it goes back to Open.
6. **Resolve.** IT clicks "Send and resolve" (or the person clicks "Mark as
   resolved"). The email says when it will close.
7. **Close.** If nobody replies for 7 days, it closes by itself. "This is
   still a problem" reopens it before then; after it closes, "Start a
   follow-up" opens a new linked request.

Every change is written to the ticket's history: who, what, when.

## 5. Features, and how each one works

### Sign-in (Microsoft 365)
- People sign in on Microsoft's own page; InH-Ticketing never sees a password.
- The app reads the person's name, email and role from Microsoft 365 at each
  sign-in, so a role change in Entra applies at their next sign-in.
- Sessions last up to 12 hours.

### New request
- **Categories:** Hardware, Software, Access, Network, Mechanics, Cleaning &
  sanitization, Other.
- **Common requests:** a picker of everyday requests, for example "Equipment
  down: a machine won't start or has stopped". A picked one becomes the
  subject and fills in the category; the subject box greys out, with a note
  that anything typed there won't be used. Three each for Mechanics and C&S
  today; admins edit the lists (one per line).
- **Attachments:** up to 5 files, 10 MB each (screenshots, PDFs, Office files,
  text, zip), dragged in or browsed.
- **"This is blocking my work"** flag, used when setting priority.
- A notice on the form: what the app is for, product complaints go to QA,
  and no passwords.

### Password check
- Before a request, reply or internal note is sent, the page asks the server
  whether the text might contain a password, PIN or code.
- If so, a warning shows where (with the password itself masked). The person
  takes it out, or ticks "It isn't a password, or I need to send it anyway".
- It leans towards false alarms on purpose, but stays quiet on everyday
  wording ("my password expired", "error code 1603", file names, "the pin
  is bent", lot and part codes, pasted timestamps).
- **Audit trail:** every "sent anyway", every password taken out after a
  warning, and every email that looks like it has one is recorded: who,
  where, which check. Never the text itself. Read-only in the admin site.
- IT sees a *Possible password* line in the ticket's history, so they can
  check it and reset the password.

### The ticket page
- **For staff:** a progress tracker (Submitted, Being worked on, Waiting on
  you, Resolved), the conversation as a chat, a reply box, and "Mark as
  resolved". Internal notes and history are never shown or emailed to them.
- **For IT:** the full timeline (replies, amber internal notes, history
  lines), a reply box that switches between public reply and internal note,
  "Send and set Waiting on User" and "Send and resolve" buttons, and a side
  panel for status, priority, assignee and category that saves as you change
  it. It saves only the field you changed, so an old page never undoes
  someone else's change, and a reply you were typing is kept. Also the requester's other tickets and any linked tickets.

### The queue
- Each department's agents get their own queue; admins see every department,
  with a department filter.
- Views: Unassigned, Assigned to me, All open, Waiting on user, Recently
  resolved (last 14 days), Archive, each with a count.
- Search by ticket number, subject or requester; filter by category or
  priority. Urgent and high tickets are marked on the left edge.
- On a phone, each ticket becomes a card.

### Email out
- Emails are queued and sent by a background worker (every 15 seconds, up to
  5 tries) through Microsoft 365, from the help-desk mailbox.
- Every email about a ticket has the same subject, `[#1042] Subject`, so mail
  apps group them and replies find their way back.
- **Staff get:** request received, IT replied, resolved (with the close date).
- **IT gets:** new request, the requester replied, assigned to you, an email
  from someone else, reopened.

### Email in
- The worker reads the help-desk mailbox every minute.
- An email with `[#1042]` in the subject is added to that ticket: as a reply
  if it's from the requester or IT, or as an internal note if it's from
  someone else (a manager's approval, say). A reply to a closed ticket opens a
  linked follow-up.
- Any other email becomes a new ticket from the sender.
- It ignores out-of-office replies and bounces (no email loops), emails from
  outside the company, and emails it has already seen. Quoted earlier emails
  are trimmed off; attachments are kept within the same limits.
- **Signatures:** the CodeTwo signature folds under "Show email signature",
  so the request comes first and the phone number is still there. It folds
  only when it finds a name, a sign-off or signature boilerplate.
- Processed emails move to a "Processed by InH-Ticketing" folder.

### Automations
- Resolved tickets close by themselves after 7 days without a reply
  (checked hourly).
- **Closed tickets are archived:** read-only, out of the working views (there's
  an Archive view), and kept for two years. Admins can take one back out.
- Follow-ups: a closed ticket offers "Start a follow-up", which links the two
  tickets; email replies to closed tickets do the same.

### Help when something goes wrong
- **Not found page:** "Go to my tickets" (or "Go to the queue" for IT), "New
  request", and a box to open a ticket by its number. It never says whether
  a ticket exists, as it also shows for tickets that aren't yours.
- **Help contact:** who to call or email, shown under "Can't sign in?" and on
  every error page. The error page works even if the database is down.
- **No double sends:** the button shows a spinner and a second click is
  ignored.

### Usage and privacy
- A page anyone can open: what the app is for, what it keeps, who can see it,
  how long it's kept, and its cookies (only the ones it needs to work; no
  tracking, no analytics). Kept out of search engines.

### Reports (admins only)
- How the help desk is doing, by team, for the last 7 days, 30 days, 90 days
  or 12 months: new requests, first response, time to resolve (not counting
  waiting on the requester), the share of blocking requests, requests over
  time, open requests by age, the most common categories and common
  requests, and email and password-check health. A CSV for spreadsheets.
- Per team, never per person, and only from what the app already keeps:
  no tracking.

### Look and feel
- "Friendly Soft": warm neutrals, one teal accent, rounded cards, chosen from
  three design options. Works on phones, follows dark mode, and turns its
  gentle motion off for people who prefer reduced motion.
- The admin site has the same look (since v0.8.4).
- Colours and fonts live in one place (plus a copy for the admin site),
  ready for another company's brand.

## 6. The systems behind it

| System | What it does |
|---|---|
| **Web app** (Django 6.1, Python) | The pages, the rules, the privacy filtering. Every rule runs on the server, not in the browser |
| **Worker** | Sends queued emails, reads the mailbox, closes resolved tickets |
| **Database** (PostgreSQL) | Tickets, replies, notes, history, the password audit trail |
| **HTTPS proxy** (Caddy) | Serves `https://helpdesk.mckennalabs.com` with the company's internal certificate; redirects plain HTTP; strict HTTPS for a year |
| **Docker Compose** | Runs the four parts (proxy, web, worker, database) together on the server; one command to update |
| **Microsoft Entra ID** | Sign-in and roles |
| **Microsoft Graph** | Sends and reads email, limited by Exchange to the help-desk mailbox only |
| **Backups** | Nightly database dump plus an attachments snapshot, kept 14 days, each one read back and checksummed. Restores check checksums, take a safety backup first, and only swap in a restore that worked |

A load test on 2026-11-09 (app held to 2 CPUs and 4 GB): responses averaged
10 to 16 ms with up to 400 people at once, none failed. The real server has
16 cores and 32 GB.

## 7. Security and compliance

- **Non-GxP:** IT support only, no FDA-required records; the risk assessment
  passed. Usage rules say what it's not for (product complaints go to QA the
  same day; regulated-system changes go through change control).
- **Privacy enforced on the server:** requesters only ever get their own
  tickets and public replies; someone else's ticket shows "Not found".
- **Mailbox locked down:** accepts internal senders only; the app can only
  use the help-desk mailbox (and each department's, once set).
- **Fake "IT" emails:** an email claiming to be from IT is only a public reply
  if Exchange confirmed the sender; otherwise it's an internal note.
- **Departments kept apart:** agents see only their department's tickets and
  notes.
- **Shared PCs:** signed-in pages aren't kept by the browser, and signing in
  ends when the browser closes.
- **Passwords:** never seen at sign-in; warned about before sending; audit
  trail without the text; admins can remove one that was pasted, from the
  ticket and the app's copies of sent emails.
- **Nothing deleted:** tickets can't be deleted; closed ones are archived.
- **Files:** always downloaded, never opened in the browser; stored under
  random names.
- **No tracking:** only necessary cookies; not indexed by search engines.
- **Reports:** admins only, per team, never figures for one person.

## 8. What's next (to Friday 2026-11-20)

| When | What |
|---|---|
| Tue Nov 10 | Demo, pilot starts, risk assessment for Mechanics and C&S |
| Tue Nov 10 | v0.9.0: Reports for admins (done) |
| Tue Nov 10 | v0.9.1: departments, the archive, the removal tool, safety fixes (done) |
| After the pilot's testing | v0.9.x: pilot fixes |
| Fri Nov 13 (or Mon 16) | v1.0.0: everything for IT finalized, a mailbox per department, server checks (restore drill, off-server backup) |
| Mon–Tue Nov 16–17 | v1.1.0 (stretch): reply templates, response targets, Teams alerts |
| Wed–Thu Nov 18–19 | v1.2.0 (stretch): more common requests and a self-fill option for Mechanics and C&S |
| Fri Nov 20 | Go / no-go, go-live date set (earliest Mon Nov 30) |

**Decisions needed:** department mailboxes (new request-only mailboxes, or a
folder in the existing ones; the app supports both); the go-live date.

## 9. Demo script (about 10 minutes)

1. **Sign in** with Microsoft 365: no password goes to the app.
2. **New request as staff:** pick a Mechanics common request ("Leak, unusual
   noise or vibration"), attach a photo, send. Show the receipt message.
3. **The password check:** type "my password is Summer24" in a reply; show
   the warning, then take it out and send.
4. **As IT:** the queue (filter to Mechanics), open the ticket, write an
   internal note, then "Send and set Waiting on User".
5. **Back as staff:** the tracker shows "Waiting on you"; reply.
6. **As IT:** "Send and resolve"; show the close date and the history.
7. **Email in:** open #1071 and fold out the signature.
8. **Safety nets:** open a ticket number that isn't yours (Not found, with
   next steps); the usage and privacy page.

## 10. Ready for the demo?

**Yes: go.** Three independent reviews of v0.8.2 on 2026-11-10 (security and
privacy, feature logic, deployment and readiness) found no way for staff to
see anyone else's tickets, notes or files. Every page was checked on desktop
and phone in light and dark mode, and the production settings check is clean.

**v0.8.3 fixes what they found for the pilot:**

- The side panel saves only the field you changed (an old page could put
  back someone else's assignment or reopen a resolved ticket).
- A reply you're typing is kept when the side panel saves.
- The password check no longer warns on "pin is bent", "pass is broken",
  lot, batch, cost or part codes, or pasted timestamps, and now catches lock
  combinations.
- Short lists at the end of an email no longer fold as a signature.
- Superscript digits ("²") and odd sign-in links no longer show an error page.
- The last "IT"-only wording staff of other teams saw.
- The deployment guide has the help contact and a rollback that keeps
  tickets; the restore script prints the right start command; the pilot
  checklist covers v0.8.

An attack test also tried SQL, shell and template injection in every input
(forms, replies, notes, search, ticket numbers, sign-in links, file names,
email): nothing ran, nothing broke, and the text is stored exactly as typed.

**One thing first:** set `HELP_CONTACT` in the server's `.env` before the
update (put the value in quotes if it contains `#`). Left blank, the sign-in
page would show the test mailbox's address.

**Still to do before v1.0.0** (none needed for the demo or pilot): a check
that emails claiming to be from IT really are (anti-spoofing), protection for
shared PCs (pages not cached after sign-out, sign-in ending when the browser
closes), and the worker waiting for database updates on start-up.

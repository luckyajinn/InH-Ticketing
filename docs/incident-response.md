# Incident response

What to do when a security breach or a vulnerability is found in
InH-Ticketing. For IT admins and the owner (the developer who owns the code
and the repository), including someone reading it for the first time during
an incident. Written 2026-11-19, for v0.10.7.

Related: threats and residual risks, [threat-model.md](threat-model.md);
sign-in and roles, [access-control.md](access-control.md); where data and
secrets are kept, [data-protection.md](data-protection.md); rules and
responsibilities, [security-policy.md](security-policy.md). Server commands:
[deployment.md](deployment.md). There, and below, `docker compose …` is short
for `docker compose -f compose.yaml -f compose.prod.yaml`, run in
`/srv/inh-ticketing/app` on the server.

## 1. What counts as an incident

Anything that may have let someone see, change or remove help-desk data they
shouldn't, or use the app's accounts or secrets. For example: a ticket, note
or file seen outside its department or role; a staff account used by someone
else; a secret from the server's `.env` pasted into a ticket, chat or email;
unknown changes on the server, in the admin log or in the repository; a
backup copied somewhere; a security flaw in the app or one of its parts; a
spoofed or malicious email in the help-desk mailbox; a password pasted into
a ticket (small, with its own playbook, 5.7).

**Not an incident:** the app is down or slow, sign-in fails after a secret
expired, emails stop, a certificate warning. Those go to
[deployment.md section 12, *Troubleshooting*](deployment.md#12-troubleshooting).
An outage that looks deliberate (unknown changes or files) is an incident.

## 2. Who does what

| Role | Does |
|---|---|
| **First responder** | The IT admin who first hears of it. Follows section 4 until the incident lead takes over |
| **Incident lead** | Sets the severity, shares out the work, keeps the timeline, decides when it's over |
| **IT admins** | The server, `.env`, backups, containers; Entra and Exchange, for those who hold those admin roles |
| **Owner** | The code, the repository and its copies, deploy keys; investigates bugs, ships fixes. Doesn't run the server |
| **Compliance lead** | Decides whether personal data or regulated records are involved, and whether anyone outside must be told (section 8) |
| **Management** | Decides on telling staff and outsiders, and on keeping the help desk closed |

> **To fill in:** who is the incident lead by default (for example the IT
> lead) and their stand-in, and the contacts below. Management and IT would
> know. Keep a printed copy: the help desk may be down during an incident.

| Role | Name | Working hours | Out of hours | Stand-in |
|---|---|---|---|---|
| Incident lead | To fill in | To fill in | To fill in | To fill in |
| IT admins (server) | To fill in | To fill in | To fill in | To fill in |
| Entra and Exchange admins | To fill in | To fill in | To fill in | To fill in |
| Owner | To fill in | To fill in | To fill in | To fill in |
| Compliance lead | To fill in | To fill in | To fill in | To fill in |
| Management | To fill in | To fill in | To fill in | To fill in |
| Internal CA (certificates) | To fill in | To fill in | To fill in | To fill in |

## 3. Severity

| Level | Plain test | Act |
|---|---|---|
| **1 Critical** | Someone controls something they shouldn't, now: the server, an Admin account, a secret in use, data being taken | Now, at any hour. Incident lead, owner and compliance lead told within 1 hour |
| **2 High** | Data or a secret was exposed, with no sign it's still in use: tickets seen across departments, a leaked secret, a compromised staff account | The same working day, compliance lead included |
| **3 Medium** | Small and contained: one ticket seen by one colleague, a pasted password, a known flaw in a part with a fix available | Within 2 working days |
| **4 Low** | Suspicious, nothing exposed: a spoofed email the app ignored, an unconfirmed report | Within a week |

When unsure, pick the higher level; it can go down later.

> **To fill in:** confirm or change these response times. Management and the
> compliance lead would know.

## 4. The first 15 minutes

1. **Write it down:** the time, what you saw, who told you, ticket numbers,
   names. Screenshots help. Keep adding to these notes, with times: they
   become the timeline (section 9).
2. **Delete nothing:** no tickets, emails, logs or backups. No `down`,
   `docker system prune` or reinstall. `up -d`, updates and `down` recreate
   containers, and **a container's logs are lost when it's recreated**.
3. **Save the logs and keep the backups** (on the server, as `inhadmin`):
   ```bash
   cd /srv/inh-ticketing/app
   D=~/incident-$(date +%Y%m%d-%H%M); mkdir -m 700 "$D"
   for s in proxy web worker db; do
     docker compose -f compose.yaml -f compose.prod.yaml logs --no-color --timestamps $s > "$D/$s.log"
   done
   KEEP_DAYS=0 ./scripts/backup.sh incident    # a backup now, deleting no old ones
   ls -l "$D"
   ```
   The nightly job deletes backups older than 14 days. To keep them while you
   investigate, `crontab -e` and put `KEEP_DAYS=0 ` just before
   `/srv/inh-ticketing/app/scripts/backup.sh` on the backup line.
4. **Contain:**

   | Situation | Do |
   |---|---|
   | One person's account | Block them in Entra, then in the app (5.2) |
   | A secret leaked | Rotate it (5.3, 5.4) |
   | The app is being misused or attacked | `docker compose -f compose.yaml -f compose.prod.yaml stop proxy`: the app closes for everyone; data and logs stay. `start proxy` reopens it |
   | Stop email in and out too | `docker compose -f compose.yaml -f compose.prod.yaml stop worker` (`start worker` later) |
   | The server itself | 5.5 |

5. **Tell** the incident lead and the owner; the compliance lead for level 1
   or 2, or if ticket content left its audience; management for level 1.
   Never describe an incident in a help-desk ticket: all IT agents read IT tickets.
6. **Pick a severity** (section 3) and the playbook below.

## 5. Playbooks

### 5.1 A ticket or file was seen by someone who shouldn't have

1. Note the ticket number, who saw it, and how (a link, the queue, an email, a move).
2. Find the cause. **Wrong Entra role:** Entra → Enterprise applications →
   InH-Ticketing → Users and groups (an agent role gives its department's
   tickets, *Admin* gives all). **Wrong department:** the ticket's history
   shows moves; the admin log shows category and department edits; a note
   marked to share goes with a moved ticket. **Anything else** (a requester
   seeing someone else's ticket): a bug, level 2, tell the owner.
3. Fix the role in Entra, or move the ticket back. A role change applies at
   the next sign-in, up to 12 hours away; to apply it now, sign the person
   out (5.2, step 3).
4. The app doesn't record who **viewed** a ticket, or who **downloaded** a
   file (planned for v0.11.0, [backlog.md](backlog.md)). Instead, search the
   saved proxy log for `/tickets/<number>/` or `/attachments/<id>/`: it gives
   times and the PC's address, not the person (section 6).
5. Tell the compliance lead if the content was personal or sensitive.

### 5.2 A staff account is compromised

1. **Entra is where it's stopped** (an Entra admin): block sign-in, reset the
   password, revoke sessions, check the MFA methods.
2. **The app keeps its own session** until the browser closes, 12 hours at
   most; revoking in Entra doesn't end it. In the admin site, **People →
   Users**, open the person and untick **Active**: their next click signs
   them out, they can't sign in again, and their emails are ignored.
3. To sign one person out everywhere without blocking them, take their
   number from their admin page's address (`/admin/accounts/user/<number>/change/`):
   ```bash
   docker compose -f compose.yaml -f compose.prod.yaml exec web python manage.py shell -c "from accounts.models import User; u = User.objects.get(pk=<number>); u.set_unusable_password(); u.save(); print('Signed out:', u)"
   ```
4. Check what the account did: ticket histories, replies and notes in its
   name, **Email out → Outbound emails**, Entra's sign-in logs. An **Admin**
   account is level 1: it sees every ticket, can remove content (shown as
   *Removed* in the history) and change departments, categories and who is
   Active (the admin log, filtered by that person).
5. When Entra confirms the account is safe, tick **Active** again.

### 5.3 The Entra client secret leaked

With it, and the tenant and client IDs (not secret), anyone on the internet
can read, move and send email as the help-desk and department mailboxes,
within Exchange's limits ([email-setup.md](email-setup.md), 3c and 4b). It
can't sign in as staff.

1. Save the logs (section 4, step 3). Make a new secret and put its Value in
   `.env`: [deployment.md section 4](deployment.md#4-microsoft-entra), step 2.
2. `docker compose -f compose.yaml -f compose.prod.yaml up -d`, then
   [the secret check](deployment.md#checking-the-client-secret-without-showing-it).
3. **Delete the old secret in Entra:** that's what stops it working. Put the
   new Value in IT's password vault and its expiry in the calendar.
4. Look for misuse: Entra sign-in logs, *Service principal sign-ins*, for
   the app from unknown addresses; the mailbox's Sent Items; a message trace.

### 5.4 The Django secret key or the database password leaked

| Secret | Protects | Rotating it |
|---|---|---|
| `DJANGO_SECRET_KEY` | Signs sign-in sessions and the one-time messages after an action | Signs everyone out. Nothing stored is encrypted with it, so no data is lost |
| `POSTGRES_PASSWORD` | The database. Its port isn't published outside Docker, so it only helps someone already on the server (then also 5.5) | Nothing visible, in this order: the database first, then `.env` |

Save the logs first (section 4, step 3), then on the server:

```bash
cd /srv/inh-ticketing/app
sed -i "s/^DJANGO_SECRET_KEY=.*/DJANGO_SECRET_KEY=$(openssl rand -hex 32)/" .env   # the secret key
NEWPW=$(openssl rand -hex 24)                                                         # the database password
docker compose -f compose.yaml -f compose.prod.yaml exec db psql -U inh -d inh -c "ALTER USER inh PASSWORD '$NEWPW'"
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$NEWPW/" .env; unset NEWPW
docker compose -f compose.yaml -f compose.prod.yaml up -d                             # either one
ls -l .env      # still -rw------- inhadmin
```

Put the new values in IT's password vault. If `web` logs `password
authentication failed`, see deployment.md section 12.

### 5.5 The server is compromised or lost

1. **Compromised:** take it off the network, but don't wipe or switch it off
   before IT decides on a snapshot for evidence.
   > **To fill in:** who can snapshot the server's virtual machine, and where
   > evidence copies are kept. The infrastructure team would know.
2. Treat everything on it as leaked: the client secret (5.3), the secret key
   and database password (5.4), the deploy key (5.6), the certificate's
   private key (ask the internal CA to revoke it), and the backups (5.11).
3. Build a new server with new secrets and restore:
   [deployment.md section 9, *Restoring onto a new server*](deployment.md#restoring-onto-a-new-server-the-old-one-is-lost).
   Use a backup from **before** the first sign of intrusion (section 7).
4. That needs a backup kept **off** the server, which isn't set up yet
   ([deployment.md section 8](deployment.md#8-backups), *Later improvement*).
   Without one, losing the server loses the tickets.

### 5.6 The deploy key or the repository is compromised

- **The deploy key** (`~/.ssh/inh_ticketing_deploy` on the server) can only
  read the company's copy of the code, which holds no secrets. The owner
  removes it from the copy; IT makes a new one
  ([deployment.md section 2](deployment.md#2-get-the-code)). The app keeps running.
- **The repository or the owner's GitHub account** (unknown commits or tags):
  1. IT admins don't update until the owner confirms which tag is safe.
  2. Check the server is on a release tag, unchanged: `git describe --tags`
     and `git status` in `/srv/inh-ticketing/app`.
  3. The owner secures the account, checks the copy's tags against their own
     repository, and sends a clean release ([company-copies.md](company-copies.md)).

### 5.7 A password was pasted into a ticket

Follow [usage-rules.md](usage-rules.md#for-staff-when-something-out-of-scope-arrives),
"A ticket containing a password":

1. IT resets that password where it's used, and tells the person.
2. An admin opens the ticket, clicks **Remove…** on the message (or *Remove a
   password from the subject*), and removes the text, the whole message or a
   file. It also comes out of the app's copies of emails about the ticket.
   The history records who removed what kind of thing, never the text.
3. Not reached: emails already delivered (ask people to delete them), the
   help-desk mailbox's Sent Items and *Processed by InH-Ticketing* folder
   (delete there in Outlook), and backups, until they're 14 days old.

### 5.8 A spoofed or malicious email reached the help-desk mailbox

The app ignores senders outside `INBOUND_ALLOWED_DOMAINS` and new requests
Exchange can't confirm, keeps an unconfirmed reply as an internal note, and
refuses `.zip` files.

1. Don't open its links or files.
2. Admin site, **Email in → Inbound emails**: find it; read *Outcome* and *Detail*.
3. If it left a bad file on a ticket, an admin removes it (**Remove…**, 5.7).
   Who downloaded it: only the proxy log, by `/attachments/<id>/` (section 6).
4. Report it to the company's mail security, who can purge it from
   mailboxes. The original is in the *Processed by InH-Ticketing* folder.
5. If it came from a real internal account, follow 5.2.

> **To fill in:** how the company reports phishing, and who can remove an
> email from every mailbox. The Exchange admin would know.

### 5.9 A known vulnerability in a dependency or base image

1. Run `docker compose -f compose.yaml -f compose.prod.yaml exec web python scripts/check_updates.py`.
   "Known security issues: none." is the all-clear.
2. **PostgreSQL or the Python base image:** IT refreshes them,
   [deployment.md section 11, *Refreshing the images*](deployment.md#refreshing-the-images-monthly).
3. **A Python package or Caddy:** send the output to the owner, who ships a
   release; install it ([deployment.md section 10](deployment.md#10-updating-and-rolling-back)).
4. **Debian:** `sudo apt update && sudo apt upgrade` ([1.3](deployment.md#13-automatic-security-updates)).
5. Being used against the app before a fix exists: level 1, `stop proxy` (section 4).

### 5.10 Someone reports a vulnerability in the app itself

1. Reports go to the owner privately, never as a help-desk ticket.
   > **To fill in:** how to report a security flaw in InH-Ticketing (an
   > address or channel). The owner and IT would decide.
2. The owner confirms it, sets the level and tells the incident lead. Until
   a fix ships, IT can close the app (`stop proxy`).
3. The owner fixes it with a test, and ships a normal release with release
   notes (`docs/releases/`), sent to the company's copy
   ([company-copies.md](company-copies.md), *Each release*), and to every
   other company's copy.
4. IT admins install it ([deployment.md section 10](deployment.md#10-updating-and-rolling-back)).

### 5.11 A backup or the backups folder was exposed

A backup holds every ticket, note and attachment, the app's email copies and
the password audit trail (not `.env`), and the sessions of people signed in then.

1. Find out what was copied, where, by whom. Remove the copy if you can.
2. `ls -ld /srv/inh-ticketing/backups` must show `drwx------ inhadmin`.
3. Sign everyone out, so no session in the copy works:
   ```bash
   docker compose -f compose.yaml -f compose.prod.yaml exec web python manage.py shell -c "from django.contrib.sessions.models import Session; print(Session.objects.all().delete())"
   ```
4. Level 2 at least: it's every ticket. Tell the compliance lead.

## 6. Where the evidence is

| Source | Where | What it shows | Kept |
|---|---|---|---|
| Ticket history | The ticket page; admin **Tickets → Tickets** | Status, assignee, category, department, moves, *Possible password*, *Removed*: who and when | With the ticket; tickets can't be deleted |
| Admin log | Admin **Administration → Log entries** | Every admin-site change: who, when, old and new values | Can't be deleted |
| Password audit trail | Admin **Tickets → Password warnings** | Each warning, *sent anyway* and emailed password; never the text | Can't be deleted |
| Inbound emails | Admin **Email in → Inbound emails** | Every email received: sender, subject, outcome, why. Not the body | In the database. An admin can delete rows here; the admin log shows who and when |
| Outbound email copies | Admin **Email out → Outbound emails** | What the app sent, to whom, the text | In the database. An admin can delete rows here too; the admin log shows it |
| People | Admin **People → Users** | Role, department, Active, *last login* (the latest only) | In the database |
| Container logs | `docker compose … logs <service>` | `proxy`: each request's time, PC address and path. `web`: requests, warnings, sign-in errors. `worker`: email in and out | 100 MB per container (5 × 20 MB); how far back depends on traffic. **Lost when the container is recreated** |
| Entra | Entra admin center: sign-in logs (and *Service principal sign-ins*), audit logs | Sign-ins and from where; role and secret changes | Set by Microsoft (about 7 days without Entra ID P1/P2, 30 with): export early |
| Exchange | The mailbox's Sent Items and *Processed by InH-Ticketing*; message trace | The emails themselves | Exchange's settings |
| Server | `journalctl -u ssh --since "7 days ago"`; `sudo journalctl _COMM=sudo` | SSH sign-ins and sudo use | The journal's settings |
| Backups | `/srv/inh-ticketing/backups` | The data each night | 14 days, unless `KEEP_DAYS=0` (section 4) |

**Not recorded today:** sign-ins inside the app (only Entra's log and *last
login*), and file and report downloads (only PC addresses in the proxy log,
while it lasts). Sign-ins and downloads are planned for v0.11.0
([backlog.md](backlog.md)); ticket page views won't be recorded (decided
2026-11-16). Save the container logs before anything recreates them
(section 4, step 3).

> **To fill in:** who can match a PC address and time to a person or device
> (the VPN and DHCP logs), and how long those are kept. The network team would know.

## 7. Recovering

| Situation | Do |
|---|---|
| Data changed or deleted, and the server is trusted | Restore a backup: [deployment.md section 9](deployment.md#9-restoring-a-backup). Everything since is lost: tell people |
| The server may be compromised | Rebuild, then restore: [section 9, *Restoring onto a new server*](deployment.md#restoring-onto-a-new-server-the-old-one-is-lost) |
| A bad release | Roll back: [section 10, *Rolling back*](deployment.md#10-updating-and-rolling-back) |

How to know it's clean:

1. The code is a release tag the owner confirmed, cloned fresh, and the
   images are rebuilt (`up -d --build`), not copied from the old server.
2. Every secret and the certificate are new (5.3 to 5.6).
3. The backup is from before the first sign of intrusion. `restore.sh`
   checks its checksums, but checksums kept on the same server only catch
   damage, not deliberate changes.
4. After restoring, read the admin log and the involved tickets' histories
   for changes nobody can explain.
5. Run the checks in [deployment.md section 7](deployment.md#7-post-install-checklist).
6. For two weeks, watch the proxy log and Entra's sign-in logs for the
   addresses and accounts involved.

## 8. Telling people

| Who | When |
|---|---|
| Incident lead, owner | Always, at once |
| Compliance lead | Level 1 or 2, or whenever ticket content reached someone it shouldn't |
| Management | Level 1, or as the compliance lead advises |
| People whose tickets were exposed | As the compliance lead and management decide |
| All staff | When the help desk is closed for long, or they must act (for example change a password) |

> **To fill in:** whether anyone outside the company must be told
> (regulators, customers, data-protection authorities), by when, and who
> decides. Legal and the compliance lead would know. It isn't in the
> repository: ask, don't guess.

## 9. Afterwards

Within two weeks of closing a level 1 or 2 incident (level 3 if useful), the
incident lead writes a short, blame-free review:

```text
Incident:       title, level, dates opened and closed
What happened:  two or three sentences
Timeline:       times from the notes: found, contained, fixed, closed
Cause:          what let it happen
Impact:         what data, how many tickets or people, who was told
What changed:   fixes shipped (versions), settings, Entra or Exchange changes
Still to do:    each item, who, by when
```

> **To fill in:** where reviews are filed and who keeps them. The compliance
> lead would know.

Then add new threats or residual risks to [threat-model.md](threat-model.md),
app fixes to [backlog.md](backlog.md), fix this document where it was wrong
or slow, and take `KEEP_DAYS=0` off the backup line (section 4).

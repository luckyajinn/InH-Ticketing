# Deploying to the internal server

How to install InH-Ticketing on the server at `https://helpdesk.mckennalabs.com`,
keep it backed up, update it, and get it back if something goes wrong. What
the server itself needs is in [server-requirements.md](server-requirements.md).

> **Status: in use.** First written for v0.6.0 and installed on the internal
> server on 2026-11-09. Before that, the same Docker setup ran on a Debian 13
> test VM for a load test (the `stress-test` branch: fake data, a self-signed
> certificate, no Microsoft 365, no email). Please fix this guide wherever it
> doesn't match what you see.

What has been checked, and what hasn't:

| Part | Checked | Not yet tested |
|---|---|---|
| Django production settings | `manage.py check --deploy` is clean; automated tests for the HTTPS redirect, HSTS and `/healthz`; served behind Caddy on the test VM | |
| `compose.prod.yaml` | The image build and `docker compose` on Linux (test VM): web, worker, database and proxy, under load | Port 80's redirect (the test VM published HTTPS only) |
| `deploy/caddy/Caddyfile` | Run by Caddy 2.11.9 on the test VM, serving HTTPS | The internal-CA certificate (the test used a self-signed one) |
| `scripts/backup.sh`, `restore.sh` | Syntax-checked with `sh -n` and `dash`; run against a stand-in for `docker` | Real Docker and PostgreSQL; cron (not run on the test VM) |
| Certificate commands (section 3) | Run end to end with a throwaway test CA | The internal CA's own process and files |
| Firewall, chrony, Entra and email from the server | | All of it |

## Contents

1. [Prepare the server](#1-prepare-the-server)
2. [Get the code](#2-get-the-code)
3. [Get the certificate](#3-get-the-certificate)
4. [Microsoft Entra](#4-microsoft-entra)
5. [The production .env](#5-the-production-env)
6. [First start](#6-first-start)
7. [Post-install checklist](#7-post-install-checklist)
8. [Backups](#8-backups)
9. [Restore drill](#9-restore-drill)
10. [Updating and rolling back](#10-updating-and-rolling-back)
11. [Routine checks](#11-routine-checks)
12. [Troubleshooting](#12-troubleshooting)

## How it fits together

| Container | What it does | Who can reach it |
|---|---|---|
| `proxy` | Caddy: HTTPS on port 443 with the internal-CA certificate; port 80 redirects to HTTPS | The LAN and VPN |
| `web` | The Django app (gunicorn). Applies database migrations when it starts | The proxy only |
| `worker` | Sends queued emails and reads the help-desk mailbox | Nobody (it only calls out) |
| `db` | PostgreSQL 17 | `web` and `worker` |

The data lives in two Docker volumes, `inh-ticketing_pgdata` (the database)
and `inh-ticketing_media` (attachments). On the server:

```
/srv/inh-ticketing/
├── app/       the code (a git checkout), and its .env
├── certs/     fullchain.pem, privkey.pem, internal-root.pem
└── backups/   one folder per backup, and backup.log
```

You'll need: the server built as in [server-requirements.md](server-requirements.md),
with a sudo account (this guide calls it `inhadmin`); an admin of the GitHub
repository; an Entra admin; whoever issues certificates from the internal CA;
and a company PC to test from.

---

## 1. Prepare the server

Sign in over SSH as `inhadmin`.

### 1.1 Updates, time zone and folders

```bash
sudo apt update && sudo apt full-upgrade -y
sudo timedatectl set-timezone America/Los_Angeles   # backup names and logs use local time

sudo mkdir -p /srv/inh-ticketing/app /srv/inh-ticketing/backups /srv/inh-ticketing/certs
sudo chown inhadmin:inhadmin /srv/inh-ticketing/app /srv/inh-ticketing/backups
sudo chmod 700 /srv/inh-ticketing/backups   # backups hold every ticket
sudo chmod 750 /srv/inh-ticketing/certs     # owned by root
```

### 1.2 Time sync

Microsoft sign-in fails if the clock is more than two minutes out.

```bash
sudo apt install -y chrony
# Use the company's time servers (ask IT which: often the domain controllers).
echo "server <time server> iburst" | sudo tee /etc/chrony/sources.d/mckennalabs.sources
sudo systemctl restart chrony
chronyc sources     # the company server, marked ^*
timedatectl         # "System clock synchronized: yes"
```

### 1.3 Automatic security updates

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades   # answer Yes
```

This installs Ubuntu's security updates daily. It doesn't reboot: some updates
(the kernel) need one. Either reboot monthly by hand, or allow automatic
reboots after the 02:30 backup by setting these in
`/etc/apt/apt.conf.d/50unattended-upgrades`:

```
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";
```

The app comes back by itself after a reboot (checked in section 7). Docker
itself comes from Docker's repository, which these updates don't cover:
update it monthly with `sudo apt update && sudo apt upgrade` (this restarts the
containers for a moment).

### 1.4 Firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
# SSH from IT admins only. Add this BEFORE enabling, from the address you're on, or you'll lock yourself out.
sudo ufw allow from <admin subnet, e.g. 10.10.5.0/24> to any port 22 proto tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

> **ufw doesn't limit Docker's ports.** Docker publishes 80 and 443 with its
> own firewall rules, which take effect before ufw's. The two `allow` lines
> only record the intent. Limit 80 and 443 to the LAN and VPN ranges on the
> network firewall in front of the server. (Filtering them on the server
> itself means rules in Docker's `DOCKER-USER` chain; not covered here.)

### 1.5 Docker Engine and Compose

From Docker's own repository (check
[docs.docker.com/engine/install/ubuntu](https://docs.docker.com/engine/install/ubuntu/)
in case the steps have changed; on Debian, use `debian` in place of `ubuntu` in both URLs):

```bash
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker inhadmin
exit    # then sign in again, so the group applies
```

Check:

```bash
docker compose version     # must be 2.24 or later
docker run --rm hello-world
systemctl is-enabled docker   # "enabled": Docker, and so the app, starts at boot
```

## 2. Get the code

The repository is private. The server gets a **read-only deploy key**: it can
fetch this one repository and nothing else.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/inh_ticketing_deploy -C "inh-ticketing deploy key ($(hostname))"
cat ~/.ssh/inh_ticketing_deploy.pub
```

A passphrase is optional: you'd type it at each update. Then, as a
repository admin on GitHub: **InH-Ticketing → Settings → Deploy keys → Add
deploy key**. Title `helpdesk server`, paste the `.pub` line, leave **Allow
write access** unticked, **Add key**.

Tell SSH to use that key for GitHub:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
    IdentityFile ~/.ssh/inh_ticketing_deploy
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
ssh -T git@github.com
```

The first time, SSH shows GitHub's key fingerprint: compare it with
[GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)
before typing `yes`. The reply should name the repository and say *You've
successfully authenticated*. If outbound port 22 is blocked, add
`Hostname ssh.github.com` and `Port 443` under `Host github.com`.

Clone, and check out the release you're installing:

```bash
git clone git@github.com:luckyajinn/InH-Ticketing.git /srv/inh-ticketing/app
cd /srv/inh-ticketing/app
git tag --list           # the releases
git checkout v0.6.0      # or the newest release; "detached HEAD" is expected
file scripts/backup.sh   # "POSIX shell script ... executable", and no "CRLF"
```

Always run a release tag on the server, never a branch.

## 3. Get the certificate

### 3.1 Create the key and the request

On the server, so the private key never leaves it:

```bash
cd ~
umask 077
openssl req -new -newkey rsa:2048 -noenc \
  -keyout privkey.pem -out helpdesk.csr \
  -subj "/CN=helpdesk.mckennalabs.com/O=McKenna Labs" \
  -addext "subjectAltName=DNS:helpdesk.mckennalabs.com"
openssl req -in helpdesk.csr -noout -text | grep -A1 "Subject Alternative Name"
# DNS:helpdesk.mckennalabs.com
```

Send `helpdesk.csr` (it isn't secret) to whoever runs the internal CA (for
AD CS, usually the *Web Server* template). Ask for:

- the server certificate, in PEM ("Base-64") format;
- the intermediate (issuing) CA certificate(s);
- the root CA certificate, to test with (company PCs already trust it). Save
  it as `internal-root.pem`, in PEM format like the others.

### 3.2 Put the files together

If the certificate isn't text starting `-----BEGIN CERTIFICATE-----`, convert it.
If the chain came as a `.p7b`, take the certificates out of it:

```bash
openssl x509 -inform der -in helpdesk.cer -out helpdesk.pem
openssl pkcs7 -inform der -print_certs -in chain.p7b -out chain.pem   # leave out -inform der if the .p7b is text
```

Build the full chain: the **server certificate first**, then the
intermediate(s). Leave the root out.

```bash
cat helpdesk.pem intermediate.pem > fullchain.pem
```

Check it before installing it:

```bash
# The name, who issued it, and when it expires: note the date.
openssl x509 -in fullchain.pem -noout -subject -issuer -enddate -ext subjectAltName
# The key matches the certificate: these two lines must be identical.
openssl x509 -in fullchain.pem -noout -pubkey | openssl sha256
openssl pkey -in privkey.pem -pubout | openssl sha256
# The order: the first subject is helpdesk.mckennalabs.com, and each issuer is the next subject.
openssl crl2pkcs7 -nocrl -certfile fullchain.pem | openssl pkcs7 -print_certs -noout
# The chain leads to the company root: "fullchain.pem: OK".
openssl verify -CAfile internal-root.pem -untrusted fullchain.pem fullchain.pem
```

### 3.3 Install it

```bash
sudo install -o root -g root -m 644 fullchain.pem     /srv/inh-ticketing/certs/fullchain.pem
sudo install -o root -g root -m 600 privkey.pem       /srv/inh-ticketing/certs/privkey.pem
sudo install -o root -g root -m 644 internal-root.pem /srv/inh-ticketing/certs/internal-root.pem
rm ~/privkey.pem ~/helpdesk.csr
```

`internal-root.pem` isn't used by the app; it lets you test with `curl` from
the server (section 7). The private key isn't in the backups: if the server
is lost, a new server gets a new certificate.

**Put the expiry date in the calendar now**, with a reminder 30 days before
and a named owner. Because of HSTS, browsers won't let anyone past an expired
certificate.

### 3.4 Renewing

Repeat 3.1 to 3.3 with a new key and request, then:

```bash
cd /srv/inh-ticketing/app
docker compose -f compose.yaml -f compose.prod.yaml restart proxy
```

Check in a browser that the new expiry date shows, and update the calendar.

## 4. Microsoft Entra

The server uses the same app registration as the pilot
([entra-setup.md](entra-setup.md)), with its own address and its own secret.
An Entra admin:

1. **Entra ID → App registrations → InH-Ticketing → Authentication.** Under
   **Web → Redirect URIs**, add `https://helpdesk.mckennalabs.com/auth/callback`
   exactly (https, no trailing slash). Keep the `localhost` one for PCs. **Save**.
2. **Certificates & secrets → New client secret.** Description `helpdesk
   server`, expiry 12 months. Copy the **Value** straight into the server's
   `.env` (section 5) and nowhere else. A separate secret per machine means
   one can be revoked without breaking the other.
3. **Put the secret's expiry in the calendar**, with a reminder a few weeks
   before. An expired secret stops all sign-in and email (`AADSTS7000222`).
4. **Enterprise applications → InH-Ticketing → Users and groups:** check
   who is assigned which role. At go-live, assign the all-staff group as
   *Requester*, and IT as *Agent* or *Admin*.

The Exchange permissions for the mailbox ([email-setup.md](email-setup.md),
3c and 4b) belong to the app registration, not to a secret, so they already
cover the server.

## 5. The production .env

All settings live in `/srv/inh-ticketing/app/.env`, readable by `inhadmin`
only. This creates it with fresh random secrets (they're written to the file
and never shown):

```bash
cd /srv/inh-ticketing/app
umask 077
cat > .env <<EOF
# InH-Ticketing production settings. Owner-only (chmod 600). Never commit or email this file.
# What each setting means: .env.example, and docs/deployment.md section 5.

# Docker Compose: always use both files; the name the proxy serves.
COMPOSE_FILE=compose.yaml:compose.prod.yaml
HELPDESK_HOSTNAME=helpdesk.mckennalabs.com

DJANGO_DEBUG=False
DJANGO_SECRET_KEY=$(openssl rand -hex 32)
DJANGO_ALLOWED_HOSTS=helpdesk.mckennalabs.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://helpdesk.mckennalabs.com
TIME_ZONE=America/Los_Angeles

# Hex only, so it is safe inside the database URL. Used when the database is first created.
POSTGRES_PASSWORD=$(openssl rand -hex 24)

ENTRA_TENANT_ID=
ENTRA_CLIENT_ID=
ENTRA_CLIENT_SECRET=
ENTRA_REDIRECT_URI=https://helpdesk.mckennalabs.com/auth/callback
ENTRA_ROLE_AGENT=Agent
ENTRA_ROLE_ADMIN=Admin

EMAIL_BACKEND=graph
SITE_URL=https://helpdesk.mckennalabs.com
# The TEST shared mailbox until the pilot ends (docs/email-setup.md).
HELPDESK_MAILBOX=helpdesk-test@mckennalabs.com
IT_NOTIFY_EMAIL=
# Shown under "Can't sign in?" and on error pages. Keep the quotes if it has a #.
HELP_CONTACT="Call IT on ext. 1234, or post in IT Help in Teams."
INBOUND_EMAIL=graph
INBOUND_ALLOWED_DOMAINS=mckennalabs.com
EOF
chmod 600 .env
nano .env       # fill in the three ENTRA_ values, HELP_CONTACT, and IT_NOTIFY_EMAIL if wanted
ls -l .env      # -rw------- 1 inhadmin inhadmin ...
```

| Setting | Value on the server | Why |
|---|---|---|
| `COMPOSE_FILE` | `compose.yaml:compose.prod.yaml` | A `docker compose` command typed without `-f` still uses both files |
| `HELPDESK_HOSTNAME` | `helpdesk.mckennalabs.com` | The name the proxy serves and redirects to |
| `DJANGO_DEBUG` | `False` | Turns on the HTTPS hardening: secure cookies, redirect, HSTS |
| `DJANGO_SECRET_KEY` | 64 random hex characters | Signs sessions. New for the server; never copy a PC's |
| `DJANGO_ALLOWED_HOSTS` | `helpdesk.mckennalabs.com` | Other names get "400 Bad Request". (`127.0.0.1` is added automatically, for Docker's health check) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://helpdesk.mckennalabs.com` | Forms must come from this address |
| `POSTGRES_PASSWORD` | 48 random hex characters | Letters and digits only, so it's safe in `DATABASE_URL` |
| `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID` | From the app registration's Overview | Same as on a PC |
| `ENTRA_CLIENT_SECRET` | The server's own secret (section 4) | |
| `ENTRA_REDIRECT_URI` | `https://helpdesk.mckennalabs.com/auth/callback` | Must match Entra exactly |
| `EMAIL_BACKEND` | `graph` | Really send email |
| `SITE_URL` | `https://helpdesk.mckennalabs.com` | Links in emails |
| `HELPDESK_MAILBOX` | The test shared mailbox during the pilot | |
| `HELP_CONTACT` | How to reach IT, e.g. `"Call IT on ext. 1234, or post in IT Help in Teams."` | Shown under "Can't sign in?" and on error pages. Blank shows "Email IT at" the mailbox above, which is the test mailbox during the pilot. Quote it if it contains `#`, or everything after the `#` is dropped |
| `REPORTS_FROM` | The go-live date, e.g. `2026-11-30` (blank until then) | Reports (`/reports/`, admins only) count tickets from this date, so pilot and test tickets don't skew them. Tickets whose subject starts with "Pilot:" are always left out |
| `INBOUND_EMAIL` | `graph` | Read the mailbox |

Things to know:

- **Only one copy of the app may read the mailbox.** Once the server reads
  it, set `INBOUND_EMAIL=off` on every PC that has it on, or emails will be
  split between two databases.
- **`POSTGRES_PASSWORD` is only used when the database is first created.**
  Changing it in `.env` later doesn't change the database's password: the
  app then can't connect (see section 12).
- Keep a copy of the `.env` values in IT's password vault. `.env` isn't in the backups.

The HTTPS settings (`DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_SECURE_HSTS_SECONDS`)
are left out on purpose: their defaults are right. See `.env.example`.

## 6. First start

From `/srv/inh-ticketing/app`:

**6.1 Check the configuration.** This reads `.env` and both Compose files:

```bash
docker compose -f compose.yaml -f compose.prod.yaml config --quiet && echo "Compose config OK"
```

**6.2 Check the proxy's configuration and the certificate files.** This
loads the Caddyfile and the certificate without starting anything *(untested;
it should catch a wrong path or a key that doesn't match)*:

```bash
docker compose -f compose.yaml -f compose.prod.yaml run --rm --no-deps proxy caddy validate --config /etc/caddy/Caddyfile
# ... "Valid configuration"
```

**6.3 Build and start everything:**

```bash
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

The first build takes a few minutes: it downloads the base images and installs
the Python packages. Then:

```bash
docker compose -f compose.yaml -f compose.prod.yaml ps
docker compose -f compose.yaml -f compose.prod.yaml logs --tail 50 web proxy
```

Within a minute `web` should show `(healthy)`: it applies the database
migrations, then starts gunicorn. `db` is `(healthy)`; `worker` and `proxy`
are `Up`. In the PORTS column, only `proxy` has `0.0.0.0:80->80/tcp` and
`0.0.0.0:443->443/tcp`; `web` shows just `8000/tcp`.

## 7. Post-install checklist

Work through this before anyone else uses the server. Keep the results with
the go-live records.

| # | Check | How | Expected |
|---|---|---|---|
| 1 | Containers running | `docker compose -f compose.yaml -f compose.prod.yaml ps` | `db` and `web` healthy, `worker` and `proxy` up |
| 2 | Port 8000 not reachable | `ss -tln \| grep 8000` | Nothing |
| 3 | HTTPS and health check, from the server | `curl -sS --cacert /srv/inh-ticketing/certs/internal-root.pem https://helpdesk.mckennalabs.com/healthz` | `ok` |
| 4 | HTTP redirects to HTTPS | `curl -sSI http://helpdesk.mckennalabs.com/queue/` | `301`, `Location: https://helpdesk.mckennalabs.com/queue/` |
| 5 | One HSTS header | `curl -sSI --cacert /srv/inh-ticketing/certs/internal-root.pem https://helpdesk.mckennalabs.com/healthz \| grep -i strict` | One line: `max-age=31536000; includeSubDomains` |
| 6 | **No browser warning on a company PC** | Open `https://helpdesk.mckennalabs.com` in Edge | A padlock; certificate issued by the internal CA |
| 7 | Sign-in works | **Sign in with Microsoft 365** | Back in the app, your name in the header |
| 8 | **The Admin role shows** | Sign in as someone with the Admin role | **Admin** badge; `/admin/` opens |
| 9 | Agents see the queue | Sign in with the Agent role | The IT queue |
| 10 | Attachments, up to the limit | Submit a ticket, then a reply with 5 files of about 9 MB each | All upload; each downloads again |
| 11 | Worker running | `docker compose -f compose.yaml -f compose.prod.yaml logs --tail 20 worker` | `Email backend: notifications.backends.GraphEmailBackend` and `Email-in: reading helpdesk-test@… every 60s` |
| 12 | **A test email out** | Submit a ticket for yourself | The receipt arrives; the worker logs `Emails: 1 sent` |
| 13 | A test email in | Email the help-desk mailbox from your account | A new ticket within a minute |
| 14 | A backup | `/srv/inh-ticketing/app/scripts/backup.sh first-install` | Ends with `Backup OK` (section 8) |
| 15 | Nightly backup scheduled | `crontab -l` | The line from section 8 |
| 16 | **Restore drill done and recorded** | Section 9 | Required before go-live |
| 17 | Survives a reboot | `sudo reboot`, wait 2 minutes, repeat checks 1, 3 and 7 | Everything back by itself |
| 18 | Expiry dates in the calendar | The certificate (3.3) and the client secret (4) | Both, with owners |
| 19 | PCs no longer read the mailbox | Section 5 | `INBOUND_EMAIL=off` on PCs |

If the server can't resolve its own name for checks 3–5, add
`--resolve helpdesk.mckennalabs.com:443:127.0.0.1` (or `:80:` for check 4).

## 8. Backups

Every night at 02:30, `scripts/backup.sh` saves the database and the
attachments into a new folder in `/srv/inh-ticketing/backups`, checks both
can be read back, and deletes backups older than 14 days. Run it by hand too,
before every update.

### Why a host cron job, not a backup container

| | Host cron job (chosen) | Backup container in compose.prod.yaml |
|---|---|---|
| Scheduling | cron: reliable, follows the server's time zone and daylight saving | A hand-written sleep loop in a container |
| Nightly and by-hand backups | The same script, `scripts/backup.sh` | Different ways to run it |
| Restoring | `restore.sh` runs on the host the same way, and reuses `backup.sh` for its safety backup | Restore is on the host anyway |
| pg_dump version | Always matches: it runs inside the `db` container | Matches only while both use the same image |
| Extra container | None | One more, running all the time |
| Downside | One crontab line outside the repository (below) | |

### Set it up

```bash
crontab -e
```

Add this line, then save:

```
30 2 * * * /srv/inh-ticketing/app/scripts/backup.sh >> /srv/inh-ticketing/backups/backup.log 2>&1
```

Try it straight away:

```bash
/srv/inh-ticketing/app/scripts/backup.sh first-install
ls -l /srv/inh-ticketing/backups/
```

Each backup is a folder such as `2026-11-06_023000` (or `2026-11-06_141500_first-install`) with:

| File | What it is |
|---|---|
| `db.dump` | The database (`pg_dump` custom format) |
| `media/` | Every uploaded attachment, as an incremental snapshot: unchanged files are shared (hard-linked) with the previous backup, so they take no extra space |
| `manifest.txt` | When, the app version, the PostgreSQL version, sizes, the latest migrations |
| `SHA256SUMS` | Checksums, checked by `restore.sh` |

Not in the backups: `.env` (keep its values in IT's password vault), the
certificate key (get a new certificate), and the Docker images (rebuilt from
git). An unfinished backup is called `….partial` and is removed.

### Check it's working

`backup.log` gets a `Backup OK` line every night. Look at it weekly:

```bash
tail -n 20 /srv/inh-ticketing/backups/backup.log
```

`BACKUP FAILED` lines say what went wrong. A `WARNING: the disk … is 80%
full` line means it's time to act: see [server-requirements.md](server-requirements.md#hardware).

### Later improvement: a copy off the server

The backups are on the same server as the data, so they don't protect
against losing the VM or its disk. Copying the backups folder somewhere else
every night (a file server, or cloud storage) is the recommended next step.

## 9. Restore drill

The risk assessment requires **one tested restore before go-live**. Do it on
the production server *before* it holds real data: that tests the real
server, and nothing is lost.

1. Create two test tickets, one with an attachment. Note their numbers.
2. Back up: `/srv/inh-ticketing/app/scripts/backup.sh drill`
3. Create a third test ticket, and delete or change something in the first two.
4. Restore the drill backup. The script lists the backups, checks the
   checksums, shows what's in the backup and asks you to type its name:
   ```bash
   cd /srv/inh-ticketing/app
   ./scripts/restore.sh                       # lists the backups
   ./scripts/restore.sh 2026-11-06_141500_drill
   ```
5. Start the app again: `docker compose -f compose.yaml -f compose.prod.yaml up -d`
6. Check: the first two tickets are back as they were, the attachment
   downloads, the third ticket is gone, sign-in works, the worker is running.
7. Fill in the record below and file it with the system's validation records.

After go-live, repeat the drill yearly or after big changes, **on a separate
test VM, never the live server**: a restore replaces everything since the
backup. On a test VM, set `EMAIL_BACKEND=file` and `INBOUND_EMAIL=off` in its
`.env` before starting it, or it will email real people and read the real mailbox.

Things to know about restoring:

- Emails that were waiting to be sent when the backup was made, and went out
  afterwards, are sent again.
- Emails that arrived after the backup was made were moved to the mailbox's
  *Processed by InH-Ticketing* folder. To get them in again, move them back
  to the Inbox and mark them unread; the worker picks them up *(untested)*.

### Restore test record

```
InH-Ticketing restore test

Date and time:
Done by:                               Reviewed by:
Server:
Backup restored (folder name):
Backup made at:                        App version (backup / code):
Restored:   [ ] database   [ ] attachments
Time taken (start of restore to app back up):

Checks
[ ] restore.sh reported the checksums OK
[ ] tickets from before the backup are present:        #
[ ] their attachments open:                            #
[ ] tickets made after the backup are gone:            #
[ ] sign-in works, roles are right
[ ] worker running; a test email was sent

Problems found, and what was done:

Result:  PASS / FAIL
Signature:
```

## 10. Updating and rolling back

### Updating to a new version

Read the release notes first (`docs/releases/vX.Y.Z.md` in the new version):
they say if there are new `.env` settings or anything else to do.

```bash
cd /srv/inh-ticketing/app
./scripts/backup.sh before-v0.7.0          # always, before updating
git describe --tags                        # note the current version
git fetch --tags
git diff --stat HEAD v0.7.0 -- '*/migrations/*' deploy/   # database changes? proxy changes?
git checkout v0.7.0
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
docker compose -f compose.yaml -f compose.prod.yaml ps
```

`up -d --build` rebuilds the app and replaces `web` and `worker`; `web`
applies any new migrations as it starts. Expect a minute or two of
downtime. If the diff showed changes under `deploy/`, also
`docker compose -f compose.yaml -f compose.prod.yaml restart proxy`. Then
repeat checks 1, 3, 7 and 11 from section 7.

Now and then, clear out old images: `docker image prune -f`.

### Rolling back

- **No database changes in the new version** (the `git diff` above listed no
  migrations): check out the old version and rebuild.
  ```bash
  git checkout v0.6.0
  docker compose -f compose.yaml -f compose.prod.yaml up -d --build
  ```
- **The new version changed the database:** the old code may not work with
  the new database, and not every migration can be undone. Restore the
  backup taken just before the update, with the old code checked out first:
  ```bash
  git checkout v0.6.0
  ./scripts/restore.sh <the before-v0.7.0 backup>
  docker compose -f compose.yaml -f compose.prod.yaml up -d --build
  ```
  Everything done in the app since the update is lost: tell people. See the
  notes at the end of section 9 about emails. Always finish with `up -d
  --build` as above: plain `up -d` would start the new version's images on
  the restored database, and they would re-apply the new migrations.
- **From v0.8.4 back to v0.8.3:** v0.8.4's only migration, `tickets` 0006,
  rewords a help text and changes nothing in the database. Check out
  `v0.8.3` and rebuild, as for no database changes; no restore needed.
- **From v0.7.0 or later back to v0.6.0, keeping the tickets made since:**
  v0.7.0 and v0.8.0 add migrations `tickets` 0004 (the password audit trail)
  and 0005 (common requests and the Mechanics and Cleaning & sanitization
  categories). Undo them *before* checking out the old version, then rebuild:
  ```bash
  ./scripts/backup.sh before-rollback
  docker compose -f compose.yaml -f compose.prod.yaml exec web python manage.py migrate tickets 0003
  git checkout v0.6.0
  docker compose -f compose.yaml -f compose.prod.yaml up -d --build
  ```
  This drops the password audit trail and the common requests. Tickets in
  the Mechanics or Cleaning & sanitization categories keep their category.

## 11. Routine checks

Monthly, about ten minutes:

| Check | How |
|---|---|
| Backups ran every night | `tail -n 40 /srv/inh-ticketing/backups/backup.log`: a `Backup OK` per night |
| Disk space | `df -h /`; `docker system df` |
| Certificate expiry | `openssl x509 -in /srv/inh-ticketing/certs/fullchain.pem -noout -enddate` |
| Client secret expiry | Entra → App registrations → InH-Ticketing → Certificates & secrets |
| Updates | `sudo apt update && sudo apt upgrade`; reboot if `/var/run/reboot-required` exists |
| Caddy | A newer 2.x patch release? Change the tag in `compose.prod.yaml` through a normal release |

## 12. Troubleshooting

Logs: `docker compose -f compose.yaml -f compose.prod.yaml logs --tail 100 <service>`
(`proxy`, `web`, `worker` or `db`).

| Symptom | Likely cause | Fix |
|---|---|---|
| Certificate warning on a company PC | The PC doesn't trust the internal root; the name isn't in the certificate's SAN; or the intermediate is missing from `fullchain.pem` | Re-run the checks in 3.2. The root reaches PCs through Group Policy or Intune |
| Browser can't connect at all | DNS, the network firewall, or `proxy` isn't running | `nslookup helpdesk.mckennalabs.com`; `docker compose … ps` |
| `proxy` keeps restarting | A certificate file is missing or unreadable, the key doesn't match, or the Caddyfile has an error | `docker compose … logs proxy`; repeat step 6.2 |
| `502 Bad Gateway` | `web` is down or still starting | `docker compose … ps`; `logs web` |
| `400 Bad Request` | Opened by IP address or a short name | Use `https://helpdesk.mckennalabs.com`. Other names need adding to `DJANGO_ALLOWED_HOSTS` |
| Too many redirects | Something in front of the proxy, or `X-Forwarded-Proto` doesn't reach Django | The proxy must be the only thing in front. Check `proxy` logs |
| `403 CSRF verification failed` | `DJANGO_CSRF_TRUSTED_ORIGINS` doesn't match the address used | Must be `https://helpdesk.mckennalabs.com` exactly |
| `AADSTS50011` at sign-in | The server's redirect URI isn't on the app registration | Section 4, step 1 |
| `AADSTS7000215` or `AADSTS7000222` | Wrong or expired client secret | New secret (section 4), update `.env`, `docker compose … up -d` |
| Sign-in fails with "not yet valid" or "expired" | The server clock is off | `chronyc tracking`, section 1.2 |
| `413` when uploading | Over the 60 MB request limit | Fewer or smaller files per reply (10 MB each, 5 at most) |
| `web` shows `(unhealthy)` | The health check can't reach the app | `docker inspect --format '{{json .State.Health}}' inh-ticketing-web-1`; `logs web` |
| `password authentication failed for user "inh"` | `POSTGRES_PASSWORD` was changed after the database was created | Put the old value back, or set the new one in the database: `docker compose … exec db psql -U inh -d inh -c "ALTER USER inh PASSWORD '<new value>'"` |
| Emails not sent | See the worker log | [email-setup.md](email-setup.md), *Troubleshooting* |
| Emails missing, or turning up in the wrong place | A PC also reads the mailbox | `INBOUND_EMAIL=off` on every PC |
| `unknown tag !reset`, or web still on port 8000 | Docker Compose older than 2.24 | Update Docker (section 1.5) |
| A script fails with `set: Illegal option -` or `$'\r'` | Windows line endings (files copied from a PC instead of cloned) | Clone with git on the server (`.gitattributes` keeps LF), or `sed -i 's/\r$//' scripts/*.sh` |
| `backup.sh: Permission denied` | The execute bit was lost | `sh /srv/inh-ticketing/app/scripts/backup.sh`, or `chmod +x scripts/*.sh` |
| No new backups | cron, or the script failed | `crontab -l`; `tail /srv/inh-ticketing/backups/backup.log`; `grep CRON /var/log/syslog` |
| `BACKUP FAILED: the database isn't running` | The app was stopped | `docker compose … up -d` |
| Disk filling up | Backups, old images | `du -sh /srv/inh-ticketing/backups`; `docker image prune -f`; [server-requirements.md](server-requirements.md#hardware) |

`docker compose …` above is short for `docker compose -f compose.yaml -f compose.prod.yaml`,
run in `/srv/inh-ticketing/app`.

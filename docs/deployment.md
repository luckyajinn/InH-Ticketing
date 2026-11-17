# Deploying to the internal server

How to install InH-Ticketing on the server at `https://helpdesk.example.com`,
keep it backed up, update it, and get it back if something goes wrong. What
the server itself needs is in [server-requirements.md](server-requirements.md).

> **Status: in use.** First written for v0.6.0 and installed on the internal
> server on 2026-11-09. Reinstalled from scratch on 2026-11-17 (the data
> from before is gone): it runs **v0.10.7**, cloned from the company's own copy.
> Before that, the same Docker setup ran on a Debian 13 test VM for a load
> test (the `stress-test` branch: fake data, a self-signed certificate, no
> Microsoft 365, no email). Please fix this guide wherever it doesn't match
> what you see.

What has been checked, and what hasn't:

| Part | Checked | Not yet tested |
|---|---|---|
| Django production settings | `manage.py check --deploy` is clean; automated tests for the HTTPS redirect, HSTS and `/healthz`; served behind Caddy on the test VM | |
| `compose.prod.yaml` | The image build and `docker compose` on Linux (test VM): web, worker, database and proxy, under load. Port 80's redirect to HTTPS, on the first install (2026-11-09; history) | |
| `deploy/caddy/Caddyfile` | Run by Caddy 2.11.9 on the test VM, serving HTTPS | The internal-CA certificate (the test used a self-signed one). **To fill in:** the date the real certificate went on (item 2 below) |
| `scripts/backup.sh`, `restore.sh` | Syntax-checked with `sh -n` and `dash`; run against a stand-in for `docker` | Real Docker and PostgreSQL; cron (not run on the test VM). **To fill in:** the date of the server's first `Backup OK` (item 5) |
| Certificate commands (section 3) | Run end to end with a throwaway test CA | The internal CA's own process and files |
| Firewall, chrony and Entra sign-in on the server | On the first install (2026-11-09; history), on Debian 13: ufw, chrony's internet time, and Microsoft 365 sign-in through the proxy | Sign-in after the 2026-11-17 reinstall (item 3) |
| Email from the server | | **To fill in:** the date email out (checks 11–12) and email in (check 13) were tested on the server (item 6) |

Rows that say "first install" are history: that install's data is gone, and
the checks must be repeated. The reinstall's own results are in the label
under [section 7](#7-post-install-checklist)'s checklist, and in the go-live
records.

## Still to fill in or add

*Keeping this guide current:* whenever a release or a decision means
something has to change on the server (a line in `.env`, the crontab, DNS,
the certificate, Entra, the deploy key), this guide is changed in the same
commit, and the change gets a label where it goes:

- **To fill in:** the guide has the place for it, but the server's value,
  date or result isn't known yet. The label says what to fill in, and with what.
- **To add:** something the guide doesn't cover yet. The label says what's
  missing, and what it will be.

Each label is also a row below. When it's done on the server, tell whoever
maintains the app (or edit this guide): the label and its row are removed,
and anything worth keeping (a date, a result) stays in the section.

Open on the server as of 2026-11-17:

| # | Section | Label | What, and with what | When |
|---|---|---|---|---|
| 1 | [1.6](#16-the-network-dns-and-wi-fi) | To fill in | The help desk's A record in the internal DNS, and a DHCP reservation for the server's address. Then remove any hosts-file entry for the help-desk name from the PCs used to test | Before go-live |
| 2 | [3](#3-get-the-certificate) | To fill in | The real certificate in place of the temporary one (3.5), which expires **2026-12-17**: which CA issues it, its expiry date, and who owns the renewal | Before 2026-12-17 |
| 3 | [4](#4-microsoft-entra) | To fill in | Sign-in fails with `AADSTS7000215` after the reinstall (2026-11-17): put the new client secret's **Value** in `.env`, check it with [the secret check](#checking-the-client-secret-without-showing-it), and delete the old server's secret in Entra | Now |
| 4 | [5.1](#51-still-to-fill-in-on-the-server) | To fill in | The `.env` values not set yet, listed in 5.1 with what goes in each | As listed there |
| 5 | [8](#8-backups) | To fill in | The nightly backup line in the crontab (`crontab -l` shows none yet), and the first `Backup OK`. The copy off the server is still undecided (2026-11-11) | Before go-live |
| 6 | [7](#7-post-install-checklist) | To fill in | The checks still open, listed under the checklist. Each one's date and result go in the go-live records | Before go-live |
| 7 | [6.2](#6-first-start) | To fill in | Run the proxy's configuration check (6.2) once on the server, and record the result | Before go-live |

## Contents

- [Still to fill in or add](#still-to-fill-in-or-add)

1. [Prepare the server](#1-prepare-the-server)
2. [Get the code](#2-get-the-code)
3. [Get the certificate](#3-get-the-certificate)
4. [Microsoft Entra](#4-microsoft-entra)
5. [The production .env](#5-the-production-env)
6. [First start](#6-first-start)
7. [Post-install checklist](#7-post-install-checklist)
8. [Backups](#8-backups)
9. [Restoring a backup](#9-restoring-a-backup)
10. [Updating and rolling back](#10-updating-and-rolling-back)
11. [Routine checks](#11-routine-checks)
12. [Troubleshooting](#12-troubleshooting)

## How it fits together

| Container | What it does | Who can reach it |
|---|---|---|
| `proxy` | Caddy: HTTPS on port 443 with the internal-CA certificate; port 80 redirects to HTTPS | The LAN and VPN |
| `web` | The Django app (gunicorn). Applies database migrations when it starts | The proxy only |
| `worker` | Sends queued emails, reads the help-desk mailbox and closes resolved tickets. Records a heartbeat each round, which its health check and Reports read | Nobody (it only calls out) |
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

Microsoft sign-in fails if the clock is more than two minutes out. The server
isn't joined to the domain, so it only needs the correct time, not the domain
controllers' time. Chrony's default internet time servers are the most
accurate source; domain controllers are sometimes a minute or more out.

```bash
sudo apt install -y chrony        # replaces systemd-timesyncd
sleep 20; chronyc sources         # one source marked ^*
timedatectl | grep -i synchronized   # "System clock synchronized: yes"
```

If every source shows `^?`, the network blocks internet time (UDP port 123).
Use the company's time servers instead (often the domain controllers):

```bash
echo "server <time server> iburst" | sudo tee /etc/chrony/sources.d/company.sources
sudo chronyc reload sources
```

### 1.3 Automatic security updates

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades   # answer Yes
```

This installs security updates daily. It doesn't reboot, but some updates
(the kernel) need one. Either reboot monthly by hand, or allow automatic
reboots at 04:00, after the 02:30 backup. A small file of its own keeps the
setting separate from the package's own config:

```bash
printf 'Unattended-Upgrade::Automatic-Reboot "true";\nUnattended-Upgrade::Automatic-Reboot-Time "04:00";\n' \
  | sudo tee /etc/apt/apt.conf.d/52inh-ticketing-reboot
cat /etc/apt/apt.conf.d/20auto-upgrades          # both lines end in "1"
systemctl list-timers 'apt-daily*' --no-pager    # apt-daily and apt-daily-upgrade
```

The app comes back by itself after a reboot (checked in section 7). Docker
itself comes from Docker's repository, which these updates don't cover:
update it monthly with `sudo apt update && sudo apt upgrade` (this restarts the
containers for a moment).

### 1.4 Firewall

First check the address you're connecting from (the first number) is inside
the admin range you'll allow, or enabling the firewall will lock you out:

```bash
echo $SSH_CLIENT
```

```bash
sudo apt install -y ufw   # not installed on Debian by default
sudo ufw default deny incoming
sudo ufw default allow outgoing
# SSH from IT admins only.
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
[docs.docker.com/engine/install/debian](https://docs.docker.com/engine/install/debian/)
in case the steps have changed; on Ubuntu, use `ubuntu` in place of `debian` in every URL):

```bash
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
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

### 1.6 The network: DNS and Wi-Fi

This part isn't on the server: it's for whoever runs the company's DNS and
Wi-Fi.

The app only works at `https://helpdesk.example.com`, from company PCs. Opening
the server's IP address, or plain `http://`, just redirects there, so every PC
has to find that name. **Phones aren't supported** (decided 2026-11-11): from a
phone, people email their request to the help-desk mailbox instead.

**DNS.** In the internal DNS (usually the domain controllers), add an A record:
`helpdesk.example.com` pointing to the server's address. Then make sure every
network staff PCs use gets its answers from that DNS:
- wired PCs and the VPN
- **the staff Wi-Fi,** for laptops: its DHCP must hand out the internal DNS
  servers, not the router or a public DNS. Otherwise a laptop on it looks the
  name up on the internet. If the domain's public DNS has a catch-all record,
  it then lands on the company's public web host instead, for example a web
  host's "coming soon" or cPanel page.

To check, on a PC run `Resolve-DnsName helpdesk.example.com`: it should give
the server's address.

> **To fill in** (item 1 of [Still to fill in or add](#still-to-fill-in-or-add)):
> the A record and the server's DHCP reservation aren't in place yet
> (2026-11-17). When they are, record the date here, and remove any
> hosts-file entry for the help-desk name from the PCs used to test.

**Guest Wi-Fi.** Docker's ports skip the server's own firewall (see 1.4), so the
network firewall in front of the server is what limits ports 80 and 443.
Allow the staff networks and the VPN, and block the guest Wi-Fi.

## 2. Get the code

The repository is private. The server gets a **read-only deploy key**: it can
fetch this one repository and nothing else.

InH-Ticketing is licensed software ([LICENSE](../LICENSE)). The repository
and its deploy keys belong to the owner, and only the owner can add or remove
them. Without a key, the server keeps running the release it has installed,
but it can't fetch new releases. Updates and new releases need the owner's
written permission.

A fresh Debian has no git:

```bash
sudo apt install -y git
ssh-keygen -t ed25519 -f ~/.ssh/inh_ticketing_deploy -C "inh-ticketing deploy key ($(hostname))"
cat ~/.ssh/inh_ticketing_deploy.pub
```

A passphrase is optional: you'd type it at each update. Send the `.pub` line
(it isn't secret) to the owner, who adds it to the company's copy of the
repository: **Settings → Deploy keys → Add deploy key**, title `helpdesk
server`, **Allow write access** unticked.

Tell SSH to use that key, under a name of its own, `github-inh`. Then a key
for another repository on the same server (another app) can have its own
name and never gets mixed up with this one:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github-inh
    HostName github.com
    User git
    IdentityFile ~/.ssh/inh_ticketing_deploy
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
ssh -T github-inh
```

The first time, SSH shows GitHub's key fingerprint: compare it with
[GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)
before typing `yes`. The reply should name the repository and say *You've
successfully authenticated*. If outbound port 22 is blocked, change
`HostName github.com` to `HostName ssh.github.com` and add `Port 443`.

Clone, and check out the release you're installing. `github-inh` stands in
for `github.com` in the address:

```bash
git clone git@github-inh:luckyajinn/InH-Ticketing.git /srv/inh-ticketing/app
cd /srv/inh-ticketing/app
git tag --list --sort=-v:refname | head -5   # the newest releases, newest first
git checkout v0.10.7     # the newest, or the one the owner named; "detached HEAD" is expected
file scripts/backup.sh   # "POSIX shell script ... executable", and no "CRLF"
```

Always run a release tag on the server, never a branch.

### 2.1 Moving the server to the company's own copy

Each company gets its own private copy of the repository, which the owner
sends releases to. A server first set up from the owner's repository moves
to the copy once. The owner moves the deploy key first (a key can belong to
only one repository), and gives you the copy's `<org>/<repository>` name.

The server reinstalled on 2026-11-17 was cloned from its copy straight
away, so it didn't need this.

```bash
cd /srv/inh-ticketing/app
git remote -v                                   # where it fetches from now
git remote set-url origin git@github-inh:<org>/<repository>.git   # the alias from section 2
git describe --tags                             # the tag checked out now: never delete this one
git fetch --tags origin
git tag --list --sort=-v:refname | head -5      # the newest releases the copy has
```

- **An older `~/.ssh/config`** (a `Host github.com` block that points at the
  deploy key): replace that block with the `github-inh` one from
  section 2 first, and check it with `ssh -T github-inh`.
- **`.env` stays as it is:** it isn't tracked, so changing the remote doesn't touch it.
- **If `git fetch` says `would clobber existing tag`:** the copy's tags are
  new objects with the same names, and the server already has them from the
  old repository. For each tag it names, other than the one `git describe
  --tags` printed, run `git tag -d <tag>`, then fetch again. For the
  checked-out tag, don't delete it: `git fetch --force origin tag <tag>`
  takes the copy's version, and `git checkout <tag>` then puts the server on
  the copy's version of it.
- **Rolling back after the move:** the copy holds only the releases the
  owner sent it, starting with v0.10.7. A release from before that is still
  on the server if it was fetched earlier (`git tag --list`); otherwise ask
  the owner.
- Then update as usual (section 10).

## 3. Get the certificate

> **To fill in** (item 2 of [Still to fill in or add](#still-to-fill-in-or-add)):
> the server has a temporary certificate from 3.5 (made at the reinstall),
> which expires **2026-12-17**. Fill in, once known: which CA issues the real one (an
> internal CA, if the company has one), its expiry date, and who owns the
> renewal. If it isn't ready by then, make a new temporary one (3.5).

### 3.1 Create the key and the request

On the server, so the private key never leaves it:

```bash
cd ~
umask 077
openssl req -new -newkey rsa:2048 -noenc \
  -keyout privkey.pem -out helpdesk.csr \
  -subj "/CN=helpdesk.example.com/O=Example Company" \
  -addext "subjectAltName=DNS:helpdesk.example.com"
openssl req -in helpdesk.csr -noout -text | grep -A1 "Subject Alternative Name"
# DNS:helpdesk.example.com
```

Send `helpdesk.csr` (it isn't secret) to whoever runs the internal CA (for
AD CS, usually the *Web Server* template). Ask for:

- the server certificate, in PEM ("Base-64") format;
- the intermediate (issuing) CA certificate(s);
- the root CA certificate, to test with (company PCs already trust it). Save
  it as `internal-root.pem`, in PEM format like the others.

### 3.2 Put the files together

Only once the CA has sent the certificate files. No files yet? Use a
temporary certificate (3.5) meanwhile: with nothing to put together, the
commands below make an empty `fullchain.pem` and every check fails.

If the certificate isn't text starting `-----BEGIN CERTIFICATE-----`, convert it.
If the chain came as a `.p7b`, take the certificates out of it:

```bash
openssl x509 -inform der -in helpdesk.cer -out helpdesk.pem
openssl pkcs7 -inform der -print_certs -in chain.p7b -out chain.pem   # leave out -inform der if the .p7b is text
```

`chain.pem` should hold the intermediate(s) only. If the `.p7b` included the
root (a certificate whose subject and issuer are the same), delete that one
from `chain.pem`. If the CA sent the intermediates as PEM files already,
join them into a file called `chain.pem`.

Build the full chain: the **server certificate first**, then the
intermediate(s). Leave the root out.

```bash
cat helpdesk.pem chain.pem > fullchain.pem
```

Check it before installing it:

```bash
# The name, who issued it, and when it expires: note the date.
openssl x509 -in fullchain.pem -noout -subject -issuer -enddate -ext subjectAltName
# The key matches the certificate: these two lines must be identical.
openssl x509 -in fullchain.pem -noout -pubkey | openssl sha256
openssl pkey -in privkey.pem -pubout | openssl sha256
# The order: the first subject is helpdesk.example.com, and each issuer is the next subject.
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

### 3.5 No certificate yet? A temporary one

So the rest of the install can go ahead while the real certificate is
arranged, the server can make a 30-day certificate for itself. Browsers will
show a warning, so it's for IT testing only, never for staff.

If you've already done 3.1 or 3.2, move those files out of the way first:
this writes a new `~/privkey.pem` and `~/fullchain.pem`, which would replace
the key the CA's certificate needs and a `fullchain.pem` built in 3.2, and
the `rm` at the end would then delete them.

```bash
cd ~
umask 077
mkdir -p ~/csr
for f in privkey.pem helpdesk.csr fullchain.pem; do [ -f "$f" ] && mv "$f" ~/csr/; done   # only the ones that exist; move them back for 3.2
openssl req -x509 -newkey rsa:2048 -noenc -days 30 \
  -keyout privkey.pem -out fullchain.pem \
  -subj "/CN=helpdesk.example.com/O=Example Company (temporary)" \
  -addext "subjectAltName=DNS:helpdesk.example.com"
sudo install -o root -g root -m 644 fullchain.pem /srv/inh-ticketing/certs/fullchain.pem
sudo install -o root -g root -m 600 privkey.pem   /srv/inh-ticketing/certs/privkey.pem
sudo install -o root -g root -m 644 fullchain.pem /srv/inh-ticketing/certs/internal-root.pem
rm ~/privkey.pem ~/fullchain.pem
sudo openssl x509 -in /srv/inh-ticketing/certs/fullchain.pem -noout -subject -enddate -ext subjectAltName
```

The same file serves as `internal-root.pem`, so the `curl --cacert` checks in
section 7 work. Browsers ignore HSTS from a site whose certificate they warn
about, so clicking through leaves nothing behind. When the real certificate
arrives, follow 3.1 to 3.3, then restart the proxy as in 3.4.

## 4. Microsoft Entra

The server uses the same app registration as the pilot
([entra-setup.md](entra-setup.md)), with its own address and its own secret.
An Entra admin:

1. **Entra ID → App registrations → InH-Ticketing → Authentication.** Under
   **Web → Redirect URIs**, add `https://helpdesk.example.com/auth/callback`
   exactly (https, no trailing slash). Keep the `localhost` one for PCs. **Save**.
2. **Certificates & secrets → New client secret.** Description `helpdesk
   server`, expiry 12 months. Copy the **Value** straight into the server's
   `.env` (section 5) and nowhere else. It's shown **only once**, right after
   you add it. The *Secret ID* column next to it isn't the secret: pasting
   that gives `AADSTS7000215` at sign-in. If the Value is lost, add a new
   secret and delete the old one. A separate secret per machine means one can
   be revoked without breaking the other.
3. **Put the secret's expiry in the calendar**, with a reminder a few weeks
   before. An expired secret stops all sign-in and email (`AADSTS7000222`).
4. **Enterprise applications → InH-Ticketing → Users and groups:** check
   who is assigned which role. At go-live, assign the all-staff group as
   *Requester*, and IT as *Agent* or *Admin*.

> **To fill in** (item 3 of [Still to fill in or add](#still-to-fill-in-or-add)):
> sign-in fails with `AADSTS7000215` since the reinstall (2026-11-17). Put
> the new secret's Value in `.env`, run `docker compose -f compose.yaml -f compose.prod.yaml up -d`,
> check it with [the secret check](#checking-the-client-secret-without-showing-it),
> and delete the old server's secret in Entra. Then fill in the new secret's
> expiry date (step 3).

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
HELPDESK_HOSTNAME=helpdesk.example.com

DJANGO_DEBUG=False
DJANGO_SECRET_KEY=$(openssl rand -hex 32)
DJANGO_ALLOWED_HOSTS=helpdesk.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://helpdesk.example.com
TIME_ZONE=America/Los_Angeles

# Hex only, so it is safe inside the database URL. Used when the database is first created.
POSTGRES_PASSWORD=$(openssl rand -hex 24)

ENTRA_TENANT_ID=
ENTRA_CLIENT_ID=
ENTRA_CLIENT_SECRET=
ENTRA_REDIRECT_URI=https://helpdesk.example.com/auth/callback
ENTRA_ROLE_AGENT=Agent
ENTRA_ROLE_ADMIN=Admin

EMAIL_BACKEND=graph
SITE_URL=https://helpdesk.example.com
# The TEST shared mailbox until the pilot ends (docs/email-setup.md).
HELPDESK_MAILBOX=helpdesk-test@example.com
IT_NOTIFY_EMAIL=
# Shown under "Can't sign in?" and on error pages. Fill in how staff reach IT
# (keep the quotes if it has a #). Blank shows the help-desk mailbox's address.
HELP_CONTACT=
# Email in stays off until it moves to the server (docs/deployment.md 5.1): only one copy may read the mailbox.
INBOUND_EMAIL=off
INBOUND_ALLOWED_DOMAINS=example.com
EOF
chmod 600 .env
nano .env       # fill in the three ENTRA_ values, HELP_CONTACT, and IT_NOTIFY_EMAIL if wanted
ls -l .env      # -rw------- 1 inhadmin inhadmin ...
```

| Setting | Value on the server | Why |
|---|---|---|
| `COMPOSE_FILE` | `compose.yaml:compose.prod.yaml` | A `docker compose` command typed without `-f` still uses both files |
| `HELPDESK_HOSTNAME` | `helpdesk.example.com` | The name the proxy serves and redirects to. Required: the proxy won't start without it |
| `DJANGO_DEBUG` | `False` | Turns on the HTTPS hardening: secure cookies, redirect, HSTS. With `True` and a real name in `DJANGO_ALLOWED_HOSTS`, the app refuses to start (v0.10.7) |
| `DJANGO_SECRET_KEY` | 64 random hex characters | Signs sessions. New for the server; never copy a PC's |
| `DJANGO_ALLOWED_HOSTS` | `helpdesk.example.com` | Other names get "400 Bad Request". (`127.0.0.1` is added automatically, for Docker's health check) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://helpdesk.example.com` | Forms must come from this address |
| `TIME_ZONE` | `America/Los_Angeles` | Dates and times in the app and in emails. Same as the server's own time zone (1.1) |
| `POSTGRES_PASSWORD` | 48 random hex characters | Letters and digits only, so it's safe in `DATABASE_URL` |
| `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID` | From the app registration's Overview | Same as on a PC |
| `ENTRA_CLIENT_SECRET` | The server's own secret (section 4) | |
| `ENTRA_REDIRECT_URI` | `https://helpdesk.example.com/auth/callback` | Must match Entra exactly |
| `ENTRA_ROLE_AGENT`, `ENTRA_ROLE_ADMIN` | `Agent`, `Admin` | The *Value* of IT's agent role and the admin role on the app registration. Only change them if the roles were named differently |
| `EMAIL_BACKEND` | `graph` | Really send email |
| `SITE_URL` | `https://helpdesk.example.com` | Links in emails |
| `HELPDESK_MAILBOX` | The test shared mailbox during the pilot | |
| `IT_NOTIFY_EMAIL` | One IT address, e.g. a distribution list or a Teams channel's address (optional) | Where IT's "new request" alerts go. **Never the help-desk mailbox:** it would read its own alerts as new requests |
| `HELP_CONTACT` | How to reach IT, e.g. `"Call IT on ext. 1234, or post in IT Help in Teams."` (blank until filled in) | Shown under "Can't sign in?" and on error pages. While blank it shows "Email IT at" the mailbox above, which is the test mailbox during the pilot. Quote it if it contains `#`, or everything after the `#` is dropped |
| `REPORTS_FROM` | The go-live date, e.g. `2026-11-30` (blank until then) | Reports (`/reports/`, admins only) count tickets from this date, so pilot and test tickets don't skew them. Tickets whose subject starts with "Pilot:" are always left out |
| `INBOUND_EMAIL` | `graph`, once no PC reads the mailbox (below) | Read the mailbox. `off` until email-in moves to the server (5.1) |
| `INBOUND_ALLOWED_DOMAINS` | The company's email domain(s), comma-separated | Email from any other domain is ignored. Blank means the help-desk mailbox's domain |
| `DEPARTMENT_MAILBOXES` | Blank until the department mailboxes are decided | e.g. `mechanics=mechanics-requests@example.com, cleaning=cs@example.com/Requests`. Each needs the Exchange steps in [email-setup.md](email-setup.md), 4d |
| `DEPARTMENT_NOTIFY_EMAILS`, `ENTRA_ROLE_AGENT_MECHANICS`, `ENTRA_ROLE_AGENT_CLEANING` | Remove (from v0.10.0) | Each department's alert address and Entra role are set in the admin site (Tickets > Departments). The upgrade to v0.10.0 copied these values there, and the logs warn while they're still in `.env` |
| `ARCHIVE_KEEP_DAYS` | Leave out (default 730, two years) | How long an archived ticket is kept; shown on the ticket |
| `AUTO_CLOSE_RESOLVED_DAYS` | Leave out (default 7) | Days after IT resolves a ticket before it closes by itself, if the requester doesn't reply. `0` never closes them |
| `INBOUND_VERIFY_IT_SENDERS` | Leave out (default on) | Every sender is checked (the name is from when only IT was): an unconfirmed reply becomes an internal note, and an unconfirmed new request is ignored ([email-setup.md](email-setup.md)) |
| `DJANGO_LOG_LEVEL` | Leave out (default `INFO`) | How much Django writes to the container logs. Only raise it (`DEBUG`) while chasing a problem |
| `INBOUND_DEFAULT_CATEGORY` | Leave out (default `Other`) | The category of a ticket that arrives by email. IT can change it on the ticket |
| `INBOUND_POLL_SECONDS` | Leave out (default 60) | How often the worker reads the mailbox, in seconds |
| `WORKER_INTERVAL_SECONDS` | Leave out (default 15) | How often the worker checks for emails to send, in seconds |

Things to know:

- **Only one copy of the app may read the mailbox.** Once the server reads
  it, set `INBOUND_EMAIL=off` on every PC that has it on, or emails will be
  split between two databases.
- **`POSTGRES_PASSWORD` is only used when the database is first created.**
  Changing it in `.env` later doesn't change the database's password: the
  app then can't connect (see section 12).
- **IT's settings stay here.** `ENTRA_ROLE_AGENT`, `IT_NOTIFY_EMAIL` and
  `HELPDESK_MAILBOX` are IT's role, alert address and mailbox. The admin site
  shows them on IT's department page, read-only. The other departments'
  roles and alert addresses are edited in the admin site instead
  ([entra-setup.md](entra-setup.md), section 3).
- Keep a copy of the `.env` values in IT's password vault. `.env` isn't in the backups.

The HTTPS settings (`DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_SECURE_HSTS_SECONDS`)
are left out on purpose: their defaults are right. See `.env.example`.

### 5.1 Still to fill in on the server

> **To fill in** (item 4 of [Still to fill in or add](#still-to-fill-in-or-add)):
> the `.env` lines below aren't set to their final values yet (2026-11-17).
> After changing any of them, run `docker compose -f compose.yaml -f compose.prod.yaml up -d`
> (section 10, *Changing a setting*), then remove its row here.

| Setting | On the server now | Fill in with | When |
|---|---|---|---|
| `INBOUND_EMAIL` | `graph`: the reinstall (2026-11-17) used this guide's old template, which had `graph` | `off` **now**, until email-in moves. Then `graph`, after setting `INBOUND_EMAIL=off` on every PC that has it on: only one copy may read the mailbox | Now; `graph` when email-in moves (checks 13 and 18) |
| `HELP_CONTACT` | Not confirmed: the reinstall (2026-11-17) used this guide's old template, which had a made-up phone line | How staff reach IT, in quotes, e.g. `"Call IT on ext. 1234, or post in IT Help in Teams."` | Now. It's blank until filled in, and while it's blank the sign-in page shows the test mailbox's address |
| `IT_NOTIFY_EMAIL` | Not confirmed (blank on the first install) | One IT address for the "new request" alerts. Never the help-desk mailbox | Before go-live, if IT wants the alerts |
| `REPORTS_FROM` | Blank | The go-live date, e.g. `2026-11-30` | At go-live |
| `HELPDESK_MAILBOX` | The test shared mailbox | The real help-desk mailbox, once its Exchange steps are done ([email-setup.md](email-setup.md)) | When the pilot ends |
| `INBOUND_ALLOWED_DOMAINS` | Not confirmed | The company's email domain(s) | With `INBOUND_EMAIL=graph` |
| `DEPARTMENT_MAILBOXES` | Blank | Each department's mailbox, as in the table above | When the department mailboxes are decided |
| `DEPARTMENT_NOTIFY_EMAILS`, `ENTRA_ROLE_AGENT_MECHANICS`, `ENTRA_ROLE_AGENT_CLEANING` | Possibly still there from before v0.10.0 | Nothing: delete the lines | If `docker compose … logs web` warns about them |

## 6. First start

From `/srv/inh-ticketing/app`:

**6.1 Check the configuration.** This reads `.env` and both Compose files:

```bash
docker compose -f compose.yaml -f compose.prod.yaml config --quiet && echo "Compose config OK"
```

**6.2 Check the proxy's configuration and the certificate files.** This
loads the Caddyfile and the certificate without starting anything. It
should catch a wrong path or a key that doesn't match:

```bash
docker compose -f compose.yaml -f compose.prod.yaml run --rm --no-deps proxy caddy validate --config /etc/caddy/Caddyfile
# ... "Valid configuration"
```

> **To fill in** (item 7 of [Still to fill in or add](#still-to-fill-in-or-add)):
> run this once on the server and record the result here.

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
migrations, then starts gunicorn. `db` is `(healthy)`; `worker` starts once
`web` is healthy and shows `(healthy)` a minute or so later; `proxy` is `Up`. In the PORTS column, only `proxy` has `0.0.0.0:80->80/tcp` and
`0.0.0.0:443->443/tcp`; `web` shows just `8000/tcp`.

## 7. Post-install checklist

Work through this before anyone else uses the server. Keep the results with
the go-live records.

| # | Check | How | Expected |
|---|---|---|---|
| 1 | Containers running | `docker compose -f compose.yaml -f compose.prod.yaml ps` | `db`, `web` and `worker` healthy, `proxy` up |
| 2 | Port 8000 not reachable | `ss -tln \| grep 8000` | Nothing |
| 3 | HTTPS and health check, from the server | `sudo curl -sS --cacert /srv/inh-ticketing/certs/internal-root.pem https://helpdesk.example.com/healthz` | `ok` |
| 4 | HTTP redirects to HTTPS | `curl -sSI http://helpdesk.example.com/queue/` | `301`, `Location: https://helpdesk.example.com/queue/` |
| 5 | One HSTS header | `sudo curl -sSI --cacert /srv/inh-ticketing/certs/internal-root.pem https://helpdesk.example.com/healthz \| grep -i strict` | One line: `max-age=31536000; includeSubDomains` |
| 6 | **No browser warning on a company PC** | Open `https://helpdesk.example.com` in Edge | A padlock; certificate issued by the internal CA |
| 7 | Sign-in works | **Sign in with Microsoft 365** | Back in the app, your name in the header |
| 8 | **The Admin role shows** | Sign in as someone with the Admin role | **Admin** badge; `/admin/` opens |
| 9 | Agents see the queue | Sign in with the Agent role | The IT queue |
| 10 | Attachments, up to the limit | Submit a ticket, then a reply with 5 files of about 9 MB each | All upload; each downloads again |
| 11 | Worker running | `docker compose -f compose.yaml -f compose.prod.yaml logs --tail 20 worker` | `Email backend: notifications.backends.GraphEmailBackend`, and `Email-in: off (INBOUND_EMAIL=off)` on a first install (`Email-in: reading helpdesk-test@… every 60s` once email-in has moved, 5.1) |
| 12 | **A test email out** | Submit a ticket for yourself | The receipt arrives; the worker logs `Emails: 1 sent` |
| 13 | A test email in | Email the help-desk mailbox from your account | A new ticket within a minute |
| 14 | A backup | `/srv/inh-ticketing/app/scripts/backup.sh first-install` | Ends with `Backup OK` (section 8) |
| 15 | Nightly backup scheduled | `crontab -l` | The line from section 8 |
| 16 | Survives a reboot | `sudo reboot`, wait 3 minutes, repeat checks 1, 3 and 7 | All four services healthy within about 3 minutes, with no manual `up` |
| 17 | Expiry dates in the calendar | The certificate (3.3) and the client secret (4) | Both, with owners |
| 18 | PCs no longer read the mailbox | On each PC that ever ran the app, open its `.env` (section 5) | `INBOUND_EMAIL=off` in each one |
| 19 | **A laptop on the staff Wi-Fi** | Open `https://helpdesk.example.com/healthz` (section 1.6) | `ok`, with no certificate warning |
| 20 | Guest Wi-Fi blocked | From a device on the guest Wi-Fi, open `http://<server address>/healthz` | No answer: a timeout is a pass. Any page or redirect means the block isn't working |

If the server can't resolve its own name for checks 3–5, add
`--resolve helpdesk.example.com:443:127.0.0.1` (or `:80:` for check 4).

> **To fill in** (item 6 of [Still to fill in or add](#still-to-fill-in-or-add)):
> the server was reinstalled on 2026-11-17, so the first install's results
> no longer count. Done on the reinstall: checks 1 to 5. **Failing:** 7
> (sign-in, `AADSTS7000215`: item 3). Not done yet: 6 (waits for the real
> certificate), 8 and 9 (the Admin and Agent roles, after sign-in), 10
> (attachments), 11–13 (email out and in), 14–15 (backups), 16 (a reboot),
> 17 (the calendar), 18 (no PC reads the mailbox), 19–20 (staff and guest
> Wi-Fi). As each one is done, put its date and result in the go-live
> records.

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

> **To fill in** (item 5 of [Still to fill in or add](#still-to-fill-in-or-add)):
> the cron line isn't on the server yet (2026-11-17). Fill in: the date it
> was added and the first nightly `Backup OK`. Still to decide: where the copy
> off the server goes (below).

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

Each backup is a folder named after its date and time, plus a label if one
was given:

- `2026-11-06_023000`: the nightly one
- `2026-11-06_141500_first-install`: by hand, with a label of your choice
- `2026-11-06_141500_before-v0.10.7`: before an update (section 10)
- `2026-11-06_141500_before-restore`: the safety backup `restore.sh` takes before it restores (section 9)

Each folder has:

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

## 9. Restoring a backup

A restore puts the help desk back to how it was when a backup was made: after
lost or damaged data, or to roll back an update (section 10, which says which
version to check out first). **Everything done in the app since that backup
is lost**, so tell people before you start.

1. Find the backup, then restore it. The script checks the backup's checksums,
   shows what's in it, asks you to type its name, and takes a safety backup of
   the current data first:
   ```bash
   cd /srv/inh-ticketing/app
   ./scripts/restore.sh                       # lists the backups
   ./scripts/restore.sh 2026-11-06_023000     # the one to restore
   ```
2. Start the app again, with the command the script prints at the end:
   `docker compose -f compose.yaml -f compose.prod.yaml up -d --build`
3. Check: tickets from before the backup are there and their attachments
   open, sign-in works, and the worker is running (checks 1, 3, 7 and 11 in
   section 7).

If the restore was the wrong one, restore the newest backup ending
`_before-restore` the same way: that's the data from just before.

A practice restore (a restore drill) isn't planned (decided 2026-11-11). To
try one anyway, use a **separate test VM, never the live server**, and set
`EMAIL_BACKEND=file` and `INBOUND_EMAIL=off` in its `.env` before starting it,
or it will email real people and read the real mailbox.

Things to know about restoring:

- Emails that were waiting to be sent when the backup was made, and went out
  afterwards, are sent again.
- Emails that arrived after the backup was made were moved to the mailbox's
  *Processed by InH-Ticketing* folder. To get them in again, move them back
  to the Inbox and mark them unread; the worker picks them up *(untested)*.

### Restoring onto a new server (the old one is lost)

You need: a backup folder from the copy off the server (section 8), the
`.env` values from IT's password vault, and someone who can issue a
certificate. *(Untested as a whole: each step is the same as on the first
install.)*

1. **Make sure the old server is off** (shut down, or off the network). If it
   came back while the new one runs, both would read the same mailbox and send
   the same emails.
2. **Build the new server:** sections 1 and 2. Then open the backup's
   `manifest.txt` and look at its "App version" line. The `git:` part is the
   version, e.g. `v0.10.7`. Check out the tag before any `-N-g…`, so
   `v0.10.7-3-gabc1234-dirty` means `git checkout v0.10.7`. If there's no tag
   (just a commit hash), check out that hash.
3. **A new certificate** for the same name: section 3. The old private key
   wasn't backed up.
4. **The `.env`** from the password vault: section 5, with the same
   `HELPDESK_HOSTNAME`. The Entra app registration and its redirect URI stay
   as they are while the name stays the same.
5. **Do steps 6.1 and 6.2 of section 6, but skip step 6.3** (it starts
   everything). Instead build the app and start the database only, so the
   worker doesn't read the mailbox into an empty database:
   ```bash
   cd /srv/inh-ticketing/app
   docker compose -f compose.yaml -f compose.prod.yaml build
   docker compose -f compose.yaml -f compose.prod.yaml up -d db
   ```
6. **Copy the backup folder in** to `/srv/inh-ticketing/backups/`, keeping its
   name, e.g. with `scp -r` or `rsync -a`. Then restore it, and start everything:
   ```bash
   ./scripts/restore.sh <the backup's folder name>
   docker compose -f compose.yaml -f compose.prod.yaml up -d --build
   ```
7. **If the server's address changed:** point the DNS record at the new one
   (section 1.6), and update the network firewall's rules for it.
8. **Check it, and set up the backups again:** the checklist in section 7
   (a restored server counts as a new install), and the cron line in section 8.
   Read "Things to know about restoring" above about emails.

### Reinstalling the server (the same machine, from scratch)

Wiping the machine and installing Debian again (done on 2026-11-17) is a
new install: sections 1 to 8, then the section 7 checklist from the start.
To keep the data, take a backup first and copy it off the machine (then
restore it as above). Also:

1. **The server's SSH host key is new.** The PC you connect from warns
   `REMOTE HOST IDENTIFICATION HAS CHANGED`. First check the new key at the
   server's own console:
   ```bash
   ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
   ```
   On the PC, remove the old entry with `ssh-keygen -R <server address>`.
   Then connect, and check the fingerprint SSH shows matches that one.
2. **The old deploy key is gone** with the old disk. Make a new one
   (section 2), and ask the owner to add it and remove the old one.
3. **The old `.env` is gone**, and with it the client secret's Value, which
   Entra never shows again. Make a new client secret (section 4) and delete
   the old one. A new `.env` gets a new `DJANGO_SECRET_KEY` and
   `POSTGRES_PASSWORD` too. Store the new values in IT's password vault.
4. **The address may change.** Check the DHCP reservation and the DNS record
   (1.6), and any hosts-file entry on the PCs used to test: one pointing at
   the old address times out (section 12).
5. **Expiry dates:** the new certificate (3.5 or 3.3) and the new secret go
   in the calendar, in place of the old ones.

## 10. Updating and rolling back

### Updating to a new version

Read the release notes first (`docs/releases/vX.Y.Z.md` in the new version):
they say if there are new `.env` settings or anything else to do.

**Skipping versions** is fine: one update applies every migration in between,
in order. But read the Upgrading section of **every** release you skip, and do
each one's "Before installing" steps first. For example, from v0.8.3 to
v0.10.5, read v0.8.4, v0.9.0, v0.9.1 (Entra roles to create first), and each
v0.10.x.
A version ending in a letter, such as v0.10.0d, changes only the documents:
there's nothing extra to do for it.

Set `NEW` to the version you're installing, then run the rest as it is:

```bash
cd /srv/inh-ticketing/app
NEW=v0.10.7                                # the version you're installing
OLD=$(git describe --tags); echo "$OLD"    # the current version: write it down, rolling back needs it
./scripts/backup.sh before-$NEW            # always, before updating
git fetch --tags
git diff --stat HEAD $NEW -- '*/migrations/*' deploy/   # database changes? proxy changes?
git checkout $NEW
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
docker compose -f compose.yaml -f compose.prod.yaml ps
```

`backup.sh` ends with `Backup OK`; if it says `BACKUP FAILED` instead, stop
there and fix that first (section 12). `git checkout` refuses if files in the
checkout were edited on the server: `git status` lists them.

`up -d --build` rebuilds the app and replaces `web` and `worker`; `web`
applies any new migrations as it starts. Expect a minute or two of
downtime. If the diff showed changes under `deploy/`, also
`docker compose -f compose.yaml -f compose.prod.yaml restart proxy`. Then
repeat checks 1, 3, 7 and 11 from section 7.

Now and then, clear out old images: `docker image prune -f`.

**Changing a setting in `.env`** (no new version): save the file, then run
`docker compose -f compose.yaml -f compose.prod.yaml up -d`, which recreates
the containers whose settings changed. A plain `restart` keeps the old
settings.

### Rolling back

`OLD` is the version you wrote down before updating (in a new terminal, set
it again, e.g. `OLD=v0.9.1`). The backup from before the update ends in
`_before-` and the new version's name: `./scripts/restore.sh` on its own lists
the backups.

- **No database changes in the new version** (the `git diff` above listed no
  migrations): check out the old version and rebuild.
  ```bash
  cd /srv/inh-ticketing/app
  git checkout $OLD
  docker compose -f compose.yaml -f compose.prod.yaml up -d --build
  ```
- **The new version changed the database:** the old code may not work with
  the new database, and not every migration can be undone. Restore the
  backup taken just before the update, with the old code checked out first:
  ```bash
  cd /srv/inh-ticketing/app
  git checkout $OLD
  ./scripts/restore.sh                        # lists the backups
  ./scripts/restore.sh <the backup ending _before-vX.Y.Z>
  docker compose -f compose.yaml -f compose.prod.yaml up -d --build
  ```
  Everything done in the app since the update is lost: tell people. See the
  notes in section 9 about emails. Always finish with `up -d
  --build` as above: plain `up -d` would start the new version's images on
  the restored database, and they would re-apply the new migrations.
- **From v0.10.6 or later back to v0.10.5 or earlier:** v0.10.6 adds
  migration `tickets` 0010 (who opened a ticket for someone else). Undo it
  first, then check out the old version and rebuild:
  `docker compose -f compose.yaml -f compose.prod.yaml exec web python manage.py migrate tickets 0009`.
  The tickets opened for someone stay theirs. (v0.10.7 adds no migrations:
  back to v0.10.6 is a checkout and rebuild.)
- **From v0.10.1 to v0.10.5 back to v0.10.0:** v0.10.1 adds migration
  `tickets` 0009 (IT's common requests for printers, passwords and Wi-Fi), and
  v0.10.3 adds `notifications` 0002 (the worker's heartbeat table). Undo them,
  then check out `v0.10.0` and rebuild:
  `docker compose -f compose.yaml -f compose.prod.yaml exec web python manage.py migrate tickets 0008`,
  then the same with `migrate notifications 0001` (from v0.10.1 or v0.10.2 it
  does nothing). The common requests are removed only where nobody has
  edited them. On v0.10.6 or later, `migrate tickets 0008` also undoes 0010.
- **From v0.10.0 back to v0.9.1:** v0.10.0 adds migrations `tickets` 0008
  (the departments table) and `accounts` 0003. If no department was added
  besides IT, Mechanics and Cleaning & sanitization, undo them, then check
  out and rebuild:
  `docker compose -f compose.yaml -f compose.prod.yaml exec web python manage.py migrate tickets 0007`
  (this also undoes 0009, and 0010, if they were applied),
  then the same with `migrate accounts 0002`. Tickets and notes keep their
  department. Put back `DEPARTMENT_NOTIFY_EMAILS` (and the two role settings,
  if they weren't the defaults) from the admin site's values. If another
  department was added, v0.9.1 can't show it: restore the backup instead.
- **From v0.9.1 back to v0.9.0:** v0.9.1 adds migrations `tickets` 0007 and
  `accounts` 0002 (departments and the archive). Restore the backup taken
  before the update, with v0.9.0 checked out, as above. Or, to keep the
  tickets made since, undo them first, then check out and rebuild:
  `docker compose -f compose.yaml -f compose.prod.yaml exec web python manage.py migrate tickets 0006`,
  then the same with `migrate accounts 0001`. That drops each category's
  department, the archive dates and which department each note belongs to.
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
| Certificate expiry | `sudo openssl x509 -in /srv/inh-ticketing/certs/fullchain.pem -noout -enddate` |
| Client secret expiry | Entra → App registrations → InH-Ticketing → Certificates & secrets |
| Updates | `sudo apt update && sudo apt upgrade`; reboot if `/var/run/reboot-required` exists |
| The app's parts: known security issues | `docker compose -f compose.yaml -f compose.prod.yaml exec web python scripts/check_updates.py`. It checks the app's packages and, since v0.10.7, the packages they need. "Known security issues: none." is the all-clear. If it lists one, a new release of the app fixes it (send the output to the app's owner, who holds the repository and its deploy keys, section 2) |
| PostgreSQL and the Python base image | Refresh them: the steps below |
| Caddy | The same script says if there's a newer release. Change the tag in `compose.prod.yaml` through a normal release |
| The worker | `ps` shows `worker` as `(healthy)`, and Reports → *Email and safety checks* says "The worker is running" |

### Refreshing the images (monthly)

Updating the app (section 10) never downloads a newer PostgreSQL or Python
base image: Docker keeps the ones it got on the first install. Their
security fixes arrive only when you refresh them. Out of hours, as it
restarts everything for a minute:

```bash
cd /srv/inh-ticketing/app
./scripts/backup.sh before-refresh
docker compose -f compose.yaml -f compose.prod.yaml pull db
docker compose -f compose.yaml -f compose.prod.yaml build --pull
docker compose -f compose.yaml -f compose.prod.yaml up -d
docker compose -f compose.yaml -f compose.prod.yaml ps
```

- `pull db` gets the newest PostgreSQL 17 (17.x: the same data format, so
  there's nothing to convert).
- `build --pull` gets the newest `python:3.13-slim` and installs the Python
  packages again, each at the newest release its pin in `requirements.txt`
  allows (the security fixes; never a bigger jump).
- `up -d` replaces `db`, `web` and `worker` with the new images. The app's
  version doesn't change.

Then repeat checks 1, 3, 7 and 11 from section 7, and run `check_updates.py`
again: its "A rebuild picks up" line should be gone. Old images stay on disk
until `docker image prune -f`.

## 12. Troubleshooting

Logs: `docker compose -f compose.yaml -f compose.prod.yaml logs --tail 100 <service>`
(`proxy`, `web`, `worker` or `db`).

| Symptom | Likely cause | Fix |
|---|---|---|
| Certificate warning on a company PC | The PC doesn't trust the internal root; the name isn't in the certificate's SAN; or the intermediate is missing from `fullchain.pem` | Re-run the checks in 3.2. The root reaches PCs through Group Policy or Intune |
| Another website opens (a web host's "coming soon" or cPanel page) | That PC looks the name up on the internet: its network (often a Wi-Fi) hands out a public DNS | Section 1.6. Compare its DNS servers with a working PC's (`ipconfig /all`) |
| Browser can't connect at all, or `ERR_CONNECTION_TIMED_OUT` | DNS, the network firewall, `proxy` isn't running, or a hosts-file entry on that PC points at an old address (after a reinstall or an address change) | `nslookup helpdesk.example.com`; `docker compose … ps`. On the PC, `Test-NetConnection helpdesk.example.com -Port 443` shows the address it really uses. Fix or remove the line in `C:\Windows\System32\drivers\etc\hosts` (as admin), then `ipconfig /flushdns` |
| `proxy` keeps restarting | A certificate file is missing or unreadable, the key doesn't match, or the Caddyfile has an error | `docker compose … logs proxy`; repeat step 6.2 |
| `502 Bad Gateway` | `web` is down or still starting | `docker compose … ps`; `logs web` |
| `web` stops at once with `DJANGO_DEBUG is on, but DJANGO_ALLOWED_HOSTS has …` | `.env` has `DJANGO_DEBUG=True` (as in `.env.example`) | Set `DJANGO_DEBUG=False` in `.env`, then `docker compose … up -d` |
| A page looks unstyled or a button does nothing, and the browser console says `Content-Security-Policy` | Something on the page isn't from the app itself (a browser extension, or a change to the templates) | Try another browser or a private window. If it's the app, report it with the console message |
| `400 Bad Request` | Opened by IP address or a short name | Use `https://helpdesk.example.com`. Other names need adding to `DJANGO_ALLOWED_HOSTS` |
| Too many redirects | Something in front of the proxy, or `X-Forwarded-Proto` doesn't reach Django | The proxy must be the only thing in front. Check `proxy` logs |
| `403 CSRF verification failed` | `DJANGO_CSRF_TRUSTED_ORIGINS` doesn't match the address used | Must be `https://helpdesk.example.com` exactly |
| `AADSTS50011` at sign-in | The server's redirect URI isn't on the app registration | Section 4, step 1 |
| `AADSTS7000215` or `AADSTS7000222` | Wrong or expired client secret. Most often the *Secret ID* was pasted instead of the **Value**, or `.env` was edited but the containers weren't recreated | [The secret check](#checking-the-client-secret-without-showing-it) below. If it's wrong: a new secret (section 4), its Value in `.env`, `docker compose … up -d`. To see only the newest attempt: `docker compose … logs --since 2m web` right after trying (plain `logs` shows the older failures too) |
| Sign-in fails with "not yet valid" or "expired" | The server clock is off | `chronyc tracking`, section 1.2 |
| `413` when uploading | Over the 60 MB request limit | Fewer or smaller files per reply (10 MB each, 5 at most) |
| `web` shows `(unhealthy)` | The health check can't reach the app | `docker inspect --format '{{json .State.Health}}' inh-ticketing-web-1`; `logs web` |
| `password authentication failed for user "inh"` | `POSTGRES_PASSWORD` was changed after the database was created | Put the old value back, or set the new one in the database: `docker compose … exec db psql -U inh -d inh -c "ALTER USER inh PASSWORD '<new value>'"` |
| `worker` shows `(unhealthy)` | It hasn't finished a round in 5 minutes: stopped, stuck, or it can't reach the database. Reports says the same | `docker compose … exec worker python manage.py check_worker`; `logs --tail 50 worker`; then `docker compose … restart worker` |
| Emails not sent | See the worker log | [email-setup.md](email-setup.md), *Troubleshooting* |
| Emails missing, or turning up in the wrong place | A PC also reads the mailbox | `INBOUND_EMAIL=off` on every PC |
| `unknown tag !reset`, or web still on port 8000 | Docker Compose older than 2.24 | Update Docker (section 1.5) |
| A script fails with `set: Illegal option -` or `$'\r'` | Windows line endings (files copied from a PC instead of cloned) | Clone with git on the server (`.gitattributes` keeps LF), or `sed -i 's/\r$//' scripts/*.sh` |
| `backup.sh: Permission denied` | The execute bit was lost | `sh /srv/inh-ticketing/app/scripts/backup.sh`, or `chmod +x scripts/*.sh` |
| No new backups | cron, or the script failed | `crontab -l`; `tail /srv/inh-ticketing/backups/backup.log`; `journalctl -u cron --since today` |
| `BACKUP FAILED: the database isn't running` | The app was stopped | `docker compose … up -d` |
| Disk filling up | Backups, old images | `du -sh /srv/inh-ticketing/backups`; `docker image prune -f`; [server-requirements.md](server-requirements.md#hardware) |

`docker compose …` above is short for `docker compose -f compose.yaml -f compose.prod.yaml`,
run in `/srv/inh-ticketing/app`.

### Checking the client secret without showing it

This checks `ENTRA_CLIENT_SECRET` in `.env` and in the running app, and
prints only its length and two yes/no answers, never the secret itself:

```bash
cd /srv/inh-ticketing/app
K=ENTRA_CLIENT_SECRET
V=$(grep "^$K=" .env | tail -1 | cut -d= -f2- | tr -d '\r\n')
case $V in   # take off one pair of surrounding quotes, as Docker Compose does
  \"*\") V=${V#\"}; V=${V%\"} ;;
  \'*\') V=${V#\'}; V=${V%\'} ;;
esac
echo "lines: $(grep -c "^$K=" .env)  length: ${#V}  looks like a Secret ID: $(printf %s "$V" | grep -cE '^[0-9a-f]{8}-[0-9a-f]{4}-')"
[ "$(printf %s "$V" | sha256sum)" = "$(docker compose -f compose.yaml -f compose.prod.yaml exec -T web printenv "$K" | tr -d '\r\n' | sha256sum)" ] \
  && echo "the app uses this value: yes" || echo "the app uses this value: NO (run docker compose ... up -d)"
unset K V
```

What good output looks like:
- **lines** `1` (two lines means the last one wins; delete the other);
- **length** about 40. Exactly 36, with **looks like a Secret ID** `1`, means
  the Secret ID was pasted: put the Value in instead;
- **looks like a Secret ID** `0`;
- **the app uses this value** `yes`. `NO` means `.env` changed after the
  containers started: run `up -d`.

One pair of quotes around the value in `.env` is fine (and needed if it has a
`#`): the check takes them off before it counts the length, the same as Docker
Compose does when it passes the value to the app.

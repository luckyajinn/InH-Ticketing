# Server requirements

What the server for InH-Ticketing needs, for whoever builds it. One Linux VM
runs everything in Docker: the web app, the email worker, PostgreSQL and a
Caddy reverse proxy. Installing the app on it is [deployment.md](deployment.md).

> Written before the server existed. The sizes are estimates; check them
> against the real server after a few months.

## At a glance

| | |
|---|---|
| Machine | One Linux VM |
| CPU, memory, disk | 2 vCPU, 4 GB RAM, 80 GB disk |
| Operating system | Ubuntu Server LTS (or Debian stable), with Docker Engine |
| Name | `helpdesk.mckennalabs.com`, in internal DNS only |
| Reached from | The LAN and the VPN. Nothing from the internet |
| Certificate | From the company's internal CA |
| Users | Fewer than 5 IT agents, up to about 300 requesters |

## Hardware

**2 vCPU.** The load is light: a few requests a minute, a handful at once.
The second CPU keeps the app responsive while a new version builds or the
nightly backup compresses the attachments.

**4 GB RAM.** Estimated memory use per container:

| Container | Typical use | Why |
|---|---|---|
| `db` (PostgreSQL 17) | 150–300 MB | Default settings (128 MB shared buffers), about 5 connections |
| `web` (gunicorn, 3 workers) | 250–400 MB | About 80–120 MB per worker |
| `worker` | ~100 MB | One Django process sending and reading email |
| `proxy` (Caddy) | 30–50 MB | Plus up to 60 MB per upload in progress (it holds each upload until it's complete) |
| Linux, Docker, SSH | ~500 MB | |
| **Total** | **~1–1.5 GB** | |

The rest is headroom for building a new version next to the running one, the
nightly backup, and the file cache that keeps PostgreSQL fast.

**80 GB disk.** One virtual disk is fine. What uses it:

| What | Size | Grows? |
|---|---|---|
| Linux, Docker, the app's images and build cache | 10–15 GB | Slowly, with each update (old images can be pruned) |
| Container logs | Up to 0.4 GB | No: capped at 100 MB per container (`compose.prod.yaml`) |
| Database | Under 0.1 GB at first | About 0.3 GB a year |
| Attachments (`media` volume) | 0 | **About 2 GB a year** expected, up to 6 GB if heavy (see below) |
| Backups | 14 nightly copies | **About 14 × the attachments**, plus the database dumps |

Attachment estimate: about 200 tickets a month from 300 people, 30% of them
with attachments, averaging 2 files of 1.5 MB (screenshots, phone photos,
PDFs) is about 180 MB a month, or 2 GB a year. Heavy use (big photos, log
archives) could triple that.

Every nightly backup holds a full copy of the attachments, so backups are
the biggest use of disk:

| Attachments stored | Backups (14 nights) | Disk used in total |
|---|---|---|
| 1 GB | ~14 GB | ~30 GB |
| 2 GB | ~28 GB | ~45 GB |
| 4 GB | ~56 GB | ~75 GB: nearly full |

So 80 GB lasts about **two years** at the expected rate, or eight months if
use is heavy. The nightly backup logs a warning once the disk is 80% full.
Before that happens, grow the virtual disk, or give the backups their own
disk, or switch the attachment backups to incremental copies (a later
improvement). Check disk use monthly ([deployment.md](deployment.md#11-routine-checks)).

## Operating system

- **Ubuntu Server LTS** (24.04 or 26.04), or **Debian stable** (13), as long
  as Docker's [install page](https://docs.docker.com/engine/install/) lists it.
  A minimal install with the OpenSSH server.
- **Docker Engine and the Docker Compose plugin from Docker's own apt
  repository** (`docker-ce`, `docker-compose-plugin`). Both are free and open
  source. Compose 2.24 or later is required.
- **Not Docker Desktop.** It is meant for PCs, not servers, and a company
  McKenna Labs' size needs a paid subscription for it.
- Not Ubuntu's own `docker.io` or snap packages: they lag behind, and the
  snap can't see `/srv`.

## Network

| What | Detail |
|---|---|
| IP address | Static, or a DHCP reservation |
| DNS | Internal A record `helpdesk.mckennalabs.com` → the server. No public DNS record |
| Inbound TCP 443 | From the LAN and VPN ranges: the app (HTTPS) |
| Inbound TCP 80 | From the same ranges. Only redirects to 443 |
| Inbound TCP 22 (SSH) | From IT admins' machines or jump host only |
| Everything else inbound | Blocked. No port forwarding or NAT from the internet |

Docker opens 80 and 443 itself, in a way the server's own firewall (ufw)
doesn't filter. So **limit 80 and 443 to the LAN and VPN on the network
firewall** in front of the server. ufw on the server still protects SSH.

Outbound, HTTPS (TCP 443) unless noted:

| Destination | Why |
|---|---|
| `login.microsoftonline.com` | Microsoft 365 sign-in, and tokens for Graph |
| `graph.microsoft.com` | Sending email, and reading the help-desk mailbox |
| `registry-1.docker.io`, `auth.docker.io`, `production.cloudflare.docker.com` | Docker Hub images (Python, PostgreSQL, Caddy) when installing and updating |
| `download.docker.com` | Docker's apt repository |
| `pypi.org`, `files.pythonhosted.org` | Python packages, while building the app |
| `github.com`, TCP 22 (or `ssh.github.com` on 443) | Fetching the code with the deploy key |
| Ubuntu or Debian mirrors, TCP 80 or 443 | Operating system updates |
| The company's time servers, UDP 123 | Time sync |
| Internal DNS, UDP/TCP 53 | Name lookups |

Don't route the Microsoft hosts through TLS inspection: the app doesn't trust
an inspection certificate, so sign-in and email would fail. If outbound
traffic must go through a web proxy, tell whoever deploys the app: Docker and
the app then need extra settings.

## Time

Run **chrony** (or systemd-timesyncd) against the company's time servers.
Microsoft's sign-in tokens allow only two minutes of clock difference: a
server clock further off than that makes everyone's sign-in fail. The
containers use the server's clock.

## Certificate

From the internal CA:

- Issued for `helpdesk.mckennalabs.com`, with that name in the **Subject
  Alternative Name** (browsers ignore the Common Name).
- RSA 2048-bit key or stronger, **without a passphrase** (the proxy starts
  unattended). The key is created on the server and never leaves it.
- PEM files: `fullchain.pem` (the server certificate first, then the
  intermediate certificates; the root isn't needed) and `privkey.pem`.
- On the server in `/srv/inh-ticketing/certs/`: the folder `750` and
  `privkey.pem` `600`, both owned by root; `fullchain.pem` `644`. The proxy
  reads them read-only.
- Company PCs must trust the internal root certificate (normally through
  Group Policy or Intune). Devices that don't, such as personal phones, show
  a certificate warning.
- **Track renewal.** Note the expiry date and put a reminder 30 days before
  it, with a named owner. Because of HSTS, browsers won't let anyone click
  past an expired certificate: the help desk stops working for everyone.

## Accounts and access

- **One non-root admin account** (this guide calls it `inhadmin`) with sudo,
  in the `docker` group, using SSH keys (password login off). Membership of
  `docker` is equivalent to root, so only for admins.
- The app lives in `/srv/inh-ticketing/` and runs, and is backed up, as that account.
- **A read-only GitHub deploy key** for the private InH-Ticketing repository,
  created on the server. It can fetch this one repository and nothing else.
- Microsoft 365: nothing is installed on the server. An Entra admin adds the
  server's address and a separate client secret ([deployment.md](deployment.md#4-microsoft-entra)).

## Not needed

- A public IP address, public DNS, port forwarding, or Let's Encrypt.
- A GPU.
- A Windows Server licence, or a Docker Desktop subscription.
- A separate database server: PostgreSQL runs in a container on this VM.
- A mail server or SMTP relay: email goes through Microsoft Graph.
- A load balancer or another reverse proxy: Caddy is included.

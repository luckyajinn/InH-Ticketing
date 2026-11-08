# Stress-test VM: step by step

Every command, from an empty Proxmox VM to the finished reports. Setup takes
about 45 minutes; the tests take about 45 more. Everything uses invented
data. Background and how to read the results: [README.md](README.md).

Commands marked **VM** run on the VM over SSH; **PC** means Git Bash on your
PC, in the repository folder.

## 1. Create the VM (Proxmox)

You need a Debian 13 netinst ISO uploaded to the Proxmox host.

**Create VM**, with these settings (anything not listed: leave the default):

| Tab | Setting |
|---|---|
| General | Name `inh-stress` |
| OS | The Debian 13 ISO |
| Disks | 40 GB |
| CPU | 1 socket, **4 cores**, Type **host** |
| Memory | **8192 MB**; open Advanced and untick **Ballooning Device**, so the VM really has 8 GB |
| Network | Your usual bridge, VirtIO |

Start it and install Debian from the console:

- **Leave the root password empty.** Debian then installs `sudo` and gives
  it to the user you create next (the steps below say `you`).
- Software selection: only **SSH server** and **standard system utilities**.

When it has rebooted, note its address from the console: `ip -4 addr`.

Why 4 cores: the app shares CPUs 0 and 1 (the planned production server's
size), and the simulated users get CPUs 2 and 3, so they don't take CPU time
from the app.

## 2. Basics (VM)

```bash
ssh you@<the VM's address>          # PC, then the rest on the VM
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl openssl tmux
nproc        # 4
free -h      # about 7.7Gi total
```

## 3. Tailscale (VM, recommended)

The test site signs everyone in automatically as fake users, so it's
published only on the VM's Tailscale address, never your home network.
Skip this step and the tests still run; you just can't open the site from
your PC.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up            # open the link it prints and approve the VM
tailscale ip -4              # 100.x.y.z: note it
```

In the Tailscale admin page you can rename the machine `inh-stress`; with
MagicDNS on, `ssh you@inh-stress` then works from your PC.

## 4. Docker (VM)

From Docker's own repository (if a step fails, compare with
[docs.docker.com/engine/install/debian](https://docs.docker.com/engine/install/debian/)):

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
sudo mkdir -p /srv/inh-stress && sudo chown "$USER" /srv/inh-stress
exit         # sign in again, so the docker group applies
```

Check, after signing in again:

```bash
docker compose version      # 2.24.4 or later
docker run --rm hello-world # "Hello from Docker!"
```

## 5. Send the code and set it up (PC)

In Git Bash, in the repository folder:

```bash
git switch stress-test
git pull
sh stress/push-to-server.sh you@inh-stress     # or you@<the VM's address>
```

It asks for the VM password twice (copying, then setting up) unless you use
an SSH key. It sends the branch's last commit, then on the VM:

1. checks Docker and openssl, and that the VM has 4 CPUs;
2. writes a stress-test `.env` with random passwords and no Microsoft 365 or
   email settings;
3. publishes the site on the Tailscale address only;
4. makes a self-signed certificate;
5. builds and starts the app (5–10 minutes the first time);
6. generates the fake data (about a minute: 12,000 tickets, about 2 GB of
   files) and saves it as the starting point every run resets to.

It ends with **Ready.** and the data counts.

**Optional: look at it.** On your PC, edit
`C:\Windows\System32\drivers\etc\hosts` as administrator and add
`100.x.y.z   inh-stress.test` (the Tailscale address). Open
https://inh-stress.test and accept the certificate warning. You're the fake
IT agent; add `?as=stress-req-0001` to the address to be a staff member.

## 6. Run the tests (VM)

First a short trial, to check everything works (about 3 minutes):

```bash
ssh you@inh-stress
cd /srv/inh-stress
sh stress/run.sh --quick
```

It should end with `=== expected: PASS. Report: stress/reports/...`. A FAIL
with numbers is a result, not a breakdown; `RUN FAILED` is a breakdown (see 8).

Then the full set, inside tmux so it carries on if SSH drops (about 45 minutes):

```bash
tmux new -s stress
sh stress/run.sh all
```

Leave tmux with **Ctrl+B, then D**; come back with `tmux attach -t stress`.
Each run first resets the data to the starting point (a few seconds).

Optional, overnight: `sh stress/run.sh soak` (normal load for 2 hours, to
catch slow leaks).

## 7. Get the reports (PC)

```bash
scp -r you@inh-stress:/srv/inh-stress/stress/reports ./stress-reports
```

Open each folder's `report.html` in a browser. The answers to "are 2 CPUs and
4 GB enough?":

- **expected** (a normal busy period): PASS, and in **Server resources** the
  **whole app** row's average CPU well under 50%, peak memory well under 3.5 GB.
- **peak** (a company-wide outage): PASS shows there's headroom.
- **stress**: the capacity line, e.g. "up to 250 people active at the same
  time", against the 35 of a normal busy period.

## 8. If something goes wrong

| What you see | What to do |
|---|---|
| `this machine has N CPUs` | The VM needs 4 cores (step 1) |
| `Docker Compose ... is too old` | Install Docker from Docker's repository (step 4), not Debian's `docker.io` |
| `permission denied ... docker.sock` | Sign out and in again after step 4 (the docker group) |
| `the app didn't become ready` | `cd /srv/inh-stress && docker compose -f compose.yaml -f compose.prod.yaml -f compose.stress.yaml logs --tail 100 web` |
| `RUN FAILED` or a report with failures | Look in `stress/reports/<folder>/locust-console.log` |
| The site doesn't open from the PC | Tailscale on both, and the hosts line (step 5) |
| After the VM restarts | `sh stress/server-setup.sh` again (the Tailscale address may come up after Docker) |
| `ValueError: I/O operation on closed file` at the end of a Locust log | Harmless: Locust closing its files; the results are complete |

To get help, bring back the message, the `locust-console.log`, and the
`logs web` output above.

## 9. Afterwards (VM)

```bash
cd /srv/inh-stress
sh stress/server-setup.sh --down     # stops it and deletes its data; reports stay
```

Then delete the VM in Proxmox when you no longer need the reports.

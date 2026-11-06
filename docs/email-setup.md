# Email setup

InH-Ticketing emails people when something happens on their ticket. Emails
are queued in the database and sent by a separate **background worker**, so
saving a ticket never waits on, or fails because of, the mail system.

## Who gets what

| Event | Email goes to |
|---|---|
| A request is submitted | The requester (a receipt), plus `IT_NOTIFY_EMAIL` if set |
| IT posts a public reply | The requester |
| The requester replies or reopens | The assignee, or `IT_NOTIFY_EMAIL` if unassigned |
| A ticket is assigned | The new assignee (not when people assign themselves) |
| IT resolves a ticket | The requester |

Internal notes never send an email and never appear in one. Nobody is
emailed about their own action. All emails about a ticket share the subject
`[#1001] <subject>`, so mail apps group them into one conversation.

Replies to these emails aren't read by the app yet (that's milestone 4), and
every email says so.

## 1. On your PC: nothing is sent

The default is `EMAIL_BACKEND=file`: emails are written to the `tmp/emails/`
folder instead of being sent. Run the worker in a second terminal, next to the server:

```powershell
.\.venv\Scripts\python.exe manage.py run_worker
```

Create a ticket or post a reply. Within 15 seconds the worker prints
`Emails: 1 sent`, and a new `.log` file appears in `tmp/emails/`; open it in
any text editor. Use `EMAIL_BACKEND=console` to see emails in the worker's
terminal instead.

The **admin site → Outbound emails** lists every email with its status. A
failed email shows the error there, and the *Retry selected emails now*
action queues it again.

## 2. Settings in `.env`

| Setting | Example | Meaning |
|---|---|---|
| `SITE_URL` | `http://localhost:8000` | Address used for links in emails |
| `HELPDESK_MAILBOX` | `helpdesk-test@mckennalabs.com` | The shared mailbox emails come from |
| `IT_NOTIFY_EMAIL` | `it-team@mckennalabs.com` | Optional: where IT's alerts go (a distribution list or Teams channel address) |
| `EMAIL_BACKEND` | `file`, `console` or `graph` | How emails leave the app |

## 3. Sending for real through Microsoft 365

This uses the same app registration as sign-in, with permission to send as
**one shared mailbox and nothing else**. Use the **test** shared mailbox,
never the live help-desk one, until the pilot is over.

### 3a. The shared mailbox

In the **Exchange admin center → Recipients → Mailboxes → Add a shared
mailbox**, create `helpdesk-test@…` if it doesn't exist. Shared mailboxes don't need a license.

### 3b. Don't add Mail.Send in Entra

> Do **not** add *Mail.Send* under the app registration's **API permissions**.
> An Entra application permission covers **every mailbox in the company**, and
> Exchange's restriction (below) can't narrow a permission Entra has already
> granted, because the two add together. If Mail.Send is there, remove it.

### 3c. Allow the app to send as the test mailbox only

In PowerShell, using an Exchange admin account:

```powershell
Install-Module ExchangeOnlineManagement -Scope CurrentUser   # once
Connect-ExchangeOnline
```

You need two IDs, both from **Entra → Enterprise applications → InH-Ticketing (Test) → Overview**:

- **Application ID:** the same value as `ENTRA_CLIENT_ID`.
- **Object ID:** the *enterprise application's* Object ID. This is **not** the
  Object ID on the App registration page; the two are different.

```powershell
$appId    = "<Application ID>"
$objectId = "<Enterprise application Object ID>"
$mailbox  = "helpdesk-test@mckennalabs.com"

# 1. Introduce the app to Exchange
New-ServicePrincipal -AppId $appId -ObjectId $objectId -DisplayName "InH-Ticketing (Test)"

# 2. A scope that contains only the test mailbox
New-ManagementScope -Name "InH-Ticketing test mailbox" `
  -RecipientRestrictionFilter "PrimarySmtpAddress -eq '$mailbox'"

# 3. Let the app send mail, but only inside that scope
New-ManagementRoleAssignment -App $appId -Role "Application Mail.Send" `
  -CustomResourceScope "InH-Ticketing test mailbox"

# 4. Check: InScope should be True for the test mailbox, False for anyone else
Test-ServicePrincipalAuthorization -Identity $appId -Resource $mailbox
Test-ServicePrincipalAuthorization -Identity $appId -Resource "someone.else@mckennalabs.com"
```

New permissions can take **up to a couple of hours** to start working.

### 3d. Switch the app over

In `.env`:

```
EMAIL_BACKEND=graph
HELPDESK_MAILBOX=helpdesk-test@mckennalabs.com
```

Restart the server and the worker. Create a test ticket for yourself: the
worker should print `Emails: 1 sent`, the receipt should arrive in your inbox,
and a copy should be in the shared mailbox's **Sent Items**.

### Troubleshooting

The error appears in the worker's terminal and on the email in the admin site.

| Error | Meaning | Fix |
|---|---|---|
| `Graph returned 403: ErrorAccessDenied` | The app isn't allowed to send as that mailbox, or the permission hasn't taken effect yet | Re-run step 4 of 3c; wait an hour |
| `Couldn't get a Graph token: invalid_client` | Client secret wrong or expired | Same fix as for sign-in |
| `Graph returned 404` / `MailboxNotEnabledForRESTAPI` | The address isn't an Exchange Online mailbox | Check `HELPDESK_MAILBOX` |
| Email stays *Pending* | The worker isn't running | Start `manage.py run_worker` |

## On the server (Docker)

`compose.yaml` runs the worker as its own `worker` container, so it starts and
restarts with the app. Run exactly one worker.

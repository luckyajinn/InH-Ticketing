# Email setup

InH-Ticketing emails people when something happens on their ticket
(sections 1–3), and can turn emails to the help-desk mailbox into tickets and
replies (section 4, *email-in*). Both are handled by a separate **background
worker**, so saving a ticket never waits on, or fails because of, the mail system.

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

An email from someone other than the requester, saved as an internal note
(see section 4), alerts the assignee too.

Each email's footer says what replying does. With email-in off: "replies
aren't added to the ticket yet". With it on, requesters are told to keep
`[#1001]` in the subject, and IT is warned that replying **posts a public reply
the requester will see**.

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

**Accept internal senders only.** InH-Ticketing is for internal staff (see
[usage-rules.md](usage-rules.md)), so make the mailbox refuse email from outside
the company. Outside senders then get a bounce from Exchange, and their email
never reaches the app. In the Exchange admin center, open the mailbox, go to
**Mail flow settings → Message delivery restrictions**, and tick **Require
that all senders are authenticated**. Or in Exchange Online PowerShell:

```powershell
Set-Mailbox -Identity "helpdesk-test@mckennalabs.com" -RequireSenderAuthenticationEnabled $true
```

To check, send an email to the mailbox from a personal (non-company) account.
It should bounce.

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

---

## 4. Email in: emails become tickets and replies

With `INBOUND_EMAIL=graph`, the worker reads the help-desk mailbox's Inbox
every minute. Each email is handled once, then marked read and moved to a
**Processed by InH-Ticketing** folder.

### What happens to an email

| The email | What the app does |
|---|---|
| An out-of-office reply, bounce, or mailing-list email | Ignores it, so mail can't loop |
| From an address outside your domain, or from the help-desk mailbox itself | Ignores it and **sends nothing back**. Replying to unknown senders would bounce mail at whoever's address was forged |
| Subject has `[#1028]`, from the requester or IT | Adds a **public reply** to #1028. Only the new text is kept, not the quoted history. A requester's reply moves *Waiting on User* back to *Open*, as on the web |
| Subject has `[#1028]`, from anyone else (a manager, say) | Adds an **internal note** that only IT sees, and alerts the assignee |
| Subject has `[#1028]` but #1028 is Closed | Starts a **new ticket** that says it follows up #1028 |
| Anything else | Creates a **new ticket**. Category: *Other*; the requester gets the usual receipt |

- **New senders:** colleagues who have never signed in get an account
  automatically, and it's linked to their Microsoft 365 account the first time
  they sign in, so their tickets follow them.
- **Attachments:** the same rules as on the web: allowed file types, 10 MB
  each, up to 5. Pictures inside signatures are skipped. Anything left out is
  listed at the end of the message.
- **Text only:** the app asks Microsoft for plain text and never stores HTML
  from outside.
- **Every email is recorded** in the admin site under **Inbound emails**, with
  what happened and why. An email that fails is retried up to 3 times; then
  it's marked read and left in the Inbox for a person to deal with.

### 4a. Try it on your PC first

The `ingest_email` command puts an email through exactly the same rules,
without Microsoft 365:

```powershell
# A new request
.\.venv\Scripts\python.exe manage.py ingest_email --from dana.whitfield@example.invalid --subject "Laptop fan is loud" --body "Sounds like a jet"

# A reply to ticket #1045 (use a real number from your queue)
.\.venv\Scripts\python.exe manage.py ingest_email --from dana.whitfield@example.invalid --subject "RE: [#1045] Outlook" --body "Still happening"

# A saved email: in Outlook, drag a message to the desktop to get a .eml file
.\.venv\Scripts\python.exe manage.py ingest_email C:\path\to\message.eml
```

With `HELPDESK_MAILBOX` blank (as on your PC), email from any domain is accepted.

### 4b. Let the app read the test mailbox

Reading, marking read and moving email needs one more Exchange permission,
scoped to the **same** management scope as sending (section 3c). In the same
Exchange Online PowerShell session:

```powershell
New-ManagementRoleAssignment -App $appId -Role "Application Mail.ReadWrite" `
  -CustomResourceScope "InH-Ticketing test mailbox"

# Check again: InScope True for the test mailbox, False for anyone else
Test-ServicePrincipalAuthorization -Identity $appId -Resource $mailbox
Test-ServicePrincipalAuthorization -Identity $appId -Resource "someone.else@mckennalabs.com"
```

As before, don't add *Mail.ReadWrite* under API permissions in Entra, because
that would cover every mailbox in the company.

### 4c. Switch it on

In `.env`:

```
INBOUND_EMAIL=graph
HELPDESK_MAILBOX=helpdesk-test@mckennalabs.com
# Optional; defaults to the mailbox's own domain
INBOUND_ALLOWED_DOMAINS=mckennalabs.com
```

Restart the worker. It should print `Email-in: reading helpdesk-test@… every 60s`.
Email the test mailbox from your own account: within a minute it shows up in the
queue, and you get a receipt.

### Things to know

- **Sender addresses can be forged.** The domain check relies on Exchange's
  spam and spoofing protection: SPF, DKIM and DMARC on your domain. IT should
  confirm DMARC is enforced before email-in is used for anything sensitive.
- **IT replying by email sends a public reply.** The footer of every IT email
  says so. For an internal note, use the ticket page.
- **Only the test mailbox.** Pointing this at the live help-desk mailbox turns
  every email in it into a ticket. Switch over only when the pilot ends.

### Troubleshooting email-in

| Worker prints | Meaning | Fix |
|---|---|---|
| `Inbox: couldn't read it (GraphError: Graph GET returned 403 ...)` | The app can't read the mailbox | Step 4b; allow time for the permission to apply |
| `Email-in: off` | `INBOUND_EMAIL` isn't `graph` | Set it in `.env` and restart the worker |
| Emails stay unread, admin shows *Error* | Processing failed | Read the error in **Inbound emails**; it retries 3 times |
| An email was ignored | It was automatic, or from another domain | The reason is in **Inbound emails** |

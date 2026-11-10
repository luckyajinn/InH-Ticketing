# Microsoft 365 (Entra ID) setup

This connects InH-Ticketing to McKenna Labs' Microsoft 365 sign-in. It takes
about 15 minutes in the [Microsoft Entra admin center](https://entra.microsoft.com).
You need rights to create app registrations and assign enterprise apps.

When you're done, you'll have four values for `.env`:

| `.env` setting | Where it comes from |
|---|---|
| `ENTRA_TENANT_ID` | App registration → Overview → **Directory (tenant) ID** |
| `ENTRA_CLIENT_ID` | App registration → Overview → **Application (client) ID** |
| `ENTRA_CLIENT_SECRET` | Certificates & secrets → the secret's **Value** |
| `ENTRA_REDIRECT_URI` | Leave as `http://localhost:8000/auth/callback` on your PC |

> Never paste the client secret into chat, email or a ticket. It only goes in `.env`.

---

## 1. Register the app

1. Go to **Entra ID → App registrations → New registration**.
2. **Name:** `InH-Ticketing (Test)`
3. **Supported account types:** *Accounts in this organizational directory only (Single tenant)*.
4. **Redirect URI:** platform **Web**, value `http://localhost:8000/auth/callback`.
   Type it exactly: `localhost`, not `127.0.0.1`, and no trailing slash.
5. Select **Register**.
6. On the **Overview** page, copy the **Application (client) ID** and the
   **Directory (tenant) ID** into `.env`.

## 2. Create a client secret

1. **Certificates & secrets → Client secrets → New client secret.**
2. Description `local dev`. Choose an expiry; 6 months is fine for a test.
3. Copy the **Value** column right away into `ENTRA_CLIENT_SECRET` in `.env`.
   It is shown only once. The *Secret ID* column is not the secret.
4. Put a calendar reminder a week before it expires. An expired secret shows
   up as error `AADSTS7000222` and nobody can sign in.

## 3. Define the app roles

**App roles → Create app role**, once for each:

| Display name | Allowed member types | Value | Description |
|---|---|---|---|
| Requester | Users/Groups | `Requester` | Can submit and follow their own tickets |
| Agent | Users/Groups | `Agent` | IT staff who work IT's tickets |
| Mechanics Agent | Users/Groups | `Agent.Mechanics` | Mechanics staff who work Mechanics' tickets |
| C&S Agent | Users/Groups | `Agent.Cleaning` | Cleaning & sanitization staff who work their tickets |
| Admin | Users/Groups | `Admin` | Sees and works every department's tickets, moves tickets between departments, Reports and the admin site |

Leave **Do you want to enable this app role?** ticked for each.

The **Value** is what appears in the sign-in token and is what the app checks.
If you use different values, set `ENTRA_ROLE_AGENT`, `ENTRA_ROLE_AGENT_MECHANICS`,
`ENTRA_ROLE_AGENT_CLEANING` and `ENTRA_ROLE_ADMIN` to match. Anyone with none of
them is treated as a Requester.

**Departments.** An agent sees and works only their own department's tickets
(each category belongs to a department, set in the admin site); an admin works
them all. Give the Mechanics and C&S groups their own role. **Never give them
the plain `Agent` role**, which is IT's. Someone with two agent roles works
for the first of IT, Mechanics, Cleaning & sanitization. A role change applies
at the person's next sign-in.

## 4. Grant consent (optional, avoids a prompt)

**API permissions** already lists *Microsoft Graph → User.Read*. Select
**Grant admin consent for McKenna Labs** so testers aren't asked to approve the
app on first sign-in.

## 5. Limit who can sign in

App registrations have a twin under **Enterprise applications** with the same
name. That's where access is controlled.

1. **Entra ID → Enterprise applications → InH-Ticketing (Test) → Properties.**
2. Set **Assignment required?** to **Yes**. Optionally set **Visible to users?**
   to **No** so it doesn't appear in My Apps during the test. **Save**.
3. **Users and groups → Add user/group:**
   - Your test group → role **Requester**.
   - Yourself → role **Admin**.
   - Any IT testers → role **Agent**.

Notes:
- Assigning a **group** needs Entra ID P1 or P2, which is included in Microsoft 365
  Business Premium, E3 and E5. Without it, assign people one at a time.
- Only **direct** members of an assigned group get access. Members of nested groups do not.
- Someone not assigned gets a friendly "you haven't been given access" page
  (Entra error `AADSTS50105`).

## 6. Try it

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver
```

Open <http://localhost:8000> and sign in. The header should show your name and
an **Admin** badge, and the home page offers a link to the admin site.

Role changes in Entra take effect the next time the person signs in. To see a
change straight away, sign out of InH-Ticketing and back in.

---

## Moving to the server

Step by step in [deployment.md](deployment.md#4-microsoft-entra). In short:

- Add a second **Web** redirect URI: `https://helpdesk.mckennalabs.com/auth/callback`,
  and set `ENTRA_REDIRECT_URI` to it in the server's `.env`. Entra only allows
  plain `http://` for `localhost`, so the server needs HTTPS.
- Use a separate client secret per environment, so you can revoke one without
  breaking the other.
- A certificate credential instead of a secret would be better still on the
  server, but the app doesn't support one yet (a later improvement).

## Troubleshooting

| Error | Meaning | Fix |
|---|---|---|
| `AADSTS50011` | Redirect URI mismatch | `ENTRA_REDIRECT_URI` must match the registration exactly, including `localhost` vs `127.0.0.1` and any trailing slash. |
| `AADSTS50105` | Person isn't assigned to the app | Add them, or their group, under Enterprise applications → Users and groups. |
| `AADSTS7000215` | Wrong client secret | Paste the secret's **Value**, not its Secret ID. |
| `AADSTS7000222` | Client secret expired | Create a new secret and update `.env`. |
| `AADSTS700016` | App not found in tenant | Check `ENTRA_CLIENT_ID` and `ENTRA_TENANT_ID`. The tenant ID is a GUID, not a domain. |
| "Your sign-in session expired" | The browser lost the session mid-sign-in | Sign in again. If it keeps happening, check that cookies aren't blocked for localhost. |
| Everyone shows as Requester | Roles missing from the token | Check the role **Values** match `.env`, and that the person or their group is assigned a role, not *Default Access*. |

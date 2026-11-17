# Company copies

*For the owner only. This file, `scripts/publish_copy.py` and
`scripts/release_body.py` are left out of every copy.*

Each company that uses InH-Ticketing gets its own copy:

- **What it is:** a private repository in the owner's GitHub organization.
- **Who can read it:** the company's named people (the **Read** role), and
  its server through a read-only deploy key.
- **Who can change it:** only the owner. The people with Read access can't
  change it.
- **What's in it:** one commit per release the owner chooses to give that
  company, with none of this repository's history, branches or owner-only files.

This repository stays the owner's private workshop. The first copy is for
the company the app was built for (decided 2026-11-16); the same steps work
for any company later.

## Setting up a company (once)

On GitHub, signed in as the owner:

1. **The organization** (only the first time): github.com → your picture →
   **Your organizations** → **New organization** → **Free**. The owner's
   account is its owner. Then, in the organization's **Settings → Member
   privileges**:
   - set **Base permissions** to **No permission**;
   - untick **Allow forking of private repositories**;
   - allow **deploy keys**. A new organization may have them switched off,
     and then the company's server key can't be added to its copy (step 5).
2. **The repository:** in the organization, **New repository**, named
   `InH-Ticketing-<Company>`:
   - **Private**;
   - no README, licence or .gitignore, so it starts empty.
3. **The first release**, from this PC:
   ```bash
   python scripts/publish_copy.py --to <org>/InH-Ticketing-<Company> --tag vX.Y.Z           # check what goes
   python scripts/publish_copy.py --to <org>/InH-Ticketing-<Company> --tag vX.Y.Z --push    # send it
   ```
4. **The company's people:**
   - Open the repository's **Settings → Collaborators and teams → Add people**.
   - Add each person, by GitHub username or email, with the role **Read**.
   - They need a GitHub account; a free one does.
   - Read means they can browse and download the code and the release notes.
     They can't push, change settings, or see any other repository.
5. **The company's server.** A deploy key can belong to only one repository.
   1. Remove the server's key from wherever it is now (for the first company,
      this repository: **Settings → Deploy keys**).
   2. Add the same `.pub` line to the copy's **Settings → Deploy keys**, read-only.
   3. On the server, point the checkout at the copy, then update as usual
      (deployment.md section 10). `.env` isn't tracked, so it stays:
      ```bash
      cd /srv/inh-ticketing/app
      git remote set-url origin git@github-inh:<org>/InH-Ticketing-<Company>.git   # the SSH alias, deployment.md section 2
      git fetch --tags origin
      ```
      If the checkout already has tags from the owner's repository, the
      fetch can refuse a tag with the same name ("would clobber existing
      tag"), because the copy's tags are new commits. Either:
      - run `git describe --tags` to see what's checked out, then
        `git tag -d <tag>` for each other tag the fetch refused (never the
        checked-out one), then `git fetch --tags origin` again; or
      - simpler, re-clone from the copy, and copy the old `.env` back.

      Then `git checkout vX.Y.Z`. [deployment.md](deployment.md) section 2.1
      covers the same thing.

## Each release

After a release is tagged here (docs/releases/README.md), send it to each
company that should have it:

```bash
python scripts/publish_copy.py --to <org>/InH-Ticketing-<Company> --tag vX.Y.Z --push
```

The tool:
- adds one commit on top of what the copy has, with an annotated tag of the
  same name;
- points links to this repository at the copy;
- leaves out the owner-only files;
- sends nothing if the copy already has exactly that release.

**Documentation-only updates** (a version ending in a letter, such as
v0.10.7c) go the same way, with that version:

```bash
python scripts/publish_copy.py --to <org>/InH-Ticketing-<Company> --tag vX.Y.Za --push
```

The version is a release that's an annotated tag here, plus one lowercase
letter: `vX.Y.Za`, and later ones use the next letter (`b`, `c`, …). The
base release must exist as a tag.

It sends what's committed on `main` (or `--ref`). Uncommitted changes aren't
sent, and `main` doesn't need to be pushed first. The tool refuses
if anything but the documents (`docs/`, `CHANGELOG.md`, `README.md`, and
the `.env.example` sample) changed
since the release, so a change to the app always needs a release. If the
app's own files changed (say, a fix listed under Unreleased), pass `--ref`
with the last documentation commit before that fix, or wait for the next
release. The copy's
`main` gets the documents, with no tag: its tags stay the releases a server
can check out.

Before sending, it checks the copy against the owner's local list of words
that must never leave this PC, `.git/info/copy-forbidden`: internal host
names, addresses, people's names. It isn't committed, so make one on any
new PC. It refuses if one is found and names the file, not the word.
- Matching ignores case. Lines starting with `#` are comments.
- It checks the copy before links are pointed at it, so the copy's own name
  may contain a listed word. It runs on dry runs too.
- If the file is missing, nothing is checked and the copy is still sent, after
  a printed note. So make the file on every PC before the first send.

Old release notes in the copy point at release pages that only exist here.
The notes themselves are in the copy, under `docs/releases/`.

## Control

- **Updates:** a company's server only gets what the owner sends to its copy.
- **Stopping updates:** remove the deploy key from the copy. The server keeps
  running the release it has.
- **Stopping someone's access:** remove them from the copy's collaborators.
  What they already downloaded stays with them, so the company's written
  terms (LICENSE, and the agreement it signs) are what limit its use.
- **Leaving a company:** the checklist is the same as before, applied to the
  copy: its deploy key, its collaborators, and the PC's GitHub sign-in.

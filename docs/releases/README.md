# Release notes

One page per version, each with screenshots of what changed. Newest first.

| Version | What | Notes |
|---|---|---|
| v0.2.0 | Tickets: queue, requests, replies, internal notes, history, attachments | [v0.2.0.md](v0.2.0.md) |
| v0.1.0 | Skeleton and Microsoft 365 sign-in | [v0.1.0.md](v0.1.0.md) |

The short list of changes per version is in [CHANGELOG.md](../../CHANGELOG.md).

## Writing notes for a new version

Every commit that changes the app gets its notes and screenshots in the same commit.

1. Bump `__version__` in `config/__init__.py` and add a section to `CHANGELOG.md`.
2. Load demo data and start the dev server:

   ```powershell
   pip install -r requirements-dev.txt      # once
   python manage.py seed_demo --clear       # skip --clear the first time
   python manage.py seed_demo
   python manage.py runserver
   ```

3. In a second terminal, take the screenshots:

   ```powershell
   python manage.py release_screenshots --out docs/releases/vX.Y.Z
   ```

   The command is in `core/management/commands/release_screenshots.py`. When a
   version adds a new screen, add a `shoot(...)` line for it there.
4. Write `docs/releases/vX.Y.Z.md`: what changed and why, a screenshot of each
   changed screen, and anything not done yet. Add a row to the table above.

Screenshots only ever use the fictional demo data, never real tickets or people.

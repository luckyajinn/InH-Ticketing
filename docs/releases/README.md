# Release notes

One page per version, each with screenshots of what changed. Newest first.

| Version | What | Notes |
|---|---|---|
| v0.7.0 | The new look, the password check with its audit trail, folded email signatures | [v0.7.0.md](v0.7.0.md) |
| v0.6.0 | Deployment package: HTTPS proxy, backups, server guides | [v0.6.0.md](v0.6.0.md) |
| v0.5.0 | Auto-close, follow-ups, FDA usage controls | [v0.5.0.md](v0.5.0.md) |
| v0.4.0 | Email in: emails become tickets and replies | [v0.4.0.md](v0.4.0.md) |
| v0.3.0 | Outbound email, worker, "Send and resolve" buttons | [v0.3.0.md](v0.3.0.md) |
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
   python manage.py release_screenshots --out docs/releases/vX.Y.Z --only 06,10
   ```

   `--only` takes the numbers of the screens that changed (leave it off to take
   all of them). The command is in `core/management/commands/release_screenshots.py`;
   when a version adds a new screen, add a `shoot(...)` line for it there.
4. Write `docs/releases/vX.Y.Z.md`: what changed and why, a screenshot of each
   changed screen, and anything not done yet. Add a row to the table above.
5. Once the version is merged into `main` and pushed, tag it and publish it on
   GitHub's Releases page. The script rewrites the notes' relative links so the
   screenshots still show there.

   ```powershell
   git tag -a vX.Y.Z -m "vX.Y.Z: <title>"
   git push origin vX.Y.Z
   .\.venv\Scripts\python.exe scripts\release_body.py . tmp\release vX.Y.Z
   gh release create vX.Y.Z --verify-tag --title "<title>" --notes-file tmp\release\vX.Y.Z.md
   ```

   Then change the version's heading in `CHANGELOG.md` from *(unreleased)* to
   its date, and add its link at the bottom of the file.

Published releases: <https://github.com/luckyajinn/InH-Ticketing/releases>

Screenshots only ever use the fictional demo data, never real tickets or people.

"""
Turn docs/releases/vX.Y.Z.md into a GitHub release body.

The notes use links relative to the repo (v0.3.0/10-composer.png, ../email-setup.md),
which don't work on GitHub's Releases page. This rewrites them to point at
the files *at a tag*, so they keep working even if files move later.

    python scripts/release_body.py . tmp/release v0.4.0
    gh release create v0.4.0 --verify-tag --title "$(cat tmp/release/v0.4.0.title)" --notes-file tmp/release/v0.4.0.md

Pass several versions, oldest first, to rebuild older releases too. Writes
<out_dir>/<version>.md (body) and <out_dir>/<version>.title.
"""
import re
import subprocess
import sys
from pathlib import Path

repo, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
remote = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                        capture_output=True, text=True, check=True).stdout.strip()
REPO_URL = remote.removesuffix(".git")


def exists_at(ref: str, path: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{ref}:{path}"],
                          capture_output=True).returncode == 0


TAGS = sys.argv[3:]


def ref_for(tag: str, path: str) -> str:
    """The first tag, from this one onward, that has the file. Tags never move."""
    for candidate in TAGS[TAGS.index(tag):]:
        if exists_at(candidate, path):
            return candidate
    return "main"


for tag in sys.argv[3:]:
    text = (repo / "docs" / "releases" / f"{tag}.md").read_text(encoding="utf-8")
    first, _, body = text.partition("\n")
    title = first.lstrip("# ").strip()

    def fix(match):
        label, target = match.group(1), match.group(2)
        if re.match(r"https?://", target):
            return match.group(0)
        if target.startswith("../"):
            path = "docs/" + target[3:]
        else:
            path = "docs/releases/" + target
        ref = ref_for(tag, path)
        url = f"{REPO_URL}/blob/{ref}/{path}"
        if path.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
            url += "?raw=true"
        return f"[{label}]({url})"

    body = re.sub(r"\[([^\]]*)\]\(([^)\s]+)\)", fix, body).strip()
    notes_ref = ref_for(tag, f"docs/releases/{tag}.md")
    body += (f"\n\n---\nFull notes in the repo: [docs/releases/{tag}.md]"
             f"({REPO_URL}/blob/{notes_ref}/docs/releases/{tag}.md) · "
             f"[CHANGELOG]({REPO_URL}/blob/main/CHANGELOG.md)\n")
    (out / f"{tag}.md").write_text(body, encoding="utf-8")
    (out / f"{tag}.title").write_text(title, encoding="utf-8")
    images = body.count("?raw=true")
    print(f"{tag}: '{title}' - {images} images, links resolved against {notes_ref if notes_ref != tag else 'the tag'}")

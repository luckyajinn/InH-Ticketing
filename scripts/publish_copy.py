"""
Publish a release to a company's own copy of the app: a private repository
in the owner's GitHub organization that the company can read but not change.

    python scripts/publish_copy.py --to <org>/<repo> --tag v0.10.7            # dry run: shows what would go
    python scripts/publish_copy.py --to <org>/<repo> --tag v0.10.7 --push     # sends it

Each run adds ONE commit to the copy's `main`, holding the app exactly as it
is at that release, and an annotated tag of the same name. The copy never
gets this repository's history, its other branches, or the owner-only files
listed in OWNER_ONLY below. Links to this repository are pointed at the copy.

Before sending anything, it refuses if the copy would contain any word from
the owner's local list, `.git/info/copy-forbidden` (one per line: internal
host names, addresses, people's names; never committed).

Step by step, with the GitHub side: docs/company-copies.md.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_SLUG = "luckyajinn/InH-Ticketing"
# Files for the owner only: release and copy tools, and the notes about copies.
OWNER_ONLY = ["scripts/publish_copy.py", "scripts/release_body.py", "docs/company-copies.md"]
FORBIDDEN_LIST = ROOT / ".git" / "info" / "copy-forbidden"
_SLUG = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
_TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")


def git(*args: str, env: dict | None = None, input: bytes | None = None, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, input=input,
                            env={**os.environ, **(env or {})})
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr.decode(errors='replace')}")
    return result.stdout.decode("utf-8", errors="replace").strip()


def previous_copy(url: str, ref: str) -> str | None:
    """The copy's current main (fetched into `ref`), or None for an empty repository."""
    result = subprocess.run(["git", "-C", str(ROOT), "fetch", "--quiet", url, f"+refs/heads/main:{ref}"],
                            capture_output=True)
    if result.returncode != 0:
        error = result.stderr.decode(errors="replace")
        if "couldn't find remote ref" in error:
            return None
        raise SystemExit(f"Couldn't read {url}:\n{error}")
    return git("rev-parse", ref)


def build_tree(tag: str, target_slug: str) -> tuple[str, list[str], list[str]]:
    """(tree id, files left out, files whose links were changed) for the copy of `tag`."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git("read-tree", f"{tag}^{{tree}}", env=env)
        files = set(git("ls-files", env=env).splitlines())
        left_out = [path for path in OWNER_ONLY if path in files]
        for path in left_out:
            git("rm", "--cached", "--quiet", "--", path, env=env)
        # Only the files that mention this repository (one `git grep`, not one process per file).
        mentions = {hit.split(":", 1)[1] for hit in
                    git("grep", "-I", "-l", "-F", "-e", SOURCE_SLUG, tag, check=False).splitlines() if hit}
        relinked = []
        for line in git("ls-files", "--stage", env=env).splitlines():
            meta, path = line.split("\t", 1)
            mode, blob, _ = meta.split()
            if mode != "100644" or path not in mentions:
                continue
            data = subprocess.run(["git", "-C", str(ROOT), "cat-file", "blob", blob], capture_output=True,
                                  check=True).stdout
            new_blob = git("hash-object", "-w", "--stdin", input=data.replace(SOURCE_SLUG.encode(),
                                                                                target_slug.encode()))
            git("update-index", "--cacheinfo", f"{mode},{new_blob},{path}", env=env)
            relinked.append(path)
        return git("write-tree", env=env), left_out, relinked


def forbidden_found(tree: str) -> list[str]:
    """'path: word' for each word from the owner's local list that's in the copy."""
    if not FORBIDDEN_LIST.exists():
        return []
    words = [w.strip() for w in FORBIDDEN_LIST.read_text(encoding="utf-8").splitlines()
             if w.strip() and not w.startswith("#")]
    found = []
    for word in words:
        hits = git("grep", "-I", "-i", "-l", "-F", "-e", word, tree, check=False)
        found += [f"{hit.split(':', 1)[1]}: one of the forbidden words" for hit in hits.splitlines() if hit]
    return sorted(set(found))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--to", required=True, help="the copy's repository, <org>/<repo>")
    parser.add_argument("--tag", required=True, help="the release to publish, e.g. v0.10.7")
    parser.add_argument("--push", action="store_true", help="send it (without this, only show what would go)")
    parser.add_argument("--url", help="push somewhere else than github.com (a test repository)")
    args = parser.parse_args()

    if not _SLUG.fullmatch(args.to) or args.to.lower() == SOURCE_SLUG.lower():
        raise SystemExit("--to must be the copy's <org>/<repo>, never this repository.")
    if not _TAG.fullmatch(args.tag) or git("cat-file", "-t", args.tag, check=False) != "tag":
        raise SystemExit(f"{args.tag} isn't an annotated release tag here (vX.Y.Z).")
    url = args.url or f"https://github.com/{args.to}.git"
    tracking = f"refs/copies/{args.to}/main"

    parent = previous_copy(url, tracking)
    tree, left_out, relinked = build_tree(args.tag, args.to)
    files = len(git("ls-tree", "-r", "--name-only", tree).splitlines())
    print(f"Copy of {args.tag} for {args.to}: {files} files.")
    print(f"  Left out (owner only): {', '.join(left_out) or 'none'}")
    print(f"  Links pointed at {args.to}: {', '.join(relinked) or 'none'}")
    print(f"  On top of: {parent[:10] + ' (the copy as it is now)' if parent else 'nothing: the first release there'}")

    problems = forbidden_found(tree)
    if problems:
        print("\nNot sent: the copy would contain words from .git/info/copy-forbidden:")
        for line in problems:
            print(f"  {line}")
        return 1
    if not FORBIDDEN_LIST.exists():
        print("  Note: no .git/info/copy-forbidden list here, so nothing was checked for private words.")
    if parent and git("rev-parse", f"{parent}^{{tree}}") == tree:
        print("\nThe copy already has exactly this. Nothing to send.")
        return 0
    if not args.push:
        print("\nDry run: nothing sent. Add --push to send it.")
        return 0

    message = (f"InH-Ticketing {args.tag}\n\nRelease notes: docs/releases/{args.tag}.md\n\n"
               "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n")
    commit = git("commit-tree", tree, *(["-p", parent] if parent else []), input=message.encode())
    tagger = git("var", "GIT_COMMITTER_IDENT")
    tag_object = git("mktag", input=(f"object {commit}\ntype commit\ntag {args.tag}\ntagger {tagger}\n\n"
                                     f"InH-Ticketing {args.tag}\n").encode())
    git("push", "--quiet", url, f"{commit}:refs/heads/main", f"{tag_object}:refs/tags/{args.tag}")
    git("update-ref", tracking, commit)
    print(f"\nSent: {args.to} main is now {commit[:10]}, tagged {args.tag}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

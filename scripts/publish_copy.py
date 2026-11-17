"""
Publish a release to a company's own copy of the app: a private repository
in the owner's GitHub organization that the company can read but not change.

    python scripts/publish_copy.py --to <org>/<repo> --tag v0.10.7            # dry run: shows what would go
    python scripts/publish_copy.py --to <org>/<repo> --tag v0.10.7 --push     # sends it
    python scripts/publish_copy.py --to <org>/<repo> --tag v0.10.7c --push    # a documentation-only update

Each run adds ONE commit to the copy's `main`, holding the app exactly as it
is at that release, and an annotated tag of the same name. The copy never
gets this repository's history, its other branches, or the owner-only files
listed in OWNER_ONLY below. Links to this repository are pointed at the copy.

A version ending in a letter (v0.10.7c) is a documentation-only update, with
no tag here. It's sent from `main` (or --ref), only if nothing but the
documents changed since its release (v0.10.7). It gets no tag in the copy
either: the copy's tags stay the releases a server can run.

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
_DOCS_VERSION = re.compile(r"^(v[0-9]+\.[0-9]+\.[0-9]+)[a-z]$")
# What a documentation-only update may change, besides the owner-only files.
DOCS_FOLDER = "docs/"
DOCS_FILES = {"CHANGELOG.md", "README.md", ".env.example"}  # .env.example: a sample, never read by the app


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


def not_docs(release: str, ref: str) -> list[str]:
    """Files other than documents that changed between `release` and `ref`."""
    changed = git("diff", "--name-only", release, ref).splitlines()
    return [path for path in changed
            if path not in OWNER_ONLY and not path.startswith(DOCS_FOLDER) and path not in DOCS_FILES]


def build_tree(tag: str, target_slug: str) -> tuple[str, str, list[str], list[str]]:
    """
    (tree id, tree before the links were changed, files left out, files whose
    links were changed) for the copy of `tag`. The private-words check reads
    the second: the copy's own name, which the owner chose, may contain one.
    """
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git("read-tree", f"{tag}^{{tree}}", env=env)
        files = set(git("ls-files", env=env).splitlines())
        left_out = [path for path in OWNER_ONLY if path in files]
        for path in left_out:
            git("rm", "--cached", "--quiet", "--", path, env=env)
        unlinked_tree = git("write-tree", env=env)
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
        return git("write-tree", env=env), unlinked_tree, left_out, relinked


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
    parser.add_argument("--tag", required=True,
                        help="the release to publish, e.g. v0.10.7, or a documentation-only update, e.g. v0.10.7c")
    parser.add_argument("--ref", default="main", help="for a documentation-only update: what to send (default main)")
    parser.add_argument("--push", action="store_true", help="send it (without this, only show what would go)")
    parser.add_argument("--url", help="push somewhere else than github.com (a test repository)")
    args = parser.parse_args()

    if not _SLUG.fullmatch(args.to) or args.to.lower() == SOURCE_SLUG.lower():
        raise SystemExit("--to must be the copy's <org>/<repo>, never this repository.")
    docs_only = _DOCS_VERSION.fullmatch(args.tag)
    if docs_only:
        release = docs_only.group(1)
        if git("cat-file", "-t", release, check=False) != "tag":
            raise SystemExit(f"{release} isn't an annotated release tag here, so {args.tag} has nothing to update.")
        if not git("rev-parse", "--verify", "--quiet", f"{args.ref}^{{commit}}", check=False):
            raise SystemExit(f"{args.ref} isn't a commit here.")
        changed = not_docs(release, args.ref)
        if changed:
            raise SystemExit(f"{args.tag} may change only the documents since {release}, but {args.ref} also "
                             f"changes: {', '.join(changed)}. Make a release instead.")
        source = args.ref
    elif not _TAG.fullmatch(args.tag) or git("cat-file", "-t", args.tag, check=False) != "tag":
        raise SystemExit(f"{args.tag} isn't an annotated release tag here (vX.Y.Z), "
                         "or a documentation-only update of one (vX.Y.Za).")
    else:
        source = args.tag
    url = args.url or f"https://github.com/{args.to}.git"
    tracking = f"refs/copies/{args.to}/main"

    parent = previous_copy(url, tracking)
    tree, unlinked_tree, left_out, relinked = build_tree(source, args.to)
    files = len(git("ls-tree", "-r", "--name-only", tree).splitlines())
    kind = f" (documentation only, from {source}; no tag)" if docs_only else ""
    print(f"Copy of {args.tag}{kind} for {args.to}: {files} files.")
    print(f"  Left out (owner only): {', '.join(left_out) or 'none'}")
    print(f"  Links pointed at {args.to}: {', '.join(relinked) or 'none'}")
    print(f"  On top of: {parent[:10] + ' (the copy as it is now)' if parent else 'nothing: the first release there'}")

    problems = forbidden_found(unlinked_tree)
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

    if docs_only:
        message = (f"InH-Ticketing {args.tag}: documentation only\n\n"
                   f"The app is the same as {release}. What changed: CHANGELOG.md, under {args.tag[1:]}.\n\n")
    else:
        message = f"InH-Ticketing {args.tag}\n\nRelease notes: docs/releases/{args.tag}.md\n\n"
    message += "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
    commit = git("commit-tree", tree, *(["-p", parent] if parent else []), input=message.encode())
    if docs_only:
        git("push", "--quiet", url, f"{commit}:refs/heads/main")
        git("update-ref", tracking, commit)
        print(f"\nSent: {args.to} main is now {commit[:10]} ({args.tag}: documentation only, no tag).")
        return 0
    tagger = git("var", "GIT_COMMITTER_IDENT")
    tag_object = git("mktag", input=(f"object {commit}\ntype commit\ntag {args.tag}\ntagger {tagger}\n\n"
                                     f"InH-Ticketing {args.tag}\n").encode())
    git("push", "--quiet", url, f"{commit}:refs/heads/main", f"{tag_object}:refs/tags/{args.tag}")
    git("update-ref", tracking, commit)
    print(f"\nSent: {args.to} main is now {commit[:10]}, tagged {args.tag}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

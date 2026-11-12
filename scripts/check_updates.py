"""
The monthly update check: known security issues and newer versions of the
app's parts. Standard library only, so it runs anywhere Python does.

On the server, it checks what the running app has installed:

    docker compose -f compose.yaml -f compose.prod.yaml exec web python scripts/check_updates.py

On a PC with the project's virtual environment, it checks that environment.

For each package in requirements.txt it asks PyPI for known security issues
(PyPI's vulnerability data, from the OSV database) in the installed version,
the newest release a rebuild would install (within the pin), and the latest
release overall. It also compares the Caddy tag in compose.prod.yaml with
Caddy's latest release on GitHub.

Exit code 0: no known security issues. 1: at least one, listed. 2: couldn't check.
What to do with the result: docs/deployment.md, section 11.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "InH-Ticketing update check"
_PIN = re.compile(r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*~=\s*([0-9][0-9.]*)")
_CADDY = re.compile(r"image:\s*caddy:([0-9.]+)")


def _get(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def pins(path: Path = ROOT / "requirements.txt") -> list[tuple[str, str]]:
    """[(package, pinned version)] for each '~=' line."""
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _PIN.match(line.split("#", 1)[0])
        if match:
            found.append((match.group(1), match.group(2)))
    return found


def in_pin(version: str, pinned: str) -> bool:
    """'~=6.1.3' allows 6.1.3 and later 6.1.x; '~=26.2' allows 26.x from 26.2."""
    parts = pinned.split(".")
    prefix = parts[:-1]
    return version.split(".")[: len(prefix)] == prefix and _key(version) >= _key(pinned)


def releases(info: dict) -> list[str]:
    """Plain numbered releases that weren't withdrawn, oldest first."""
    plain = [
        version for version, files in info["releases"].items()
        if re.fullmatch(r"[0-9]+(\.[0-9]+)*", version) and files and not all(f.get("yanked") for f in files)
    ]
    return sorted(plain, key=_key)


def issues(name: str, version: str) -> list[str]:
    """Known security issues in one version: 'GHSA-... (fixed in 6.1.4)'."""
    found = []
    for vuln in _get(f"https://pypi.org/pypi/{name}/{version}/json").get("vulnerabilities") or []:
        if vuln.get("withdrawn"):
            continue
        fixed = ", ".join(vuln.get("fixed_in") or []) or "no fix yet"
        found.append(f"{vuln.get('id')} (fixed in {fixed})")
    return found


def installed(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def main() -> int:
    problems, rebuild, deliberate = [], [], []
    print(f"{'Package':16} {'Installed':10} {'Rebuild gets':13} {'Latest':10} Known security issues")
    try:
        for name, pinned in pins():
            info = _get(f"https://pypi.org/pypi/{name}/json")
            available = releases(info)
            newest = max((v for v in available if in_pin(v, pinned)), key=_key, default=pinned)
            latest = available[-1] if available else newest
            have = installed(name)
            checked = have or newest
            found = issues(name, checked)
            print(f"{name:16} {have or '-':10} {newest:13} {latest:10} {'; '.join(found) or 'none'}")
            if found:
                problems.append(f"{name} {checked}: {'; '.join(found)}")
            if have and _key(newest) > _key(have):
                rebuild.append(f"{name} {have} -> {newest}")
            if _key(latest) > _key(newest):
                deliberate.append(f"{name} {latest} (the pin allows up to {newest})")

        compose = (ROOT / "compose.prod.yaml").read_text(encoding="utf-8")
        caddy = _CADDY.search(compose)
        latest_caddy = _get("https://api.github.com/repos/caddyserver/caddy/releases/latest")["tag_name"].lstrip("v")
        if caddy:
            print(f"{'Caddy (proxy)':16} {caddy.group(1):10} {'-':13} {latest_caddy:10} see Caddy's release notes")
            if _key(latest_caddy) > _key(caddy.group(1)):
                deliberate.append(f"Caddy {latest_caddy} (compose.prod.yaml has {caddy.group(1)})")
    except Exception as exc:  # no network, PyPI or GitHub down
        print(f"\nCouldn't finish the check: {type(exc).__name__}: {exc}")
        return 2

    print()
    print("Known security issues: " + ("none." if not problems else ""))
    for line in problems:
        print(f"  {line}")
    if rebuild:
        print("A rebuild (`build --pull`) picks up: " + ", ".join(rebuild) + ".")
    if deliberate:
        print("Newer than the pins, for a new release of the app: " + ", ".join(deliberate) + ".")
    print("PostgreSQL 17 and the Python base image: refreshed by the monthly pull and rebuild (deployment.md, 11).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

"""scripts/check_updates.py, without the network: PyPI and GitHub are faked."""

import importlib.util
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import TestCase, mock

from django.conf import settings

_spec = importlib.util.spec_from_file_location(
    "check_updates", Path(settings.BASE_DIR) / "scripts" / "check_updates.py")
check_updates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_updates)

FILE = [{"yanked": False}]


def fake_get(vulnerable=()):
    """PyPI with Django 6.1.4 and 6.2.0 out (and a withdrawn 6.1.5), Caddy 2.11.9."""
    def get(url):
        if "api.github.com" in url:
            return {"tag_name": "v2.11.9"}
        name, _, version = url.split("/pypi/")[1].removesuffix("/json").partition("/")
        if version:
            vulns = [{"id": "GHSA-test", "fixed_in": ["6.1.4"]}] if (name, version) in vulnerable else []
            return {"vulnerabilities": vulns}
        numbers = {"Django": ["6.1.3", "6.1.4", "6.2.0", "6.2rc1"], "gunicorn": ["26.2.0", "27.0.0"]}
        releases = {v: FILE for v in numbers.get(name, ["1.0.0"])}
        if name == "Django":
            releases["6.1.5"] = [{"yanked": True}]
        return {"releases": releases}
    return get


class CheckUpdatesTests(TestCase):
    def run_check(self, vulnerable=(), installed="6.1.3"):
        out = StringIO()
        with mock.patch.object(check_updates, "_get", side_effect=fake_get(vulnerable)), \
                mock.patch.object(check_updates, "installed",
                                  side_effect=lambda name: installed if name == "Django" else None), \
                redirect_stdout(out):
            code = check_updates.main()
        return code, out.getvalue()

    def test_reads_the_pins(self):
        found = dict(check_updates.pins())
        self.assertEqual(found["Django"], settings_django_pin())
        self.assertIn("psycopg", found)  # psycopg[binary]
        self.assertIn("gunicorn", found)  # with its platform marker

    def test_what_a_pin_allows(self):
        self.assertTrue(check_updates.in_pin("6.1.4", "6.1.3"))
        self.assertFalse(check_updates.in_pin("6.2.0", "6.1.3"))
        self.assertFalse(check_updates.in_pin("6.1.2", "6.1.3"))
        self.assertTrue(check_updates.in_pin("26.9", "26.2"))
        self.assertFalse(check_updates.in_pin("27.0", "26.2"))

    def test_skips_previews_and_withdrawn_releases(self):
        info = fake_get()("https://pypi.org/pypi/Django/json")
        self.assertEqual(check_updates.releases(info), ["6.1.3", "6.1.4", "6.2.0"])

    def test_all_clear(self):
        code, out = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("Known security issues: none.", out)
        self.assertIn("A rebuild (`build --pull`) picks up: Django 6.1.3 -> 6.1.4.", out)
        self.assertIn("Django 6.2.0 (the pin allows up to 6.1.4)", out)
        self.assertIn("gunicorn 27.0.0", out)
        self.assertNotIn("Caddy 2.11.9 (", out)  # compose.prod.yaml already has it

    def test_a_known_issue_in_the_installed_version(self):
        code, out = self.run_check(vulnerable={("Django", "6.1.3")})
        self.assertEqual(code, 1)
        self.assertIn("Django 6.1.3: GHSA-test (fixed in 6.1.4)", out)

    def test_withdrawn_advisories_are_ignored(self):
        with mock.patch.object(check_updates, "_get", return_value={"vulnerabilities": [
                {"id": "GHSA-old", "withdrawn": "2026-01-01", "fixed_in": []}]}):
            self.assertEqual(check_updates.issues("Django", "6.1.3"), [])

    def test_no_network(self):
        out = StringIO()
        with mock.patch.object(check_updates, "_get", side_effect=OSError("no route to host")), redirect_stdout(out):
            self.assertEqual(check_updates.main(), 2)
        self.assertIn("Couldn't finish the check: OSError: no route to host", out.getvalue())


def settings_django_pin() -> str:
    line = next(l for l in (Path(settings.BASE_DIR) / "requirements.txt").read_text().splitlines()
                if l.startswith("Django~="))
    return line.split("~=")[1].strip()


class IndirectPackagesTests(TestCase):
    """v0.10.7: what the pinned packages need is checked too."""

    REQUIRES = {
        "Django": ["asgiref>=3.9", "sqlparse>=0.5", 'tzdata; sys_platform == "win32"',
                   'argon2-cffi>=23; extra == "argon2"'],
        "psycopg": ['psycopg-binary==3.3.8; extra == "binary"', 'psycopg-pool; extra == "pool"'],
        "asgiref": ["typing_extensions>=4"],
        "psycopg-binary": [],
    }
    INSTALLED = {"asgiref": "3.13.0", "sqlparse": "0.6.1", "typing_extensions": "4.16.0", "psycopg-binary": "3.3.8"}

    def indirect(self, names, extras=None):
        with mock.patch.object(check_updates.metadata, "requires", side_effect=lambda n: self.REQUIRES.get(n, [])), \
                mock.patch.object(check_updates, "installed", side_effect=self.INSTALLED.get):
            return check_updates.indirect(names, extras)

    def test_follows_needs_of_needs_and_the_extras_asked_for(self):
        found = self.indirect(["Django", "psycopg"], {"psycopg": {"binary"}})
        self.assertEqual(found, [("asgiref", "3.13.0"), ("psycopg-binary", "3.3.8"), ("sqlparse", "0.6.1"),
                                 ("typing_extensions", "4.16.0")])

    def test_leaves_out_extras_not_asked_for_and_what_isnt_installed(self):
        names = [name for name, _ in self.indirect(["Django", "psycopg"])]
        self.assertNotIn("psycopg-binary", names)  # no [binary] asked for
        self.assertNotIn("tzdata", names)  # not installed (Windows only)
        self.assertNotIn("argon2-cffi", names)

    def test_reads_the_extras_in_requirements(self):
        self.assertEqual(check_updates.pinned_extras().get("psycopg"), {"binary"})

    def test_a_known_issue_in_an_indirect_package_fails_the_check(self):
        out = StringIO()
        with mock.patch.object(check_updates, "_get", side_effect=fake_get(vulnerable={("sqlparse", "0.6.1")})), \
                mock.patch.object(check_updates, "installed", side_effect=lambda name: None), \
                mock.patch.object(check_updates, "indirect", return_value=[("sqlparse", "0.6.1")]), \
                redirect_stdout(out):
            code = check_updates.main()
        self.assertEqual(code, 1)
        self.assertIn("sqlparse 0.6.1: GHSA-test", out.getvalue())

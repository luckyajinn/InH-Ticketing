"""
Delete attachment files that no ticket refers to. STRESS-TEST BRANCH ONLY.

stress/run.sh puts the database back to the saved starting point before each
run. Files uploaded during earlier runs stay on disk, but nothing refers to
them any more; this removes them, so repeated runs don't fill the disk.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from tickets.models import Attachment


class Command(BaseCommand):
    help = "Delete attachment files that no ticket refers to (stress-test mode only)."

    def handle(self, *args, **options):
        if not getattr(settings, "STRESS_TEST_MODE", False):
            raise CommandError("This only runs with STRESS_TEST_MODE=1 (the stress-test server).")
        media = Path(settings.MEDIA_ROOT)
        folder = media / "attachments"
        if not folder.is_dir():
            self.stdout.write("No attachment files.")
            return
        keep = set(Attachment.objects.values_list("file", flat=True))
        removed = freed = 0
        for path in [p for p in folder.rglob("*") if p.is_file()]:
            if path.relative_to(media).as_posix() not in keep:
                freed += path.stat().st_size
                path.unlink()
                removed += 1
        for directory in sorted((p for p in folder.rglob("*") if p.is_dir()), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
        self.stdout.write(f"Removed {removed} unused attachment files ({freed / 1e6:,.0f} MB).")

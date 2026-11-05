import shutil
import tempfile
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import User
from tickets import services
from tickets.models import Category


def make_user(name="Dana Whitfield", role=User.Role.REQUESTER) -> User:
    user = User.objects.create(
        username=f"test-{uuid.uuid4().hex[:8]}",
        display_name=name,
        email=f"{name.lower().replace(' ', '.')}@example.invalid",
        role=role,
    )
    return user


def make_ticket(requester, subject="Printer jammed", category=None, **kwargs):
    return services.create_ticket(
        requester=requester,
        subject=subject,
        description=kwargs.pop("description", "It jams every few pages."),
        category=category or Category.objects.get(name="Hardware"),
        **kwargs,
    )


def upload(name="screenshot.png", content=b"fake image bytes", content_type="image/png"):
    return SimpleUploadedFile(name, content, content_type=content_type)


class MediaTestCase(TestCase):
    """Stores uploaded files in a throwaway folder that is deleted afterwards."""

    @classmethod
    def setUpClass(cls):
        cls._media_dir = tempfile.mkdtemp(prefix="inh-test-media-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)

    def setUp(self):
        self.requester = make_user("Dana Whitfield")
        self.other_requester = make_user("Tom Reyes")
        self.agent = make_user("Sam Patel", User.Role.AGENT)
        self.agent2 = make_user("Alex Morgan", User.Role.AGENT)

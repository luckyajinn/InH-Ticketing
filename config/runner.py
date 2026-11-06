"""
The test runner for `manage.py test` (settings.TEST_RUNNER).

Django's test client sends plain-HTTP requests. With DEBUG off, as on the
server or anywhere without a .env, SECURE_SSL_REDIRECT would answer every one
of them with a redirect to HTTPS, so it is switched off for the test run.
Tests of the redirect itself switch it back on with override_settings
(core/tests/test_security.py).
"""

from django.conf import settings
from django.test.runner import DiscoverRunner


class PlainHttpTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._saved_ssl_redirect = settings.SECURE_SSL_REDIRECT
        settings.SECURE_SSL_REDIRECT = False

    def teardown_test_environment(self, **kwargs):
        settings.SECURE_SSL_REDIRECT = self._saved_ssl_redirect
        super().teardown_test_environment(**kwargs)

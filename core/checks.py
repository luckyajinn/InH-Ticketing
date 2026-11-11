"""Start-up checks: settings from older versions that no longer do anything."""

import os

from django.core import checks

# Moved to the admin site (Tickets > Departments) in v0.10.0. The upgrade
# copied their values into each department.
RETIRED = {
    "ENTRA_ROLE_AGENT_MECHANICS": "each department's Entra app role",
    "ENTRA_ROLE_AGENT_CLEANING": "each department's Entra app role",
    "DEPARTMENT_NOTIFY_EMAILS": "each department's alert address",
}


@checks.register()
def retired_settings(app_configs, **kwargs):
    return [
        checks.Warning(
            f"{name} is no longer used: {where} is set in the admin site (Tickets > Departments).",
            hint="The upgrade to v0.10.0 copied its value there. Remove it from .env.",
            id="core.W001",
        )
        for name, where in RETIRED.items()
        if os.environ.get(name, "").strip()
    ]

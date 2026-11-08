"""Helpers for the stress-test tests. STRESS-TEST BRANCH ONLY."""

import importlib.util
from pathlib import Path

from django.conf import settings


def load_stress_module(name: str):
    """Import stress/<name>.py (the load generator's files aren't a Python package)."""
    path = Path(settings.BASE_DIR) / "stress" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"stress_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

"""Manual Statlocker UI probe, superseded by ``python main.py --diagnose``."""

import pytest

pytestmark = pytest.mark.skip(reason="manual probe; use python main.py --diagnose")


def test_inspect_current_data():
    """Placeholder for the old ad-hoc script."""

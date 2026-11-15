"""Manual icon probe, superseded by ``python main.py --diagnose``."""

import pytest

pytestmark = pytest.mark.skip(reason="manual probe; use python main.py --diagnose")


def test_check_wpa_icons_found():
    """Placeholder for the old ad-hoc script."""

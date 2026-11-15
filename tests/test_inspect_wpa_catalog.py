"""Manual catalog probe, superseded by ``python main.py --diagnose``."""

import pytest

pytestmark = pytest.mark.skip(reason="manual probe; use python main.py --diagnose")


def test_check_wpa_catalog_match():
    """Placeholder for the old ad-hoc script."""

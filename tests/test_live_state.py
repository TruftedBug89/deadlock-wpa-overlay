"""Manual live-state probe, superseded by ``python main.py --diagnose``."""

import pytest

pytestmark = pytest.mark.skip(reason="manual probe; use python main.py --diagnose")


def test_live_data_source_state():
    """Placeholder for the old ad-hoc script."""

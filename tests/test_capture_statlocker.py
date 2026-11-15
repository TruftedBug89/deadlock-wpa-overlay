"""Manual live probe, superseded by ``python main.py --diagnose``."""

import pytest

pytestmark = pytest.mark.skip(reason="manual Statlocker probe; use python main.py --diagnose")


def test_capture_statlocker():
    """Kept as a placeholder so the old filename still explains itself."""

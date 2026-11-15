"""The no-game lifecycle runs through the packaged overlay pipeline."""

import pytest

from tests.match_lifecycle_sim import run


def test_no_game_match_lifecycle_through_real_overlay_pipeline():
    try:
        report = run()
    except RuntimeError as err:
        if "Tk unavailable" in str(err):
            pytest.skip(str(err))
        raise

    assert report["early"]["stage"] == "early"
    assert report["early"]["next"] == ("Talon Trick", 1, 500)
    assert report["mid"]["stage"] == "mid"
    assert report["mid"]["next"] == ("Mid Relic", 2, 5000)
    assert report["late"]["stage"] == "late"
    assert report["late"]["next"] == ("Late Hammer", 4, 6400)
    assert report["ended"] == {
        "match_id": None,
        "hero": "Unknown",
        "stage": "",
        "souls": 0,
        "items": [],
        "next": None,
        "candidates": [],
        "counters": [],
        "status": "connecting",
        "in_match": False,
    }
    assert report["restarted"]["match_id"] == "9002"
    assert report["restarted"]["hero"] == "Test Enemy"
    assert report["restarted"]["next"] == ("Mystic Sign", 1, 500)
    assert all(name != "Talon Trick" for name, _tier, _cost in report["restarted"]["items"])
    assert report["hud"]["ended_kind"] == "status"
    assert report["hud"]["restarted_kind"] == "items"
    assert report["source"] == {
        "class": "AdvisorDataSource",
        "advisor": True,
        "api": "https://api.deadlock-api.com",
        "database_connections": 0,
    }


def test_advisor_is_default_and_statlocker_stays_optional():
    from main import parse_args

    assert parse_args([]).source == "advisor"
    assert parse_args(["--source", "statlocker"]).source == "statlocker"

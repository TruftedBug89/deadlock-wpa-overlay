"""Background polling backs off without claiming that a running game is connected."""

from models import GameState, OverlayConfig
from runtime_policy import poll_interval


def test_idle_backoff_and_active_preference():
    config = OverlayConfig(refresh_seconds=20)
    assert poll_interval(config, GameState(), running=False) == 60
    assert poll_interval(config, GameState(scan_status="needs_match")) == 30
    assert poll_interval(config, GameState(is_in_match=True)) == 20
    config.refresh_seconds = 300
    assert poll_interval(config, GameState(is_in_match=True)) == 30


def test_running_game_with_missing_public_match_has_actionable_status(monkeypatch, tmp_path):
    from tests.test_advisor_source import ASSETS
    from advisor_source import AdvisorDataSource
    monkeypatch.setattr("advisor_live.game_running", lambda: True)
    monkeypatch.setattr("advisor_api.find_active_match", lambda _: None)
    advisor = AdvisorDataSource(account_id=12345, require_match=True,
                                assets_fetcher=lambda: ASSETS, cache_path=tmp_path)
    state = advisor.get_game_state()
    assert state.scan_status == "needs_match" and not state.is_in_match
    assert not state.recommended_items

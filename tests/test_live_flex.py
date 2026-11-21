"""Optional flex observations never block or replace the main roster."""

import io
from types import SimpleNamespace

import live_flex
from tests.test_live_match import sse


def test_team_query_accepts_only_recent_observation_for_selected_team(monkeypatch):
    rows = [
        {"tick": 779, "m_iTeamNum": 2, "flex_mask": "0700000000000000"},
        {"tick": 899, "m_iTeamNum": 3, "flex_mask": "0700000000000000"},
        {"tick": 901, "m_iTeamNum": 2, "flex_mask": "0700000000000000"},
        {"tick": 900, "m_iTeamNum": 2, "flex_mask": "0500000000000000"},
    ]
    monkeypatch.setattr(live_flex.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(sse(rows)))
    assert live_flex.fetch_team_flex(90, 2, 900) == (900, 2)


def test_probe_is_async_and_throttled_while_results_expire(monkeypatch):
    pending, wakes = [], []
    now = [100.0]
    monkeypatch.setattr(live_flex.time, "monotonic", lambda: now[0])

    def delayed(target, args, **_kwargs):
        return SimpleNamespace(start=lambda: pending.append(lambda: target(*args)))

    monkeypatch.setattr(live_flex, "Thread", delayed)
    monkeypatch.setattr(live_flex, "fetch_team_flex", lambda *_: (900, 2))
    probe = live_flex.TeamFlexProbe()
    request = lambda tick: probe.value_or_schedule(90, 2, tick, lambda: wakes.append(True))
    assert request(901) is None
    assert request(901) is None
    assert len(pending) == 1
    pending.pop()()
    assert wakes == [True] and request(901) == 2
    assert request(1021) is None and not pending
    now[0] += 46
    assert request(901) is None and len(pending) == 1
    probe.reset()
    pending.pop()()
    assert wakes == [True] and request(901) is None

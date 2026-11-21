"""Local identity uses filenames only and never guesses between accounts."""

import local_account


def test_steam64_account_keeps_exact_digits_through_config():
    from config import _from_dict, _to_dict
    steam_id = local_account.STEAM64_BASE + 1001
    for value in (steam_id, str(steam_id), 1001):
        assert _to_dict(_from_dict({"account_id": value}))["account_id"] == 1001
    assert local_account.normalize_account_id("²") is None
    assert local_account.normalize_account_id("18446744073709551616") is None


def configure(monkeypatch, tmp_path):
    clock = [0.0]
    monkeypatch.setattr(local_account, "_CACHE", {"id": None, "at": None})
    monkeypatch.setattr(local_account, "_candidate_dirs", lambda: [tmp_path])
    monkeypatch.setattr(local_account.time, "monotonic", lambda: clock[0])
    return clock


def test_missing_account_is_retried_after_backoff(monkeypatch, tmp_path):
    clock = configure(monkeypatch, tmp_path)
    assert local_account.find_account_id() is None
    (tmp_path / "account_123456.stats").touch()
    clock[0] = 59
    assert local_account.find_account_id() is None
    clock[0] = 60
    assert local_account.find_account_id() == 123456


def test_multiple_accounts_are_unknown(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    for name in ("account_123456.stats", "account_654321.stats"):
        (tmp_path / name).touch()
    assert local_account.find_account_id() is None


def test_duplicate_paths_do_not_make_one_account_ambiguous(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    (tmp_path / "account_123456.stats").touch()
    monkeypatch.setattr(local_account, "_candidate_dirs", lambda: [tmp_path, tmp_path])
    assert local_account.find_account_id() == 123456


def test_discovery_includes_running_custom_library(monkeypatch, tmp_path):
    monkeypatch.setattr(local_account, "_running_game_directory", lambda: tmp_path)
    assert tmp_path in local_account._candidate_dirs()

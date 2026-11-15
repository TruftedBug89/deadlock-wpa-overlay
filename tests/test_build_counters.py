"""Build-aware counter selection: pool, strongest enemy, build-bound picks."""

from build_counters import build_pool, rank_pool_items, strongest_enemy

BODY = {
    "recommended": {
        "items": [
            {"itemId": 101, "name": "Lucky Shot", "slotType": "weapon", "tier": 3, "className": "upgrade_lucky_shot"},
            {"itemId": 102, "name": "Spirit Burn", "slotType": "spirit", "tier": 4, "className": "upgrade_spirit_burn"},
            {"itemId": 0, "name": "Broken Row"},
        ]
    },
    "situational": [
        {"itemId": 103, "name": "Spiritual Overflow", "slotType": "spirit", "tier": 4},
        {"itemId": 101, "name": "Lucky Shot", "slotType": "weapon"},
    ],
    "itemValues": {
        "items": [
            {"itemId": 104, "name": "Escalating Exposure", "tier": "S"},
        ]
    },
}

POOL = build_pool(BODY)


def test_build_pool_collects_core_situational_and_values():
    assert set(POOL) == {101, 102, 103, 104}
    assert POOL[101]["name"] == "Lucky Shot"
    assert POOL[104]["name"] == "Escalating Exposure"


def test_build_pool_ignores_invalid_payloads():
    assert build_pool({}) == {}
    assert build_pool(None) == {}
    assert build_pool({"recommended": {"items": [{"name": "No Id"}]}}) == {}


def _matchups():
    return [
        {"hero_id": 17, "enemy_hero_id": 11, "matches": 50000, "win_rate": 0.44},
        {"hero_id": 17, "enemy_hero_id": 20, "matches": 9000, "win_rate": 0.47},
        {"hero_id": 99, "enemy_hero_id": 63, "matches": 90000, "win_rate": 0.10},
    ]


def test_strongest_enemy_is_worst_matchup_for_our_hero():
    threat = strongest_enemy(_matchups(), 17, [11, 20, 63])
    assert threat["enemy_id"] == 11
    assert threat["win_rate"] == 0.44


def test_strongest_enemy_respects_enemy_filter():
    threat = strongest_enemy(_matchups(), 17, [20, 63])
    assert threat["enemy_id"] == 20


def test_strongest_enemy_prefers_more_games_on_a_tie():
    rows = [
        {"hero_id": 17, "enemy_hero_id": 11, "matches": 1000, "win_rate": 0.45},
        {"hero_id": 17, "enemy_hero_id": 20, "matches": 9000, "win_rate": 0.45},
    ]
    assert strongest_enemy(rows, 17, [11, 20])["enemy_id"] == 20


def test_strongest_enemy_without_data():
    assert strongest_enemy([], 17, [11]) is None
    assert strongest_enemy(_matchups(), 17, [63]) is None


def _stats():
    return [
        {"item_id": 101, "vs": {"11": 0.56}, "n": {"11": 2400}},
        {"item_id": 102, "vs": {"11": 0.52}, "n": {"11": 24000}},
        {"item_id": 103, "vs": {"11": 0.54}, "n": {"11": 12000}},
        {"item_id": 999, "vs": {"11": 0.99}, "n": {"11": 50000}},  # not in build
    ]


def test_rank_pool_items_only_returns_build_items():
    picks = rank_pool_items(POOL, _stats(), limit=3)
    names = [pick["name"] for pick in picks]
    assert names == ["Lucky Shot", "Spiritual Overflow", "Spirit Burn"]
    assert "Lucky Shot" not in [pick["name"] for pick in rank_pool_items(POOL, _stats(), limit=3, exclude=["Lucky Shot"])]


def test_rank_pool_items_reports_win_rate_and_samples():
    top = rank_pool_items(POOL, _stats(), limit=1)[0]
    assert top["win_rate"] == 0.56
    assert top["samples"] == 2400


def test_rank_pool_items_drops_duplicate_names():
    pool = dict(POOL)
    pool[105] = {"item_id": 105, "name": "Lucky Shot"}
    stats = _stats() + [{"item_id": 105, "vs": {"11": 0.60}, "n": {"11": 100}}]
    names = [pick["name"] for pick in rank_pool_items(pool, stats, limit=5)]
    assert names.count("Lucky Shot") == 1

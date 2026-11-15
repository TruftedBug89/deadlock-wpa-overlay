# Architecture

One Python process owns a Tk UI and one background worker. Advisor mode is
the default. [API_GUIDE.md](API_GUIDE.md) is the current evidence and endpoint
contract; legacy Statlocker screen mirroring is a separate source.

## Contracts

`models.py` defines `GameState`, `WpaItem`, `CounterItem`, `Candidate`,
`Scored`, `MatchContext` and `OverlayConfig`. Unknown purchase budgets are
`None`. `MatchContext.ownership_known` distinguishes missing inventory from
an explicitly empty inventory. `Scored.affordable_now` is unknown, true or
false. Only true supports `WpaItem.can_buy` and `GameState.next_buy`.

`Candidate.evidence` records comparable general/enemy counts, the item pool
baselines, basis, targets and gate decisions. Displayed WR is unsmoothed;
ranking uses a separate estimate. `GameState.valid_until` bounds live-card
freshness. A preview has no live validity deadline or confirmed next buy.

## Advisor data flow

```text
explicit match ID / public active matches
                  |
            live_match.py (SSE)
                  |
     advisor_live.py -> match_context.py
                  |
advisor_api.py -> advisor_source.py -> advisor_evidence.py
       |               |                    |
 expiring JSON     integration       item_stats.py
                       |                    |
                       +---- recommendation_engine.py
                                      |
                                 GameState queue
                                      |
                              ui/main_window.py
                                      |
                       minimal_view.py / counter_view.py
```

| Module | Responsibility |
| --- | --- |
| `advisor_api.py` | Public HTTP requests, expiry, atomic JSON caching, retry delays and active-match discovery |
| `advisor_live.py` | Confirm live identity, freshness and inventory; optional match-ID-only corner OCR; no companion reads |
| `live_match.py` | Parse SSE fields, require complete ticks, cache snapshots, handle termination and replayed ticks |
| `match_context.py` | Compute live lead, damage share, leaders, bank and ownership knowledge |
| `item_stats.py` | Validate counts, pool adjacent buckets, measured/smoothed rates and weighted baselines |
| `advisor_evidence.py` | Align cohorts, apply counter gates, retain evidence and rejected claims |
| `recommendation_engine.py` | Five score terms, purchase/slot gates and deterministic sorting |
| `advisor_source.py` | Refresh catalog/analytics, combine evidence and context, build state and explanation |
| `item_economy.py` | Explicit stage and comfortable-price policy |
| `ui/minimal_view.py` | Main item, measured WR and one reason |
| `ui/counter_view.py` | Counter gain chips |
| `ui/counter_panel.py` | Counter visibility and enemy-filter label |
| `ui/main_window.py` | Worker, queue, fresh state signatures and independent live-card expiry |
| `ui/overlay_render.py` | Reuse widgets unless content kind/count changes |
| `ui/hud_geometry.py` | Fixed card sizes and panel dimensions, DPI and user scale |
| `ui/theme.py` | Shared colours, font family and soul formatting |
| `ui/hover_controls.py` | Dwell-to-reveal grip and gear without stealing clicks |
| `ui/drag_handler.py` | Drag, right/left edge snap and position persistence |
| `ui/overlay_settings.py` | Live settings: layout, size, opacity, details, docking |
| `ui/state_updates.py` | Worker polling, queue drain and state signatures |
| `ui/positioning.py` | Monitor bounds and corner/manual placement |

Catalog and analytics can expire during a running process. No expired cache
is used after a fetch failure. Counter filters are selected from measured
live leaders, or the supplied enemy roster when leaders are unknown.
Every counter comparison shares one bracket or one overall basis.
The worst historical hero matchup is reported separately from item evidence.

## Threading and freshness

Network, cache I/O and icon prewarming run on the worker. Tk only drains
`queue.Queue(maxsize=4)` every 200 ms and updates widgets. Worker polling waits
20 seconds during a match, 30 seconds while discovering one, and 60 seconds
when the game is closed. Live success/miss TTLs are 6/4 seconds.
The UI removes a state's cards at `valid_until`, even without a worker result.
Same-name items still rerender when price, WR, sample, reason, affordability,
counter gain or target changes.

Tests create Tk windows with `enable_worker=False`; production retains the
worker by default. Source modules remain under 500 lines.

## Optional legacy source

`data_source.py`, `statlocker_discovery.py`, `log_tracker.py`,
`live_screen_reader.py`, `wpa_detector.py`, `card_detector.py` and
`statlocker_counters.py` implement optional Statlocker mirroring. These are
not called by the advisor. The shared UI accepts either source's `GameState`.
Legacy OCR gaps remain unresolved. Its diagnostic command is `--diagnose`;
the advisor uses `--explain`.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

Synthetic API tests cover the base-rate trap and count validation, same-basis
fallback, budget/ownership/threat transitions, stale caches and retry delays.
The lifecycle simulation runs through the real advisor, queue and Tk renderer
with network boundaries injected. Manual live-host probes skip themselves.

## Stable queues and public releases

recommendation_queue.py retains IDs over the complete freshly eligible score
pool. Contracts live in models.RecommendationQueueState. advisor_source wires
main and counter queues into the live path; previews remain stateless. Evidence
updates on every poll. Scheduled reviews add at most one new item, while safety
invalidation and affordability take precedence over stability.

version.py is the release version. release_package.py builds a clean executable
and archives explicit public files. build_assets.py creates original app artwork.
public_guard.py checks tracked paths before reading public text, reports no secret
values, and enforces source size/typography. CI uses pinned dependencies/actions;
tag releases publish only after tests and packaging pass. Local account settings,
logs, caches, captures, recordings and assistant context never belong in Git.

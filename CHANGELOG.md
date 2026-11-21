# Changelog

## 2.4.0 - 2026-11-21 (preview)

- Show Deadlock's shop artwork from the live catalog in item and build views.
- Give larger samples more influence and use the spendable wallet for price fit.
- Require counters to clear an uncertainty margin and the enemy pool baseline.
- Keep stage win rates for recommendations when only an overall counter is available.
- Use live inventory capacity and owned components in the queue and build board.
- Show an optional Sell / Buy pair when slots are full and the replacement meets stricter evidence gates.
- Retry with the roster-only broadcast query if the team-slot projection is rejected.
- Use recent hourly analytics and refresh the catalog when the client version changes.

## 2.3.2 - 2026-11-20 (preview)

- Show automatic match discovery and broadcast wait as separate statuses.
- Keep the last detected ID through a short failure to read the match stamp.
- Allow the spectator relay's startup retries to finish and report failures by status.
- Avoid repeating hover placement and stacking while controls are already visible.

## 2.3.1 - 2026-11-19 (preview)

- Retry match-ID capture from the visible corner when the game window is blank.
- Recognize thin match stamps using grayscale and inverted OCR inputs.
- Skip replayed SSE ticks while waiting for a newer complete live roster.
- Add an opt-in local playtest health report and an explicit preferences path.

## 2.3.0 - 2026-11-18 (preview)

- Compact build board with separate Plan and Match tabs and stable item rows.
- Switch between Minimal and Full build from the hover controls.
- Show SAVE and unknown-budget markers even in the icon strip.
- Accept SteamID64 in match settings and discard advice from superseded retries.
- Keep connection status visible when live advice expires during a game.
- Limit icon download work and refresh the HUD when artwork arrives.

## 2.2.0 - 2026-11-17 (preview)

- Full current-build board alongside the minimal five-item HUD.
- Owned items, measured enemy threats and expanded validated item plans.
- Better view settings and connection recovery/status details.
- Discovery recovery when the public watch list is incomplete or stale.
- Headless CI separates native desktop OCR integration from deterministic tests.


## 2.1.0 - 2026-11-15 (preview)

- Stable item and counter queues with adjustable review cadence.
- Fresh evidence and immediate safety checks continue between queue reviews.
- Hover settings, dragging and size controls in the minimal HUD.
- Owned components inform upgrade progression and slot checks.
- Conservative match identity checks, optional match-ID-only OCR, slow idle polling.
- Bounded logs, ambiguous account detection safeguards and synthetic test data.
- Public Windows build workflow, versioned ZIP packages and SHA-256 checksums.

Live discovery can miss matches. Real-match end-to-end validation remains
outstanding; unavailable live data hides purchase advice.

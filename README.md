# Deadlock WPA Overlay

A small Windows HUD with a steady purchase queue for the current Deadlock match.
Advice comes from deadlock-api.com analytics and live broadcasts. No companion
app is required. Hover to reveal settings, drag to move, and resize from either edge.

[Download builds](https://github.com/TruftedBug89/deadlock-wpa-overlay/releases) |
[API walkthrough](API_GUIDE.md) | [Privacy](PRIVACY.md) | [Changelog](CHANGELOG.md)

**Preview release:** automated tests cover the picker, live-state parsing and HUD.
Real-match end-to-end validation remains outstanding. Public discovery can miss
matches and corner OCR may fail. Missing or stale data hides purchase advice.

## Install and connect

1. Download the Windows x64 ZIP and SHA256SUMS.txt from a release. Extract the ZIP.
2. Verify the ZIP hash with `Get-FileHash .\DeadlockWPAOverlay-2.2.0-windows-x64.zip -Algorithm SHA256`.
3. Run DeadlockWPAOverlay.exe. The executable is unsigned and Windows may warn.
4. Hover the HUD and click its gear, or choose **Overlay Settings** from the tray.
5. Enter your numeric Steam account ID and click **Connect / retry**. Each friend
   configures their own account; no account or personal settings ship in the build.
6. Optionally enable **Read match ID from game corner**. When the public watch list
   misses your game, it reads only the corner match ID, in memory, at most once
   every 45 seconds. Otherwise enter the match ID in settings yourself.

Your account must appear in the API roster before advice is shown. Deadlock
running is not proof of an active broadcast. The public list covers only the
watch tab's top 200 games. Minimized windows and unreadable stamps return unknown.
Windows 10/11 x64 is required; corner OCR also needs a Windows OCR language installed.

## Minimal HUD or full build

Choose **Minimal** for up to five queued items, or **Full build** for a larger
board with full item names, prices, measured WR, owned items and current threats.
The build plan expands to at most twelve legal picks as your inventory and
current-stage evidence allow. Empty positions are not filled with guesses.

The full plan is a current-game plan, not a promised end-game build. SAVE targets
remain clearly marked and affordability is per item, not a claim that the entire
plan can be bought together. Enemy soul and damage leaders update from broadcasts;
their measured counter evidence can change the plan at its next queue review.

## A steady queue

The first card is the next queued purchase. The remaining cards follow it from
left to right. The order stays steady while the game is being checked.

- Every **150 seconds** by default, review the queue and append at most one better
  suggestion on the right. Choose 2, 2.5 or 3 minutes in settings.
- A bought or invalid item leaves on the next live update. Remaining valid items
  keep their order; gaps refill one at a time. Affordability always updates now.
- All displayed prices, evidence and SAVE labels come from the fresh calculation.
  The queue remembers item IDs, never old snapshots. Counters use the same policy.
- New matches, heroes or early/mid/late stages start a new queue. Affordable picks
  remain before savings targets. No forced rotation if the current picks still win.

A SAVE label is a savings target, not a purchase you can make now. Four category
slots, owned items and catalog upgrade components are checked on every scan.
Unknown inventory, bank balance or owned-item catalog data hides purchase advice.

## Evidence, without a wall of numbers

Each card shows its name, measured historical WR and one short reason. Counter
chips show measured gain against a comparable general sample. Both general and
enemy samples require at least 100 observations. Counters must also beat the
weighted enemy-pool baseline; a gain over a bad item baseline is insufficient.

The picker uses team soul lead, damage share, fed enemies, your bank and inventory.
It merges the three nearest net-worth buckets and falls back to overall data when
samples are thin. Owned components can make an upgrade preferable; unverified
upgrade discounts are never assumed. No handwritten matchup table or item-pair
synergy endpoint is used. Historical associations cannot guarantee a good buy.

API reads run in a background worker: normally every 20 seconds in a match,
30 seconds while discovering, and 60 seconds with the game closed. Cards expire
45 seconds after their snapshot if fresh data fails. Analytics cache for 6 hours;
catalogs for 7 days. Queue review timing is separate from safety revalidation.

## Controls

| Control | Action |
| --- | --- |
| Hover | Reveal gear, grip and side resize handles |
| Gear / right click | Live settings, connection and queue cadence |
| Side handles | Resize the HUD |
| F8 | Toggle row / stack |
| F9 | Lock / unlock movement |
| F10 | Show / hide |
| Tray menu | Settings, positioning and exit |

Settings save locally. A small monitor gets a scrollable settings panel. There
is no telemetry, automatic log upload, administrator requirement or startup service.
Game artwork is fetched at runtime from catalog URLs and is not included in releases.

## Develop and verify

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-build.lock
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe main.py --source advisor --account ACCOUNT_ID --read-match-id
```

Replace ACCOUNT_ID with your numeric Steam account ID. Tests use synthetic match
fixtures and mocked network/capture boundaries. Manual probes are skipped. Headless CI also skips native Windows OCR integration
checks; deterministic OCR parsing and discovery recovery still run with mocks.

```powershell
.venv\Scripts\python.exe main.py --explain --preview-hero 1 --preview-souls 20000 --enemy-heroes 2,3
.venv\Scripts\python.exe main.py --explain --match-id MATCH_ID --account ACCOUNT_ID
```

The JSON includes evidence counts, score terms, exclusions, queue decisions and
freshness. Previews have unknown affordability. See [API_GUIDE.md](API_GUIDE.md)
for endpoint parameters and [ARCHITECTURE.md](ARCHITECTURE.md) for module contracts.
Optional legacy Statlocker code is retained for compatibility, but public builds
do not ship its heading template and that mode is not the supported default.

## Builds and releases

```powershell
.venv\Scripts\python.exe public_guard.py
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe release_package.py
```

Output: dist/releases/DeadlockWPAOverlay-2.2.0-windows-x64.zip plus SHA256SUMS.txt.
The packager includes explicit public inputs only, never a portable configuration.
Build dependencies are version-pinned. This does not promise bit-for-bit identical
executables across different Windows/Python builds.

Windows CI tests and builds on pushes and pull requests. After updating version.py
and CHANGELOG.md, pushing a matching vX.Y.Z tag creates a GitHub prerelease with a
Windows ZIP and checksum. Actions are SHA-pinned; only the release job gets write
permission. Review the source, privacy checks and CI before publishing a tag.

The code and generated app mark use the [MIT license](LICENSE). Third-party
runtime notices ship with releases. Deadlock names and remotely fetched game
artwork belong to their respective owners. This is an unofficial community tool.

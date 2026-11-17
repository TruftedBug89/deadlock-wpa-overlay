# Advisor API and evidence walkthrough

Verified against the public API specification on 2026-11-14:
[endpoint reference](https://api.deadlock-api.com/docs),
[OpenAPI schema](https://api.deadlock-api.com/openapi.json), and
[item analytics implementation](https://github.com/deadlock-api/deadlock-api/blob/master/api/src/routes/v1/analytics/item_stats.rs).

Advisor mode uses public deadlock-api.com data. It does not read Statlocker,
a companion database, or gameplay values from pixels. Optional corner OCR
reads only the match ID; all recommendation inputs remain API data. The legacy
`--source statlocker` mode is separate.

## 1. Identify the live match

Use `--match-id` and `--account` when available. Without a match ID, the advisor
calls `GET /v1/matches/active?account_ids=ACCOUNT_ID`. Exactly one returned match
is required. This list covers the watch tab's top 200 matches, so discovery
cannot find every player's game. A missing or ambiguous result hides advice;
provide the match ID explicitly or opt into corner ID reading in that case. Discovery is cached for 30 seconds.

The account can also be identified from the name of a local
`account_<id>.stats` file. Its contents are never read. An explicit `--hero`
can identify your player only when no account ID is configured. A configured
account must appear in the API roster, even when OCR or a manual hero is used.

`--read-match-id` checks only the Deadlock window corner after watch-list
discovery fails. Two OCR readings must agree. Successes and failures are
cached for 45 seconds. Images stay in memory and are never saved. Minimized
windows or unreadable stamps return unknown, never a guessed ID.

## 2. Load the catalog

| Request | Returned data used | Local expiry |
| --- | --- | --- |
| `GET /v1/assets/items?only_shopable_items=true` | ID, name, class name, slot category, cost, tier, image, disabled/shopable flags | 7 days |
| `GET /v1/assets/heroes` | Hero IDs and names | 7 days |

Only enabled, shopable upgrade items with a recognized category are candidates.
Unknown names, prices, categories, or owned IDs that cannot be resolved to this
catalog cannot support live purchase advice. Removed entries are cleared when
the catalog refreshes. The in-memory catalog expires too, even if the overlay
has been running for more than a week.

## 3. Read live state through SSE

`GET /v1/matches/demo/live/query?match_id=MATCH_ID&query=URL_ENCODED_SQL`
uses `Accept: text/event-stream`. `live_match.QUERY` selects from
`CCitadelPlayerController`:

- `tick`, `entity_index`, team, account and hero IDs identify the roster.
- Gold net worth plus AP net worth gives earned souls. `m_iGold` is unspent
  gold, the actual purchase budget. These are separate quantities.
- Hero damage supplies your team damage share and the enemy damage leader.
- Healing, objective damage, level, kills, deaths and assists are decoded;
  they currently add no independent score term.
- `m_vecUpgrades` supplies owned item IDs. An empty vector means no items;
  an omitted vector is unknown. Little-endian hex entries are decoded to
  their low 32-bit catalog IDs.

The reader accepts one complete 12-player tick, without combining partial
ticks. SSE `end` and `error` events invalidate the read. CRLF framing is
supported. Successful snapshots are cached for 6 seconds, failures for 4.
A reconnect replaying the preceding cached tick does not renew its freshness.
No snapshot, unknown budget, unknown inventory, or unresolved owned catalog
IDs means no purchase cards. A present empty inventory after selling the last
item clears ownership immediately.

The worker polls every 20 seconds by default during a match, every 30 seconds
while discovering one, and every 60 seconds when the game is closed.
A live recommendation expires 45
seconds after snapshot receipt, including time spent fetching analytics.
Tk independently removes expired cards if the worker is blocked. This is
bounded polling, not a guarantee of instant game events or zero upstream delay.

The API documents 20 live queries/minute per IP and limited spectating of new
match IDs. Already spectated matches are cached upstream for an hour.

## 4. Request comparable item statistics

General example:

```text
/v1/analytics/item-stats?hero_id=1&min_matches=1&bucket=net_worth_by_5000
```

Enemy-filtered example:

```text
/v1/analytics/item-stats?hero_id=1&enemy_hero_ids=2,3&min_matches=1&bucket=net_worth_by_5000
```

The API still supports `hero_id`, although its schema marks it deprecated in
favor of `hero_ids`. Each row includes `item_id`, `bucket`, `wins`, `losses`,
`matches`, `players`, and average purchase/sale timing. Net-worth buckets refer
to net worth at purchase. They are historical purchase cohorts, not predictions
of what the current match will do.

Date, mode and rank filters are omitted. The current API defaults are normal
mode, ranked/unranked matches, and a rolling 30-day history. This is not an
explicit current-patch-only dataset. Each request's recorded fetch time matters
when interpreting the evidence.

At 20k souls, merge the 15k, 20k and 25k buckets per item. Requesting
`min_matches=1` preserves small component buckets; the client enforces 100
observations after pooling. If a comparison is thin or absent, both its general
and enemy rows fall back to unbucketed requests with `min_matches=100`.
Never compare a bracket row against an overall row. Each candidate records
its basis, so a scan can honestly report `mixed`.

If the overall comparison is also missing, a valid general bracket row can
still rank without a counter bonus. Invalid counts, missing wins, and
inconsistent wins/losses are rejected.

`enemy_hero_ids=2,3` means matches against **any** listed enemy, not necessarily
both in the same game. Live soul and hero-damage leaders select the relevant
enemy filter. If both identify one enemy, the label names that enemy; multiple
targets use `LINEUP`. Without measured leaders, use the supplied enemy roster.

The API's `players` counts distinct accounts buying that item. It is not the
denominator of a hero pick rate. The popularity term now uses item purchases
divided by all eligible item purchases in the same pool. It is called
`purchase_share` in the explanation, and its UI label is `POPULAR`, not `CORE`.

## 5. Reject the base-rate trap

Every counter must satisfy all three conditions:

1. Both comparison rows have at least 100 observations.
2. Enemy-filtered WR is strictly above the eligible enemy pool's
   purchase-weighted baseline: `sum(wins) / sum(matches)`.
3. Enemy-filtered WR minus the same item's general WR is at least 0.004,
   or 0.4 percentage points.

A 37.1% result that improves on a 25% general row still fails if the enemy
pool's baseline is higher. The historical rates describe associations and do
not establish that buying an item causes that gain. Minimum sample gates are
not significance tests; repeated purchases and overlapping cohorts limit
statistical independence.

`GET /v1/analytics/hero-counter-stats?min_matches=200` separately returns
hero/enemy pairs, `wins` and `matches_played`. The advisor retains rows for
your hero and current enemies and records the lowest measured matchup rate.
That historical matchup does not relabel a multi-enemy item query as evidence
against one particular hero.

No `item-permutation-stats` or inferred item synergy is used.

## 6. Rank and render

`score = edge + popularity + counter + tempo + stance`

| Term | Calculation |
| --- | --- |
| Edge | `(smoothed WR - same-basis item-pool baseline) * 100`, capped to -5..5 |
| Popularity | `min(1, purchase_share * 2) * 0.5` |
| Counter | `min(3, accepted gain * 100) * 0.8`, otherwise zero |
| Tempo | `-min(1, abs(cost-target)/target) * 6.5`, with another -0.6 while saving |
| Stance | At most +0.3: ahead favors weapon/spirit, behind favors vitality; dealing at least one third of team hero damage instead favors vitality to protect the carry |

The ranking estimate uses `(wins + 10) / (matches + 20)`.
The card's `WR` uses the actual `wins / matches`, not this estimate.
Baselines are weighted item-purchase pools, not independently measured hero
win rates. Tempo and stance are explicit ranking policy, not measured win-rate
improvements. Target price is `clamp(0.55 * earned_souls, 500, 6400)`.
Lead thresholds are 1.5k early, 4k mid, 8k late; stages change at 6k and 14k souls.

Rank affordable items first, then score, sample count and WR. Remove owned,
unpriced and unearned items. Category limits are applied after sorting, so
catalog order cannot discard the strongest item. Preserve the configured
four slots per category. Savings targets are allowed only as `SAVE amount`,
never `next_buy` or counter chips. A live `next_buy` must be affordable now.

Cards show item, measured `WR`, and one reason. Priority is `SAVE`, unknown
budget in previews, enemy evidence, carry protection, stance, popularity, then
`MEASURED EDGE`. Counter chips show `+4.1 pts`; this is gain against that item's
own general rate. Their header identifies the enemy filter. The full counts
stay in the explanation instead of filling the HUD.

## 7. Cache, failures and reproducibility

Analytics and matchup JSON responses expire locally after 6 hours. Catalog
responses expire after 7 days. Cache keys separate hero, sorted enemy IDs and
bucket mode; the new stats namespace avoids reusing old pre-filtered buckets.
Empty responses are cached. Expired responses are never used after a failed
refresh. The API itself caches analytics requests for an hour. These fixed
windows do not guarantee immediate patch freshness.

HTTP 429, 503 and 504 responses respect a numeric `Retry-After`; if absent,
the client waits 60 seconds before retrying that URL. Assets use a 60-second
timeout, analytics 30 seconds, live reads 8 seconds. Failures clear purchase
advice or suppress unavailable counter evidence, without fabricated values.
Other analytics failures also receive a 60-second local retry delay, so a
slow unavailable counter endpoint does not block every subsequent live scan.

```powershell
.venv\Scripts\python.exe main.py --explain --preview-hero 1 --preview-souls 20000 --enemy-heroes 2,3
.venv\Scripts\python.exe main.py --explain --match-id MATCH_ID --account ACCOUNT_ID
.venv\Scripts\python.exe -m pytest tests -q
```

Replace the uppercase placeholders with your actual numeric IDs. A preview
has no live bank or inventory and is explicitly marked in its JSON; it is not
confirmed purchase advice.

`candidate_evidence` includes rejected comparisons as well as accepted ones:
item ID, basis/window, general and enemy wins/counts, all baseline pool counts,
gain, thresholds and decision. `items` includes the five score terms and
affordability. `requests` records hero/enemy/bucket filters, cache use and fetch
times; `assets_fetched_at`, `live_tick`, `valid_until` and `context` describe
freshness and live inputs. These fields reproduce the counter claim without
another API request whose underlying data may have changed.

## Inventory-aware progression

The catalog's `component_items` relationships now identify real upgrades.
Owned items and ingredients of an already-owned upgrade are excluded. An
upgrade that consumes an owned component can reuse its occupied category slot
and receives a small +0.3 tempo preference. The explanation names those owned
components. Prices remain the catalog price; no unverified component discount
or sale proceeds are assumed. This is item progression, not pairwise synergy.

## Stable recommendation queues

Live scoring and safety gates still run each poll. The display queue stores only
item IDs, then replaces each entry with freshly scored evidence. Previously held
items may remain outside the current top few ranks if they still pass all gates.

A 150-second review (configurable to 120 or 180) admits at most one better outsider
at the right. It replaces the weakest queued entry while preserving the others'
relative order. With no better option, nothing rotates. Invalid entries disappear
immediately, and one missing position may refill per poll. Affordable entries
always precede SAVE targets. Match, player, hero or stage changes reset the queue.
Counter chips use the same mechanism over validated enemy evidence.

The explanation includes queue and counter_queue: action, previous_ids,
selected_ids, interval_seconds and seconds_until_review. The item details and
claims remain from the newest snapshot. Queue timing never extends valid_until.

## Full build and discovery recovery (2.2)

Full mode extends the minimal queue with a separately stable, slot-legal tail
up to twelve recommendations. All entries use current evidence and the same
inventory, price, sample and freshness gates. Enemy soul and damage leaders
are reported only when measured. Prices and affordability are per item.

Automatic discovery considers the opt-in corner ID and public watch list,
then a recently verified match. A stale automatic ID does not permanently block
other candidates. Failed candidates back off for thirty seconds. Explicit retry
clears connection caches; changing account identity also resets discovery.
The corner reader uses the verified foreground game process and client bounds,
without depending on its title or rendering an entire window. It stores no images.
Settings show the current failure reason. Game detection alone never proves a
broadcast is available, and real-game validation remains outstanding.

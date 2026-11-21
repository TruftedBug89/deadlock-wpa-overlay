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

Use `--match-id` and `--account` when available. For automatic discovery, the
advisor checks the in-game corner when enabled and also calls
`GET /v1/matches/active?account_ids=ACCOUNT_ID`. The watch-list path requires
exactly one result and covers the watch tab's top 200 matches. Discovery is
cached for 30 seconds. A previously confirmed broadcast can bridge a short
discovery gap; fresh roster data must still confirm the player.

The account can also be identified from the name of a local
`account_<id>.stats` file. Its contents are never read. An explicit `--hero`
can identify your player only when no account ID is configured. A configured
account must appear in the API roster, even when OCR or a manual hero is used.

`--read-match-id` checks only the Deadlock window corner. Two OCR readings
must agree. Successes and failures are
cached for 45 seconds. Images stay in memory and are never saved. Minimized
windows or unreadable stamps return unknown, never a guessed ID.

## 2. Load the catalog

| Request | Returned data used | Local expiry |
| --- | --- | --- |
| `GET /v1/assets/items?only_shopable_items=true` | ID, name, class name, slot category, cost, tier, `shop_image`, disabled/shopable flags | 7 days |
| `GET /v1/assets/heroes` | Hero IDs and names | 7 days |
| `GET /v1/assets/steam-info` | Published `client_version` for refresh decisions | Checked every 15 minutes while advising |

Only enabled, shopable upgrade items with a recognized category are candidates.
Unknown names, prices, categories, or owned IDs that cannot be resolved to this
catalog cannot support live purchase advice. Removed entries are cleared when
the catalog refreshes. The in-memory catalog expires too, even if the overlay
has been running for more than a week. A newly observed client version also
invalidates the catalog and local analytics immediately. If version lookup
fails, existing catalog and analytics still follow their normal expiry.

## 3. Read live state through SSE

`GET /v1/matches/demo/live/query?match_id=MATCH_ID&query=URL_ENCODED_SQL`
uses `Accept: text/event-stream`. The query returns the roster projection from
`CCitadelPlayerController` and combines it with an optional `CCitadelTeam`
projection using `UNION ALL`:

- `tick`, `entity_index`, team, account and hero IDs identify the roster.
- Gold net worth plus AP net worth gives earned souls. `m_iGold` is unspent
  gold, the actual purchase budget. These are separate quantities.
- Hero damage supplies your team damage share and the enemy damage leader.
- Team number and `m_nFlexSlotsUnlocked` establish inventory capacity when a
  recent team row is available for the confirmed player. The unlock field is
  a bit mask encoded as little-endian bytes. The roster remains usable
  without team rows. A schema rejection retries the roster projection within
  the original time limit.
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
`GET /v1/matches/live/urls` lists cached broadcast URLs from the same relay
used by the live query. Match discovery can fall back to another source for
the ID. A failure to start the actual broadcast still pauses live advice.

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

`min_unix_timestamp` is midnight UTC seven days before the scan date, so every
pool uses the same recent cutoff and shares upstream cache entries. Mode and
rank filters use the API defaults for normal ranked/unranked games. The
window can span a balance patch. Its exact cutoff and the observed catalog
version are available in `--explain`.

At 20k souls, merge the 15k, 20k and 25k buckets per item. In the first
bracket, merge 0, 5k and 10k. Requesting
`min_matches=1` preserves small component buckets; the client enforces 100
observations after pooling. If general bracket evidence is thin, the ranking
uses unbucketed evidence with `min_matches=100`. When a counter comparison is
thin, both its general and enemy rows use the same overall fallback. It can
appear as an overall counter while the main ranking keeps its bracket evidence.
Each candidate records both bases. A scan using more than one ranking basis
reports `mixed`.

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

Every counter must satisfy four conditions:

1. Both comparison rows have at least 100 observations.
2. Enemy-filtered WR is strictly above the eligible enemy pool's
   purchase-weighted baseline: `sum(wins) / sum(matches)`.
3. Enemy-filtered WR minus the same item's general WR is at least 0.004,
   or 0.4 percentage points.
4. The enemy row's Wilson lower bound exceeds both the general row's Wilson
   upper bound and the enemy pool baseline. The remaining margin is the
   supported gain. The bound uses `z = 1.2815515655`.

A 37.1% result that improves on a 25% general row still fails if the enemy
pool's baseline is higher. Historical rates describe associations. The
uncertainty margin is a ranking safeguard because repeated purchases and
overlapping cohorts limit statistical independence.

`GET /v1/analytics/hero-counter-stats?min_matches=200&same_lane_filter=false` also receives
the recent cutoff and separately returns
hero/enemy pairs, `wins` and `matches_played`. The advisor retains rows for
your hero and current enemies and records the lowest measured matchup rate.
That historical matchup does not relabel a multi-enemy item query as evidence
against one particular hero.

Item compatibility uses catalog components, current slots and inventory. The
analytics query does not use item-pair permutations.

## 6. Rank and render

`score = edge + popularity + counter + tempo + stance`

| Term | Calculation |
| --- | --- |
| Edge | `clamp((observed WR - same-basis item-pool baseline) * 100, -5, 5) * matches / (matches + 400)` |
| Popularity | `min(1, purchase_share * 2) * 0.5` |
| Counter | `min(3, supported gain * 100) * 0.8` for accepted, same-basis comparisons |
| Tempo | `-min(1, abs(cost-target)/target) * 1.5`, with another -0.6 while saving or +0.3 for an upgrade to owned components |
| Stance | At most +0.3: ahead favors weapon/spirit, behind favors vitality; dealing at least one third of team hero damage instead favors vitality to protect the carry |

The card's `WR` uses the actual `wins / matches`. Baselines are weighted
item-purchase pools. Tempo and stance are ranking preferences. Target price is
`clamp(0.55 * earned_souls, 500, 6400)`. For a buyable item, the target is capped
at the current wallet so a tight budget can surface a good cheaper purchase.
Lead thresholds are 1.5k early, 4k mid, 8k late; stages change at 6k and 14k souls.

Rank affordable items first, then score, sample count and WR. Remove owned,
unpriced and unearned items. Category limits are applied after sorting, so
catalog order cannot discard the strongest item. The plan applies a four-item
category limit for recommendations and checks against total inventory capacity.
Savings targets are allowed only as `SAVE amount`,
never `next_buy` or counter chips. A live `next_buy` must be affordable now.

Cards show item, measured `WR`, and one reason. Priority is `SAVE`, unknown
budget in previews, enemy evidence, carry protection, upgrade, popularity,
above-pool win rate, then stance and stage fit. Counter chips show `+4.1 pts`
for the measured gain against that item's general rate. Their header identifies
the enemy filter. The full counts
stay in the explanation instead of filling the HUD.

## 7. Cache, failures and reproducibility

Analytics and matchup JSON responses expire locally after one hour. Catalog
responses expire after seven days. Cache keys separate hero, sorted enemy IDs
and bucket mode. Cache entries also record the cutoff and version so advancing
the window or updating the game cannot reuse an old local cohort.
Empty responses are cached. Expired responses are never used after a failed
refresh. The API itself caches analytics requests for an hour. These fixed
windows do not guarantee immediate patch freshness.

HTTP 429, 503 and 504 responses respect a numeric `Retry-After`; if absent,
the client waits 60 seconds before retrying that URL. Assets use a 60-second
timeout and analytics 30 seconds. An initial live read allows 68 seconds for the
relay to start; a read after a verified tick allows 22 seconds. Automatic discovery
retains a detected match ID for up to three minutes between successful reads.
After a terminal broadcast error, the HUD shows `BROADCAST UNAVAILABLE / AUTO RETRY`.
The next attempt backs off for at least 60 seconds. HTTP 502 and SSE status 502
mean the API could not fetch the live relay. The broadcast URL endpoint shares
the relay cache, so a second URL lookup does not supply an independent feed.
Failures clear purchase advice or suppress unavailable counter evidence.
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
item ID, ranking and counter bases/windows, wins and sample counts for each
row, pool counts, raw gain, both Wilson bounds, supported gain, and decision.
`items` includes the five score terms and
affordability. `requests` records hero/enemy/bucket filters, cache use and fetch
times; `assets_fetched_at`, `live_tick`, `valid_until` and `context` describe
freshness and live inputs. These fields reproduce the counter claim without
another API request whose underlying data may have changed.

## Inventory-aware progression

The catalog's `component_items` relationships identify real upgrades.
Owned items and ingredients of an already-owned upgrade are excluded. An
upgrade that consumes an owned component can reuse its occupied category slot
and receives a small +0.3 tempo preference. A planned component is reserved
once, and a queue cannot contain both an upgrade and its ingredient as final
options. Prices use the full catalog price.

The standard inventory starts with nine universal slots and can reach twelve
through Walker objectives. If the API omits slot unlocks, purchase advice uses
only free base slots and slot-neutral conversions. Twelve held items establish
a full inventory on their own. [Valve's inventory slot patch notes](https://forums.playdeadlock.com/threads/11-21-2025-update.90383/)

With a confirmed full inventory, the Full build board can suggest one optional
replacement. The wallet must cover the full new price independent of the sale.
The old and new items must have the same category, activation type and current
net-worth bracket, with at least 600 observations each. The new item's 95%
one-sided Wilson lower bound must beat the weighted pool and exceed the held
item's upper bound by at least 1.5 percentage points. Keep useful same-bracket
counters and planned components. Available component upgrades take priority.
`inventory_replacement` records the names, counts, bounds, price and inventory
capacity used. These are historical purchase outcomes.

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
The corner reader uses the verified foreground game process and client bounds.
If window capture yields blank pixels, it tries the same on-screen crop after
checking focus and sampling for obstructions. It stores no images.
The broadcast reader skips replayed ticks and keeps reading for a newer complete
roster within the request deadline.
Settings show the current failure reason. Game detection alone never proves a
broadcast is available, and real-game validation remains outstanding.

## How other tools rank items

| Tool | Documented approach |
| --- | --- |
| Statlocker | Estimates purchase-time changes in a match-state probability model from replay timelines. A public item win rate alone cannot reproduce those estimates. [Statlocker methodology](https://statlocker.gg/about) |
| Deadlock Blueprint | Adds counter rules to an ordered build and protects components selected for upgrades. Its published client checks periodically for generated data. [Queue logic](https://github.com/PedroGomesFR/deadlock-blueprint/blob/main/src/services/recommendations.ts) |
| Lockdex | Uses hourly snapshots and recent samples when a patch has limited history. Its phase views distinguish what people buy from the effect of buying it. [Lockdex methodology](https://lockdex.io/about) |

The overlay adopts recent cohorts, an explicit observation window, and
component protection. Deadlock API also offers item-flow statistics conditioned
on items bought in specific phases. A late connection gives the overlay the
held items but may lack their purchase times, so it leaves that inference out.
[Deadlock API endpoint schema](https://api.deadlock-api.com/openapi.json)

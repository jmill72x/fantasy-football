# Auction Cheatsheet Pipeline — Design

**Date:** 2026-08-01
**League:** STRIPES FANTASY FOOTBALL LEAGUE (SFFL), CBS Sports Fantasy
**Status:** Design approved, pending spec review

## Problem

The SFFL auction is conducted offline. Draft results are entered into CBS by the
commissioner afterward, so no draft app can sync live. Every ranking product must
therefore be reduced to a static artifact before auction day, and maintained by hand
during it.

Compounding this, the league's settings are unusual enough that generic rankings are
actively wrong: a Team QB slot, a merged WR/TE position, five flexible lineup slots,
and threshold-based scoring. The 2025 cheatsheet was built on FantasyPros' default
settings and therefore ranked individual quarterbacks — a position that does not exist
in this league.

The goal is a repeatable pipeline that converts any service's export into two
artifacts: a dense Excel sheet for two-sided printing, and a scrolling PDF sized for
markup on an iPad Pro 11" with Apple Pencil.

The repository must outlive any one subscription. Which service is used is a
configuration choice, not an architectural one.

## League Profile

### Structure

| Setting | Value |
|---|---|
| Teams | 12 (2 divisions) |
| Roster | 13 total — 8 starters, 5 bench |
| Auction budget | $110 per team |
| Format | Full redraft |
| Scoring | Head-to-head, points |
| Player pool | AFC + NFC |

Total league capital is $1,320 across 156 roster spots — an average of **$8.46 per
player**.

### Lineup

| Slot | Min | Max |
|---|---|---|
| TQB | 1 | 1 |
| RB | 1 | 4 |
| WR | 1 | 4 |
| TE | 0 | 4 |
| K | 1 | 1 |
| DST | 1 | 1 |

TQB, K, and DST are fixed at one each. The remaining **five slots are flexible**
across RB/WR/TE, with a floor of one RB and one WR/TE.

Two league-specific facts that no generic tool models:

1. **TQB is a team unit** — the cumulative totals of all quarterbacks on an NFL
   franchise. There are 32 draftable TQBs, not ~40 quarterbacks.
2. **WR and TE are the same position** — rostered and scored identically. This is why
   TE's active minimum is 0. Valuation must treat them as one pool.

**Confirmed:** CBS enforces a minimum of **one from the merged WR/TE pool**, not one WR
specifically. The displayed `WR min 1, TE min 0` is an artifact of CBS listing the two
separately; a lineup of 1 RB + 1 TE + 3 RB is legal.

So the binding lineup constraint is: **TQB + K + DST fixed at one each, then five
flexible slots across RB/WR/TE with a floor of one RB and one WR/TE.** Replacement level
must be computed against that constraint, not against per-position minimums.

### Scoring

All scoring is **threshold-based**. Points come from banded stat totals, not per-unit
rates.

**Passing** — Yards: 150–250=2, 251–350=4, 351–450=5, 451+=7. Completions: 15–19=2,
20–24=3, 25–29=4, 30–34=5, 35–39=6, 40+=7. TD 5 (+1 if 36+ yds). INT −1. 2PT 2.

**Rushing** — Yards: 50–74=2, 75–99=3, 100–124=4, 125–149=5, 150–174=6, 175–199=7,
200–224=8, 225–249=9, 250+=10. TD 3 (+2 if 3–35 yds, +5 if 36+). 2PT 2.

**Receiving** — Yards: 50–74=1, 75–99=2, 100–124=3, 125–149=4, 150–174=5, 175–199=6,
200+=7. Receptions: 5–6=2, 7–8=3, 9–10=4, 11–12=6, 13+=7. TD 5 (+1 if 36–74, +3 if
75+). 2PT 2. Offensive fumble recovery TD 4.

**Kicking** — FG 1 + distance bonus (+1 for 20–29, +2 for 30–39, +3 for 40–49, +4 for
50–59, +7 for 60+). Missed FG (1–49) −1. XP 1.

**Defense/ST** — Points allowed: 0–2=6, 3–5=5, 6=4, 7–9=3, 10–13=2, 14=1, 15+=0.
Yards allowed: 0–150=6, 151–250=4, 251–299=3, 300–350=2, 351–399=0, 400–499=−1,
500+=−2. Def/ST TD 6. Safety 4. INT 1. Fumble recovery 1. ST 2PT conversion 2.
ST one-point safety 1. Sacks: 0 below 3, then 3 at exactly 3 and +1 per sack after
(verified — see below).

#### Consequences

**Hard floors.** Receptions score nothing below 5. Rushing and receiving yards score
nothing below 50. Passing yards nothing below 150. A large share of real weekly stat
lines score zero.

**Convex tiers.** Receiving yards pay ~0.013 pts/yd at 50–74 but ~0.034 pts/yd at
175–199, capping at 200+. The league pays for spike weeks, not steady accumulation —
the opposite of most managers' instincts and of per-unit PPR rankings.

**Season totals cannot produce correct values.** Thresholds apply to each week's stat
line. Two players with identical season totals score differently based on
distribution, and the thresholds sit where the mass of the distribution is.

**Ambiguous sack scoring — two candidate readings.** CBS states `0-2 SACKs = 0 points
for every 1 SACK`, `4-99 SACKs = 1 point for every 1 SACK`, `Plus a 3 point bonus @ 3+
SACK`. Both readings agree that 0–2 sacks score 0 and 3 sacks score 3. They diverge
above that:

| Sacks | (A) bonus covers first 3 | (B) bonus is additive |
|---|---|---|
| 3 | 3 | 3 |
| 4 | 4 | 7 |
| 5 | 5 | 8 |

**RESOLVED — (A) is correct.** Verified against the Eagles DST 2025 game log, weeks
13–17, in `poc/verify_dst_scoring.py`. (A) matches CBS on 5 of 5 weeks; (B) on 2 of 5.
Week 15 is the clean discriminator: **4 sacks, and CBS awarded 4 sack points, not 7.**

So sacks score **0 below 3, then 3 points at 3, then +1 per sack thereafter** —
0, 0, 0, 3, 4, 5, 6, … The bonus is not additive; it subsumes the first three sacks.

Those same five games independently validated the rest of the DST model. Computed
totals matched CBS exactly every week, confirming the points-allowed bands,
interceptions at 1, fumble recoveries at 1, and the yards-allowed table across five
distinct bands (75, 220, 275, 331, 425 yards hitting `0-150`, `151-250`, `251-299`,
`300-350`, `400-499`).

This is the golden-file pattern the rest of the scoring engine should follow: a real
CBS stat line, the points CBS awarded, and an assertion. It also demonstrates why
weekly data matters — one screenshot resolved a rule ambiguity and verified most of a
position's scoring surface.

### Silent auction (round 1)

Round 1 is a **sealed-bid first-price auction for draft position**:

- All 12 managers submit a blind bid
- Every bidder receives a round-1 player, in descending bid order, **each paying their
  own bid**
- Ties broken by a pre-submitted **bump bid**
- Winners pick any player they want
- The resulting order sets **nomination order for every subsequent round, repeating**

The open auction begins in round 2.

#### Empirics — five years, `data/league/silent-auction-bids.csv`

**The bump rule, derived from 48 rows of 2021–2024 data:**

> Cap cost = bid, **plus the bump only if your bump uniquely wins a tie.**
> No tie, or a lost tie, and the bump costs nothing. If bumps *also* tie, it goes to a
> live auction and the price escalates past bid+bump.

45 of 48 rows fit exactly. All three exceptions are bump-ties resolved live — most
visibly 2023's four-way tie at $39, where three managers bumped $1 and the slots
resolved to $42/$41/$40.

**The bump is therefore cheap optionality, and this league misprices it.** Ties involve
50–67% of managers every year, yet ten documented cases exist of a manager losing a
draft slot to a larger bump. Italian Style Partiers bid top-five every year but bumped
$0 in three of four, losing a slot each time — including the #1 overall pick in 2024,
to a $1 bump.

**Round 1 consumes far more capital than first assumed:**

| | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| Round 1 total | $432 | $412 | $416 | $412 | $415 |
| Share of $1,320 | 32.7% | 31.2% | 31.5% | 31.2% | 31.4% |

**~31–33% of all league capital, blind, every year**, within a percentage point. After
round 1 the average team holds ~$75 for 12 players — **$6.25 each**. An earlier estimate
of 18% was wrong by most of a factor of two.

**The floor is $26, not the $20 first assumed.** The low bid is exactly $26 in all five
years and never once below — consistent with it being a hard rule (confirmed below).

**Bids cluster** at $26, $30–31, $33, $35, $38–39, and $41, so bidding $1 above a cluster
is nearly free. Six of twelve managers are highly predictable year over year — Bravo
Company has bid exactly $26 five years running; Aggressive Gamblers bids $26–27 with a
$2 bump every year; Stupid Mutants bids $39–42 with a $1 bump every year.

**Rules confirmed by the commissioner (2026-08-02):** the bid floor is **$26**, a real
rule rather than a convention. A manager who does not submit a bid **forfeits their
first-round pick entirely** and takes no round-1 player.

#### Is the floor an overpay at slot 12?

The hypothesis: since the marginal round-1 player must cost $26, and that player might
clear for less once open bidding starts, the tail of the silent round could be
systematically overpriced.

**2025 data does not support it.** Only 5 of 144 open-auction players cost $26 or more
and the open auction averages $6.26/player — but the single highest open-auction price
was **$32 (Jonathan Taylor)**, above the $26 paid at slot 12. Twelve managers holding
cash and thin rosters bid residual scarcity straight back up, so the best asset
available after the silent round cost *more* than the cheapest silent slot.

Rank-for-rank premium of silent price over the Nth-most-expensive open player averages
**$9.60**, and is larger at the top (slots 1–6: $10.70) than the bottom (7–12: $8.50).
The floor compresses the tail rather than inflating it.

Caveat: one year of price data, comparing prices rather than evaluating player quality.
CBS draft results for 2021–2024 would settle it.

## Architecture

Four components plus a planner. Components 1 and 2 are the durable asset; 3 and 4 are
replaceable.

```
leagues/sffl/2026.yaml     settings profile, versioned per season
sources/*.yaml             one per service — mappings + capabilities
identity/aliases.yaml      accumulated name/team fixes
layouts/*.yaml             render spec — drives both Excel and PDF
src/{ingest,value,render}/
data/  output/             gitignored
```

### 1. League profile (`leagues/sffl/2026.yaml`)

Every threshold table, roster rule, budget figure, and the WR/TE merge, encoded once
as data. Versioned per season so a 2027 rule change is a new file and prior years still
reproduce exactly.

This is data, not code, because it is the component that must be right.

### 2. Ingest and normalize

**Canonical schema.** Everything downstream reads this and never a service's format:

```
player_key  name  team  pos  bye  tier
rank_overall  rank_pos  adp  ecr
proj_*        per-stat season projections where available
value_source  the service's own auction $
notes  injury_status  source  source_year
```

Missing fields are null, never absent, so the renderer degrades rather than crashes.

**Source profiles.** One YAML per service — column mapping, file globs, capabilities:

```yaml
files: ["*LEAGUE*.csv"]
columns:
  Player: name
  "Auction $": value_source
capabilities:
  league_aware: true
  provides_tqb: true
  provides_auction_values: true
  provides_weekly: false
```

Adding a service is a ~20-line YAML with no code change. Header auto-detection proposes
the mapping on first run against a synonym dictionary; confirming once writes the
profile.

**File sets, not files.** The 2022 FantasyPros extract was eight per-position files;
Draft Sharks ships two. Globs are mandatory — a single-file importer breaks immediately.

**Capabilities drive graceful degradation.** When `provides_tqb` is false, the pipeline
either synthesizes team totals by aggregating a franchise's quarterbacks, or reports
plainly that the source cannot serve this league's most important position.

**Identity resolution.** The component that decides whether this survives to 2028.
Observed in existing files: `Patrick Mahomes II`, `Marvin Harrison Jr.`,
`Kenneth Walker III`, `Aaron Jones Sr.`, and team codes that disagree (`JAC`/`JAX`,
`LV`/`LVR`, `WAS`/`WSH`). A single 2025 FantasyPros file formats the same player as
`Ja'Marr Chase (WR - CIN)` in one column block and `Ja'Marr Chase - CIN` in another.

Worse, the league's own records are hand-typed by the commissioner. The 2025 roster
sheet misspells roughly 9% of 156 names: `JAMAAR CHASE`, `JAAMYR GIBBS`, `TYREKE HILL`,
`TUA TAGOVIOLOA`, `MARVIN HARRSON JR`, `TJ HOCHENSON`, `CAM SKATEBO`, `AARON ROGERS`,
`JOKOBI MEYERS`, `TYLER ALGIER`, `MARVIN MIMMS JR`, `CHASE MACLAUGHLIN`, `DAVON ACHANE`,
and `BRANDONAIYUK` with the space omitted.

An alias table alone cannot absorb this, because a fresh set of typos arrives every
year. Approach:

1. Deterministic normalization — strip suffixes, fold punctuation, canonicalize teams
2. `identity/aliases.yaml` for known fixes, accumulating over time
3. **Fuzzy matching with a review queue** for the remainder, surfacing each unmatched
   name with its best candidates for one-keystroke confirmation, which then writes back
   to the alias file

**Unmatched players fail loudly.** A silently dropped Bijan Robinson is a disaster
discovered mid-auction.

Two league-specific mappings the naive schema misses:

- **TQB units are recorded by their starting quarterback's name.** `JOSH ALLEN $23` on a
  roster is the Buffalo team QB unit. Rosters may hold **more than one TQB** — TQB has
  no roster-total limit, only a start-one limit — so `JOSH ALLEN` and `KYLER MURRAY` can
  coexist as two franchise units on one team.
- **Defenses use a third naming convention.** `PHILLY D` / `KC D` / `MINNESOTA D` in
  league records, versus `Denver Broncos` in both FantasyPros and Draft Sharks.

### 3. Value engine

Emits two columns side by side:

- **`value_source`** — the service's own auction value, passed through
- **`value_custom`** — computed against the league profile, using the merged WR/TE pool
  and replacement level derived from five flexible slots across 12 teams

The delta between them is the edge indicator.

**Stated bias.** `value_custom` approximates threshold scoring by applying tier tables
to per-game averages derived from season projections. This is knowably wrong in a
specific direction: averaging collapses the variance that convex tiers reward, so it
**systematically undervalues high-variance players and overvalues steady ones**. The
magnitude is largest for receivers near the 5-reception and 50-yard floors.

It is shipped anyway, clearly labeled, because the delta against a league-aware source
is informative even when the absolute number is biased. If a service exposing weekly
projections is adopted, this component is replaced without touching ingest or render.

### 4. Render

One declarative layout spec emits both targets.

**Excel — unchanged from current practice.** Two sheets, dense, two-sided print, flipped
by hand during the auction. This is a solved problem and is preserved as-is; the layout
spec simply emits a dense profile.

**PDF — portrait, two-up, continuous scroll.** Sized for iPad Pro 11" M4 (2420×1668 @
264 ppi).

Geometry was chosen by measurement:

| Orientation | Usable width | Visible height | Columns | Rows | On screen |
|---|---|---|---|---|---|
| Landscape | 626pt | 455pt | 2–3 | 28 | 56–84 |
| **Portrait** | 425pt | 660pt | 2 | 41 | **~82** |

Portrait wins because the scroll axis and long axis agree — vertical flicking is free,
horizontal panning is friction on every markup. Row height 16pt, dense but writable
given a horizontally generous write-in box.

**Color as an edge bar, not a fill.** A 5pt solid chip on each row's left edge, full
row height. The 2022 template flooded cells with position color, which is fine on paper
but fights Pencil ink. The bar costs ~2% of width, reads instantly when scanning, and
never sits under handwriting. Five groups: TQB, RB, WR/TE, K, DST — with WR and TE
sharing a hue (TE a lighter variant) so the merged pool reads as one block while
remaining distinguishable.

**Three sections, with PDF outline bookmarks** so the budget tracker is one tap away
rather than 200 players of scrolling:

1. **Overall board** — deepest section, color-barred, two-up, write-in price column
2. **Position boards** — RB, WR/TE, TQB (all 32), K, DST
3. **Auction management** — budget tracker, roster slots, 12-team spend grid, silent
   auction planner

### 5. Silent auction planner

A pre-draft worksheet, not a cheatsheet page. For each candidate: your value, the bid
that wins at each rank, and resulting budget per remaining slot at each bid level.

Driven by `data/league/silent-auction-bids.csv` rather than arithmetic alone. Because
bids cluster and six of twelve managers are highly predictable, the planner should show
the **historical bid distribution by rank**, flag the cluster points, and recommend a
bump — the bump is free unless it wins, and half the field ties every year.

Reference math: after a $26 bid, $84 remains for 12 players; reserving $1 minimums
leaves $72 discretionary. At $40, that becomes $58.

**Manager profile: Sgt Hulka's Big Toes.** Top-4 in four of five years, two #1 finishes.
The most concentrated bidder in the league — 2025 round-1 price $43 against a $34.6
league mean, top-3 spend $91 against a $76 mean, and seven $1 players against a mean of
5.4. The one poor year, 2022, is the only year the bid was $30 with a $0 bump; the tie
was lost and the slot fell to 9th.

## Testing

- **League profile** — scoring functions tested against hand-computed stat lines at
  every threshold boundary, including the 3-sack discontinuity
- **Ingest** — golden-file tests against the real 2022, 2024, and 2025 extracts already
  in iCloud, which cover three services and three formats
- **Identity** — an assertion that every player in a source resolves or is reported;
  regression cases for each observed name variant
- **Render** — page geometry assertions (row counts, no horizontal overflow) rather
  than pixel comparison

## Non-Goals

- Live draft sync. The auction is offline; this is the premise of the project.
- Replicating CBS scoring for in-season use. Draft prep only.
- Recommending a subscription. See `docs/research/2026-service-evaluation.md`.
- Keeper logic. Full redraft.

## Open Questions

1. **Replacement-level policy.** Starter-based (61st flex) gives only 72 players
   positive VORP, concentrating the $1,164 surplus so the top player reaches 48% of
   budget. Draftable-pool-based (156th, the last player actually rostered) spreads
   dollars wider and caps the top nearer $30–35. Starter-based is textbook VORP;
   draftable-pool is more common for auctions. One-line change, materially different
   board. Decide before the engine is built.

## Vendor Confirmation (2026-08-02)

Draft Sharks supports TQB, confirmed three independent ways: 32 TQB rows in the 2024
export, `TQB Team Quarterback` in their web sync configurator, and `Team Quarterback: 1`
under Advanced Positions in the live 2026 iPad app with this league synced.

The app also reports the league as `12 TEAM · REDRAFT · AUCTION · 13 ROUNDS` with
`RB/WR/TE: 3` pure-flex — 8 starters total, matching CBS.

**Draft type is a manual override that must be re-applied and verified.** CBS reports
the league as a Snake draft — the offline auction is invisible to it — so every Draft
Sharks sync imports as Snake and has to be changed to Auction by hand.

This is the likely cause of the unusable auction values in the 2024 export, whose ADP
column uses round.pick snake notation (`5.01`, `7.07`, `3.06`) and whose `Auction $`
column reads `$-11` on every row. Snake configuration, meaningless auction prices.

**Checklist item before every extract:** confirm draft type is AUCTION. In particular,
confirm it *after* using "Re-sync League", which may reset the override. A silently
reverted setting produces a plausible-looking file with a worthless value column.

Remaining vendor question is **banded scoring**, not TQB: can Draft Sharks express
`50-74 ReYds = 1, 75-99 = 2, ...`? This is what disqualified FantasyPros.

## Validation Deferred to First Real Extract

The 2024 Draft Sharks export projects WRs far below TEs (Lamb 142 vs Kelce 235) despite
the two being the same position under league rules. Most likely a bad extract or a
TE premium in that season's sync config. Not worth debugging against data that will be
replaced — but the first 2026 extract must be checked for this before any value output
is trusted.

## Carried Into the Value-Engine Plan

Residual items from the scoring-and-ingest branch, parked deliberately rather than fixed:

1. **`pass_att` is no longer ingested.** Both source profiles dropped it to satisfy the
   new stat-vocabulary validation, while `tqb.py`'s `PASSING_STATS` still lists it, so it
   is always absent. Nothing consumes it today. If the value engine wants attempt volume,
   add it to `STAT_KEYS` and restore the mapping rather than re-adding it to the profiles
   alone.
2. **`leagues/sffl/2026.yaml` header comment is stale.** It says "inclusive both ends.
   Outside all bands = 0", which stopped being accurate when band lookup changed to
   "first band whose high >= value" (values above the top band now take the top band's
   points; the floor still returns 0). This is the file the league owner edits by hand.
3. **Footballguys cannot serve kickers.** That vendor supplies only total field goals, not
   the by-distance split the scoring requires, so `pk` is excluded from its position
   filter. Kickers must come from Draft Sharks.
4. **DST season scoring is knowingly wrong.** Averaging puts every defense below the
   3-sack per-game threshold, so ~42 projected sacks contribute zero of a ~92-point total.
   Pinned by `test_known_limitation_season_path_zeroes_all_dst_sacks`. The weekly
   distribution model must change this deliberately.
5. **`Resolver` is built and tested but wired to nothing.** Cross-vendor player merging is
   the value engine's job; until then no pipeline code drains `unresolved`.
6. **WR/TE are not yet merged into one pool.** Deliberate — valuation is the next plan.

## Scoring Validation Against Live CBS Output (2026-08-03)

The scoring engine was validated against roughly 250 real 2025 weekly stat lines
pulled from the live league site via browser automation, each compared to the fantasy
points CBS itself awarded. Scripts live in `poc/validate_*.py`.

**Band coverage: 44 of 45.**

| table | proven | outstanding |
|---|---|---|
| pass_yds | 4/4 | — |
| pass_cmp | 6/6 | — |
| rec_yds | 7/7 | — |
| rec_ct | 5/5 | — |
| def_pa | 7/7 | — |
| def_ya | 7/7 | — |
| rush_yds | 8/9 | `250+` |

Kicking: 6 of 7 rules proven (17/17 weeks exact). Only the sub-50 missed-FG penalty
is unproven — the sampled kicker missed none inside 50 all season.

`rush_yds 250+` is **unprovable from 2025**, not wrong: the season high was Jonathan
Taylor's 244 yards, six short of the boundary.

### Rules discovered that the settings page does not state

- **No fumble-lost penalty.** Multiple games with a lost fumble scored exactly base.
- **No penalty for a missed extra point** (4-of-5 and 0-of-2 XP weeks both exact).
- **No penalty for a missed 50+ field goal** (0-of-2 from 50+, still exact).

### Findings

- **One CBS data error.** Barkley 2025 wk16 (132 rush yds, 1 TD, 12 pts) fits no legal
  touchdown value. Two independent games — Henderson's 147 and 148, Henry's clean
  126-yard/no-TD 5 — confirm the `125-149 = 5` band the anomaly appeared to contradict.
- **TQB logs display the primary passer but score the whole quarterback room.**
  Unexplained weeks track quarterback usage exactly: Philadelphia 0 of 18, Denver 1 of
  19, Dallas 3 of 17. This confirms `build_tqb`'s aggregation is correct, and means TQB
  weeks cannot be fully verified from the visible log.
- **2024 is a different rulebook.** Barkley's 2024 season mismatches in 3 of 20 weeks,
  two of which contain zero touchdowns. Prior seasons must never be used to validate
  current bands. This is why `leagues/sffl/<year>.yaml` is versioned per season.

### Validated touchdown asymmetry

| distance | rushing | receiving |
|---|---|---|
| 1-2 yds | 3 | 5 |
| 3-35 yds | 5 | 5 |
| 36-74 yds | 8 | 6 |
| 75+ yds | 8 | 8 |

Short and long tiers are equal; the middle tiers are not. A goal-line rushing TD scores
3 where a 5-yard receiving TD scores 5, and a 36-74 yard rushing TD scores 2 more than
the equivalent reception. Deliberate per the commissioner. The value engine must not
assume touchdown parity across positions.

## TODO: Widen the Weekly Collection (start a fresh session)

`data/weekly/2025/` is currently a **starter sample**: 18 players, 301 player-weeks,
seeded by `poc/seed_weekly.py` from logs gathered while validating the scoring engine.
It covers every position and is enough to build and prove the calibration curves end to
end. It is **too thin to trust the curves themselves** — 18 players cannot span the
range of per-game means the curves interpolate over.

**Target: roughly 120 players** — about 30 each at RB and WR/TE, 15-20 each at TQB, K
and DST — chosen to span low, middle and high per-game means at every position.

**Method, already proven:**

1. Harvest player IDs per position from
   `/stats/data-stats-report/all:<POS>/season:2025/standard/stats?print_rows=9999`,
   read with `get_page_text`. Do NOT read that table with `javascript_tool` — a content
   filter rejects the response.
2. Fetch each game log from inside the page with `javascript_tool`, which works and is
   far cheaper than navigating per player:

   ```js
   const res = await fetch('/players/playerpage/gamelog/<ID>/', {credentials:'same-origin'});
   const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
   const t = Array.from(doc.querySelectorAll('table')).find(x => x.rows.length > 10);
   ```

   Row 0 is the stat-group row (expand by colspan), row 1 the headers, rows 2+ the data.
   Column layout differs per position, so map `(group, header)` pairs rather than
   positions.
3. Regular season only, weeks 1-18. Omit weeks a player did not appear rather than
   writing zeros — a bye must not drag a per-game mean down.
4. Append to `data/weekly/2025/<POS>.csv` using the header in
   `docs/superpowers/plans/2026-08-03-value-engine.md` Task 1.

**Integrity check to re-run after widening:** score every seeded row with `score_game`
and compare to `cbs_fpts`. Rows may fall short (TD distance bonuses are not published),
but **no row may exceed** its CBS value. An over-scoring row means a transcription error.

Do this in a fresh session — it is mechanical work that needs none of the design context.

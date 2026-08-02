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

**Open item:** CBS lists `WR min 1, TE min 0`, which would reject a lineup of 1 RB +
1 TE + 3 RB. Confirm whether CBS enforces this or whether the merge is complete.

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
ST one-point safety 1. Sacks: 0–2 = 0/sack, 4+ = 1/sack, plus a 3-point bonus at 3+.

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

**Suspected config bug.** Sacks score `0/sack` in the 0–2 band and `1/sack` in the
4–99 band. Exactly 3 sacks falls in neither, so a 3-sack game scores only the +3 bonus
while 4 sacks scores 7. The engine must reproduce CBS's behavior exactly, not the
intended behavior. Flagged for the commissioner.

### Silent auction (round 1)

Round 1 is a **sealed-bid first-price auction for draft position**:

- All 12 managers submit a blind bid, minimum ~$20
- Every bidder receives a round-1 player, in descending bid order, **each paying their
  own bid**
- Ties broken by a pre-submitted **bump bid**, which adds to the price paid
- Winners pick any player they want
- The resulting order sets **nomination order for every subsequent round, repeating**

The open auction begins in round 2.

This consumes **≥$240 — over 18% of all league capital — blind, on 7.7% of rostered
players**. It is simultaneously the highest-leverage and highest-variance decision of
the draft, and it also confers repeating nomination control, an asset nobody prices.

**Open item:** whether the minimum is exactly $20, and what happens to a non-bidder.
"Forfeits a first-round pick" and "secures pick 12 cheaply" are mutually exclusive.

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

Approach: deterministic normalization (strip suffixes, fold punctuation, canonicalize
teams) plus a hand-editable `identity/aliases.yaml` that accumulates every fix ever
made. **Unmatched players fail loudly.** A silently dropped Bijan Robinson is a
disaster discovered mid-auction.

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

Reference math: after a $20 bid, $90 remains for 12 players; reserving $1 minimums
leaves $78 discretionary. At $35, that becomes $63.

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

1. Does CBS enforce `WR min 1` despite the WR/TE merge?
2. Exact silent auction minimum, and treatment of a non-bidder
3. Does Draft Sharks' 2026 CBS sync still emit TQB rows? Verified present in the 2024
   export (32 rows with projections and TQB-specific ADP); this most affects the
   subscription decision.
4. Is the sack scoring gap at exactly 3 intentional?
5. **Replacement-level policy.** Starter-based (61st flex) gives only 72 players
   positive VORP, concentrating the $1,164 surplus so the top player reaches 48% of
   budget. Draftable-pool-based (156th, the last player actually rostered) spreads
   dollars wider and caps the top nearer $30–35. Starter-based is textbook VORP;
   draftable-pool is more common for auctions. One-line change, materially different
   board. Decide before the engine is built.

## Validation Deferred to First Real Extract

The 2024 Draft Sharks export projects WRs far below TEs (Lamb 142 vs Kelce 235) despite
the two being the same position under league rules. Most likely a bad extract or a
TE premium in that season's sync config. Not worth debugging against data that will be
replaced — but the first 2026 extract must be checked for this before any value output
is trusted.

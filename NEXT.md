# NEXT — pick up here

Handoff notes for a fresh session. Read this first, then the spec and the relevant plan.

## Where things stand

Auction cheatsheet pipeline for the STRIPES Fantasy Football League (CBS). Four plans;
**plans 1 and 2 are merged and done.** The valuation is finished and validated against
real prices. What remains is rendering it onto paper and an iPad.

| | Status |
|---|---|
| **Plan 1 — scoring foundation & ingest** | ✅ merged, 64 tests |
| **Plan 2 — value engine (VORP → dollars)** | ✅ merged, plus valuation corrections, lineup floors and market calibration — 165 tests |
| **Plan 3 — Excel + PDF renderers** | ⬅️ **NEXT.** Not written. Every design decision is settled (see below); first task is installing `reportlab`/`openpyxl` and pinning a `requirements.txt` |
| **Plan 4 — silent auction planner** | not written — consumes plan 2 values |

Verify state in one command:

```bash
cd ~/Projects/fantasy-football && ./.venv/bin/pytest -q && git log --oneline -3
```

**What works today — this is the production command.** It reads an extract, scores it
against league rules, values the pool, fits both the replacement policy and the market
price curve against 154 real 2025 prices, and writes a priced board:

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli value \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026 \
  --policy fit --prices data/league/auction-rosters-2025.csv \
  --curves calibration/2025.yaml --out board.csv
```

543 players, TQB=32. Every row carries **MY$** (worth against replacement) and **EST$**
(what the room will pay). Nothing renders it yet — that is plan 3.

## GOAL THIS WEEK — a full dry run

Produce **real Excel and PDF cheatsheets from today's archived extracts**, end to end,
before 2026-08-10. Everything must work on current data so the week of 08-23 is a pure
data refresh with no code changes and no surprises.

Done means: `sffl` reads an extract, values the pool, and writes both artifacts — and
Jeff has marked up the PDF on the iPad and printed the Excel.

### Current position

Update this block at the end of every session so the next one can resume blind.

- [x] Plan 1 — scoring foundation & ingest (merged, 64 tests)
- [x] TODO A — execute plan 2, the value engine (all 8 tasks)
- [x] Valuation corrections — K/DST flat at $1, TQB + DST markets joined to the fit
- [x] Lineup floors — 1 RB and 1 WR/TE enforced at flex replacement
- [x] Market calibration — EST$ (what the room pays) beside MY$ (what he's worth), 165 tests
- [x] Plan 3 written — `docs/superpowers/plans/2026-08-04-renderers.md`, 3 tasks
- [x] `reportlab` 5.0.0 + `openpyxl` 3.1.5 installed, `requirements.txt` pinned
- [ ] **Plan 3 IN FLIGHT on branch `renderers`** — see "Renderers: live status" below
- [ ] Write plan 4 (silent auction planner), then execute it
- [ ] TODO B — widen the weekly collection to ~120 players (needs `claude --chrome`)
- [ ] Full dry run: generate both artifacts, review on the iPad
- [ ] Clean licensed values out of the two tracked fixtures (see FOLLOW-UP below)

Work top to bottom. Each unchecked box is the next thing to do.

### Renderers: live status (branch `renderers`, not yet merged)

**Check this branch, not `main`, for renderer progress.** `git log --oneline main..renderers`.

| Task | State |
|---|---|
| 1 — render rows, tiers, byes (`src/sffl/render/rows.py`) | ✅ done, reviewed, 179 tests |
| 2 — PDF (`src/sffl/render/pdf.py`) | ⚠️ built (185 tests) — review found **one Critical**, fix in flight |
| 3 — Excel + `render` CLI command | not started |

**Task 2's open Critical:** the Overall Board was including K and DST. The spec is explicit
that it carries TQB/RB/WR/TE only, and that K/DST appear together on their own page — the
validated colour palette depends on it, having been checked as *two disjoint sets* because
those six colours were never supposed to co-occur. One-line filter; being fixed.

**Real-data render works:** 18 pages, every section populated (TQB 32, RB 122, WR 194,
TE 105, K 35, DST 32). Drops to 17 once the Critical is fixed.

**Found during the real run — 23 of 543 players carry placeholder team codes** (`UNS` ×22
unsigned free agents, `RK` ×1). They have no NFL team, so no bye week, and `build_rows`
correctly raises rather than rendering a blank. All sit below replacement, so they affect
no dollar value. Task 3 filters them at render time and reports the count — dropping them
silently would be the wrong shape of fix.

**Carry into plan 3 — the caveats that must survive onto the printed page:**
EST$ is a *floor* at the very top, not a point estimate. Spread is unmeasured, so render
it blank and never `$0`. Both are explained below; the person bidding reads the board,
not the source.

## Timeline — hard deadline

| Date | What |
|---|---|
| 2026-08-03 | Plan 1 merged. Extracts archived to iCloud as insurance. |
| 2026-08-04 | Plan 2 merged. K/DST at $1, 154 of 156 prices joining, lineup floors, MY$/EST$ two-column board. |
| **by 2026-08-10** | **Full dry run complete** — plans 2-4 built and both artifacts generated from today's data. |
| **week of 2026-08-23** | **Re-pull fresh extracts** from Draft Sharks and Footballguys for final rankings. Confirm Draft Sharks still reads **AUCTION**, not Snake — every sync imports as Snake and a reverted setting yields a plausible file with a worthless value column. |
| **2026-08-26** | **AUCTION.** Excel and PDF must be generated and printed/loaded before this. |

The dry run exists so the 08-23 refresh is a data swap. Do not leave the renderers
until after the refresh — build them against today's archived extracts.

## Facts a fresh session must NOT re-derive

- **The scoring engine is validated and must not be modified.** 44 of 45 bands proven
  against ~250 real CBS weekly observations. Details in the spec.
- **Never mix seasons.** 2024 CBS points use different scoring rules. Only 2025 may
  calibrate 2026.
- **Touchdowns are not symmetric across positions.** Goal-line rushing scores 3 where a
  short receiving TD scores 5; 36-74 yard rushing scores 8 where receiving scores 6.
- **WR and TE are ONE position.** Never split them for valuation.
- **The repo is public.** `data/extracts/` and `data/weekly/` are gitignored because they
  hold licensed vendor and CBS data. Never commit from either.
- **Python 3.9.6 only.** No `match`, no `int | None`. Use the venv at `.venv/`.
- **A zero is not a no-op for `def_pa` and `def_ya`.** Both band the value `0` at their
  MAXIMUM (6 points). Any code that loops over `lg.bands` for every player pays a phantom
  shutout to every receiver and kicker. `score_game` gates its defense block on
  `pos == "DST"` for exactly this reason, and the same trap was caught twice more during
  plan 2 — once in `build_curves`, once in `score_season_calibrated`. Both are now gated
  by `calibrate.STAT_POSITIONS`. Do not "simplify" those gates away.
- **`band_points` floors, `expected_points` clamps.** Below the first band, `band_points`
  returns 0; `expected_points` returns the curve's lowest anchor. Swapping one for the
  other without a position gate paid every non-passer 72 phantom season points. Producer
  and consumer must agree on `STAT_POSITIONS`.
- **Replacement level is `starter`, fitted, not chosen.** See the table above.

## TODO A — DONE. Plan 2 results (2026-08-04)

*(TODO B below is a data-collection chore that produces no code. The numbered plans are
the implementation roadmap above.)*

The value engine is built and works on real data. What you can run today:

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli value \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026 \
  --policy fit --prices data/league/auction-rosters-2025.csv \
  --curves calibration/2025.yaml --out board.csv
```

**The replacement-level open question is now answered empirically — and on a much wider
base of evidence than the first pass gave it.** Fitted against **154 of 156** real 2025
prices (production path, i.e. run WITH `--curves` as above):

| policy | mae | rmse | top10_mae |
|---|---|---|---|
| **starter** (chosen) | $5.73 | $9.46 | **$11.24** |
| draftable | $5.44 | $8.12 | $16.32 |

Per pool, starter policy:

| pool | n | mae |
|---|---|---|
| DST | 12 | $0.58 (flat $1 — see below) |
| K | 12 | $0.25 (flat $1 — see below) |
| FLEX | 109 | $6.28 |
| TQB | 21 | $8.98 |

**154 of 156 joins, up from 108 — and the 108 was never a whole-board number.** The roster
sheet writes defenses as `PHILLY D` and Team QB units by their 2025 starting quarterback's
name, so before this branch neither the DST nor the TQB market matched anything in the
pool at all. The old $11.68 top10_mae was computed on RB/WR/TE/K only; nothing said so at
the time. The only two prices that still don't join — Joe Mixon and Ricky Pearsall — are
genuinely absent from the 2026 Draft Sharks extract, not a resolution failure.

`draftable` wins slightly on overall error but is far worse at the top of the board, and
the top is where a mispriced board costs real money — so `choose_policy` tiebreaks on
`top10_mae` and picks **starter**. Do not re-litigate this without new price data.

Replacement levels under starter: DST 63.9, FLEX 63.8, K 141.1, TQB 239.9 pts, at
**$0.7273 per VORP point** (up from $0.6465 — flat-pricing K/DST returns their VORP share
to the pools people actually bid on).

New modules: `weekly.py`, `calibrate.py`, `consensus.py`, `value.py`, `fit.py`, plus
`score_season_calibrated` in `pool.py` and the `value` CLI command.
`calibration/2025.yaml` is committed derived data (aggregate curve points only, no
player data) generated by `poc/build_calibration.py`.

### Things plan 3 must know

- **TWO numbers render, not one.** `_dollars` (MY$) is worth against replacement;
  `_est_price` (EST$) is what the room will pay. Both go on the board — the gap between
  them is the edge. Also on each record: `_season_points`, `_vorp`. `_est_price` is
  absent when the run had no `--prices`, so plan 3 must render it blank, never $0.
- **`_spread_<stat>` and `_n_sources` are NOT populated yet.** Only `consensus.merge`
  writes them and nothing calls it — see the wiring gap below. The CLI now writes an
  **empty string**, not `0.0`, for those columns so a zero can never be mistaken for a
  measurement. Plan 3 must handle empty.
- **Kickers and defenses are now priced flat at $1, closing the earlier open question.**
  21 real 2025 prices back this: K n=9 ranged $1–$3 (seven of nine at exactly $1); DST
  n=12 ranged $1–$3. Their projected point spreads are real but not actionable, and the
  league already prices them as fungible $1 fillers, so the model now matches the market
  instead of paying one of them ~$20. Configured via `flat_priced_pools` in
  `leagues/sffl/2026.yaml`; validated at load time in `src/sffl/league.py`. No K or DST
  appears in the top 25 by dollar value anymore. On today's archived extract the top 25
  is 6 RB, 3 TE, 3 TQB, 13 WR — re-measure against whatever extract is live when this is
  read, since the position mix will shift as projections refresh.
- **Flat-pricing K/DST also silences the documented DST sack-zeroing limitation**
  (`src/sffl/pool.py:23-35` — season-averaging zeroes every defense's sack points) **for
  pricing purposes.** DST dollars no longer depend on DST points at all, which is fine for
  the auction but means the per-pool fit table can never again surface that failure. If
  the DST model itself is ever revisited, don't look to the fit table for evidence either
  way.

### Known gaps carried forward

1. **`consensus.py` is written, tested, and wired to nothing.** The `value` command reads
   one extract. Merging Draft Sharks + Footballguys into a consensus with the spread
   preserved is the single biggest remaining edge and is not yet reachable from the CLI.
2. **The calibration curves rest on 18 players** (301 player-weeks) — that is TODO B.
   `expected_points` clamps silently outside the observed range, and `rec_yds` currently
   interpolates a straight line across a 66-yard gap with no observations in it, which is
   where most of the board lives.
3. Sacks are still uncorrected (see Open questions).

### Plan 3 — decisions Jeff settled on 2026-08-04

1. **Columns.** Derive `Tier` and `AVG PTS` from data already modelled. `AVG PTS` is
   `_season_points / games`. `Tier` comes from natural breaks in `_dollars` within each
   position group — the gaps between clusters are the useful thing at the table ("if I
   miss him, the next one is $8 cheaper"). The 2022 sheet ran tiers 1-6; match that depth
   unless the breaks say otherwise.
2. **Bye weeks — SOLVED.** Neither vendor has them: verified against the Draft Sharks
   header and all 61 Footballguys columns. Now in `leagues/nfl-byes-2026.yaml`, keyed by
   canonical team code, two independent sources agreeing on all 32. **Jeff should
   spot-check it before the auction** — it is the only file here sourced from outside the
   pipeline. Note the file quotes its keys deliberately: unquoted `NO` parses as boolean
   false under YAML 1.1 and silently dropped New Orleans on the first pass.
3. **THEIR$ — DROP IT.** Decided. It was FantasyPros' `VALUES` column, read at
   `poc/render_poc.py:123` from `~/Library/Mobile Documents/com~apple~CloudDocs/Fantasy
   Football/cheatsheet (3).csv`, rendered at `:207`/`:237`, and populated for K/DST only
   (Draft Sharks rows set `"their": None` at `:75` because that vendor's auction column is
   broken). Jeff's reason for dropping it is the important part and generalises: **those
   numbers are not customised to this league** — they assume a ~$200 cap, so FantasyPros
   prices Ja'Marr Chase at $62 when $43 is the highest price this league has ever paid.
   An uncalibrated vendor number is not defendable at the table. Do not reintroduce it
   from another vendor without calibrating to this league's capital first.
4. **RB / WR-TE floors — DONE**, merged. Both are hard lineup requirements and are now
   enforced in `replacement_levels`. **No dollar values changed:** the natural top 60 flex
   is 19 RB and 41 WR/TE against floors of 12 and 12, so the floors do not bind on this
   extract. It is a guard for a future one.

   Worth recording so nobody re-derives it: forcing a floor can only **raise** the flex
   replacement level, never lower it. A floored-in player displaces a higher-ranked one,
   so the best *excluded* player improves. An early draft of the brief asserted the
   opposite and was provably wrong.

### RESOLVED — MY$ / EST$, the two-column board (2026-08-04)

Jeff chose option C below. `_dollars` (MY$) keeps its meaning: worth against
replacement. `_est_price` (EST$) is what the room will actually charge, fitted from
this league's own prices in `src/sffl/market.py`, and it occupies the column THEIR$
vacated. **The gap between the two columns is the edge.**

Fitted curve: `price = 2.248 * value^0.551`, from **130** observations — K and DST are
excluded from the fit because their `_dollars` is $1 by policy, not by model, so they
were 24 points at `x = log(1) = 0` anchoring the intercept. Excluding them measured
better or equal in **all six** bands.

| model band | MY$ bias | EST$ bias |
|---|---|---|
| $30+ | +$13.2 | **+$0.2** |
| $20-30 | +$7.4 | +$4.3 |
| $10-20 | +$0.5 | +$1.1 |
| $5-10 | -$4.2 | -$1.6 |
| $2-5 | -$4.3 | -$1.2 |
| $1-2 | -$2.6 | -$1.1 |

**EST$ is a floor at the very top, not a point estimate.** The fit is concave, so it
compresses range; the $30+ band average is excellent while the single most expensive
player still runs above the estimate. Top EST$ is $32.27 against a $43 record high.
Budget above EST$ for your number-one target. This caveat is in `market.py`'s docstring
and on the printed board header — **plan 3 must carry it onto the PDF**, because the
person bidding reads the board, not the module.

Correcting the tail is **cheap and deferred, not unaffordable**: weighting the four
existing closed-form sums (~4 lines) measured Pareto-better at both ends
(`b` 0.551 → 0.653; MAE on paid ≥ $25 $13.42 → $12.34 AND on paid ≤ $3 $3.96 → $3.50).
Not adopted three weeks out on in-sample single-year evidence. Revisit with 2026 prices.

### FOLLOW-UP — licensed values in two tracked fixtures

`tests/fixtures/draftsharks_sample.csv` and `draftsharks_value_sample.csv` carry
verbatim Draft Sharks figures (Josh Allen `348.5/3981.4/28.39/10.2/598.4/10.54`, Eagles
DEF `310/4930/42/14/9/3`). Committed since `55d5d49`, before this work, in a PUBLIC
repo. `draftsharks_market_fit_sample.csv` had the same rows and they were invented out.
The same cleanup is owed to these two — they exist only so no pool is empty, so the
numbers can be anything.

### Original finding — the model's top end is hotter than this league has ever paid

Found 2026-08-04 while checking Jeff's remark that "$47 or $48 would be a record high."
He is right, and it is measurable. Highest price ever paid in this league: **$43**
(Ja'Marr Chase, 2025). The model's top three are $54.2, $53.7, $47.0.

Bias against the 154 matched 2025 prices, by model dollar band:

| model band | n | model avg | actually paid | bias |
|---|---|---|---|---|
| $30+ | 13 | $40.1 | $26.9 | **+$13.2** |
| $20-30 | 10 | $22.9 | $15.5 | +$7.4 |
| $10-20 | 19 | $14.7 | $14.3 | +$0.5 |
| $5-10 | 7 | $8.8 | $13.0 | -$4.2 |
| $2-5 | 13 | $3.5 | $7.8 | -$4.3 |
| $1-2 | 92 | $1.0 | $3.6 | -$2.6 |

Monotonic and systematic. The board still totals exactly $1,320 — the total is right, the
**distribution is too steep**. This is the whole of the $11.24 top10_mae. Cause is
structural, not a bug: linear VORP-to-dollars assumes points are fungible currency, but a
real auction is budget-constrained (nobody spends $54 and still fills 13 spots) and needs
to fill every roster spot, so the top compresses and the $1 tail is bid up.

**Design question to settle before plan 3 renders anything**, because it decides what the
column means:

- **A — MY$ = what it will cost.** Calibrate to observed prices. Best for budgeting.
- **B — MY$ = what he is worth to me.** Leave it. The board then says "Nacua is worth $54,
  he will go for $43, bid." Best for finding edges. This is what it does today.
- **C — both.** Keep MY$ as value, add EST$ calibrated to this league.

Recommendation is **C, using the column THEIR$ just vacated** — swap an uncalibrated
vendor guess for a league-calibrated price prediction fitted on 154 real prices. Same page
width, far better column. Fit a monotone transform from model dollars to observed price
and renormalise so the board still sums to `total_capital()`.

This is a value-engine change, so like the lineup floors it lands **before** the renderers.

### Still blocking plan 3

**Excel target is now known.** Jeff supplied the 2022 workbook, preserved (gitignored) at
`data/extracts/_templates/stripes-2022-rankings-template.xlsx`. Requirement: **prints on
2 letter sheets, back to back.** Measured format:

| | |
|---|---|
| One sheet, landscape letter, 97% scale, gridlines off | |
| Three 6-column groups: `A-F`, `H-M`, `O-T`, separated by 0.9-wide spacers `G`, `N` | |
| Calibri 8pt throughout, bold headers, conditional formatting drives tier shading | |
| Widths: rank 2.8, name 11.6, Team/Bye 5.1, pos 3.8, tier 3.8, pts 3.5 | |
| 118 rows. OVERALL spans groups 1+2 (ranks 1-116, rows 1-59); position blocks stack below and fill group 3 | |
| 2022 columns were `Rank, Name, Team/Bye, Pos, Tier, AVG PTS` — the QB block alone had a `$` column | |

- **Confirm the THEIR$ recommendation** above (drop it, widen PAID). One-line answer.
- **`reportlab` and `openpyxl` are not installed in `.venv/`**, and there is no
  `requirements.txt`. `poc/render_poc.py` cannot run today. Installing them is the first
  task of plan 3; pin a `requirements.txt` at the same time, since the repo has no
  dependency manifest and the 08-23 refresh must not surprise anyone.
- **`poc/render_poc.py` still carries its own `load_ds`, `load_fp_kdst` and `value_pool`.**
  Plan 3 replaces all three with the real engine — `build_pool`, `score_season_calibrated`,
  `replacement_levels`, `assign_vorp`, `assign_dollars` — and keeps only the `Sheet` class,
  which is the settled, iPad-reviewed layout. The poc's own valuation is now obsolete and
  must not be carried forward: it predates flat-priced K/DST, the TQB/DST price joins, and
  the calibration curves.

## TODO B — widen the weekly collection (a data chore, NOT a plan)

**Full detail is in the spec** under *"TODO: Widen the Weekly Collection"* — target,
method, the JS that works, the trap that wasted three attempts, and the integrity check.

Short version: the calibration curves are currently built from 18 players. That proves
the mechanism but is too thin to trust the curves. Target ~120 players spanning the
range of per-game means. It is mechanical browser work needing none of the design
context, which is exactly why it belongs in its own session.

Requires launching with `claude --chrome` — browser tools are off by default.

Do TODO A first if you only have appetite for one; the code is identical whether the
curves come from 18 players or 120, and widening later changes no code.

## Open questions

1. `rush_yds 250+` is the one unproven band — no 2025 game reached it (season high 244).
   Unprovable for now, not wrong.
2. Sacks are not corrected by the calibration curves; they use a threshold rule rather
   than a band table, so a defense averaging 2.5 sacks per game still scores zero across
   a season. Pinned by a characterization test. Needs a threshold-aware curve.
3. Which subscription to buy. Draft Sharks and Footballguys both export per-stat
   projections and are already ingested. See `docs/research/2026-service-evaluation.md`.
4. **TQB is the worst-fitting pool** — mae $8.98, 1.4x FLEX's $6.28 — and the second most
   expensive pool on the board after FLEX. **Do not treat that mae as a model-quality
   score until its two components are separated; a reviewer already did the separation
   once, so don't re-derive it:**
   - The residuals are **structured, not random noise.** Rushing-QB franchises are
     under-priced (BAL −$28, WAS −$27, PHI −$18); pocket-passer franchises are
     over-priced (DAL +$21, CIN +$17, MIN +$16). WAS is the sharpest case: it averages
     45.8 rush yd/gm, under the scoring bands' 50-yard floor, so season-averaging
     (`score_season`'s known bias — see `src/sffl/pool.py:14-33`) scores that production
     as zero every week it doesn't clear 50 on its own.
   - The remainder is **irreducible by construction**, not a modeling gap to close: the
     fit asks a 2026 point projection to explain a 2025 price for an entity — a Team QB
     unit — whose actual quarterback turns over wholesale between those two years far
     more often than any skill player's roster spot does.
   - Until someone separates "how much of $8.98 is the rushing-QB averaging bias" from
     "how much is un-fixable year-over-year turnover," TQB's mae is not comparable to
     FLEX's on the same terms.

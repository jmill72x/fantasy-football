# NEXT — pick up here

Handoff notes for a fresh session. Read this first, then the spec and the relevant plan.

## Where things stand

Auction cheatsheet pipeline for the STRIPES Fantasy Football League (CBS). Four plans;
**plan 1 is merged and done**.

| | Status |
|---|---|
| **Plan 1 — scoring foundation & ingest** | ✅ merged, 64 tests green |
| **Plan 2 — value engine (VORP → dollars)** | ✅ complete, 120 tests green |
| **Plan 3 — Excel + PDF renderers** | not written — write next |
| **Plan 4 — silent auction planner** | not written — consumes plan 2 values |

Verify state in one command:

```bash
cd ~/Projects/fantasy-football && ./.venv/bin/pytest -q && git log --oneline -3
```

What works today:

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli ingest \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026
```

Turns any vendor extract into a scored, league-correct pool — 543 players, TQB=32.

## GOAL THIS WEEK — a full dry run

Produce **real Excel and PDF cheatsheets from today's archived extracts**, end to end,
before 2026-08-10. Everything must work on current data so the week of 08-23 is a pure
data refresh with no code changes and no surprises.

Done means: `sffl` reads an extract, values the pool, and writes both artifacts — and
Jeff has marked up the PDF on the iPad and printed the Excel.

### Current position

Update this block at the end of every session so the next one can resume blind.

- [x] Plan 1 — scoring foundation & ingest (merged, 64 tests)
- [x] TODO A — execute plan 2, the value engine (all 8 tasks, 120 tests)
- [ ] Write plan 3 (renderers), then execute it — **blocked on 4 decisions, below**
- [ ] Write plan 4 (silent auction planner), then execute it
- [ ] TODO B — widen the weekly collection to ~120 players
- [ ] Full dry run: generate both artifacts, review on the iPad

Work top to bottom. Each unchecked box is the next thing to do.

## Timeline — hard deadline

| Date | What |
|---|---|
| 2026-08-03 | Plan 1 merged. Extracts archived to iCloud as insurance. |
| 2026-08-04 | Plan 2 complete — real priced board generated from archived extracts. |
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

**The replacement-level open question is now answered empirically.** Fitted against 108
matched 2025 prices:

| policy | mae | rmse | top10_mae |
|---|---|---|---|
| **starter** (chosen) | $5.92 | $9.12 | **$11.68** |
| draftable | $5.88 | $8.38 | $18.21 |

`draftable` wins slightly on overall error but is far worse at the top of the board, and
the top is where a mispriced board costs real money — so `choose_policy` tiebreaks on
`top10_mae` and picks **starter**. Do not re-litigate this without new price data.

Replacement levels under starter: DST 63.9, FLEX 63.8, K 141.1, TQB 239.9 pts, at
**$0.6465 per VORP point**.

New modules: `weekly.py`, `calibrate.py`, `consensus.py`, `value.py`, `fit.py`, plus
`score_season_calibrated` in `pool.py` and the `value` CLI command.
`calibration/2025.yaml` is committed derived data (aggregate curve points only, no
player data) generated by `poc/build_calibration.py`.

### Things plan 3 must know

- **`_dollars` is the number to render.** Also on each record: `_season_points`, `_vorp`.
- **`_spread_<stat>` and `_n_sources` are NOT populated yet.** Only `consensus.merge`
  writes them and nothing calls it — see the wiring gap below. The CLI now writes an
  **empty string**, not `0.0`, for those columns so a zero can never be mistaken for a
  measurement. Plan 3 must handle empty.
- **A kicker still lands in the top 25 by dollar value** (~$20). No DST does anymore.
  Worth a human sanity-check against real market pricing before the auction — it may be
  correct (this league pays kickers well) or it may mean K replacement level is too low.

### Known gaps carried forward

1. **`consensus.py` is written, tested, and wired to nothing.** The `value` command reads
   one extract. Merging Draft Sharks + Footballguys into a consensus with the spread
   preserved is the single biggest remaining edge and is not yet reachable from the CLI.
2. **The calibration curves rest on 18 players** (301 player-weeks) — that is TODO B.
   `expected_points` clamps silently outside the observed range, and `rec_yds` currently
   interpolates a straight line across a 66-yard gap with no observations in it, which is
   where most of the board lives.
3. Sacks are still uncorrected (see Open questions).

### Plan 3 is blocked on these decisions

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

Still open, and each changes the plan:

1. **Which columns for 2026?** The 2022 sheet's `Tier` and `AVG PTS` do not exist in the
   plan 2 output, which produces `_dollars`, `_vorp`, `_season_points`. Straight swap of
   `AVG PTS → $`, or keep tiers and derive them from dollar breaks?
2. **Bye weeks.** The template wants `Team/Bye` and the Draft Sharks extract has no bye
   column — confirmed against `sources/draftsharks.yaml` and the raw header. Needs either
   a small hand-maintained 32-team bye YAML, or the column drops to team-only.
3. **THEIR$ on the PDF.** The DS auction column is known-broken. Drop it and widen the
   write-in box, populate from Footballguys, or leave blank as a write-in?
4. **RB floor.** `poc/render_poc.py`'s `value_pool` enforces ≥1 RB per team when locating
   flex replacement; the shipped `value.py` does not. The league rule is "floor of 1 RB
   and 1 WR/TE." Fixing it changes every dollar value, so it belongs *before* the
   renderers if it happens at all.

**Also blocking execution:** `reportlab` and `openpyxl` are not installed in `.venv/`, and
there is no `requirements.txt`. `poc/render_poc.py` cannot run today.

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
4. Whether a kicker belongs in the top 25 by dollar value. The fitted board puts one
   there at ~$20. Needs a human read against real market pricing, not more code.

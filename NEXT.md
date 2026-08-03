# NEXT — pick up here

Handoff notes for a fresh session. Read this first, then the spec and the relevant plan.

## Where things stand

Auction cheatsheet pipeline for the STRIPES Fantasy Football League (CBS). Four plans;
**plan 1 is merged and done**.

| | Status |
|---|---|
| **Plan 1 — scoring foundation & ingest** | ✅ merged, 64 tests green |
| **Plan 2 — value engine (VORP → dollars)** | 📋 written, not started |
| **Plan 3 — Excel + PDF renderers** | not written — write after plan 2 lands |
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
- [ ] TODO A — execute plan 2, the value engine
- [ ] Write plan 3 (renderers), then execute it
- [ ] Write plan 4 (silent auction planner), then execute it
- [ ] TODO B — widen the weekly collection to ~120 players
- [ ] Full dry run: generate both artifacts, review on the iPad

Work top to bottom. Each unchecked box is the next thing to do.

## Timeline — hard deadline

| Date | What |
|---|---|
| 2026-08-03 | Plan 1 merged. Extracts archived to iCloud as insurance. |
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

## TODO A — execute plan 2: the value engine

*(TODO A and TODO B are the next two things to DO. They are not plans 3 and 4 — the
numbered plans are the implementation roadmap above. TODO A executes plan 2; TODO B is
a data-collection chore that produces no code.)*


**Plan:** `docs/superpowers/plans/2026-08-03-value-engine.md` — 8 tasks, 44 steps, all
with real code.

Builds: empirical calibration curves replacing the banding approximation, multi-source
consensus with the spread preserved, replacement level **fitted against 156 real 2025
prices** rather than chosen, VORP-to-dollars, and a `value` CLI command.

Ready to run now. `data/weekly/2025/` already holds a starter sample (regenerate with
`./.venv/bin/python poc/seed_weekly.py` — 18 players, 301 player-weeks). Tasks 4-8 do
not need weekly data at all.

Execute with `superpowers:subagent-driven-development`, on a feature branch created
**in place** rather than a worktree — `data/extracts/` is gitignored and the real-data
verification steps need it.

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

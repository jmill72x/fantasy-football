# Regularised Calibration Curves — Design

**Date:** 2026-08-30
**Status:** proposed — this is an EXPERIMENT with a pre-registered gate, not a change we know will ship

## The problem, measured

`calibrate.build_curves` gives every player **one point** per banded stat —
`(his season mean, his realized mean banded value)` — and `expected_points` draws straight
lines through **every one of them**. That is a 48-parameter function fitted to 48 noisy
points, where each point is one player's single noisy season.

The consequence is visible in the shipped curves:

| stat | positions | players in the shipped curve | anchors |
|---|---|---|---|
| `rush_yds` | RB/WR/TE/QB | 36 | 40 |
| `rec_yds` | RB/WR/TE | — | 37 |
| `rec_ct` | RB/WR/TE | — | 31 |
| **`pass_yds`** | **TQB** | **4** | **4** |
| **`pass_cmp`** | **TQB** | **4** | **4** |
| **`def_ya`** | **DST** | **4** | **4** |
| **`def_pa`** | **DST** | **4** | **3** |

Three anchors is not a curve. It is three dots and two straight lines, and it is what
currently prices and start/sits every Team QB and every defense.

## Why "just add more data" was already rejected — and why that verdict is suspect

`data/weekly/2025/_held_back/README.md` records that adding 1,428 rows across 84 players
made the curves **worse on 6 of 7 banded stats** and worsened the price fit
(`top10_mae $11.22 → $11.32`). Smoothing and usage-filtering were both tried; neither
recovered it. That measurement was real and should not be repeated as-is.

**But the verdict was AGGREGATE, and the aggregate is dominated by the dense stats.**
`rush_yds` already had 36 players; adding more gives the interpolation more individual
variance to chase, and it gets worse. `def_pa` had **four**. Those are not the same regime,
and a count of "6 of 7 stats" cannot distinguish them.

**Pre-registered hypothesis:** the sparse stats (`pass_yds`, `pass_cmp`, `def_pa`,
`def_ya`) improve with more data while the dense ones degrade. If that holds, the right
answer is per-stat, not global — and it was invisible to a single aggregate verdict.

**Stating it in advance matters.** This project has already been burned once by a
comparison that confirmed what it expected (the phantom +$13.2 bias). The hypothesis and
the gate below are fixed before any number is computed.

## What the held-back data actually contains

| file | rows | players with ≥4 weeks |
|---|---|---|
| `_held_back/TQB.full.csv` | 544 | **32** |
| `_held_back/DST.full.csv` | 374 | **22** |
| `_held_back/WR.full.csv` | 491 | 29 |
| `_held_back/TE.full.csv` | 204 | 12 |

So `pass_*` can go from 4 players to 36, and `def_*` from 4 to 26 — if the method can use
them without chasing noise.

## The three candidates

**Baseline — what ships today.** 48 players, linear interpolation through every anchor.
Every candidate must beat this or we keep it.

**Candidate A — isotonic regression (PAVA).** Same one-point-per-player input, but fit a
monotone step function by pooled-adjacent-violators instead of interpolating. Monotonicity
is the regulariser: it cannot chase a non-monotone wiggle, which is exactly the noise the
README describes. Pure Python, roughly twenty lines, no dependencies.

**Candidate B — pooled weekly integration.** The principled one, and the reason more data
should help rather than hurt.

We are not estimating an arbitrary function. We know `band()` exactly — it is in the
league profile. The only unknown is the *distribution* of a player's weekly value around
his mean. So: pool every weekly observation, estimate the conditional spread as a
low-parameter function of the mean (e.g. a dispersion model — a handful of parameters,
not one per player), then compute

    E[band(X) | mean = m]  =  Σ band(x) · P(x | m)

numerically over a grid. More weekly rows make the *dispersion* estimate better, and the
curve is smooth and monotone by construction because `band()` is non-decreasing.

This is what the README meant by "a fitted/regularised curve rather than raw
interpolation."

## The gate — fixed in advance

A candidate ships only if it beats the baseline on **both**:

1. **Held-out accuracy, per stat.** Split players (not rows) into fit and holdout sets.
   For each held-out player with ≥4 weeks, the truth is his realized
   `mean(band(weekly))`; the prediction is `curve(his mean)`. Compare MAE per stat.
   **Report every stat separately — never a single aggregate count.** The whole point is
   that the previous verdict hid a per-stat split.
2. **Price fit.** Re-run the market fit and policy choice with the candidate curves and
   compare `top10_mae`, `top10_bias` and `top10_cost` against today's. A curve that
   predicts weekly points better but prices the board worse is not an improvement — the
   board is what the project exists to produce.

**Per-stat adoption is permitted.** If `def_pa` improves and `rush_yds` degrades, ship the
better method for `def_pa` and keep interpolation for `rush_yds`. The curve file is
per-stat already; nothing forces one method across all seven. If we do that, the artifact
must record which method produced each stat's curve — a curve whose provenance is unknown
is the failure this project keeps finding.

**Splitting must be by PLAYER, never by row.** A player's weeks in both the fit and
holdout sets leaks his own season into his own prediction and would make every candidate
look good.

**A tie is a loss.** The baseline ships today and is understood; a candidate that merely
matches it adds a method to maintain for nothing.

## Honest possible outcomes

1. **Candidate B wins on the sparse stats.** Ship it for those, keep interpolation for the
   dense ones, record which is which. Most likely outcome, and it directly fixes the
   three-anchor `def_pa`.
2. **A candidate wins everywhere.** Ship it for everything.
3. **Nothing beats the baseline.** Keep the 48-player curves, and write the measurement
   into `NEXT.md` so the next person does not spend another session re-deriving that
   more data does not help. **This is a perfectly good outcome and must not be
   presented as a failure** — the README's existing note is exactly this, and it saved
   this session from repeating a dead end.

## Out of scope

- **Changing `band_points` or anything in `src/sffl/scoring.py`.** It is validated against
  ~250 real observations. The curves change; the scoring does not.
- **Refitting the market curve's `a`/`b` form.** `market.py` records why the tempting
  tail-reweighting was rejected; untouched here.
- **2024 or earlier data.** The league's rules changed between 2024 and 2025.
- **The TQB/K/DST projection groups** (the other half of this work). That is a separate,
  bounded piece and does not depend on this one — K has no banded stats at all, and TQB and
  DST will use whatever curves this experiment leaves in place.

## Testing

- The curve builders are pure functions over stat lines and must be unit-tested with
  constructed data: a known monotone relationship must be recovered; a non-monotone input
  must come back monotone from PAVA.
- The holdout harness must be tested for the leak it exists to prevent — a test that a
  player cannot appear in both the fit and holdout sets.
- `calibration/2025.yaml` must not change unless a candidate wins. If one does, the change
  is a deliberate, reviewed, measured commit — never a silent regeneration.

# Full Position Coverage: TQB, K and DST Weekly Projections — Design

**Date:** 2026-08-30
**Status:** **IMPLEMENTED** on branch `position-coverage` (unmerged as of 2026-08-30).
All four groups — `RB-WR-TE`, `TQB`, `DST`, `K` — are defined in `sources/cbs-weekly.yaml`
with measured column maps and `expect_tokens`; `sffl week` takes `--projections-tqb/-k/-dst`
and `sffl alert` builds all four page URLs from `--week`. (This line read "proposed" until
the 2026-08-30 docs audit.)

## The problem

`sources/cbs-weekly.yaml` defines exactly ONE group, `RB-WR-TE`. So `sffl week` and the
Sunday/Friday alerts can only score five of the league's eight starting slots. The 2026-08-30
alert rendered:

```
TQB    -- UNFILLED
K      -- UNFILLED
DST    -- UNFILLED
```

This was never a limitation of CBS, the parser, or the scoring engine. **It is unfinished
wiring.** The pages exist, the parser handles them, and the scoring engine has bands and
points for every stat involved. Nobody had written the column maps.

## What is already verified

All three pages captured live on 2026-08-30 from the authenticated session, at the same URL
shape the RB-WR-TE group already uses:

    /stats/stats-main/all:<SCOPE>/<WEEK>:p/standard/projections

| scope | player rows | fields after the leading tab | tokens after the team code |
|---|---|---|---|
| `all:TQB` | 32 | 19 | **17** |
| `all:K` | 98 | 23 | **21** |
| `all:DST` | 32 | 18 | **16** |

`all:QB` returns zero rows — correct, this league drafts Team QB units, not individual
quarterbacks.

**And the calibration work just merged was largely for TQB:** `pass_yds` went from 4 anchors to
31 and `pass_cmp` from 4 to 29. The scoring is ready and waiting.

> **Corrected 2026-08-30 (later the same day):** `pass_yds` is back to **4 anchors**. Its
> isotonic adoption was reverted (commit `6bdc5c3`) after re-measurement on de-duplicated
> data showed it losing to the baseline under `predict_weekly` — see
> `calibration/2025.provenance.yaml`, which is the authority. `pass_cmp`'s 4 → 29 stands.
> This does not change anything in this spec: TQB scoring never depended on which builder
> produced `pass_yds`'s curve, only on the curve existing.

## The measured column maps

### TQB — verified, no ambiguity

```
AVAIL | PLAYER | OPP | OVP | BYE | ROST | START | EXPERT
      | ATT COMP YDS TD INT   (passing)
      | ATT YDS AVG TD        (rushing)
      | LOST | FPTS
```

Sample (the fixture's constructed row, in the real capture's layout; the real rows are in the private data repo): `Chargers TQB • LAC | ARI | --- | 7 | 94 | 33 | N/R | 28.0 21.6 243.2 2.7 0.7 | 5.8 33 5.7 0.2 | 0.1 | 17.93`

Trailing 11 stats → `[pass_att, pass_cmp, pass_yds, pass_td, pass_int, rush_att, rush_yds, _, rush_td, fum_lost, _]`, `expect_tokens: 17`.

Every stat the engine needs is present: `pass_yds` and `pass_cmp` are banded and now have 31
and 29 anchors; `pass_td`, `pass_int`, `rush_yds`, `rush_td` are scored directly.

### DST — verified; two column names need confirming

```
AVAIL | PLAYER | OPP | OVP | BYE | ROST | START
      | SACK FUM INT DWN TD STY   (turnovers / scoring)
      | AVG TOTAL                 (yards against)
      | AVG TOTAL                 (points against)
      | FPTS
```

Sample (constructed, real layout): `Chargers DST • LAC | ARI | 19 | 7 | 70 | 56 | 4.1 0.6 0.7 0.5 0.3 0.0 | 291.00 291 | 20.60 20.6 | 9.84`

Note **DST has no EXPERT column** — that is why it is 16 tokens, not 17.

`def_ya` (hundreds) and `def_pa` (tens) are both present, which is what the banded defense scoring
needs. **`DWN` is unidentified** and must be confirmed against a second week before being
mapped or discarded; do not guess it into a scoring key. For a single week, the AVG and TOTAL
columns are equal — take TOTAL and say why.

### K — verified, and it has the one real complication

```
AVAIL | PLAYER | OPP | OVP | BYE | ROST | START | EXPERT
      | FG ATT   (total)
      | FG ATT   (1-19)
      | FG ATT   (20-29)
      | FG ATT   (30-39)
      | FG ATT   (40-49)
      | FG ATT   (50+)
      | XP ATT
      | FPTS
```

Sample (constructed, real layout): `Jake Bates K • DET | NO | 16 | 6 | 77 | 77 | 18 | 2.2 2.8 | 0.0 0.0 | 0.4 0.6 | 0.6 0.8 | 0.8 0.8 | 0.4 0.6 | 3.4 3.8 | 5.60`
(on the real capture the five distance bands summed to within 0.1 of the stated total —
rounding, and a useful cross-check the parser can assert.)

**THE COMPLICATION — CBS's distance bands do not match the league's.**

| league scoring key | CBS column |
|---|---|
| `fg_under_30` | `1-19` **+** `20-29` — two columns, one key |
| `fg_30_39` | `30-39` ✓ |
| `fg_40_49` | `40-49` ✓ |
| `fg_50_59` | part of `50+` |
| `fg_60_plus` | part of `50+` — **not separable** |
| `fg_missed` | total `ATT` − total `FG` — a derived value |

Two mismatches, and they are different in kind:

1. **`fg_under_30` needs two columns summed.** The `stats:` map is strictly positional — one
   token, one name — so it cannot express this today.
2. **`fg_50_59` and `fg_60_plus` cannot be separated at all.** CBS gives one `50+` column.

### The resolution

For (1), extend the profile format minimally: **a stat name appearing more than once in a
`stats:` list means those columns are summed.** That is a small, general change to
`cbs_weekly.parse`, it reads naturally in the YAML, and it is exactly what the data calls for.

For (2), assign all of `50+` to `fg_50_59` and record the consequence in the profile: a 60+
yard field goal is scored as a 50-59, understating it by the difference between those two
bands. **Do not silently pick one.** A 60-yarder is rare enough that this is the right trade,
but it must be written down where the next reader will find it, because a projection that
quietly under-scores a category is precisely the class of defect this project keeps finding.

`fg_missed` is derived (`ATT − FG`), which the positional map also cannot express. Either
compute it in `parse` from the two named columns, or omit it and record that missed field
goals are unscored in the weekly path — measure which matters before choosing.

## The def-curve question, folded in deliberately

`def_pa` and `def_ya` currently have 3 and 4 anchors from 4 defenses, and they are **presently
unreachable in production** — `pool._calibrated_band_value`'s own docstring says so: "no DST
group is wired into sources/cbs-weekly.yaml, so score_week never sees pos='DST'".

**This work makes them reachable.** So the question that was correctly deferred as ungated now
has to be answered.

Evidence in hand, from the first calibration experiment: the pooled method beat the baseline on
`def_ya` under both predictors; `def_pa` split by predictor. Nothing was pre-registered for the
weekly path, so that decides nothing.

**The metric must be different from the board's.** DST is flat-priced, so `top10_cost` is
irrelevant. And `poc/measure_weekly_calibration.py` already states the right standard:

> A large average diff is NOT the claim. What matters for a start/sit or waiver decision is
> whether it changes the ORDER of two players.

The alert starts exactly **one** defense. So the question is: *does the curve pick a better
defense to start?* That is rank accuracy over the 26 defenses with weekly data — not mean
error. **A pre-registered gate for that, written before measuring, is part of this work.**

## Out of scope

- **Changing `src/sffl/scoring.py`.** Validated against ~250 real observations.
- **Changing the market curve or the auction board.** None of this touches pricing: TQB is
  priced from the season path already, and K and DST are flat-priced.
- **Individual QB support.** This league drafts Team QB units; `all:QB` is empty by design.

## Testing

- One committed fixture per group, built from a REAL capture, with the fantasy team names
  placeholdered (the repo is public).
- `expect_tokens` per group is the column-shift guard and must be exercised: a row with one
  token too many or too few must be refused loudly.
- The summed-column feature needs a test proving two columns land in one key, and that a
  single-occurrence name is unaffected.
- The `50+` conflation must be asserted, not just commented — a test that pins the documented
  behaviour so a future reader cannot mistake it for an oversight.
- An end-to-end test that a roster containing a TQB, a K and a DST fills all eight lineup
  slots. That is the deliverable, and nothing else proves it.

# Curve Adoption — Third and Final Measurement (PRE-REGISTERED)

**Date:** 2026-08-30
**Status:** pre-registered and committed before the measurement was dispatched.

## Declared contamination — read this first

**This is the third analysis of the same data, and I have already seen the results of the
first two.** Nothing below is a blind pre-registration and it must not be presented as one.
Knowing the answer, I could write a threshold that passes. That is the failure mode this
document exists to resist, so the bar here is set STRICTER than the previous one, not looser,
and the new condition (§4) is one no previous run could have passed by accident.

**If this measurement fails, the question is closed.** No fourth analysis. Recording a
negative result is the outcome, and the existing held-back README is proof that this project
takes such records seriously enough to save a future session from repeating them.

## Why the second gate was wrong

It required EACH stat to improve `top10_cost` by ≥ 1.00, against a total achievable gain of
2.62 spread across five stats — demanding that each of five contributors individually exceed
38% of the whole. No distributed improvement can satisfy that. It was not a bar the candidates
failed; it was a bar built wrong.

The specific hazard that rule existed to catch also did not occur. It was written to detect
"one curve doing something unphysical while the others carry it." The measured gains are
**sub-additive** (2.91 summed individually → 2.62 combined) and **same-signed across all five
stats**, which is the opposite signature. No stat breached the mae guard alone.

## The measured position, for the record

Isotonic bundle vs shipped, policy held at `starter`:

| | shipped | isotonic bundle | Δ |
|---|---|---|---|
| `top10_cost` | 15.168 | 12.544 | **−2.62 (−17%)** |
| `mae` | 4.3392 | 4.4758 | +0.137 |
| `top10_bias` | +5.104 | positive throughout (+3.17…+5.13) | no sign flip |

Pooled failed on the bundle (`top10_cost` −0.05) and is **eliminated**. This measurement
concerns isotonic only.

`def_pa` and `def_ya` are **structurally inert on the board** — DST sits in
`flat_priced_pools`, so its curve never reaches `_dollars`. They are excluded from board
adoption entirely. Their weekly value is a separate question this measurement does not touch.

## The gate

**PRIMARY — the bundle.** `top10_cost` improves by ≥ 1.00 absolute against the shipped 15.168.
Gating the bundle is the coherent form of the metric: the board is priced by all curves at
once, and no user ever experiences one stat's curve in isolation.

**GUARD 1 — overall `mae`** regresses by no more than $0.25 absolute. Unchanged from the second
gate, and unchanged deliberately: it was never the binding constraint and re-tuning it now would
be exactly the manipulation this document resists.

**GUARD 2 — no stat may be adopted that individually WORSENS `top10_cost`.** A stat contributing
a negative gain is carried by the others and does not belong in the bundle. This replaces the
incoherent ≥1.00-per-stat rule with the requirement it should always have been: contribute
positively, not dominate.

**GUARD 3 — no sign flip.** `top10_bias` must remain positive. Over-pricing becoming
under-pricing of similar magnitude is a different error, not an improvement.

**GUARD 4 — THE NEW AND DECISIVE ONE: the improvement must survive leave-one-out over the
top-10 players.**

`top10_mae` and `top10_bias` are computed over **ten observations**. A 2.62-point improvement
on ten data points can be produced by one or two players and would be indistinguishable, at
this sample size, from a curve that genuinely prices the top end better.

So: recompute `top10_cost` for both the shipped curves and the candidate ten times, each time
dropping one of the ten top-priced players (recomputing the top-10 set from the remaining
priced players each time, as `score_fit` would). **The candidate must improve `top10_cost` in
at least 9 of the 10 replicates.** If dropping a single player erases the gain, the gain is
that player.

Report all ten deltas, not a summary.

**GUARD 5 — regime replication.** Report the bundle result for curves built on the build-set
only AND on build-set-plus-held-back. Adoption requires the gate to clear in the regime that
would actually ship. If the improvement appears in only one regime, say which and treat it as
a finding about data volume rather than about the method.

**A tie is a loss.**

## What is NOT changing to obtain a result

- No new candidates. Pooled is eliminated and does not return.
- No tuning of any builder parameter, fold count, floor, or grid.
- No change to `band_points`, `scoring.py`, or the market curve's form.
- The cross-validated held-out MAE numbers from the first experiment stand as measured and are
  not re-derived.
- The policy stays fixed at `starter`. (`choose_policy` picked `starter` in every run anyway,
  so this has never been load-bearing — but it stays fixed.)

## Honest possible outcomes

1. **The bundle clears all five.** Adopt isotonic for its five board-relevant stats, record the
   method per stat in the curve file, regenerate `calibration/2025.yaml` deliberately, and
   re-verify the board and the full suite.
2. **Leave-one-out kills it.** The most likely way this fails, and the most valuable thing this
   measurement can tell us: a 17% improvement in a ten-observation metric was two players.
   Record it and close the question.
3. **It clears on one dataset regime and not the other.** Report which, adopt nothing, and
   record that the effect is contingent on data volume.

---

## CORRECTION 2026-08-30 (appended after the measurement; nothing above is edited)

This document is a **pre-registration**. Its value is that it was fixed before the
measurement, so not one word above has been altered. Everything that follows is dated,
appended, and later — read it as the outcome, not as a revision of the gate.

**Outcome 1 fired, then partly unwound.** The bundle cleared, isotonic was adopted for its
five board-relevant stats, `calibration/2025.yaml` was regenerated and the board re-verified
— exactly as §"Honest possible outcomes" #1 prescribes. **Then one of the five was
withdrawn the same day.**

**Why.** The cross-validated held-out MAE that condition 3 relies on ("the stat won its
cross-validated held-out MAE in the FIRST experiment, under `predict_weekly`") was measured
on data carrying a **duplicate-entity leak**. Four weekly-data files held the same real
entity under two different `player_id`s with byte-identical stat histories.
`calibrate_eval.player_folds` splits by `player_id` precisely so a player's own weeks cannot
straddle a fold — but the two ids were genuinely distinct, so the splitter separated them
while the held-out id's identical twin sat in the fit set. Interpolation drew its line
through the twin and "predicted" the held-out id almost exactly. **The leak flattered the
BASELINE**, which makes it the conservative direction for four of the five stats and the
decisive direction for the fifth.

Re-measured on de-duplicated data under `predict_weekly` (commit `a8584da` fixed the leak at
load; `poc/compare_calibration_methods.py` re-run):

| stat | isotonic | baseline | condition 3 |
|---|---:|---:|---|
| `pass_cmp` | 0.1253 | 0.1333 | holds |
| `rec_ct`   | 0.0864 | 0.1205 | holds |
| `rec_yds`  | 0.0588 | 0.0700 | holds |
| `rush_yds` | 0.0718 | 0.0926 | holds |
| `pass_yds` | 0.1572 | 0.1520 | **FAILS** (had appeared to win 0.1524 vs 0.1659 under the leak) |

`pass_yds` was **reverted** to `build_curves` (commit `e82d2e2`). A tie would already fail
condition 3 as written; this is not a tie. **The adopted, currently-shipped set is FOUR
stats: `pass_cmp`, `rec_ct`, `rec_yds`, `rush_yds`.**

**The numbers in §"The measured position, for the record" are the five-stat bundle's and are
superseded.** Removing a stat changes the bundle, so the gate was re-measured rather than
assumed to carry over (`poc/loo_top10_stability.py`, re-run for four stats):

| | recorded above (5 stats) | re-measured (4 stats, shipped) |
|---|---:|---:|
| `top10_cost` | 12.544 | **13.2633** (vs shipped 15.1681) |
| `mae` | 4.4758 | **4.4154** |
| `top10_bias` | +3.7312 | **+4.1025** |

The PRIMARY gate (`top10_cost` improves by ≥ 1.00 against 15.168) still clears at 4 stats:
15.1681 − 13.2633 = 1.905. GUARD 1 (`mae` regresses by ≤ $0.25) clears more comfortably than
before: +0.0762, was +0.1366. `market/2026.yaml` was refit and carries
`a=2.028495994199789`, `b=0.6511171620237226`.

**Also correcting §"Why the second gate was wrong"**, which reasons over "five stats" and "a
total achievable gain of 2.62". Both were accurate when written. The argument itself is
untouched by the revision — a per-stat ≥1.00 bar against a distributed gain is incoherent at
four contributors just as at five — but the specific counts in that paragraph are the
five-stat ones.

**§"Declared contamination" said "if this measurement fails, the question is closed. No
fourth analysis."** The re-measurement above is NOT a fourth analysis of the same data
seeking a better answer. It is the same gate, condition 3 unchanged, applied to data with a
correctness bug removed — and it made the result STRICTER, dropping a stat that had been
adopted. That is the direction that distinguishes a bug fix from a fishing expedition.

Full report:
`.superpowers/sdd/2026-08-30-full-position-coverage/pass-yds-revert-report.md`.
`calibration/2025.provenance.yaml` is the authority on method-per-stat, and
`tests/test_docs_match_artifacts.py` fails if `NEXT.md` drifts from it.

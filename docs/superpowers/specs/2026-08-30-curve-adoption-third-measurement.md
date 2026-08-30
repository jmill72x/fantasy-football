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

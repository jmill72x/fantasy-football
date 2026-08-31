# Defense Curves for the Weekly Path — PRE-REGISTERED GATE

**Date:** 2026-08-30
**Status:** pre-registered and committed BEFORE any measurement was run.

## Why this exists now

`def_pa` and `def_ya` have **3 and 4 anchors, built from 4 defenses**. Until today they were
**unreachable in production** — `pool._calibrated_band_value`'s own docstring says so: "no DST
group is wired into sources/cbs-weekly.yaml, so score_week never sees pos='DST'". The position
coverage work just wired one in. They are now live, and the question that was correctly deferred
as ungated has to be answered.

Held-back data makes 26 defenses available against the 4 currently used.

## The metric is RANK, not error — and that is not a convenience

`poc/measure_weekly_calibration.py` already states the standard in its own closing note:

> A large average diff is NOT the claim. What matters for a start/sit or waiver decision is
> whether it changes the ORDER of two players.

The alert starts **exactly one** defense. A curve that predicts every defense's points 2 points
low but ranks them perfectly costs nothing; a curve with lower mean error that inverts the top
two costs a start/sit decision every week. Mean error is the wrong instrument here, and the
board metric (`top10_cost`) is irrelevant because DST is flat-priced.

**Measure the full weekly DST score, not the banded component alone.** `def_pa` and `def_ya` are
two inputs among several — sacks, interceptions, fumble recoveries, touchdowns and safeties are
unbanded points the curve never touches. Ranking on the banded part alone would measure
something the alert never does.

## The gate

**Design.** Cross-validate by defense (never by row — a defense's own weeks in its own fit set
would let interpolation predict it almost exactly). Collect one out-of-fold prediction per
defense with ≥4 weeks, then compare against its realized `mean(band(weekly))`-based full weekly
score across the whole set at once. That yields one interpretable number per candidate rather
than a noisy per-fold average.

**PRIMARY — Spearman rank correlation** between predicted and realized full weekly DST score,
across all defenses with ≥4 weeks.

**SECONDARY — top-1 hit rate**: does the predicted-best defense actually have the highest
realized score? Reported, never gating on its own — with n≈26 a single flip moves it by 4
points, which is noise.

**Candidates:** the shipped interpolation from 4 defenses; `build_curves_isotonic` from all 26;
`build_curves_pooled` from all 26. `def_pa` and `def_ya` may be adopted independently — they are
separate curves and nothing requires one method for both.

## The honest problem with this measurement, stated up front

**n ≈ 26. Spearman's standard error at that sample size is roughly 1/√25 ≈ 0.20.** A difference
of 0.05 is indistinguishable from noise, and this project has already been burned once by
adopting a difference that measurement could not support.

So: **a candidate is adopted only if it beats the baseline's Spearman by ≥ 0.15**, and does not
reduce the top-1 hit rate. That threshold is set from the sample size, not from the results —
it is roughly one standard error, which is the smallest difference this data can honestly
resolve.

**If no candidate clears 0.15, the finding is "underpowered — keep the baseline", not "the
candidates failed."** Those are different statements and only one of them is true. Say the
underpowered one.

**A tie is a loss.** The baseline ships and is understood.

## Declared in advance: what would make me discard a result

- **A candidate that wins Spearman while losing top-1.** With one defense started per week, a
  curve that orders the middle better and the top worse is not an improvement.
- **A win that depends on which fold count is used.** Report k=5 and leave-one-out. If they
  disagree, the effect is not real at this sample size.
- **A win driven by one defense.** Drop each defense in turn and recompute; if the margin
  collapses below 0.15 on any single drop, it is that defense, not the curve.

## Out of scope

- **The board.** DST sits in `flat_priced_pools`; these curves provably cannot reach `_dollars`.
  Verified earlier: swapping them was measurably inert (Δ 0.0000).
- **`src/sffl/scoring.py`.** Untouched.
- **The five stats adopted on 2026-08-30.** Settled; not reopened.

## Honest possible outcomes

1. **A candidate clears 0.15 on both fold counts and survives the drop-one check.** Adopt for
   that stat, record the method in `calibration/2025.provenance.yaml`, regenerate deliberately,
   and re-verify the alert.
2. **Nothing clears it.** Record that the measurement is underpowered at n=26 and that the
   4-defense curves stand for want of evidence, not for merit. Note what would change the
   answer: another season of weekly data.
3. **A candidate clears on one fold count and not the other.** Report both, adopt nothing, and
   record the instability.

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

---

## CORRECTION, 2026-08-30 — the sample is 22, not 26

The repo owner asked why the count was 26 rather than 32. Checking rather than answering from
memory: **it is 22.** The 4 defenses in the build set are a SUBSET of the 22 held-back ones, not
additional to them — the overlap is all four, so the union is 22.

```
build set : 4 distinct (17 weeks each)
held back : 22 distinct
overlap   : 4  (all of them)
union     : 22
```

Every statement of "26" above this line is wrong, including the one used to derive the
threshold. Left in place rather than edited, so the correction is visible.

**Consequence for the gate.** Spearman's standard error at n=22 is 1/sqrt(21) ≈ **0.218**, not
the ≈0.20 quoted. The 0.15 threshold therefore sits BELOW one standard error, making it a
weaker bar relative to noise than intended — so a bare clear at 0.15 is LESS meaningful, not
more.

**The threshold is NOT being raised.** Moving it after learning the sample size is the same
error as moving it after seeing results, and this project has been burned by that once already.
It stands at 0.15. The real protection was never the arithmetic: it is conditions 3 and 4 —
the result must hold under both fold counts AND survive dropping each defense in turn — and
those do not depend on the standard error at all. A candidate that clears 0.15 but fails either
is discarded, exactly as written.

**Why 22 and not 32, and what would fix it.** No principled reason. The August scrape captured
22 of the 32 defenses — its own README records 84 players across WR/TE/DST/TQB, so it was a
bounded pull rather than a filtered one. The missing 10 are not unavailable; nobody fetched
them. Scraping them would take n from 22 to 32, cutting the standard error to about 0.18 —
still not enough to resolve a small difference, but a real improvement, and the single cheapest
thing that would make this question answerable.

---

## CORRECTION, 2026-08-30 (final-branch review) — the sample is 21, not 22

The duplicate-entity data-integrity fix (commit `a8584da`, `sffl.weekly.load_weekly` now
collapses byte-identical-history duplicate ids at load) found that the held-back DST file
itself carries the Vikings under two different CBS ids (`1916`/`1918`) with byte-identical
weekly stats. **The 22 count above included this duplicate as two defenses; the real
distinct count is 21.** Every statement of "22" above this line (including the one used to
derive the ≈0.218 standard error) is left in place rather than edited, exactly as the "22, not
26" correction above was — so both corrections stay visible in sequence.

**Consequence for the gate.** Spearman's standard error at n=21 is 1/sqrt(20) ≈ **0.224**,
marginally weaker still than the ≈0.218 quoted above — the same direction of consequence
already noted there (the 0.15 threshold sits further below one standard error, so a bare
clear is even less meaningful). The threshold is, again, NOT being raised for the same reason
already given: moving it after learning the sample size is the same error as moving it after
seeing results.

**The gate was run on the corrected n=21** (commit `9b2fcdc`, `poc/measure_dst_ranking.py`,
which loads through `load_weekly` and so gets the de-duplicated count automatically, with no
script change needed): no candidate (`build_curves_isotonic` or `build_curves_pooled`) cleared
the pre-registered ≥0.15 Spearman margin on both k=5 and leave-one-out. Per this document's own
"Honest possible outcomes" #2 and the "underpowered... not... failed" instruction above: **the
correct statement is that this measurement is underpowered at n=21, keeping the baseline for
want of evidence, not that the candidates failed.**

**Also correcting §"Out of scope" above ("The five stats adopted on 2026-08-30. Settled; not
reopened.")** — that line is itself now stale, for an unrelated reason discovered later the
same day: `pass_yds`'s cross-validated win was measured on data with the same duplicate-entity
leak described above, and did not survive re-measurement on de-duplicated data under the
production weekly predictor (0.1572 vs baseline 0.1520 — a loss). It was reverted (commit
`e82d2e2`). **The adopted, currently-shipped set is four stats: `pass_cmp`, `rec_ct`,
`rec_yds`, `rush_yds`.** This does not reopen anything in scope for THIS gate (`def_pa`/
`def_ya` were never part of that adoption either way), but the line asserting "the five stats"
as settled fact is no longer accurate and should not be relied on. See `NEXT.md`'s
isotonic-adoption note for the current numbers.

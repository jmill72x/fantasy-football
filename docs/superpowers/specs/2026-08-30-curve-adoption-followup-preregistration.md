# Curve Adoption Follow-Up — PRE-REGISTRATION

**Date:** 2026-08-30
**Status:** pre-registered. **Committed BEFORE any follow-up measurement was run.**

## Why this document exists

The first experiment's gate said a candidate must "not worsen the price fit" without naming a
metric. Both candidates then improved `top10_cost` by 12.6–15.6% while worsening overall
`mae` by 2.3–3.0%. Reinterpreting an ambiguous gate after seeing which way the numbers fell is
exactly the move that produced this project's phantom +$13.2 bias. So the rule is fixed here,
in writing, before the follow-up runs.

**The result that motivated this follow-up, for the record:**

| curve set | mae | top10_mae | top10_bias | top10_cost |
|---|---|---|---|---|
| shipped | 4.3392 | 10.0638 | +5.1042 | 15.168 |
| isotonic | 4.4691 | 8.9531 | +3.8560 | 12.809 |
| pooled | 4.4405 | 9.4305 | +3.8304 | 13.261 |

## The argument for `top10_cost` as primary — made in advance

It is not a metric invented for this follow-up. `fit.top10_cost` already decides this
project's replacement policy, and its docstring states the reasoning:

> Noise averages out across thirteen roster spots; a policy that under-prices every expensive
> player by $10 loses every one of them.

Overall `mae` is dominated by the cheap end — **63 of 130 fitted observations sit in the $1–2
band**. Being $0.13 further off on a dollar filler cannot cost a roster spot. Being $2.36
closer on the sixteen players that consume most of a $260 budget can decide the auction.

That is the argument. It stands or falls on its own, and it is written down before the numbers
are re-run.

## The gate — fixed, quantitative, and in absolute dollars

A candidate is adopted for a stat only if **all four** hold:

1. **PRIMARY — `top10_cost` improves by ≥ 1.00 absolute** (≥ ~6.6% of the shipped 15.168).
   Below a dollar of systematic error on a top-10 pick is noise against bids of $26+.
2. **SECONDARY GUARD — overall `mae` regresses by no more than $0.25 absolute** (~5.8%).
   A quarter-dollar of average error, concentrated in a band where most observations are $1–2
   players, cannot cost a roster spot. A larger regression means the curve is broken somewhere
   that matters and the top-10 gain is not worth it.
3. **The stat must also have won its cross-validated held-out MAE** in the first experiment,
   under the production weekly predictor (`predict_weekly`, which wraps
   `pool._calibrated_band_value`). A stat that only wins on the board and loses on the thing the
   curve actually predicts is a coincidence, not an improvement.
4. **The replacement policy must be HELD FIXED at `starter`** across every candidate and the
   baseline. `choose_policy` consults the observed prices, so a candidate that flips the policy
   would change the board for a reason that has nothing to do with its curve. Holding it fixed
   isolates the curve's effect. Report what `choose_policy` WOULD have picked, but do not let it
   vary.

**A tie is a loss.** The baseline ships today and is understood.

**Per-stat adoption only.** A method is adopted for the stats where it wins, never globally, and
the curve file must record which method produced each stat's curve.

## What is NOT being changed to obtain a result

- No new candidate methods. The two under test are the two already built and reviewed.
- No tuning of `MIN_MEAN_FLOOR`, the grid rule, the fold count, or any builder parameter.
- No change to `band_points`, `src/sffl/scoring.py`, or the market curve's `a`/`b` form.
- The first experiment's cross-validated MAE numbers are **not** re-run or re-derived. They
  stand as measured.

## Declared in advance: what would make me abandon this

- If `top10_cost` improves but the **direction** of `top10_bias` flips (over-pricing becomes
  under-pricing of similar magnitude), that is not an improvement — it is a different error.
  Report the signed bias, not just its absolute value.
- If the improvement comes from a single stat swap that also moves overall `mae` beyond the
  guard, the honest reading is that one curve is doing something unphysical and the others are
  carrying it. Report per-stat swaps individually, not only the combined set.
- If holding the policy fixed at `starter` erases the gain, the gain was the policy, not the
  curve.

## Honest possible outcomes

1. **A candidate clears all four for some stats.** Adopt for those stats, record the method per
   stat, regenerate `calibration/2025.yaml` deliberately, and re-verify the board.
2. **`top10_cost` improves but the mae guard trips.** Do not adopt. Record that the trade is
   real but larger than declared acceptable — and that the threshold was set in advance, not
   after.
3. **The gain disappears under a fixed policy, or per-stat.** Do not adopt. That is the most
   informative outcome of the three, because it would mean the first measurement was reading a
   policy flip or an interaction rather than a curve.

---

## CORRECTION 2026-08-30 (appended after the measurement; nothing above is edited)

This document is a **pre-registration** — committed before the follow-up ran, and left
word-for-word intact. Everything below is dated, appended, and later.

**The gate was applied and four candidates were adopted, not five.** `poc/followup_curve_
adoption.py` implements the four conditions above verbatim. Its condition-3 table was
originally transcribed from a cross-validated comparison run on data carrying a
**duplicate-entity leak**: four weekly files held the same real entity under two different
`player_id`s with byte-identical histories, so `calibrate_eval.player_folds` put a held-out
id in one fold while its identical twin sat in the fit set. Interpolation — **the baseline**
— was the beneficiary.

Re-measured on de-duplicated data under `predict_weekly` (the production weekly predictor
condition 3 names), `pass_yds` **flips from a win to a loss**: 0.1572 isotonic vs 0.1520
baseline, where the leaked run had shown 0.1524 vs 0.1659. It was adopted on the leaked
numbers and then **reverted** (commit `e82d2e2`). `pass_cmp` (0.1253 vs 0.1333), `rec_ct`
(0.0864 vs 0.1205), `rec_yds` (0.0588 vs 0.0700) and `rush_yds` (0.0718 vs 0.0926) all hold
post-dedup. **The adopted set is four stats: `pass_cmp`, `rec_ct`, `rec_yds`, `rush_yds`.**

**The motivating table in §"Why this document exists" is superseded as a description of what
ships.** Those rows (`shipped` 4.3392 / 10.0638 / +5.1042 / 15.168; `isotonic` 4.4691 /
8.9531 / +3.8560 / 12.809; `pooled` 4.4405 / 9.4305 / +3.8304 / 13.261) were measured
pre-dedup across five stats. The committed `market/2026.yaml` today carries
`a=2.028495994199789`, `b=0.6511171620237226`, `mae=4.4154`, `top10_mae=9.1609`,
`top10_bias=4.1025`, fit on 130 observations. The `pooled` row is doubly moot:
`build_curves_pooled` was independently eliminated as a candidate method by the later
third-measurement gate and was never re-measured post-dedup. **Do not cite the `pooled`
numbers as current evidence for anything.**

**Still true and worth keeping:** the argument in §"The argument for `top10_cost` as primary"
stands unchanged, including "63 of 130 fitted observations sit in the $1–2 band" — the
observation count is still 130 in `market/2026.yaml`'s own `evidence` block. And the
document's opening warning — that reinterpreting an ambiguous gate after seeing which way the
numbers fell "is exactly the move that produced this project's phantom +$13.2 bias" — is what
the withdrawal above honours rather than contradicts: condition 3 was applied unchanged to
corrected data, and it removed a stat that had already been adopted.

Full report:
`.superpowers/sdd/2026-08-30-full-position-coverage/pass-yds-revert-report.md`.

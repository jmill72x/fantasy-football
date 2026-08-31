"""Curve-adoption follow-up: apply the PRE-REGISTERED gate, exactly as written.

CORRECTED 2026-08-30 (final-branch review, review round 2): the CONDITION-3 table
transcribed below (`WINNERS_UNDER_PREDICT_WEEKLY`) was sourced from a cross-validated
comparison run BEFORE the duplicate-entity data-integrity fix (commit `a8584da`). A
held-out player's byte-identical duplicate id sat in the fit set for some folds,
letting interpolation (the baseline) "predict" it almost exactly - flattering the
baseline and making isotonic's margin look bigger than it honestly was. Re-run clean
on de-duplicated data (`predict_weekly`, the production weekly predictor - see
NEXT.md's dedup note and `.superpowers/sdd/2026-08-30-full-position-coverage/
dedup-report.md`), `pass_yds` FLIPS from a win (0.1524 vs 0.1659, leaked) to a LOSS
(0.1572 vs 0.1520, deduped) and does NOT belong in the isotonic winner set. It was
adopted anyway on the leaked numbers, then reverted (commit `e82d2e2`) once this was
caught. The table and `WINNERS_UNDER_PREDICT_WEEKLY` below are updated to the deduped
numbers so that re-running this script today does not re-recommend `pass_yds`.
The isotonic winner set is now FOUR stats: `pass_cmp`, `rec_ct`, `rec_yds`, `rush_yds`.
The `pooled` column/winner list below was NOT re-measured post-dedup (out of scope for
the dedup fix) - it does not matter operationally, since `build_curves_pooled` was
independently eliminated as a candidate method entirely by the later third-measurement
gate (`poc/loo_top10_stability.py`; see NEXT.md): "failed the bundle gate outright...
does not return as a candidate." Do not act on the `pooled` numbers below as current
evidence for anything.

Gate: docs/superpowers/specs/2026-08-30-curve-adoption-followup-preregistration.md
(committed as c6dc0b7, BEFORE this script was run). This script does not
choose, tune, or reinterpret anything the gate does not already say. It
measures, prints every table the gate requires, and reports the verdict.

FOUR CONDITIONS, per stat, ALL required for a candidate to be adopted:
  1. top10_cost improves by >= 1.00 absolute vs the shipped 15.168.
  2. Overall mae regresses by no more than $0.25 absolute vs the shipped 4.3392.
  3. The stat won its cross-validated held-out MAE in the FIRST experiment,
     under predict_weekly (the production weekly predictor). The `isotonic`
     numbers below are the 2026-08-30 de-duplicated re-measurement (see the
     CORRECTED note above and `.superpowers/sdd/2026-08-30-full-position-
     coverage/dedup-report.md`) - NOT the original leaked transcription from
     .superpowers/sdd/2026-08-30-regularised-calibration-curves/task-4-report.md,
     which is preserved only for the (moot) `pooled` column (see
     WINNERS_UNDER_PREDICT_WEEKLY below, with the source table transcribed
     in a comment).
  4. The replacement policy is HELD FIXED at "starter" for every candidate
     and the baseline. This script computes fit.score_fit(lg, pool, prices,
     "starter") directly and never calls fit.choose_policy for the reported
     numbers - choose_policy is invoked ONLY as a side, diagnostic
     computation to report what it WOULD have picked, and that result plays
     no part in the gate.

BASELINE FOR NON-SWAPPED STATS: the LITERAL shipped curve,
`calibration/2025.yaml` (read-only - never written to). Verified byte-for-
-content equal to `build_curves(lg, build-set-only lines)`: 811 player-weeks,
48 players (corrected 2026-08-30 to 777 player-weeks / 46 players - RB.csv
carried a duplicate-entity pair; see NEXT.md - the curve itself, and this
script's conclusions, are unaffected), the same data `market/2026.yaml` was fit against. This is what
"the shipped build_curves for every other stat" means here: not a curve
rebuilt on more data by the same builder, but the actual thing that ships
today, so that swapping zero stats reproduces the shipped mae/top10 numbers
exactly (see the sanity check at the top of the run) and each per-stat swap
is isolated against a truly untouched baseline.

CANDIDATE CURVES FOR WINNING STATS: built by build_curves_isotonic /
build_curves_pooled on the "combined" dataset (build-set + held-back) - the
regime in which condition 3 (see below) actually measured each stat as a
winner, and the same dataset Step 3 of the Task 4 report used to build its
own full candidate sets. Condition 3's predict_weekly numbers are read off
that same combined-dataset table in the Task 4 report, so the evidence used
to select a stat and the data used to build its swapped-in curve are the
same regime throughout. This pairing (shipped-exact baseline + combined-
-data-built candidate) is a judgment call this script states plainly, per
the brief's instruction to "say exactly how you did it" - the pre-
-registration text does not pin either choice explicitly.

PER-STAT ADOPTION ONLY: a candidate method is used for a stat ONLY where it
won condition 3; every other stat uses the shipped build_curves. Two
candidate sets are built for each method: every winning stat swapped ALONE
(one run per stat), and all of that method's winning stats swapped together
(the combined set) - both are measured and reported, per the spec's
instruction not to report only the combined set.

NOTHING IS TUNED: no floor, grid, fold count, or builder parameter is
touched. No new candidate methods. Curves are written to scratch paths only
- never to calibration/2025.yaml. market/2026.yaml is never touched (no
fit-market --out call writes there).

Run: PYTHONPATH=src ./.venv/bin/python poc/followup_curve_adoption.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sffl.calibrate import (                                      # noqa: E402
    build_curves_isotonic,
    build_curves_pooled,
    load_curves,
    save_curves,
)
from sffl.fit import choose_policy, load_prices, score_fit, top10_cost  # noqa: E402
from sffl.league import load_league                               # noqa: E402
from sffl.pool import build_pool, score_season_calibrated          # noqa: E402
from sffl.weekly import load_weekly                                # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
LEAGUE_PROFILE_PATH = os.path.join(ROOT, "leagues", "sffl", "2026.yaml")
BUILD_SET_DIR = os.path.join(ROOT, "data", "weekly", "2025")
HELD_BACK_DIR = os.path.join(BUILD_SET_DIR, "_held_back")
BUILD_SET_POSITIONS = ["DST", "K", "RB", "TQB", "WR"]
HELD_BACK_POSITIONS = ["DST", "TQB", "WR", "TE"]

SOURCE_PROFILE = os.path.join(ROOT, "sources", "draftsharks.yaml")
EXTRACT_FILE = os.path.join(
    ROOT, "data", "extracts", "Draft Sharks", "2026", "rankings-2026-08-23.csv")
PRICES_FILE = os.path.join(ROOT, "data", "league", "auction-rosters-2026.csv")
TQB_STARTERS_FILE = os.path.join(ROOT, "identity", "tqb-2026-starters.yaml")
YEAR = 2026

SCRATCH_DIR = "/private/tmp/claude-501/-Users-jeff-Projects-fantasy-football/e29be1c8-4a81-4926-9ec2-a7593da02577/scratchpad"

SHIPPED_MAE = 4.3392
SHIPPED_TOP10_MAE = 10.0638
SHIPPED_TOP10_BIAS = 5.1042
SHIPPED_TOP10_COST = round(SHIPPED_TOP10_MAE + abs(SHIPPED_TOP10_BIAS), 4)  # 15.168

TOP10_COST_GATE = 1.00   # must IMPROVE by at least this much (absolute $)
MAE_GUARD = 0.25         # must not REGRESS by more than this much (absolute $)

# ---------------------------------------------------------------------------
# CONDITION 3 - the `isotonic` columns/rows below are the DE-DUPLICATED
# re-measurement (`predict_weekly`, production weekly predictor; see
# `.superpowers/sdd/2026-08-30-full-position-coverage/dedup-report.md` and
# NEXT.md's dedup note) - corrected 2026-08-30, see the module docstring's
# CORRECTED note above for why. The original transcription (from the Task 4
# report at .superpowers/sdd/2026-08-30-regularised-calibration-curves/
# task-4-report.md, lines 96-104) was measured on data with a leaked
# duplicate-entity player_id and is preserved only in the `(leaked, NOT
# re-verified)` rows/columns - do not treat those as current evidence.
#
# A stat is a "winner" for a method here iff that method's MAE beat the
# baseline's MAE (a tie would be a loss; none of the rows below tie).
#
# stat        baseline   isotonic   winsCond3?              source
# pass_cmp    0.1333     0.1253     yes (0.1253<0.1333)      deduped
# pass_yds    0.1520     0.1572     NO (0.1572>0.1520, LOSES) deduped - FLIPPED from the
#                                                              leaked table's apparent win
# rec_ct      0.1205     0.0864     yes (0.0864<0.1205)      deduped
# rec_yds     0.0700     0.0588     yes (0.0588<0.0700)      deduped
# rush_yds    0.0926     0.0718     yes (0.0718<0.0926)      deduped
#
# `pooled` column (leaked, NOT re-verified post-dedup - moot regardless, see
# the module docstring: build_curves_pooled was independently eliminated as
# a candidate method entirely by the later third-measurement gate):
# stat        baseline   pooled     winsCond3?
# def_pa      0.1740     0.1701     yes (0.1701<0.1740, leaked, not re-verified)
# def_ya      0.1408     0.1232     yes (0.1232<0.1408, leaked, not re-verified)
# pass_cmp    0.1199     0.1235     no (worse, leaked, not re-verified)
# pass_yds    0.1659     0.1467     yes (leaked table only - pass_yds lost condition 3
#                                    under isotonic post-dedup; pooled itself was never
#                                    re-run post-dedup and is moot regardless)
# rec_ct      0.1155     0.0845     yes (0.0845<0.1155, caveat, leaked, not re-verified)
# rec_yds     0.0622     0.0933     no (worse, leaked, not re-verified)
# rush_yds    0.0908     0.0771     yes (0.0771<0.0908, leaked, not re-verified)
# ---------------------------------------------------------------------------
WINNERS_UNDER_PREDICT_WEEKLY = {
    "isotonic": ["pass_cmp", "rec_ct", "rec_yds", "rush_yds"],
    "pooled": ["def_pa", "def_ya", "pass_yds", "rec_ct", "rush_yds"],
}


def load_lines(data_dir, positions):
    lines = []
    for pos in positions:
        path = os.path.join(data_dir, "{0}.csv".format(pos))
        lines.extend(load_weekly(path))
    return lines


def load_held_back_lines():
    lines = []
    for pos in HELD_BACK_POSITIONS:
        path = os.path.join(HELD_BACK_DIR, "{0}.full.csv".format(pos))
        lines.extend(load_weekly(path))
    return lines


def make_candidate_curves(baseline_curves, full_method_curves, stats_to_swap):
    """Baseline curves for every stat, except `stats_to_swap` from the method."""
    out = dict(baseline_curves)
    for stat in stats_to_swap:
        out[stat] = full_method_curves[stat]
    return out


def evaluate(lg, pool, prices, curves, label):
    """Score `curves` against real prices with the policy HELD FIXED at
    'starter' (condition 4). Also computes 'draftable' as a side, diagnostic
    figure ONLY to report what choose_policy would have picked - it plays no
    part in the gate numbers below, which come exclusively from the
    'starter' report.
    """
    for p in pool:
        p.stats["_season_points"] = score_season_calibrated(lg, p, curves)
    pool.sort(key=lambda p: -p.stats["_season_points"])

    starter_report = score_fit(lg, pool, prices, "starter")

    # Diagnostic only, per condition 4: report what choose_policy WOULD have
    # picked, without letting it vary the gate's own numbers. choose_policy
    # itself mutates the pool's _vorp/_dollars as a side effect (see its
    # docstring) - harmless here since starter_report was already computed
    # and captured above, and nothing below re-reads pool state.
    would_pick, reports = choose_policy(lg, pool, prices)

    return {
        "label": label,
        "mae": starter_report["mae"],
        "top10_mae": starter_report["top10_mae"],
        "top10_bias": starter_report["top10_bias"],
        "top10_cost": top10_cost(starter_report),
        "would_pick_policy": would_pick,
    }


def verdict_for_stat(result):
    """Apply all four conditions to one (method, stat) result. Condition 3
    is baked into which (method, stat) pairs are ever evaluated at all (see
    WINNERS_UNDER_PREDICT_WEEKLY), so it always reads True here - the table
    still names it explicitly so the report is self-contained.
    """
    top10_cost_delta = SHIPPED_TOP10_COST - result["top10_cost"]  # positive = improvement
    mae_delta = result["mae"] - SHIPPED_MAE  # positive = regression

    c1 = top10_cost_delta >= TOP10_COST_GATE
    c2 = mae_delta <= MAE_GUARD
    c3 = True  # by construction - only condition-3 winners are ever evaluated
    c4 = True  # policy held fixed at starter throughout, by construction

    passed = c1 and c2 and c3 and c4
    return {
        "top10_cost_delta": top10_cost_delta,
        "mae_delta": mae_delta,
        "c1": c1, "c2": c2, "c3": c3, "c4": c4,
        "passed": passed,
    }


def fmt_row(cols, widths):
    return " | ".join(str(c).ljust(w) for c, w in zip(cols, widths))


def main():
    lg = load_league(LEAGUE_PROFILE_PATH)

    build_set_lines = load_lines(BUILD_SET_DIR, BUILD_SET_POSITIONS)
    held_back_lines = load_held_back_lines()
    combined_lines = build_set_lines + held_back_lines

    print("Combined dataset (for candidate curves): {0} player-weeks, {1} distinct "
          "players".format(len(combined_lines), len({ln.player_id for ln in combined_lines})))
    print("Build-set-only dataset (matches the shipped calibration/2025.yaml): "
          "{0} player-weeks, {1} distinct players".format(
              len(build_set_lines), len({ln.player_id for ln in build_set_lines})))

    # THE LITERAL SHIPPED CURVE - read-only, never written to. Used as the
    # fallback for every non-swapped stat. Verified (see module docstring)
    # to equal build_curves(lg, build_set_lines) exactly.
    baseline_curves = load_curves(os.path.join(ROOT, "calibration", "2025.yaml"))
    isotonic_full = build_curves_isotonic(lg, combined_lines)
    pooled_full = build_curves_pooled(lg, combined_lines)

    full_curves_by_method = {"isotonic": isotonic_full, "pooled": pooled_full}

    # Write every curve set touched to scratch, never to calibration/2025.yaml.
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    save_curves(baseline_curves, os.path.join(SCRATCH_DIR, "curves_baseline.yaml"))
    save_curves(isotonic_full, os.path.join(SCRATCH_DIR, "curves_isotonic_full.yaml"))
    save_curves(pooled_full, os.path.join(SCRATCH_DIR, "curves_pooled_full.yaml"))

    pool = build_pool(lg, SOURCE_PROFILE, EXTRACT_FILE, YEAR, None)
    prices = load_prices(PRICES_FILE, tqb_starters_path=TQB_STARTERS_FILE,
                          season=YEAR, require_file_season=True)

    print()
    print("=" * 100)
    print("SANITY CHECK: baseline_curves (the literal calibration/2025.yaml, zero "
          "stats swapped) run through this script's own pipeline, policy held "
          "fixed at 'starter', should reproduce market/2026.yaml's numbers exactly.")
    print("=" * 100)
    baseline_result = evaluate(lg, pool, prices, baseline_curves, "baseline")
    print("baseline: mae={mae:.4f} top10_mae={top10_mae:.4f} top10_bias={top10_bias:+.4f} "
          "top10_cost={top10_cost:.4f} (choose_policy would pick: {would_pick_policy})"
          .format(**baseline_result))
    print("shipped (market/2026.yaml): mae={0:.4f} top10_mae={1:.4f} top10_bias={2:+.4f} "
          "top10_cost={3:.4f}".format(
              SHIPPED_MAE, SHIPPED_TOP10_MAE, SHIPPED_TOP10_BIAS, SHIPPED_TOP10_COST))
    print()

    # -----------------------------------------------------------------
    # TABLE 1: each winning stat swapped ALONE.
    # -----------------------------------------------------------------
    print("=" * 100)
    print("TABLE 1: per-stat swaps, INDIVIDUALLY (one stat swapped from the "
          "shipped baseline at a time)")
    print("=" * 100)
    widths = [10, 9, 11, 9, 11, 12, 9, 11, 9, 4, 4, 4, 4, 6]
    header = ["method", "stat", "top10_cost", "d_t10c", "mae", "top10_bias",
              "mae_d", "would_pick", "c1", "c2", "c3", "c4", "PASS"]
    print(fmt_row(header, widths))

    per_stat_results = {}  # (method, stat) -> result dict
    for method, winning_stats in WINNERS_UNDER_PREDICT_WEEKLY.items():
        full_curves = full_curves_by_method[method]
        for stat in winning_stats:
            candidate = make_candidate_curves(baseline_curves, full_curves, [stat])
            result = evaluate(lg, pool, prices, candidate, "{0}:{1}".format(method, stat))
            v = verdict_for_stat(result)
            per_stat_results[(method, stat)] = (result, v)
            row = [
                method, stat,
                "{0:.4f}".format(result["top10_cost"]),
                "{0:+.4f}".format(v["top10_cost_delta"]),
                "{0:.4f}".format(result["mae"]),
                "{0:+.4f}".format(result["top10_bias"]),
                "{0:+.4f}".format(v["mae_delta"]),
                result["would_pick_policy"],
                "Y" if v["c1"] else "N",
                "Y" if v["c2"] else "N",
                "Y" if v["c3"] else "N",
                "Y" if v["c4"] else "N",
                "PASS" if v["passed"] else "fail",
            ]
            print(fmt_row(row, widths))
    print()
    print("(d_t10c = top10_cost improvement vs shipped {0:.4f}, positive = better; "
          "mae_d = mae regression vs shipped {1:.4f}, positive = worse)".format(
              SHIPPED_TOP10_COST, SHIPPED_MAE))
    print()

    # -----------------------------------------------------------------
    # TABLE 2: combined sets (all of a method's condition-3 winners at once).
    # -----------------------------------------------------------------
    print("=" * 100)
    print("TABLE 2: combined sets (all condition-3 winning stats for a method, "
          "swapped together)")
    print("=" * 100)
    print(fmt_row(header, widths))

    combined_results = {}
    for method, winning_stats in WINNERS_UNDER_PREDICT_WEEKLY.items():
        full_curves = full_curves_by_method[method]
        candidate = make_candidate_curves(baseline_curves, full_curves, winning_stats)
        save_curves(candidate, os.path.join(SCRATCH_DIR, "curves_{0}_combined.yaml".format(method)))
        result = evaluate(lg, pool, prices, candidate, "{0}:combined".format(method))
        v = verdict_for_stat(result)
        combined_results[method] = (result, v)
        row = [
            method, "+".join(winning_stats),
            "{0:.4f}".format(result["top10_cost"]),
            "{0:+.4f}".format(v["top10_cost_delta"]),
            "{0:.4f}".format(result["mae"]),
            "{0:+.4f}".format(result["top10_bias"]),
            "{0:+.4f}".format(v["mae_delta"]),
            result["would_pick_policy"],
            "Y" if v["c1"] else "N",
            "Y" if v["c2"] else "N",
            "Y" if v["c3"] else "N",
            "Y" if v["c4"] else "N",
            "PASS (all-4, combined-set reading)" if v["passed"] else "fail (combined-set reading)",
        ]
        print(fmt_row(row, widths))
    print()

    # -----------------------------------------------------------------
    # Declared-in-advance checks.
    # -----------------------------------------------------------------
    print("=" * 100)
    print("DECLARED-IN-ADVANCE CHECKS")
    print("=" * 100)
    print("Sign of top10_bias: shipped = {0:+.4f} (over-pricing). Any candidate whose "
          "sign flips is a DIFFERENT error, not an improvement, per the spec.".format(
              SHIPPED_TOP10_BIAS))
    for (method, stat), (result, v) in per_stat_results.items():
        same_sign = (result["top10_bias"] >= 0) == (SHIPPED_TOP10_BIAS >= 0)
        print("  {0:10s} {1:10s} top10_bias={2:+.4f}  {3}".format(
            method, stat, result["top10_bias"],
            "same sign" if same_sign else "SIGN FLIPPED"))
    for method, (result, v) in combined_results.items():
        same_sign = (result["top10_bias"] >= 0) == (SHIPPED_TOP10_BIAS >= 0)
        print("  {0:10s} {1:10s} top10_bias={2:+.4f}  {3}".format(
            method, "combined", result["top10_bias"],
            "same sign" if same_sign else "SIGN FLIPPED"))
    print()

    print("=" * 100)
    print("FINAL VERDICT, stat by stat (all four conditions)")
    print("=" * 100)
    any_pass = False
    for (method, stat), (result, v) in sorted(per_stat_results.items()):
        status = "ADOPT" if v["passed"] else "reject"
        any_pass = any_pass or v["passed"]
        print("  {0} / {1}: {2}  (top10_cost {3:.4f}, delta {4:+.4f}; "
              "mae {5:.4f}, delta {6:+.4f})".format(
                  method, stat, status, result["top10_cost"], v["top10_cost_delta"],
                  result["mae"], v["mae_delta"]))
    print()
    if not any_pass:
        print("NO (method, stat) pair clears all four pre-registered conditions.")
    else:
        print("At least one (method, stat) pair clears all four conditions - see ADOPT rows above.")


if __name__ == "__main__":
    main()

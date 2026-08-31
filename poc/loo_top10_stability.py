"""Third and final curve-adoption measurement: leave-one-out top10 stability.

Gate: docs/superpowers/specs/2026-08-30-curve-adoption-third-measurement.md
(committed as 17bcb91, BEFORE this script was run and BEFORE any number in
it was seen). This script does not choose, tune, or reinterpret anything the
gate does not already say.

RE-RUN 2026-08-30 with FOUR stats, not five: pass_yds was reverted out of
the bundle (it failed condition 3 of this same gate under de-duplicated
data - see .superpowers/sdd/2026-08-30-full-position-coverage/
pass-yds-revert-report.md). Removing a stat changes the bundle, so the
PRIMARY/guard numbers below are re-measured, not assumed to carry over from
the five-stat run.

IMPORTANT: `calibration/2025.yaml` is no longer a stand-in for "the shipped,
never-isotonic baseline" - it now itself contains the four-stat isotonic
bundle (this script's own candidate). Loading it as `baseline_curves` would
silently turn every "swap" below into a no-op for stats already isotonic in
that file. `baseline_curves` is therefore rebuilt HERE, fresh, from
`build_curves` on the build set only - the literal pre-adoption curve the
gate's hardcoded SHIPPED_* constants below describe - never loaded from the
committed file.

THE DECISIVE NEW TEST (guard 4). `top10_mae`/`top10_bias` are computed over
TEN observations - so a 2.62-point top10_cost improvement could be produced
by one or two players and would be indistinguishable, at n=10, from a
genuinely better curve. This script recomputes top10_cost for the shipped
curves and for the isotonic bundle TEN times, each time excluding one of the
ten top-priced players from the priced set and recomputing the top-10 set
from the remaining priced players - exactly as `fit.score_fit` does
internally (`sorted(pairs, key=lambda t: -t[1])[:10]`) - so each replicate
has a genuine ten-player top set with the eleventh-priced player promoted
in. The candidate must improve top10_cost in >= 9 of 10 replicates.

Machinery reused verbatim from prior measurements rather than rebuilt:
  - poc/compare_calibration_methods.py: dataset loading (build-set vs
    build-set + held-back), builder list.
  - poc/followup_curve_adoption.py: `make_candidate_curves`, the "literal
    shipped curve as baseline for non-swapped stats" pattern, `evaluate`'s
    shape (score_fit held at policy="starter", choose_policy computed only
    as a side diagnostic, per condition 4 / the spec's policy-held-fixed
    requirement).

THE BUNDLE. Four board-relevant isotonic winners - pass_cmp, rec_ct,
rec_yds, rush_yds. pass_yds is EXCLUDED (reverted 2026-08-30: it lost
condition 3 of this gate on de-duplicated data). def_pa/def_ya are EXCLUDED
FROM ADOPTION ENTIRELY per the spec: DST sits in `flat_priced_pools`, so its
curve never reaches `_dollars` and swapping it is structurally inert on the
board.

NOTHING IS TUNED: no floor, grid, fold count, or builder parameter is
touched, no new candidate methods. Curves are written to scratch paths only
(never calibration/2025.yaml); market/2026.yaml is never opened for
writing.

Run: PYTHONPATH=src ./.venv/bin/python poc/loo_top10_stability.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sffl.calibrate import build_curves, build_curves_isotonic, save_curves  # noqa: E402
from sffl.fit import choose_policy, load_prices, score_fit, top10_cost      # noqa: E402
from sffl.identity import normalize_name                                   # noqa: E402
from sffl.league import load_league                                        # noqa: E402
from sffl.pool import build_pool, score_season_calibrated                  # noqa: E402
from sffl.value import assign_dollars, assign_vorp, replacement_levels     # noqa: E402
from sffl.weekly import load_weekly                                        # noqa: E402

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

SCRATCH_DIR = ("/private/tmp/claude-501/-Users-jeff-Projects-fantasy-football/"
               "e29be1c8-4a81-4926-9ec2-a7593da02577/scratchpad")

SHIPPED_MAE = 4.3392
SHIPPED_TOP10_MAE = 10.0638
SHIPPED_TOP10_BIAS = 5.1042
SHIPPED_TOP10_COST = round(SHIPPED_TOP10_MAE + abs(SHIPPED_TOP10_BIAS), 4)  # 15.168

TOP10_COST_GATE = 1.00
MAE_GUARD = 0.25

# The four board-relevant isotonic winning stats. pass_yds excluded 2026-08-30
# (reverted - lost condition 3 on de-duplicated data). def_pa/def_ya excluded
# per the spec (structurally inert on the board - DST is flat-priced).
BUNDLE_STATS = ["pass_cmp", "rec_ct", "rec_yds", "rush_yds"]

POLICY = "starter"


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
    out = dict(baseline_curves)
    for stat in stats_to_swap:
        out[stat] = full_method_curves[stat]
    return out


def evaluate(lg, pool, prices, curves, label):
    """score_fit held fixed at policy='starter'. choose_policy is computed
    only as a side diagnostic (its result plays no part in the gate), per
    the same discipline used in poc/followup_curve_adoption.py.
    """
    for p in pool:
        p.stats["_season_points"] = score_season_calibrated(lg, p, curves)
    pool.sort(key=lambda p: -p.stats["_season_points"])

    starter_report = score_fit(lg, pool, prices, POLICY)
    would_pick, _reports = choose_policy(lg, pool, prices)

    return {
        "label": label,
        "mae": starter_report["mae"],
        "top10_mae": starter_report["top10_mae"],
        "top10_bias": starter_report["top10_bias"],
        "top10_cost": top10_cost(starter_report),
        "would_pick_policy": would_pick,
    }


def dollar_price_pairs(lg, pool, prices, curves):
    """(key, model_dollars, actual_price) for every priced pool player,
    under `curves` and policy='starter' - the identical computation
    `fit.score_fit` performs to build its own (unlabelled) `pairs` list,
    with the player's canonical key carried alongside so a leave-one-out
    replicate can exclude a specific player.
    """
    for p in pool:
        p.stats["_season_points"] = score_season_calibrated(lg, p, curves)
    pool.sort(key=lambda p: -p.stats["_season_points"])

    levels = replacement_levels(lg, pool, POLICY)
    assign_vorp(lg, pool, levels)
    assign_dollars(lg, pool)

    pairs = []
    for p in pool:
        key = normalize_name(p.name)
        if key in prices:
            pairs.append((key, p.stats["_dollars"], prices[key]))
    return pairs


def top10_metrics_from_pairs(pairs):
    """Exactly score_fit's top-10 computation: sorted by actual price desc,
    first 10, mae/bias/cost over that set.
    """
    top = sorted(pairs, key=lambda t: -t[2])[:10]
    errs = [abs(m - a) for _k, m, a in top]
    bias = sum(m - a for _k, m, a in top) / len(top)
    mae = sum(errs) / len(errs)
    return {"top10_mae": mae, "top10_bias": bias, "top10_cost": mae + abs(bias)}


def loo_replicates(pairs):
    """The ten (excluded_key, reduced_pairs) replicates: drop each of the
    ORIGINAL top-10-by-price players in turn, recomputing the top-10 set
    from what remains (the 11th-priced player is promoted in).
    """
    original_top10 = sorted(pairs, key=lambda t: -t[2])[:10]
    excluded_keys = [k for k, _m, _a in original_top10]
    reps = []
    for excl in excluded_keys:
        reduced = [t for t in pairs if t[0] != excl]
        reps.append((excl, reduced))
    return reps


def fmt_row(cols, widths):
    return " | ".join(str(c).ljust(w) for c, w in zip(cols, widths))


def main():
    lg = load_league(LEAGUE_PROFILE_PATH)

    build_set_lines = load_lines(BUILD_SET_DIR, BUILD_SET_POSITIONS)
    held_back_lines = load_held_back_lines()
    combined_lines = build_set_lines + held_back_lines

    print("Build-set only: {0} player-weeks, {1} distinct players".format(
        len(build_set_lines), len({ln.player_id for ln in build_set_lines})))
    print("Build-set + held-back: {0} player-weeks, {1} distinct players".format(
        len(combined_lines), len({ln.player_id for ln in combined_lines})))
    print()

    # The literal pre-adoption shipped curve - build_curves on the build set
    # only, for every stat. Rebuilt fresh here rather than loaded from
    # calibration/2025.yaml: that file now itself ships the four-stat
    # isotonic bundle (this script's own candidate), so loading it as
    # "baseline" would make every swap below a no-op for the four already-
    # isotonic stats. This is exactly what the hardcoded SHIPPED_* constants
    # above describe, and the sanity check below confirms it reproduces them.
    baseline_curves = build_curves(lg, build_set_lines)

    isotonic_full_buildset = build_curves_isotonic(lg, build_set_lines)
    isotonic_full_combined = build_curves_isotonic(lg, combined_lines)

    candidate_buildset = make_candidate_curves(
        baseline_curves, isotonic_full_buildset, BUNDLE_STATS)
    candidate_combined = make_candidate_curves(
        baseline_curves, isotonic_full_combined, BUNDLE_STATS)

    os.makedirs(SCRATCH_DIR, exist_ok=True)
    save_curves(baseline_curves, os.path.join(SCRATCH_DIR, "curves_baseline.yaml"))
    save_curves(candidate_buildset, os.path.join(SCRATCH_DIR, "curves_isotonic_bundle_buildset.yaml"))
    save_curves(candidate_combined, os.path.join(SCRATCH_DIR, "curves_isotonic_bundle_combined.yaml"))

    pool = build_pool(lg, SOURCE_PROFILE, EXTRACT_FILE, YEAR, None)
    prices = load_prices(PRICES_FILE, tqb_starters_path=TQB_STARTERS_FILE,
                          season=YEAR, require_file_season=True)

    print("=" * 100)
    print("SANITY CHECK: literal shipped curve through this pipeline, policy='starter',")
    print("should reproduce market/2026.yaml's numbers.")
    print("=" * 100)
    baseline_result = evaluate(lg, pool, prices, baseline_curves, "baseline")
    print("baseline: mae={mae:.4f} top10_mae={top10_mae:.4f} top10_bias={top10_bias:+.4f} "
          "top10_cost={top10_cost:.4f} (choose_policy would pick: {would_pick_policy})"
          .format(**baseline_result))
    print("shipped (market/2026.yaml): mae={0:.4f} top10_mae={1:.4f} top10_bias={2:+.4f} "
          "top10_cost={3:.4f}".format(
              SHIPPED_MAE, SHIPPED_TOP10_MAE, SHIPPED_TOP10_BIAS, SHIPPED_TOP10_COST))
    print()

    # ------------------------------------------------------------------
    # GUARD 2: per-stat swaps, individually, on the ship-candidate regime
    # (isotonic curves built on build-set + held-back). No stat may
    # individually WORSEN top10_cost.
    # ------------------------------------------------------------------
    print("=" * 100)
    print("GUARD 2: per-stat swaps, individually (curves built on build-set + held-back)")
    print("=" * 100)
    widths = [10, 11, 9, 9, 11, 9]
    print(fmt_row(["stat", "top10_cost", "d_t10c", "mae", "top10_bias", "mae_d"], widths))
    guard2_all_nonnegative = True
    for stat in BUNDLE_STATS:
        candidate = make_candidate_curves(baseline_curves, isotonic_full_combined, [stat])
        result = evaluate(lg, pool, prices, candidate, "isotonic:{0}".format(stat))
        d_t10c = SHIPPED_TOP10_COST - result["top10_cost"]
        mae_d = result["mae"] - SHIPPED_MAE
        if d_t10c < 0:
            guard2_all_nonnegative = False
        print(fmt_row([
            stat, "{0:.4f}".format(result["top10_cost"]), "{0:+.4f}".format(d_t10c),
            "{0:.4f}".format(result["mae"]), "{0:+.4f}".format(result["top10_bias"]),
            "{0:+.4f}".format(mae_d),
        ], widths))
    print()
    print("GUARD 2 verdict: {0}".format(
        "PASS - every stat contributes >= 0 to top10_cost" if guard2_all_nonnegative
        else "FAIL - at least one stat individually worsens top10_cost"))
    print()

    # ------------------------------------------------------------------
    # PRIMARY / GUARD 1 / GUARD 3 / GUARD 5: the bundle, both regimes.
    # ------------------------------------------------------------------
    print("=" * 100)
    print("PRIMARY + GUARD 1 + GUARD 3 + GUARD 5: the bundle, both dataset regimes")
    print("=" * 100)
    regime_results = {}
    for regime_label, candidate in [
        ("build-set only", candidate_buildset),
        ("build-set + held-back (ship regime)", candidate_combined),
    ]:
        result = evaluate(lg, pool, prices, candidate, "isotonic:bundle:{0}".format(regime_label))
        d_t10c = SHIPPED_TOP10_COST - result["top10_cost"]
        mae_d = result["mae"] - SHIPPED_MAE
        same_sign = (result["top10_bias"] >= 0) == (SHIPPED_TOP10_BIAS >= 0)
        regime_results[regime_label] = (result, d_t10c, mae_d, same_sign)
        print("{0}:".format(regime_label))
        print("  top10_cost={0:.4f}  d_t10c={1:+.4f}  (PRIMARY {2})".format(
            result["top10_cost"], d_t10c, "PASS" if d_t10c >= TOP10_COST_GATE else "FAIL"))
        print("  mae={0:.4f}  mae_d={1:+.4f}  (GUARD1 {2})".format(
            result["mae"], mae_d, "PASS" if mae_d <= MAE_GUARD else "FAIL"))
        print("  top10_bias={0:+.4f}  (GUARD3 {1})".format(
            result["top10_bias"], "PASS (same sign)" if same_sign else "FAIL (sign flip)"))
        print("  choose_policy would pick: {0}".format(result["would_pick_policy"]))
        print()

    # ------------------------------------------------------------------
    # GUARD 4 - THE DECISIVE NEW TEST: leave-one-out over the top-10 players.
    # Run against the ship-regime bundle (build-set + held-back), the
    # candidate the gate is actually deciding on.
    # ------------------------------------------------------------------
    print("=" * 100)
    print("GUARD 4 (DECISIVE): leave-one-out top10_cost stability, ship-regime bundle")
    print("(build-set + held-back isotonic curves for the 4 board stats)")
    print("=" * 100)

    shipped_pairs = dollar_price_pairs(lg, pool, prices, baseline_curves)
    bundle_pairs = dollar_price_pairs(lg, pool, prices, candidate_combined)

    shipped_keys = set(k for k, _m, _a in shipped_pairs)
    bundle_keys = set(k for k, _m, _a in bundle_pairs)
    print("priced pairs: shipped n={0}, bundle n={1}, same player set: {2}".format(
        len(shipped_pairs), len(bundle_pairs), shipped_keys == bundle_keys))

    full_shipped_top10 = top10_metrics_from_pairs(shipped_pairs)
    full_bundle_top10 = top10_metrics_from_pairs(bundle_pairs)
    print("full top10 (no exclusion) sanity check: shipped top10_cost={0:.4f}  "
          "bundle top10_cost={1:.4f}".format(
              full_shipped_top10["top10_cost"], full_bundle_top10["top10_cost"]))
    print()

    shipped_reps = dict(loo_replicates(shipped_pairs))
    bundle_reps = dict(loo_replicates(bundle_pairs))
    # The excluded-player set is determined solely by actual price, so it is
    # identical whichever curve's pairs it is derived from.
    excluded_keys_ordered = [k for k, _m, _a in
                              sorted(shipped_pairs, key=lambda t: -t[2])[:10]]

    widths2 = [26, 14, 14, 10, 8]
    print(fmt_row(["excluded player", "shipped t10c", "bundle t10c", "delta", "better?"], widths2))
    n_improved = 0
    deltas = []
    for excl in excluded_keys_ordered:
        s_metrics = top10_metrics_from_pairs(shipped_reps[excl])
        b_metrics = top10_metrics_from_pairs(bundle_reps[excl])
        delta = s_metrics["top10_cost"] - b_metrics["top10_cost"]  # positive = bundle better
        deltas.append(delta)
        improved = delta > 0
        n_improved += int(improved)
        print(fmt_row([
            excl, "{0:.4f}".format(s_metrics["top10_cost"]),
            "{0:.4f}".format(b_metrics["top10_cost"]),
            "{0:+.4f}".format(delta), "yes" if improved else "NO",
        ], widths2))
    print()
    print("GUARD 4: bundle improves top10_cost in {0} of 10 leave-one-out replicates "
          "(need >= 9).".format(n_improved))
    print("GUARD 4 verdict: {0}".format("PASS" if n_improved >= 9 else "FAIL"))
    print()

    # Also run guard 4 against the build-set-only bundle, for completeness
    # (not the decisive comparison - the ship regime above is).
    print("-" * 100)
    print("GUARD 4, informational only: same leave-one-out test against the ")
    print("build-set-only bundle (not the regime that would ship).")
    print("-" * 100)
    bundle_bs_pairs = dollar_price_pairs(lg, pool, prices, candidate_buildset)
    bundle_bs_reps = dict(loo_replicates(bundle_bs_pairs))
    n_improved_bs = 0
    for excl in excluded_keys_ordered:
        s_metrics = top10_metrics_from_pairs(shipped_reps[excl])
        b_metrics = top10_metrics_from_pairs(bundle_bs_reps[excl])
        delta = s_metrics["top10_cost"] - b_metrics["top10_cost"]
        improved = delta > 0
        n_improved_bs += int(improved)
        print("  excl={0:26s} shipped={1:.4f} bundle_bs={2:.4f} delta={3:+.4f} {4}".format(
            excl, s_metrics["top10_cost"], b_metrics["top10_cost"], delta,
            "yes" if improved else "NO"))
    print("build-set-only bundle improves in {0} of 10 replicates.".format(n_improved_bs))
    print()

    # ------------------------------------------------------------------
    # FINAL VERDICT
    # ------------------------------------------------------------------
    print("=" * 100)
    print("FINAL VERDICT (ship regime = build-set + held-back)")
    print("=" * 100)
    ship_result, ship_d_t10c, ship_mae_d, ship_same_sign = regime_results[
        "build-set + held-back (ship regime)"]
    bs_result, bs_d_t10c, bs_mae_d, bs_same_sign = regime_results["build-set only"]

    c_primary = ship_d_t10c >= TOP10_COST_GATE
    c_guard1 = ship_mae_d <= MAE_GUARD
    c_guard2 = guard2_all_nonnegative
    c_guard3 = ship_same_sign
    c_guard4 = n_improved >= 9
    # GUARD 5 per the spec's own wording is NOT "both regimes must pass" -
    # it is "report both; adoption requires the gate to clear in the regime
    # that would actually ship" (build-set + held-back here). Both-regimes
    # clearing is reported as a bonus fact, not required.
    ship_regime_clears_primary = c_primary
    both_regimes_clear_primary = c_primary and (bs_d_t10c >= TOP10_COST_GATE)

    print("PRIMARY (top10_cost improves >= 1.00, ship regime): {0} ({1:+.4f})".format(
        "PASS" if c_primary else "FAIL", ship_d_t10c))
    print("GUARD 1 (mae regresses <= 0.25, ship regime): {0} ({1:+.4f})".format(
        "PASS" if c_guard1 else "FAIL", ship_mae_d))
    print("GUARD 2 (no stat individually worsens top10_cost): {0}".format(
        "PASS" if c_guard2 else "FAIL"))
    print("GUARD 3 (top10_bias keeps its sign): {0}".format(
        "PASS" if c_guard3 else "FAIL"))
    print("GUARD 4 (>=9/10 leave-one-out replicates improve): {0} ({1}/10)".format(
        "PASS" if c_guard4 else "FAIL", n_improved))
    print("GUARD 5 (ship regime = build-set + held-back clears PRIMARY): {0} "
          "(build-set-only d_t10c={1:+.4f}, combined/ship d_t10c={2:+.4f}; "
          "both regimes clear PRIMARY: {3})".format(
              "PASS" if ship_regime_clears_primary else "FAIL",
              bs_d_t10c, ship_d_t10c, both_regimes_clear_primary))
    print()

    all_pass = c_primary and c_guard1 and c_guard2 and c_guard3 and c_guard4
    print("OVERALL: {0}".format("ADOPT" if all_pass else "REJECT / QUESTION CLOSED"))


if __name__ == "__main__":
    main()

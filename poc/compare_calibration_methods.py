"""Task 4 measurement: does regularising the curve builder beat interpolation?

THE QUESTION. Fantasy scoring is BANDED, so E[band(X)] != band(E[X]). The
shipped builder (`build_curves`) gives every qualifying player exactly one
anchor - his own (mean, realized) pair - and interpolates straight lines
through them: 36 players' worth of anchors for rush_yds (corrected
2026-08-30 to 34 - RB.csv carried a duplicate-entity pair under two
player_ids; see NEXT.md), but only FOUR for each defensive stat, so a
three-segment "curve" prices and start/sits every defense in the league.

Adding the 84 held-back players was tried once (see
data/weekly/2025/_held_back/README.md) and judged "worse on 6 of 7 stats".
That verdict was an AGGREGATE - and the aggregate is dominated by the stats
(rush_yds, rec_yds, rec_ct, pass_yds, pass_cmp) that already had 30-48
players. The pre-registered hypothesis this script tests: the SPARSE stats
(def_pa, def_ya - 4 players each in the build set) improve when given more
players, while the DENSE ones degrade, and a single global verdict hides
that split.

THIS SCRIPT PRODUCES A MEASUREMENT, NOT A CHANGE. It does not write
calibration/2025.yaml. It never prints a single aggregate "X of 7" verdict -
every stat is reported on its own row, because collapsing them is the exact
mistake being corrected.

Two datasets:
  1. build-set only:        data/weekly/2025/{DST,K,RB,TQB,WR}.csv
  2. build-set + held-back: the above plus
                             data/weekly/2025/_held_back/{DST,TQB,WR,TE}.full.csv

Two predictors (both must be reported - they answer different questions):
  - predict_weekly - what `pool.score_week` actually calls (wraps the curve
    in `pool._calibrated_band_value`'s monotone envelope before
    interpolating). This is `cross_validate`'s default.
  - predict_raw    - what `pool.score_season_calibrated` (the AUCTION BOARD
    path) actually calls: plain linear interpolation, no envelope.

Three builders: build_curves (baseline), build_curves_isotonic (candidate A,
monotone PAVA fit), build_curves_pooled (candidate B, pools multiplicative
residuals across players and integrates band() over them).

Run: PYTHONPATH=src ./.venv/bin/python poc/compare_calibration_methods.py
"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sffl.league import load_league                              # noqa: E402
from sffl.weekly import load_weekly                               # noqa: E402
from sffl.calibrate import (                                      # noqa: E402
    MIN_WEEKS,
    STAT_POSITIONS,
    build_curves,
    build_curves_isotonic,
    build_curves_pooled,
)
from sffl.calibrate_eval import cross_validate, predict_raw, predict_weekly  # noqa: E402

LEAGUE_PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..",
                                   "leagues", "sffl", "2026.yaml")
BUILD_SET_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "weekly", "2025")
HELD_BACK_DIR = os.path.join(BUILD_SET_DIR, "_held_back")

BUILD_SET_POSITIONS = ["DST", "K", "RB", "TQB", "WR"]
HELD_BACK_POSITIONS = ["DST", "TQB", "WR", "TE"]

BUILDERS = [
    ("build_curves (baseline)", build_curves),
    ("build_curves_isotonic (A)", build_curves_isotonic),
    ("build_curves_pooled (B)", build_curves_pooled),
]

PREDICTORS = [
    ("predict_weekly (score_week path)", predict_weekly),
    ("predict_raw (auction-board path)", predict_raw),
]

RECEIVING_COUNT_CAVEAT = (
    "  CAVEAT (measured by a reviewer, not tuned away): build_curves_pooled's "
    "MIN_MEAN_FLOOR excludes 30.8% of receivers from the rec_ct residual pool "
    "(0% excluded for pass_yds/pass_cmp/def_pa/def_ya, 4.7% for rush_yds), "
    "then this stat is scored against ALL held-out receivers, including the "
    "excluded low-volume ones. For the 12 excluded receivers, realized total "
    "was 0.353 vs pooled prediction 0.032 - the miss is a few hundredths of a "
    "point against band values of 2-7. Read rec_ct's pooled MAE as handicapped "
    "in DIRECTION (biased against pooled) but negligible in SIZE, not a clean "
    "loss."
)


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


def players_per_stat(lg, lines, min_weeks=MIN_WEEKS):
    """Distinct players (>= min_weeks weeks, position eligible) per stat.

    This is the SAME filter build_curves applies before it hands a player an
    anchor point, so the count shown is "how many anchors would the baseline
    curve have" - the number that tells a reader which regime a stat is in.
    """
    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)

    counts = {}
    for stat in lg.bands:
        n = 0
        for weeks in by_player.values():
            if len(weeks) < min_weeks:
                continue
            if weeks[0].pos not in STAT_POSITIONS[stat]:
                continue
            n += 1
        counts[stat] = n
    return counts


def run_dataset(lg, dataset_name, lines):
    print("=" * 100)
    print("DATASET: {0}  ({1} player-weeks, {2} distinct players)".format(
        dataset_name, len(lines), len({ln.player_id for ln in lines})))
    print("=" * 100)

    counts = players_per_stat(lg, lines)

    for predictor_label, predictor in PREDICTORS:
        print()
        print("-" * 100)
        print("PREDICTOR: {0}".format(predictor_label))
        print("-" * 100)

        results = {}  # builder_label -> {stat: row}
        for builder_label, builder in BUILDERS:
            results[builder_label] = cross_validate(
                lg, lines, builder, predict=predictor)

        header = "{0:12s} {1:>8s}".format("stat", "players")
        for builder_label, _ in BUILDERS:
            header += " | {0:>26s}".format(builder_label)
        print(header)

        for stat in sorted(lg.bands):
            row = "{0:12s} {1:>8d}".format(stat, counts[stat])
            maes = {}
            for builder_label, _ in BUILDERS:
                r = results[builder_label][stat]
                if r["mae"] is None:
                    cell = "n=0 (no data)"
                else:
                    cell = "n={0:<4d} mae={1:.4f} ecf={2}".format(
                        r["n"], r["mae"], r["empty_curve_folds"])
                    maes[builder_label] = r["mae"]
                row += " | {0:>26s}".format(cell)
            print(row)

            if maes:
                best_label = min(maes, key=lambda k: maes[k])
                is_baseline_best = best_label == BUILDERS[0][0]
                distinct_values = sorted(set(round(v, 6) for v in maes.values()))
                if len(distinct_values) == 1:
                    verdict = "TIE across all builders that produced a curve -> a tie is a LOSS for every candidate (baseline ships today)."
                elif is_baseline_best:
                    verdict = "baseline wins (lowest MAE) - no candidate beats it here."
                else:
                    margin_vs_baseline = maes.get(BUILDERS[0][0])
                    if margin_vs_baseline is None:
                        verdict = "{0} has the lowest MAE among builders with data, but the baseline produced no curve here (n=0) so there is nothing for it to beat.".format(best_label)
                    else:
                        verdict = "{0} beats the baseline here: {1:.4f} < {2:.4f}.".format(
                            best_label, maes[best_label], margin_vs_baseline)
                print("  -> " + verdict)
            else:
                print("  -> no builder produced a scoreable curve for this stat under this predictor/dataset.")

            if stat == "rec_ct":
                print(RECEIVING_COUNT_CAVEAT)
        print()


def main():
    lg = load_league(LEAGUE_PROFILE_PATH)

    build_set_lines = load_lines(BUILD_SET_DIR, BUILD_SET_POSITIONS)
    held_back_lines = load_held_back_lines()
    combined_lines = build_set_lines + held_back_lines

    print(__doc__)

    run_dataset(lg, "build-set only", build_set_lines)
    run_dataset(lg, "build-set + held-back", combined_lines)

    print("=" * 100)
    print("REMINDER: no aggregate verdict follows. Read each stat row on its own -")
    print("that is the entire point of this script. A stat's regime (see the")
    print("'players' column) is what determines whether more data helps it.")
    print("=" * 100)


if __name__ == "__main__":
    main()

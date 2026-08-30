"""Build 2025 expectation curves from real CBS weekly data.

Per-stat, by adopted method (see docs/superpowers/specs/2026-08-30-curve-
adoption-third-measurement.md, cleared, and
.superpowers/sdd/2026-08-30-regularised-calibration-curves/third-measurement-report.md):

  - pass_cmp, pass_yds, rec_ct, rec_yds, rush_yds (the five board-relevant
    stats `_dollars` actually prices): `build_curves_isotonic` on the FULL
    dataset - the build set PLUS the previously held-back weeks
    (`data/weekly/2025/_held_back/*.full.csv`). Measured: top10_cost
    15.1681 -> 12.5436, mae 4.3392 -> 4.4758, top10_bias +5.1042 -> +3.7312.
  - def_pa, def_ya: unchanged, `build_curves` on the build set only. NOT
    adopted for isotonic/full-dataset treatment - two independent reasons,
    both binding: (1) DST sits in `flat_priced_pools`, so its curve never
    reaches `_dollars` - structurally inert on the board; (2) the weekly
    (in-season) path where a DST curve DOES matter was never covered by any
    pre-registered gate here. Do not "adopt for consistency" - that is
    exactly how an ungated change would ride along with a gated one.

This script is the single source of truth for calibration/2025.yaml: re-running
it against the same weekly data (build set + held-back, both gitignored but
real) reproduces the committed file byte-for-byte. Provenance - which method
and which dataset built each stat, and the player/anchor counts - is written
to the sibling calibration/2025.provenance.yaml, NOT into calibration/2025.yaml
itself: `calibrate.load_curves` does
`{k: [(float(m), float(e)) for m, e in v] for k, v in raw.items()}` and will
crash on any key whose value is not a list of (mean, expected) pairs, so a
metadata block cannot live inside the curve file.

Input:
  data/weekly/2025/{DST,K,RB,TQB,WR}.csv              (build set, gitignored)
  data/weekly/2025/_held_back/{DST,TQB,WR,TE}.full.csv (held-back, gitignored)
Output:
  calibration/2025.yaml              (generated curves, tracked)
  calibration/2025.provenance.yaml   (generated provenance, tracked)
"""

import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sffl.calibrate import (  # noqa: E402
    MIN_WEEKS,
    STAT_POSITIONS,
    build_curves,
    build_curves_isotonic,
    save_curves,
)
from sffl.league import load_league  # noqa: E402
from sffl.weekly import load_weekly  # noqa: E402

# Explicit constants at top
LEAGUE_PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..",
                                   "leagues", "sffl", "2026.yaml")
WEEKLY_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "weekly", "2025")
HELD_BACK_DIR = os.path.join(WEEKLY_DATA_DIR, "_held_back")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "calibration", "2025.yaml")
PROVENANCE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "calibration", "2025.provenance.yaml")

BUILD_SET_POSITIONS = ["DST", "K", "RB", "TQB", "WR"]
HELD_BACK_POSITIONS = ["DST", "TQB", "WR", "TE"]
SEASON = 2025

# The five board-relevant isotonic winners, adopted on the full dataset. See
# docs/superpowers/specs/2026-08-30-curve-adoption-third-measurement.md - the
# gate that cleared - and the third-measurement report for the numbers.
ISOTONIC_FULL_DATASET_STATS = [
    "pass_cmp", "pass_yds", "rec_ct", "rec_yds", "rush_yds",
]
# def_pa/def_ya stay on the shipped build_curves/build-set-only path.
INTERPOLATED_BUILD_SET_STATS = ["def_pa", "def_ya"]


def load_all_weekly(data_dir, positions, suffix=".csv"):
    """Load and concatenate weekly data for all positions."""
    all_lines = []
    for pos in positions:
        path = os.path.join(data_dir, "{0}{1}".format(pos, suffix))
        lines = load_weekly(path)
        all_lines.extend(lines)
    return all_lines


def _dataset_counts(lines):
    player_ids = Counter(ln.player_id for ln in lines)
    return len(player_ids), len(lines)


def _player_count_for_stat(lines, stat, min_weeks=MIN_WEEKS):
    """Distinct players actually contributing an anchor to `stat`'s curve.

    Mirrors the exact filter build_curves/build_curves_isotonic apply
    internally (>= min_weeks appearances, position eligible for this stat)
    so the provenance count matches what really went into the curve, not
    just what was loaded from disk.
    """
    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)
    count = 0
    for weeks in by_player.values():
        if len(weeks) < min_weeks:
            continue
        if weeks[0].pos not in STAT_POSITIONS[stat]:
            continue
        count += 1
    return count


def main():
    # Load league profile
    lg = load_league(LEAGUE_PROFILE_PATH)

    # Load the two datasets. Held-back's ".full.csv" files layer additional
    # weeks (and additional players) on top of the build set - see
    # data/weekly/2025/_held_back/README.md.
    build_set_lines = load_all_weekly(WEEKLY_DATA_DIR, BUILD_SET_POSITIONS)
    held_back_lines = load_all_weekly(HELD_BACK_DIR, HELD_BACK_POSITIONS, ".full.csv")
    full_dataset_lines = build_set_lines + held_back_lines

    build_set_players, build_set_weeks = _dataset_counts(build_set_lines)
    full_players, full_weeks = _dataset_counts(full_dataset_lines)

    # Build both candidate curve sets. Each is computed for every banded stat
    # in the league profile; only the relevant subset of each is kept below,
    # so a stat's curve always comes from exactly one of the two calls.
    interpolated_buildset = build_curves(lg, build_set_lines)
    isotonic_full = build_curves_isotonic(lg, full_dataset_lines)

    curves = {}
    provenance = {}
    for stat in lg.bands:
        if stat in ISOTONIC_FULL_DATASET_STATS:
            curves[stat] = isotonic_full[stat]
            provenance[stat] = {
                "method": "build_curves_isotonic",
                "dataset": "build_set_plus_held_back",
                "player_count": _player_count_for_stat(full_dataset_lines, stat),
                "anchor_count": len(curves[stat]),
            }
        elif stat in INTERPOLATED_BUILD_SET_STATS:
            curves[stat] = interpolated_buildset[stat]
            provenance[stat] = {
                "method": "build_curves",
                "dataset": "build_set_only",
                "player_count": _player_count_for_stat(build_set_lines, stat),
                "anchor_count": len(curves[stat]),
                "note": ("excluded from isotonic/full-dataset adoption: "
                         "structurally inert on the board (DST sits in "
                         "flat_priced_pools, so this curve never reaches "
                         "_dollars) and its weekly-path behaviour was never "
                         "covered by any pre-registered gate"),
            }
        else:
            raise ValueError(
                "stat {0} in lg.bands is not classified into either "
                "ISOTONIC_FULL_DATASET_STATS or INTERPOLATED_BUILD_SET_STATS "
                "- update poc/build_calibration.py".format(stat))

    # Write the curves through the same serializer production code uses, so
    # the two can never drift. No timestamp in the header - re-running the
    # generator against the same weekly data must produce a byte-identical
    # file, not a timestamp-only diff on every run.
    header_lines = [
        "# Generated expectation curves from 2025 weekly data",
        "# Generated by: poc/build_calibration.py",
        "# Two build regimes, per stat (see calibration/2025.provenance.yaml",
        "# for the full per-stat record):",
        "#   isotonic ({0}): build_curves_isotonic on the build set plus".format(
            ", ".join(ISOTONIC_FULL_DATASET_STATS)),
        "#     held-back weeks - {0} distinct players, {1} player-weeks".format(
            full_players, full_weeks),
        "#   interpolated ({0}): build_curves on the build set only -".format(
            ", ".join(INTERPOLATED_BUILD_SET_STATS)),
        "#     {0} distinct players, {1} player-weeks".format(
            build_set_players, build_set_weeks),
        "",
    ]

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    save_curves(curves, OUTPUT_PATH)
    with open(OUTPUT_PATH) as fh:
        body = fh.read()
    with open(OUTPUT_PATH, "w") as fh:
        fh.write("\n".join(header_lines) + "\n")
        fh.write(body)

    _save_provenance(provenance, PROVENANCE_PATH)

    # Print summary
    print("Build set: {0} player-weeks, {1} distinct players".format(
        build_set_weeks, build_set_players))
    print("Full dataset (build set + held-back): {0} player-weeks, {1} distinct players".format(
        full_weeks, full_players))
    print("\nBanded stat curve points by stat:")
    for stat in sorted(curves.keys()):
        p = provenance[stat]
        print("  {0:12s}: {1:3d} points  [{2}, {3}, {4} players]".format(
            stat, len(curves[stat]), p["method"], p["dataset"], p["player_count"]))

    print("\nWrote curves to {0}".format(OUTPUT_PATH))
    print("Wrote provenance to {0}".format(PROVENANCE_PATH))


def _save_provenance(provenance, path):
    """Write the per-stat provenance record as plain YAML.

    Deliberately a SEPARATE file from calibration/2025.yaml - see the module
    docstring for why a metadata block cannot live inside the curve file
    itself (calibrate.load_curves would crash on it).
    """
    import yaml

    header = (
        "# Provenance for calibration/2025.yaml, one entry per banded stat:\n"
        "# which method built its curve, from which dataset, and how many\n"
        "# players/anchors that produced. Generated by poc/build_calibration.py -\n"
        "# do not hand-edit. tests/test_calibrate.py::"
        "test_every_curve_stat_has_provenance_and_vice_versa\n"
        "# keeps this file and calibration/2025.yaml's stat keys from drifting apart.\n"
    )
    with open(path, "w") as fh:
        fh.write(header)
        yaml.safe_dump(provenance, fh, default_flow_style=False, sort_keys=True)


if __name__ == "__main__":
    main()

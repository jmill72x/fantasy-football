"""Judge a calibration curve honestly: cross-validated, by player, per stat.

WHY THIS EXISTS. The shipped curves interpolate straight lines through one
point per player. Adding more players was tried once and judged "worse on 6 of
7 stats" - but that verdict was AGGREGATE, and the aggregate is dominated by the
stats that already had 36 players. `def_pa` has four. Those are different
regimes and a count of stats cannot tell them apart, so this module reports
every stat separately and never collapses them.

THE LEAK IT EXISTS TO PREVENT. A player's weeks must never be in both the fit
and the holdout set: interpolation would then draw its line straight through
his own point and predict him almost exactly. Splitting is by PLAYER, always.

WHY K-FOLD RATHER THAN ONE HOLDOUT. With 26 defenses, a single 20% holdout
judges on five players and the answer moves with the split. K-fold uses every
player as holdout exactly once, which at these sample sizes is the difference
between a measurement and an anecdote.
"""

from collections import defaultdict

from sffl.scoring import band_points

DEFAULT_K = 5
MIN_WEEKS = 4


def player_folds(lines, k=DEFAULT_K):
    """Deterministic disjoint player-id folds. Sorted, then dealt round-robin.

    Deterministic on purpose: a random split makes a rerun disagree with itself,
    and this measurement decides whether a curve ships.
    """
    players = sorted({ln.player_id for ln in lines})
    folds = [set() for _ in range(k)]
    for i, pid in enumerate(players):
        folds[i % k].add(pid)
    return folds


def realized(lg, weeks, stat):
    """A player's TRUE expected banded value: mean(band(week)), not band(mean).

    This is the quantity the curve is trying to predict, and the reason the
    curves exist at all - E[band(X)] != band(E[X]).
    """
    table = lg.bands[stat]
    vals = [w.stats.get(stat, 0.0) for w in weeks]
    return sum(band_points(table, v) for v in vals) / len(vals)


def cross_validate(lg, lines, builder, k=DEFAULT_K, min_weeks=MIN_WEEKS):
    """Per-stat MAE of `builder`'s curves, cross-validated by player.

    `builder(lg, lines)` returns {stat: [(mean, expected), ...]}.
    Returns {stat: {"mae": float, "n": int}} - n is how many held-out player
    predictions the MAE is over, which is as important as the MAE itself when
    a stat has four players.
    """
    from sffl.calibrate import STAT_POSITIONS, expected_points

    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)

    errs = defaultdict(list)
    for fold in player_folds(lines, k):
        fit_lines = [ln for ln in lines if ln.player_id not in fold]
        curves = builder(lg, fit_lines)
        for pid in fold:
            weeks = by_player[pid]
            if len(weeks) < min_weeks:
                continue
            pos = weeks[0].pos
            for stat in lg.bands:
                if pos not in STAT_POSITIONS[stat]:
                    continue
                curve = curves.get(stat) or []
                if not curve:
                    continue
                vals = [w.stats.get(stat, 0.0) for w in weeks]
                mean = sum(vals) / len(vals)
                errs[stat].append(
                    abs(expected_points(curve, mean) - realized(lg, weeks, stat)))

    return dict((s, {"mae": sum(e) / len(e), "n": len(e)})
                for s, e in errs.items() if e)

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

THE PREDICTOR MUST MATCH WHAT SHIPS. There are two production consumers of a
curve, and they do not predict the same way:
  - `pool.score_season_calibrated` (the AUCTION BOARD path) interpolates the
    raw curve with `calibrate.expected_points` - see `predict_raw` below.
  - `pool.score_week` (the WEEKLY path - start/sit, waivers) runs the curve
    through `pool._calibrated_band_value` first, which builds a monotone
    envelope over the anchors before interpolating - see `predict_weekly`
    below. `pool._monotone_envelope`'s own docstring records that the real
    curves are NOT monotone (a 21.0 yd/game rush anchor pays MORE than a
    25.7 yd/game one on real data), and the envelope corrects much of that
    at consumption time.
`realized()` above is `mean(band(weekly))` - a WEEKLY quantity - so the
predictor this harness judges against by default is `predict_weekly`, the
same one `score_week` actually uses. Scoring against raw interpolation
instead would credit a monotonicity-enforcing candidate (e.g. isotonic
regression) for fixing noise the envelope has already fixed at consumption
time, and could invert the experiment's conclusion. `predict_raw` remains
available, explicitly, for anyone who wants to judge the board path instead
- but a caller must say which one produced a given number: `cross_validate`
stamps every returned row with `"predictor": predict.__name__` for exactly
that reason.
"""

from collections import defaultdict

from sffl.calibrate import MIN_WEEKS, STAT_POSITIONS, expected_points
from sffl.pool import _calibrated_band_value
from sffl.scoring import band_points

DEFAULT_K = 5


def predict_weekly(lg, stat, curve, mean):
    """The production WEEKLY predictor - what `pool.score_week` actually
    calls. Builds a monotone envelope over `curve`'s anchors before
    interpolating, correcting the intra-span noise and both seam bugs
    documented on `pool._calibrated_band_value`. THE DEFAULT for
    `cross_validate`, because `realized()` is a weekly quantity and this is
    the weekly consumer.
    """
    return _calibrated_band_value(lg, stat, curve, mean)


def predict_raw(lg, stat, curve, mean):
    """The production AUCTION-BOARD predictor - what
    `pool.score_season_calibrated` actually calls: raw linear interpolation
    over `curve`, with no monotonicity correction. Kept available, explicit,
    for anyone who wants to judge the board path instead of the weekly one -
    never used unless a caller passes it as `predict`.
    """
    return expected_points(curve, mean)


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


def cross_validate(lg, lines, builder, k=DEFAULT_K, min_weeks=MIN_WEEKS,
                    predict=predict_weekly):
    """Per-stat MAE of `builder`'s curves, cross-validated by player.

    `builder(lg, lines)` returns {stat: [(mean, expected), ...]}.
    `predict(lg, stat, curve, mean) -> float` turns one of those curves into
    a single prediction. Defaults to `predict_weekly` - the SAME function
    `pool.score_week` uses in production - because `realized()` (the ground
    truth this is scored against) is a weekly quantity. Pass `predict_raw`
    explicitly to judge the auction-board path instead; see the module
    docstring for why the two are not interchangeable and why the default
    matters.

    Returns {stat: {"mae": float or None, "n": int, "empty_curve_folds": int,
    "predictor": str}}:
      - "n" is how many held-out player predictions the MAE is over, which is
        as important as the MAE itself when a stat has four players.
      - "mae" is None when n == 0 - there is nothing to average, and a 0.0
        would silently read as a perfect score.
      - "empty_curve_folds" counts folds (out of k) where `builder` returned
        no curve at all for this stat, so that fold's holdout players for
        this stat could not be scored and are absent from "n" with no other
        signal. This matters most for stats with few players (e.g. def_pa),
        where an empty fold is a realistic outcome, not a bug.
      - "predictor" is `predict.__name__` - stamped onto every row so a
        table of MAEs can never be shown, saved, or compared without saying
        which predictor produced it.

    EVERY stat in `lg.bands` is present in the result, even with n=0. Two
    builders must be compared over populations the caller can see are the
    same size - a stat silently missing from one builder's output and not
    the other's would let a comparison go unnoticed rather than flagged.

    `min_weeks` filters which HELD-OUT players are scored; it is
    deliberately not forwarded to `builder`, whose own min-weeks filtering
    (if any) governs which players its curves are fit from. The two are
    independent knobs by design - a candidate builder may legitimately fit
    on a different minimum than the one this harness scores against.
    """
    for stat in lg.bands:
        if stat not in STAT_POSITIONS:
            raise ValueError(
                "stat {0} in lg.bands has no position mapping".format(stat))

    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)

    errs = defaultdict(list)
    empty_curve_folds = defaultdict(int)
    for fold in player_folds(lines, k):
        fit_lines = [ln for ln in lines if ln.player_id not in fold]
        curves = builder(lg, fit_lines)
        for stat in lg.bands:
            if not curves.get(stat):
                empty_curve_folds[stat] += 1
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
                    abs(predict(lg, stat, curve, mean) - realized(lg, weeks, stat)))

    result = {}
    for stat in lg.bands:
        e = errs.get(stat, [])
        result[stat] = {
            "mae": (sum(e) / len(e)) if e else None,
            "n": len(e),
            "empty_curve_folds": empty_curve_folds.get(stat, 0),
            "predictor": predict.__name__,
        }
    return result

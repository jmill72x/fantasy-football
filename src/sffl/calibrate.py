"""Measure what banded scoring really yields, instead of assuming.

score_season approximates a season by banding the per-game mean. The honest
quantity is the EXPECTED banded value across a player's actual weeks. For every
banded stat this module builds a curve from real weekly data:

    per-game mean  ->  mean of band(weekly value) across that player's weeks

Consumers interpolate the curve instead of calling band_points on the mean.
"""

import math
from collections import defaultdict
from typing import Dict, List, Set, Tuple

import yaml

from sffl.scoring import band_points

MIN_WEEKS = 4

# Floor on a player's per-stat mean before his weeks contribute residuals to
# the pool (see _pooled_residuals / build_curves_pooled below). One unit in
# the stat's own scale (a yard, a catch, a completion, a point allowed) is
# small next to the league's own band floors - the lowest yardage band starts
# at 50 - so this excludes only players whose usage is so marginal that a
# single incidental play would dominate the ratio r = value / mean and
# distort the pooled distribution with an artifact of near-zero division,
# not real scatter. It is NOT a usage cutoff; report the fraction it
# excludes per stat rather than tuning it away.
MIN_MEAN_FLOOR = 1.0

# Bounds on how many points build_curves_pooled puts in a stat's grid. The
# floor keeps a thin/narrow-range stat (e.g. 4 defenses) from collapsing to
# 1-2 points; the ceiling keeps a wide-range stat from producing an unwieldy
# curve file. Neither bound was hit by every stat in the 2025 data - see
# _stat_grid for the density rule that usually decides the count first.
GRID_MIN_POINTS = 5
GRID_MAX_POINTS = 200

# Mapping of banded stat names to the positions that can produce them.
# This filters players to only contribute their relevant stats, avoiding
# silent contamination. Example: def_pa/def_ya have a 0-yard floor with
# maximum points (6), so a non-defense player's default 0.0 would yield 6,
# creating a false anchor in the defense curve.
STAT_POSITIONS = {
    "pass_yds": {"QB", "TQB"},
    "pass_cmp": {"QB", "TQB"},
    "rush_yds": {"QB", "TQB", "RB", "WR", "TE"},
    "rec_yds": {"RB", "WR", "TE"},
    "rec_ct": {"RB", "WR", "TE"},
    "def_pa": {"DST"},
    "def_ya": {"DST"},
}  # type: Dict[str, Set[str]]


def build_curves(lg, lines, min_weeks=MIN_WEEKS):
    """Return {stat: [(mean, expected_points), ...]} sorted by mean."""
    # Validate that all banded stats have position mappings.
    for stat in lg.bands:
        if stat not in STAT_POSITIONS:
            raise ValueError("stat {0} in lg.bands has no position mapping".format(stat))

    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)

    points = defaultdict(list)  # type: Dict[str, List[Tuple[float, float]]]
    for _, weeks in by_player.items():
        if len(weeks) < min_weeks:
            continue
        # Get position from first week (all weeks for same player have same position).
        player_pos = weeks[0].pos
        for stat, table in lg.bands.items():
            # Only include a player if their position can produce this stat.
            if player_pos not in STAT_POSITIONS[stat]:
                continue
            vals = [w.stats.get(stat, 0.0) for w in weeks]
            mean = sum(vals) / len(vals)
            expected = sum(band_points(table, v) for v in vals) / len(vals)
            points[stat].append((mean, expected))

    curves = {}
    for stat, pairs in points.items():
        merged = defaultdict(list)
        for mean, exp in pairs:
            merged[round(mean, 3)].append(exp)
        curves[stat] = sorted((m, sum(v) / len(v)) for m, v in merged.items())
    for stat in lg.bands:
        curves.setdefault(stat, [])
    return curves


def _pooled_residuals(lines, stat, min_mean=1e-6):
    """Multiplicative residuals r = weekly_value / player_mean, pooled across players.

    This is the estimator this module is built around. `band()` is known
    exactly - it is a table in the league profile - so the only unknown is
    how a player's week scatters around his own mean. A player averaging 20
    yards who varies +/-50% and one averaging 200 who varies +/-50% produce
    the SAME residuals (0.5, 1.5, ...): dividing out each player's own mean
    is what makes it valid to pool his weeks with everyone else's into one
    shared distribution. That is also what lets more data help here, unlike
    build_curves: an extra player's weeks sharpen the shared residual
    distribution instead of adding one more individual anchor to interpolate
    through.

    Players whose mean is below `min_mean` are skipped entirely (see
    MIN_MEAN_FLOOR): near zero, r blows up on a single incidental play and
    the ratio measures division instability, not scatter.
    """
    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)

    residuals = []
    for weeks in by_player.values():
        vals = [w.stats.get(stat, 0.0) for w in weeks]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        if mean < min_mean:
            continue
        residuals.extend(v / mean for v in vals)
    return residuals


def _stat_grid(bands, means, min_points=GRID_MIN_POINTS, max_points=GRID_MAX_POINTS):
    """Choose grid points spanning `means`, dense enough not to skip a band.

    The grid is derived from the data, not hardcoded: its endpoints are the
    observed min/max player mean for this stat (expected_points clamps
    outside them, so this is the curve's whole usable domain). Its spacing
    is derived from the league profile: half the narrowest FINITE band width
    for this stat (the last band is open-ended by convention - see
    band_points - and excluded from that computation), which guarantees at
    least two grid points fall inside the tightest band anywhere in the
    observed range, so linear interpolation between consecutive anchors can
    never step clean over a band. GRID_MIN_POINTS/GRID_MAX_POINTS then only
    correct the extremes: a thin stat (few players, narrow range) from
    collapsing to 1-2 points, and a wide stat from producing an unwieldy file.
    """
    lo, hi = min(means), max(means)
    if hi <= lo:
        return [lo]

    finite_widths = [high - low + 1 for low, high, _pts in bands[:-1]]
    if finite_widths:
        step = min(finite_widths) / 2.0
    else:
        step = (hi - lo) / float(min_points - 1)

    n = int(math.ceil((hi - lo) / step)) + 1
    n = max(n, min_points)
    n = min(n, max_points)
    return [lo + i * (hi - lo) / (n - 1) for i in range(n)]


def build_curves_pooled(lg, lines, min_weeks=MIN_WEEKS, grid=None):
    """Same shape as build_curves, estimated by pooling residuals instead.

    build_curves gives every qualifying player exactly one anchor point - his
    own (mean, realized) pair - and interpolates straight lines through them,
    so each additional player is one more individual noisy season for the
    curve to chase. This is the opposite bet: band() is known exactly, so the
    only thing to estimate is how a player's weeks scatter around his own
    mean. _pooled_residuals estimates that scatter from EVERY qualifying
    week of EVERY qualifying player at once (see its docstring for why
    pooling is valid), and this function then evaluates
    E[band(X) | mean=m] ~= mean over pooled residuals of band(m * r)
    at a grid of means (see _stat_grid). More weekly rows sharpen the shared
    residual distribution rather than adding anchors to chase.

    The result is smooth and non-decreasing by construction: band() is
    non-decreasing and every residual is > 0, so m1 < m2 implies
    m1 * r <= m2 * r for every pooled r, hence band(m1 * r) <= band(m2 * r)
    and the average over residuals preserves that order.

    `grid`, if given, overrides the derived grid (mainly for tests); the
    normal path derives it per stat from the data via _stat_grid.
    """
    for stat in lg.bands:
        if stat not in STAT_POSITIONS:
            raise ValueError("stat {0} in lg.bands has no position mapping".format(stat))

    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)

    curves = {}
    for stat, table in lg.bands.items():
        eligible = [
            weeks for weeks in by_player.values()
            if len(weeks) >= min_weeks and weeks[0].pos in STAT_POSITIONS[stat]
        ]
        if not eligible:
            curves[stat] = []
            continue

        means = [sum(w.stats.get(stat, 0.0) for w in weeks) / len(weeks) for weeks in eligible]
        eligible_lines = [w for weeks in eligible for w in weeks]
        residuals = _pooled_residuals(eligible_lines, stat, min_mean=MIN_MEAN_FLOOR)
        if not residuals:
            curves[stat] = []
            continue

        stat_grid = grid if grid is not None else _stat_grid(table, means)
        n = len(residuals)
        curves[stat] = [
            (m, sum(band_points(table, m * r) for r in residuals) / n)
            for m in stat_grid
        ]

    return curves


def _pava(points):
    """Pooled Adjacent Violators: the least-squares monotone fit to `points`.

    `points` is [(x, y), ...] sorted by x. Returns the same x's with a
    non-decreasing y. Where the input violates monotonicity, the violating run
    is replaced by its average - which is exactly the regularisation this is
    for: a dip caused by one player's noisy season gets pooled with its
    neighbours instead of being drawn through.

    Pure stdlib; numpy and scipy are not installed and must not be added.
    """
    blocks = []  # (sum_y, weight, last_x_index)
    for i, (_x, y) in enumerate(points):
        blocks.append([float(y), 1.0, i])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s2, w2, _ = blocks.pop()
            blocks[-1][0] += s2
            blocks[-1][1] += w2
            blocks[-1][2] = i
    out = []
    idx = 0
    for total, weight, _last in blocks:
        avg = total / weight
        for _ in range(int(weight)):
            out.append((points[idx][0], avg))
            idx += 1
    return out


def build_curves_isotonic(lg, lines, min_weeks=MIN_WEEKS):
    """Same input as build_curves, but fitted monotone rather than interpolated.

    WHY. build_curves draws straight lines through every player's point, so each
    additional player gives the curve one more noisy season to chase - which is
    why adding the held-back data made it worse. Monotonicity is a regulariser
    that costs nothing in truth: band() is non-decreasing, so E[band(X)] is
    non-decreasing in E[X], and a curve that respects that cannot follow a dip
    that only noise produced.
    """
    raw = build_curves(lg, lines, min_weeks)
    return dict((stat, _pava(pairs) if pairs else []) for stat, pairs in raw.items())


def expected_points(curve, mean):
    """Linear interpolation over the curve, clamped at both ends."""
    if not curve:
        return 0.0
    if mean <= curve[0][0]:
        return curve[0][1]
    if mean >= curve[-1][0]:
        return curve[-1][1]
    for i in range(1, len(curve)):
        x0, y0 = curve[i - 1]
        x1, y1 = curve[i]
        if x0 <= mean <= x1:
            if x1 == x0:
                return y1
            t = (mean - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return curve[-1][1]


def save_curves(curves, path):
    payload = {k: [[float(m), float(e)] for m, e in v] for k, v in curves.items()}
    with open(path, "w") as fh:
        yaml.safe_dump(payload, fh, default_flow_style=False, sort_keys=True)


def load_curves(path):
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    return {k: [(float(m), float(e)) for m, e in v] for k, v in raw.items()}

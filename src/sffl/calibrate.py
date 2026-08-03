"""Measure what banded scoring really yields, instead of assuming.

score_season approximates a season by banding the per-game mean. The honest
quantity is the EXPECTED banded value across a player's actual weeks. For every
banded stat this module builds a curve from real weekly data:

    per-game mean  ->  mean of band(weekly value) across that player's weeks

Consumers interpolate the curve instead of calling band_points on the mean.
"""

from collections import defaultdict
from typing import Dict, List, Tuple

import yaml

from sffl.scoring import band_points

MIN_WEEKS = 4


def build_curves(lg, lines, min_weeks=MIN_WEEKS):
    """Return {stat: [(mean, expected_points), ...]} sorted by mean."""
    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)

    points = defaultdict(list)  # type: Dict[str, List[Tuple[float, float]]]
    for _, weeks in by_player.items():
        if len(weeks) < min_weeks:
            continue
        for stat, table in lg.bands.items():
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

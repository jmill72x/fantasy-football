"""Merge several analysts' projections into one consensus record plus a spread.

The spread is kept deliberately. Scoring bands are convex, so disagreement about
a player carries information his mean does not - and no vendor publishes it.
"""

from collections import defaultdict
from typing import List

from sffl.schema import PlayerProjection


def _stdev(values):
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return var ** 0.5


def merge(projections, resolver=None):
    """Group by player key and average each stat across the sources that report it."""
    groups = defaultdict(list)
    for p in projections:
        key = p.key() if resolver is None else (
            resolver.resolve(p.name, p.team, p.pos) or p.key())
        groups[key].append(p)

    out = []  # type: List[PlayerProjection]
    for _, members in groups.items():
        first = members[0]
        by_stat = defaultdict(list)
        for m in members:
            for stat, val in m.stats.items():
                if stat.startswith("_"):
                    continue
                by_stat[stat].append(val)

        stats = {}
        for stat, vals in by_stat.items():
            stats[stat] = sum(vals) / len(vals)
            stats["_spread_" + stat] = _stdev(vals)
        stats["_n_sources"] = float(len(members))

        out.append(PlayerProjection(
            name=first.name, team=first.team, pos=first.pos,
            source="consensus", source_year=first.source_year,
            games=sum(m.games for m in members) / len(members),
            stats=stats, raw_name=first.raw_name, set_name=None,
        ))
    out.sort(key=lambda p: p.name)
    return out

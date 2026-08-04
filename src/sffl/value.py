"""Replacement level and value over replacement.

RB, WR and TE form ONE pool - they are the same position in this league and
compete for the same five flexible lineup slots. TQB, K and DST each have exactly
one starting slot per team.
"""

FLEX = ("RB", "WR", "TE")
POOLS = ("TQB", "FLEX", "K", "DST")


def _pool_of(pos):
    return "FLEX" if pos in FLEX else pos


def _sorted_points(pool, name):
    vals = [p.stats.get("_season_points", 0.0) for p in pool if _pool_of(p.pos) == name]
    return sorted(vals, reverse=True)


def _starter_counts(lg):
    return {"TQB": lg.teams, "FLEX": lg.teams * lg.flex_slots,
            "K": lg.teams, "DST": lg.teams}


def replacement_levels(lg, pool, policy):
    """Points threshold below which a player is freely available."""
    if policy not in ("starter", "draftable"):
        raise ValueError(
            "unknown replacement policy %r; expected 'starter' or 'draftable'" % policy)

    starters = _starter_counts(lg)
    if policy == "starter":
        depths = dict(starters)
    else:
        total_starters = sum(starters.values())
        drafted = lg.teams * lg.roster_size
        depths = {}
        for name, n in starters.items():
            depths[name] = int(round(drafted * (float(n) / total_starters)))

    levels = {}
    for name in POOLS:
        pts = _sorted_points(pool, name)
        idx = depths[name]
        levels[name] = pts[idx] if idx < len(pts) else (pts[-1] if pts else 0.0)
    return levels


def assign_vorp(lg, pool, levels):
    """Write stats['_vorp'] on every record. Never negative."""
    for p in pool:
        base = levels.get(_pool_of(p.pos), 0.0)
        p.stats["_vorp"] = max(0.0, p.stats.get("_season_points", 0.0) - base)

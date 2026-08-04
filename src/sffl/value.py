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


def _largest_remainder_allocation(lg, starters):
    """Allocate roster spots to pools using largest remainder method.

    This ensures depths sum exactly to lg.teams * lg.roster_size, handling
    the fact that proportional allocation often lands on .5 boundaries.

    Returns dict mapping pool names to allocated depths, guaranteed to sum
    to lg.teams * lg.roster_size.
    """
    total_starters = sum(starters.values())
    drafted = lg.teams * lg.roster_size

    # Calculate exact shares and separate into floor + fractional part
    allocations = {}
    remainders = []
    for name, n in starters.items():
        exact = drafted * (float(n) / total_starters)
        floor = int(exact)
        frac = exact - floor
        allocations[name] = floor
        if frac > 0:
            remainders.append((frac, name))

    # Distribute leftover units to pools with largest remainders.
    # Tie-break: larger starter count first (more fundamental to league), then name (deterministic).
    leftover = drafted - sum(allocations.values())
    remainders.sort(key=lambda x: (-x[0], -starters[x[1]], x[1]))
    for i in range(leftover):
        allocations[remainders[i][1]] += 1

    return allocations


def replacement_levels(lg, pool, policy):
    """Points threshold below which a player is freely available."""
    if policy not in ("starter", "draftable"):
        raise ValueError(
            "unknown replacement policy %r; expected 'starter' or 'draftable'" % policy)

    starters = _starter_counts(lg)
    if policy == "starter":
        depths = dict(starters)
    else:
        depths = _largest_remainder_allocation(lg, starters)

    levels = {}
    for name in POOLS:
        pts = _sorted_points(pool, name)
        idx = depths[name]
        if len(pts) == 0:
            # Empty pool: cannot compute a replacement level. Raise loudly.
            raise ValueError(
                "no players in pool %r; cannot compute replacement level" % name)
        elif idx < len(pts):
            # Pool is deep enough; use the exact replacement threshold.
            levels[name] = pts[idx]
        else:
            # Pool is shallower than depth index (e.g., only 50 FLEX available but need 61st).
            # Use the worst available player as a bounded degradation: the error is at most
            # the gap from the worst available to the true depth point, not unbounded to zero.
            levels[name] = pts[-1]
    return levels


def assign_vorp(lg, pool, levels):
    """Write stats['_vorp'] on every record. Never negative.

    Raises ValueError if a pool with players in the pool list is missing from levels.
    """
    # Determine which pools have players in the input pool.
    pools_with_players = set()
    for p in pool:
        pools_with_players.add(_pool_of(p.pos))

    # Verify all pools with players are in levels.
    for pool_name in pools_with_players:
        if pool_name not in levels:
            raise ValueError(
                "pool %r has players but is missing from replacement levels" % pool_name)

    # Assign VORP: points above replacement, floored at zero.
    for p in pool:
        pool_name = _pool_of(p.pos)
        base = levels[pool_name]  # Safe: we verified above.
        p.stats["_vorp"] = max(0.0, p.stats.get("_season_points", 0.0) - base)


def assign_dollars(lg, pool):
    """Distribute the league's surplus in proportion to VORP.

    Every roster spot costs at least $1, so teams * roster_size dollars are
    committed before anything else. What remains is allocated by VORP share.
    Returns the dollars-per-VORP-point rate.
    """
    total_vorp = sum(p.stats.get("_vorp", 0.0) for p in pool)
    rate = (lg.surplus() / total_vorp) if total_vorp > 0 else 0.0
    for p in pool:
        p.stats["_dollars"] = 1.0 + p.stats.get("_vorp", 0.0) * rate
    return rate

"""Replacement level and value over replacement.

RB, WR and TE form ONE pool - they are the same position in this league and
compete for the same five flexible lineup slots. TQB, K and DST each have exactly
one starting slot per team.

Any pool named in the league YAML's `flat_priced_pools` (see `LeagueProfile.
flat_priced_pools` in `sffl.league`) is priced at a fixed dollar amount instead
of by VORP: `assign_vorp` silently zeroes `_vorp` for its members and
`assign_dollars` writes the configured price directly, excluding them from the
surplus split entirely.
"""

FLEX = ("RB", "WR", "TE")
POOLS = ("TQB", "FLEX", "K", "DST")


def _pool_of(pos):
    return "FLEX" if pos in FLEX else pos


def _sorted_points(pool, name):
    vals = [p.stats["_season_points"] for p in pool if _pool_of(p.pos) == name]
    return sorted(vals, reverse=True)


def _sorted_flex_records(pool):
    """FLEX pool player records (RB/WR/TE), sorted descending by points.

    Unlike _sorted_points, this keeps the records (not just the point
    values) because flex starter selection below has to know each player's
    position to enforce the RB and WR/TE floors.
    """
    recs = [p for p in pool if _pool_of(p.pos) == "FLEX"]
    return sorted(recs, key=lambda p: p.stats["_season_points"], reverse=True)


def _select_flex_starters(lg, recs, depth):
    """Select the depth-sized flex starting set, respecting the league's
    lineup floors: each of lg.teams teams must start at least 1 RB and at
    least 1 WR/TE (WR and TE are one position here and share a single
    floor - never one floor each).

    `recs` must already be sorted descending by points; `depth` must be
    strictly less than len(recs) (the caller handles the shallow-pool case
    separately). Returns the set of selected indices into `recs`. Indices
    are used - not object identity - because two player records can
    compare equal on points.

    This same selection is used for both the "starter" and "draftable"
    replacement policies (only `depth` differs between them): it is the
    same "who is above replacement" question asked at two depths, and at
    draftable's much greater depth the floors simply never bind.
    """
    teams = lg.teams
    if depth < 2 * teams:
        raise ValueError(
            "flex starter depth %d is less than 2 * lg.teams (%d): the "
            "league requires %d RB-floor slots plus %d WR/TE-floor slots, "
            "which cannot both fit in a %d-player flex lineup"
            % (depth, 2 * teams, teams, teams, depth))

    rb_idx = [i for i, p in enumerate(recs) if p.pos == "RB"]
    wrte_idx = [i for i, p in enumerate(recs) if p.pos in ("WR", "TE")]

    if len(rb_idx) < teams:
        raise ValueError(
            "flex pool has only %d RB but the league requires %d (1 RB "
            "floor per team x %d teams)" % (len(rb_idx), teams, teams))
    if len(wrte_idx) < teams:
        raise ValueError(
            "flex pool has only %d WR/TE but the league requires %d (1 "
            "WR/TE floor per team x %d teams)" % (len(wrte_idx), teams, teams))

    # Reserve the top `teams` at each floor position...
    selected = set(rb_idx[:teams])
    selected.update(wrte_idx[:teams])

    # ...then fill whatever is left with the best remaining players
    # regardless of position.
    need = depth - len(selected)
    for i in range(len(recs)):
        if need <= 0:
            break
        if i not in selected:
            selected.add(i)
            need -= 1
    return selected


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

    unscored = [p.name for p in pool if "_season_points" not in p.stats]
    if unscored:
        raise ValueError(
            "%d pool player(s) have no _season_points (e.g. %r); the pool has "
            "not been scored. Call build_pool or score_season_calibrated first."
            % (len(unscored), unscored[0]))

    starters = _starter_counts(lg)
    if policy == "starter":
        depths = dict(starters)
    else:
        depths = _largest_remainder_allocation(lg, starters)

    levels = {}
    for name in POOLS:
        if name == "FLEX":
            recs = _sorted_flex_records(pool)
            idx = depths[name]
            if len(recs) == 0:
                # Empty pool: cannot compute a replacement level. Raise loudly.
                raise ValueError(
                    "no players in pool %r; cannot compute replacement level" % name)
            elif idx < len(recs):
                # Pool is deep enough to fill every flex starter slot -
                # enforce the RB and WR/TE lineup floors when choosing who
                # starts, then take the best player left out of that set.
                selected = _select_flex_starters(lg, recs, idx)
                levels[name] = next(
                    recs[i].stats["_season_points"]
                    for i in range(len(recs)) if i not in selected)
            else:
                # Pool is shallower than depth index (e.g., only 50 FLEX
                # available but need the 61st). Same bounded degradation as
                # below - the floors don't apply when there aren't enough
                # players to fill starters at all, only to choose among them.
                levels[name] = recs[-1].stats["_season_points"]
            continue

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
        if pool_name in lg.flat_priced_pools:
            # Fungible by league convention - see flat_priced_pools in the
            # league YAML. Zero VORP keeps them out of the surplus split.
            p.stats["_vorp"] = 0.0
            continue
        p.stats["_vorp"] = max(0.0, p.stats.get("_season_points", 0.0) - base)


def assign_dollars(lg, pool):
    """Distribute the league's surplus in proportion to VORP.

    Every roster spot costs at least $1, so teams * roster_size dollars are
    committed before anything else. What remains is allocated by VORP share.
    Returns the dollars-per-VORP-point rate.
    """
    unvalued = [p.name for p in pool if "_vorp" not in p.stats]
    if unvalued:
        raise ValueError(
            "%d pool player(s) have no _vorp (e.g. %r); call assign_vorp "
            "before assign_dollars." % (len(unvalued), unvalued[0]))

    total_vorp = sum(p.stats["_vorp"] for p in pool)
    rate = (lg.surplus() / total_vorp) if total_vorp > 0 else 0.0
    for p in pool:
        flat = lg.flat_priced_pools.get(_pool_of(p.pos))
        if flat is not None:
            p.stats["_dollars"] = float(flat)
        else:
            p.stats["_dollars"] = 1.0 + p.stats["_vorp"] * rate
    return rate

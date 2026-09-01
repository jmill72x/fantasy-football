"""The best legal starting lineup, and what one more player would add to it.

PURE ON PURPOSE. This module takes `Candidate` tuples rather than
`PlayerProjection`, performs no I/O, and knows nothing about scoring. It is the
piece with real logic in it, so it must be exhaustively testable with no
fixtures and no network - see the brute-force test.

WHY THE OPTIMUM IS A SUBSET, NOT AN ASSIGNMENT. The flex-eligible slots
(RB, WR/TE, FLEX x3) are interchangeable: every legal lineup uses exactly five
players from the RB/WR/TE pool with at least one RB and at least one WR or TE,
and its total is the sum of their points. The slot LABELS do not affect the
total, so maximizing over assignments is the same as choosing the best legal
five-player subset. That is why a subset search is exact here and not a
heuristic.
"""

from collections import namedtuple

# `team` is OPTIONAL (defaults to "") and unused by every function in this
# module - `best_lineup`/`delta` only ever read `.pos`/`.points`/`.name`, and
# it has NO EFFECT on which lineup is chosen. It exists purely so a CALLER
# (`sffl.cli._cmd_alert`) can round-trip a candidate's team through to
# `sffl.alert._start_sit_diff`, which needs (name, pos, team) - not name
# alone, and not even (name, pos) - to tell two rostered picks that share a
# display name apart (an NFL team rostered for both TQB and DST is a real,
# reproduced case; two different NFL players sharing a name is a real,
# documented one - see identity.player_key, which this field lets a caller
# reconstruct for a Candidate the same way it already can for a
# PlayerProjection). Added with a default so every existing call site that
# never mentions `team` - this module's own tests included - is unaffected.
Candidate = namedtuple("Candidate", "name pos points team", defaults=("",))
LineupResult = namedtuple("LineupResult", "slots total")

_FLEX = ("RB", "WR", "TE")


def _sorted(cands):
    """Highest points first, name ascending as the tiebreak.

    Deterministic ties matter: the weekly diff reports what changed since the
    last run, and two runs that disagree about an identical roster would report
    changes that did not happen.
    """
    return sorted(cands, key=lambda x: (-x.points, x.name))


def _best_flex_five(cands, n, need):
    """Best `n`-player subset of the flex pool meeting the `need` floors.

    `need` maps a label to the set of positions that satisfies it, e.g.
    {"rb": {"RB"}, "wrte": {"WR", "TE"}}.
    """
    ranked = _sorted(cands)
    chosen = list(ranked[:n])
    for _label, positions in sorted(need.items()):
        if any(x.pos in positions for x in chosen):
            continue
        replacement = next((x for x in ranked
                            if x.pos in positions and x not in chosen), None)
        if replacement is None:
            continue
        # Drop the cheapest chosen player who is not the sole satisfier of
        # another floor, so repairing one floor cannot break another.
        droppable = []
        for x in chosen:
            others = [c for c in chosen if c is not x]
            if all(any(o.pos in p for o in others)
                   for _l, p in need.items() if any(c.pos in p for c in chosen)):
                droppable.append(x)
        if not droppable:
            droppable = list(chosen)
        worst = _sorted(droppable)[-1]
        chosen[chosen.index(worst)] = replacement
    return chosen


def best_lineup(lg, candidates):
    """The highest-scoring legal lineup, as (slots, total).

    `slots` is in league order and carries None for any slot the roster cannot
    fill - an unfillable slot is reported, never silently skipped and never
    filled with an ineligible player.
    """
    remaining = list(candidates)
    flex_slots = [(s, e) for s, e in lg.lineup if set(e) & set(_FLEX)]
    fixed_slots = [(s, e) for s, e in lg.lineup if not set(e) & set(_FLEX)]

    filled = {}
    for slot, elig in fixed_slots:
        pick = next((x for x in _sorted(remaining) if x.pos in elig), None)
        filled[slot] = pick
        if pick is not None:
            remaining.remove(pick)

    pool = [x for x in remaining if x.pos in _FLEX]
    need = {}
    for slot, elig in flex_slots:
        if set(elig) != set(_FLEX):
            need[slot] = set(elig)
    picked = _best_flex_five(pool, len(flex_slots), need)

    # Assign narrowest-eligibility slots first (RB-only, then WR/TE-only,
    # then the fully-open FLEXes). A wide slot filled ahead of a narrow one
    # can claim the only candidate that satisfies the narrow slot, leaving it
    # empty and silently dropping a chosen player - nothing about `lg.lineup`
    # guarantees narrow-before-wide declaration order, so the assignment
    # order must not depend on it either. See
    # test_the_result_does_not_depend_on_the_order_slots_are_declared.
    picked_sorted = _sorted(picked)
    for slot, elig in sorted(flex_slots, key=lambda se: len(se[1])):
        pick = next((x for x in picked_sorted if x.pos in elig), None)
        filled[slot] = pick
        if pick is not None:
            picked_sorted.remove(pick)

    slots = [(s, filled.get(s)) for s, _e in lg.lineup]
    # sum()'s start defaults to int 0, so an empty/all-None roster would
    # return an int total - the brief specifies float.
    total = sum((x.points for _s, x in slots if x is not None), 0.0)
    return LineupResult(slots=slots, total=total)


def delta(lg, roster, addition):
    """How much `addition` would improve the optimal lineup. Never negative."""
    base = best_lineup(lg, roster).total
    with_add = best_lineup(lg, list(roster) + [addition]).total
    return max(0.0, with_add - base)


def best_add_drop(lg, roster, addition):
    """Which rostered player to release for `addition`, and the resulting gain.

    Returns `(drop, net)` - `drop` is the `Candidate` to release, or None
    when the roster is under `roster_size` and nobody need be released.

    WHY THIS EXISTS: the DROP, not the number. `--waivers` ranked additions
    and never said who to release, but this league caps the roster at 13 and
    every claim is a SWAP - so "pick up X" was advice that could not be
    acted on without a second decision the tool declined to make.

    **`net` is NOT a correction to `delta`, and this was measured before it
    was claimed.** An earlier version of this docstring asserted that `delta`
    overstates the gain by charging nothing for the released player. That is
    false at this league's geometry: 8 lineup slots against a 13-man roster
    means that after adding a candidate at least 6 players sit outside the
    optimal lineup, so SOME release always costs zero and `net == delta`
    exactly. Checked over 3000 randomised rosters at sizes 9, 11 and 13:
    3000 equal, 0 different (see
    test_the_drop_is_free_at_this_league_s_roster_size). `net` is returned
    anyway because it is what a caller should display and because the
    identity is a property of THESE numbers, not a law - a league with a
    deeper lineup or a shallower bench would break it, and then this
    function is already right.

    So the real content is the tiebreak among releases that all cost zero
    THIS WEEK. Two rules:

    - EVERY rostered player is tried, starters included. Releasing a starter
      is occasionally correct (two players, one slot) and a rule of thumb
      that excluded them would hide those. The optimizer decides.
    - Ties break to the LOWEST-scoring player. Positional necessity needs no
      special case: dropping a lone kicker leaves the K slot unfilled and the
      optimizer sees that cost directly, so it never proposes it.

    WHAT THIS CANNOT SEE: bye weeks, and next week. Every zero-cost release
    is equal to a one-week optimizer, and they are not equal in a season.
    Callers must present the drop as the cheapest release THIS WEEK, never as
    an unconditional recommendation.
    """
    base = best_lineup(lg, roster).total
    best_total = None
    best_drop = None
    # An open spot is not a drop. Only offered when the roster is genuinely
    # under the cap - `roster_size` is the league's own number, never 13
    # hard-coded here.
    if len(roster) < lg.roster_size:
        best_total = best_lineup(lg, list(roster) + [addition]).total
        best_drop = None
    for i, dropped in enumerate(roster):
        kept = list(roster[:i]) + list(roster[i + 1:]) + [addition]
        total = best_lineup(lg, kept).total
        if (best_total is None or total > best_total
                or (total == best_total and best_drop is not None
                    and dropped.points < best_drop.points)):
            best_total = total
            best_drop = dropped
    return best_drop, max(0.0, best_total - base)

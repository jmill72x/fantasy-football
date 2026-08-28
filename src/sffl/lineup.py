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

Candidate = namedtuple("Candidate", "name pos points")
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

    picked_sorted = _sorted(picked)
    for slot, elig in flex_slots:
        pick = next((x for x in picked_sorted if x.pos in elig), None)
        filled[slot] = pick
        if pick is not None:
            picked_sorted.remove(pick)

    slots = [(s, filled.get(s)) for s, _e in lg.lineup]
    total = sum(x.points for _s, x in slots if x is not None)
    return LineupResult(slots=slots, total=total)


def delta(lg, roster, addition):
    """How much `addition` would improve the optimal lineup. Never negative."""
    base = best_lineup(lg, roster).total
    with_add = best_lineup(lg, list(roster) + [addition]).total
    return max(0.0, with_add - base)

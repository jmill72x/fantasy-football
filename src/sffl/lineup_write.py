"""Plan the swaps that turn a CBS lineup into a target one. PURE - no I/O.

WHY A PLANNER SEPARATE FROM THE DRIVER. "What exactly am I about to do, in
what order" is worth computing, printing and reviewing BEFORE a browser is
opened, on a command that edits a real team. This module produces that and
touches nothing, so it is cheap to test exhaustively; the driver stays thin.

CORRECTED 2026-09-01, after a live run. An earlier version of this docstring
said CBS had NO SAVE BUTTON and that a half-finished sequence would leave a
mixed lineup with nothing to roll back. That was wrong, and wrong in the
frightening direction: the save control is the SAME "Set Lineup" button that
enters edit mode, which a keyword search for save/submit/apply/done does not
match. Swaps are client-side until that button is pressed a second time, so
the commit IS atomic - every swap lands together or none does. The driver
correspondingly stages all swaps, verifies the whole arrangement, and only
then commits.
"""

from collections import namedtuple

# One player as CBS's edit-mode page presents him. `player_id` is CBS's own,
# lifted from the row's playerpage link - the join key, so no name matching
# is involved anywhere in the write path. `starting` is whether the row sits
# above CBS's RESERVES marker.
LineupSlot = namedtuple("LineupSlot", "player_id name pos starting")

# One click-pair. CBS's edit mode swaps two players when their `moveSource`
# buttons are clicked in turn, so a move is always a PAIR, never a single
# player "sent to the bench" - there is no bench to send him to that does not
# also bring someone up.
Swap = namedtuple("Swap", "bench_id bench_name promote_id promote_name")


def plan_swaps(current, target_ids):
    """Swaps that turn `current` into a lineup whose starters are `target_ids`.

    `current` is [LineupSlot]; `target_ids` is the set of player_ids that
    SHOULD be starting. Returns [Swap], empty when the lineup already matches.

    Raises ValueError if `target_ids` names a player who is not on the roster
    at all, or if the target and current starter counts differ - both mean the
    caller computed the target against a different roster than the page shows,
    and swapping blind would bench a real player to promote a phantom.

    Pairing is DETERMINISTIC: benchings and promotions are each ordered by the
    page's own row order, then zipped. Two runs on the same inputs produce the
    same clicks in the same order, which is what makes a partial application
    diagnosable - "it stopped after step 2" means something specific.
    """
    by_id = dict((s.player_id, s) for s in current)
    unknown = [pid for pid in target_ids if pid not in by_id]
    if unknown:
        raise ValueError(
            "target lineup names %d player id(s) not on the roster page: %s - "
            "refusing to swap against a roster this page does not show"
            % (len(unknown), ", ".join(sorted(unknown))))

    starting_now = [s for s in current if s.starting]
    if len(target_ids) != len(starting_now):
        raise ValueError(
            "target lineup has %d starters but the page shows %d - refusing "
            "to apply a plan built against a different lineup shape"
            % (len(target_ids), len(starting_now)))

    to_bench = [s for s in current if s.starting and s.player_id not in target_ids]
    to_promote = [s for s in current
                  if not s.starting and s.player_id in target_ids]
    # Equal by construction once the counts above agree, but asserted rather
    # than assumed: an unequal zip would silently drop a swap and leave the
    # lineup one player short of the target while reporting success.
    if len(to_bench) != len(to_promote):
        raise ValueError(
            "internal: %d to bench against %d to promote"
            % (len(to_bench), len(to_promote)))
    return [Swap(b.player_id, b.name, p.player_id, p.name)
            for b, p in zip(to_bench, to_promote)]


def describe_plan(swaps):
    """The plan as text for a human to approve. Empty plan says so plainly."""
    if not swaps:
        return "  lineup already matches the target - no changes to make."
    out = []
    for i, s in enumerate(swaps, 1):
        out.append("  %d. BENCH   %-22s (id %s)" % (i, s.bench_name, s.bench_id))
        out.append("     START   %-22s (id %s)" % (s.promote_name, s.promote_id))
    out.append("")
    out.append("  %d swap(s), applied together. They are staged in the browser"
               % len(swaps))
    out.append("  and committed in ONE submit at the end, so a run that stops")
    out.append("  early sends nothing and leaves the CBS lineup untouched.")
    return "\n".join(out)


def verify_applied(current, target_ids):
    """(ok, wrong_starters, missing_starters) after a swap, from a fresh read.

    The driver calls this between steps. Comparing player IDS, never names or
    row order: CBS reorders rows as players move, so "row 3 changed" proves
    nothing, while an id set is exactly the claim being made.
    """
    now = set(s.player_id for s in current if s.starting)
    want = set(target_ids)
    return (now == want, sorted(now - want), sorted(want - now))

"""Rest-of-season trade valuation. PURE - no I/O, no network, no clock.

WHY A SEPARATE MODULE FROM `lineup`. `lineup` answers "who do I start THIS
WEEK", on one week's projected stat line. A trade is a claim about the
REMAINDER of the season, so every number here is a rest-of-season total and
the two must not be mixed: a player worth starting this week can be worth
less than his backup over the twelve weeks that follow, and vice versa.

WHY MARGINAL LINEUP VALUE AND NOT PROJECTED POINTS. A fourth running back's
points are largely unreachable - this league starts one RB and three FLEX,
so his production only counts when it displaces someone. Ranking trade
targets by raw projection therefore systematically overvalues depth at
positions you are already deep in, which is exactly the mistake that makes a
lopsided trade look fair. Every value here is the change in the OPTIMAL
LINEUP's rest-of-season total, which is the only thing that scores points.

THE APPROXIMATION, STATED UP FRONT. `best_lineup` over rest-of-season totals
picks one lineup and assumes you start it every remaining week. You do not:
byes and injuries force substitutions, and the real season is a sequence of
weekly optimisations. This overstates a starter's value relative to the
bench player who covers his bye - the direction matters, so `games_remaining`
below at least removes the bye from each player's own total rather than
pretending everyone plays every week. A full week-by-week simulation is the
honest version and is deliberately NOT attempted here; the spec called for
rest-of-season projections, and CBS supplies one aggregate, not 12 weeks.
"""

from sffl.lineup import Candidate, best_lineup

# The NFL regular season this league scores. Weeks 1-18; CBS's own season
# totals cover the same span (see poc/seed_weekly.py's docstring), so a
# rest-of-season count derived from it is on the same basis as the data.
LAST_REGULAR_WEEK = 18


def games_remaining(week, bye, last_week=LAST_REGULAR_WEEK):
    """How many games a player has LEFT, counting from `week` inclusive.

    `bye` is his team's bye week, or 0 when unknown. A bye that has not
    happened yet is one fewer game he will actually play, and dividing a
    rest-of-season total by an uncorrected week count would inflate his
    per-game line for every week of the rest of the season - the exact input
    the calibration curves are most sensitive to.

    A bye of 0 (CBS printed "--", or a free agent with no team) means
    UNKNOWN, and is treated as "no bye to skip" rather than guessed. That
    can overcount by one game out of a dozen; inventing a bye week could
    remove a game the player will really play, which is worse and silent.
    """
    if week > last_week:
        return 0
    left = last_week - max(week, 1) + 1
    if bye and week <= bye <= last_week:
        left -= 1
    return max(0, left)


def lineup_value(lg, candidates):
    """The optimal lineup's total over `candidates`. The unit everything uses."""
    return best_lineup(lg, list(candidates)).total


def acquisition_value(lg, roster, incoming):
    """Rest-of-season lineup points gained by ADDING `incoming`, never negative.

    Deliberately ignores the roster cap: this answers "what is he worth to
    me", which is the question a trade asks. What it costs to make room is
    `release_cost`, and `evaluate_trade` is where the two meet - a trade
    moves players both ways and does not consume a roster spot the way a
    waiver claim does.
    """
    base = lineup_value(lg, roster)
    return max(0.0, lineup_value(lg, list(roster) + [incoming]) - base)


def release_cost(lg, roster, outgoing):
    """Rest-of-season lineup points LOST by giving `outgoing` away.

    Zero for anyone the optimal lineup does not use - which is most of a
    bench, and is the whole reason a trade can be positive-sum. Matched by
    name, position and team, the same triple used everywhere else in this
    codebase, because two rostered players can share a display name (an NFL
    team held at both TQB and DST is the reproduced case).
    """
    key = (outgoing.name, outgoing.pos, outgoing.team)
    kept = [c for c in roster if (c.name, c.pos, c.team) != key]
    if len(kept) == len(roster):
        raise ValueError(
            "%r (%s, %s) is not on this roster - refusing to price a trade "
            "that gives away a player you do not have"
            % (outgoing.name, outgoing.pos, outgoing.team))
    return max(0.0, lineup_value(lg, roster) - lineup_value(lg, kept))


def evaluate_trade(lg, roster, give, get):
    """Net rest-of-season lineup change for the roster's owner. Signed.

    NOT `sum(acquisition_value) - sum(release_cost)`. Those are each computed
    against the CURRENT roster and do not compose: two receivers who each add
    4 points alone may add 5 together, because the second only displaces the
    first. The whole post-trade roster is optimised once, which is the only
    figure that survives contact with a two-for-two.

    A NEGATIVE result is returned as-is, not clamped. This is the one place
    in the module where the sign is the answer.
    """
    give_keys = set((c.name, c.pos, c.team) for c in give)
    kept = [c for c in roster if (c.name, c.pos, c.team) not in give_keys]
    missing = len(give) - (len(roster) - len(kept))
    if missing:
        raise ValueError(
            "%d of the %d players offered are not on this roster - refusing "
            "to price a trade that gives away players you do not have"
            % (missing, len(give)))
    return lineup_value(lg, kept + list(get)) - lineup_value(lg, roster)


def rank_targets(lg, roster, market, top=10):
    """League-wide acquisition targets, best first.

    `market` is [(Candidate, owner_label)] for players held by OTHER teams.
    Returns [(candidate, owner, gain)] sorted by gain descending, then by
    rest-of-season points descending, then name - the same tiebreak ladder
    the waiver board uses, and for the same reason: among players who add
    nothing to THIS lineup, the better player is the better target anyway.
    """
    scored = []
    for cand, owner in market:
        scored.append((cand, owner, acquisition_value(lg, roster, cand)))
    scored.sort(key=lambda t: (-t[2], -t[0].points, t[0].name))
    return scored[:top]


def draft_proposal(my_team, their_team, give, get, my_net, their_net):
    """A plain-text trade proposal for a HUMAN to review and send.

    Never sent by this code - `sffl trade` has no path to another manager,
    deliberately. A trade offer is a message to a real person in Jeff's
    league, and the tool's job stops at drafting it.

    States both sides' numbers, including when the counterparty comes out
    ahead. A proposal that quotes only the proposer's gain is one the
    recipient can check in thirty seconds and resent for the rest of the
    season; and if their side does not survive being written down, that is
    worth knowing BEFORE sending it.
    """
    def names(cs):
        return ", ".join("%s (%s)" % (c.name, c.pos) for c in cs) or "nobody"

    lines = [
        "To: %s" % their_team,
        "From: %s" % my_team,
        "",
        "Proposing:",
        "  You get:  %s" % names(give),
        "  I get:    %s" % names(get),
        "",
        "Rest-of-season starting-lineup points, under this league's scoring:",
        "  my side:    %+.2f" % my_net,
        "  your side:  %+.2f" % their_net,
        "",
    ]
    if their_net > 0 and my_net > 0:
        lines.append("Both lineups improve - different needs, not a discount.")
    elif their_net <= 0:
        lines.append(
            "This one is in my favour on paper (%+.2f to you). Sending it "
            "anyway in case the positional fit is worth more to you than the "
            "projection says - tell me what would make it work." % their_net)
    else:
        lines.append(
            "This one favours you on paper (%+.2f to %+.2f). I want the "
            "positional fit." % (their_net, my_net))
    return "\n".join(lines)

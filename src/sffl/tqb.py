"""Build Team QB units by summing a franchise's quarterbacks.

The league starts one TQB per team - the cumulative totals of every quarterback
on an NFL franchise. No vendor models this slot, so we construct it.
"""

from collections import defaultdict

from sffl.identity import NFL_TEAMS
from sffl.schema import PlayerProjection

PASSING_STATS = ("pass_att", "pass_cmp", "pass_yds", "pass_td", "pass_int",
                 "pass_2pt", "rush_yds", "rush_td", "rush_2pt")

MAX_GAMES = 17


def build_tqb(lg, players, set_name=None):
    """Return one TQB PlayerProjection per franchise found in `players`.

    When set_name is None, all quarterbacks must have set_name=None.
    If any quarterback has a non-None set_name, ValueError is raised with the
    distinct set names found. This prevents silent stat inflation from mixing
    multiple analyst projections of the same quarterback. For single-vendor
    datasets (all set_name=None), pass set_name=None or omit it.
    """
    by_team = defaultdict(list)

    # Check for mixed set_name values when set_name=None
    if set_name is None:
        non_none_sets = set()
        for p in players:
            if p.pos == "QB" and p.set_name is not None:
                non_none_sets.add(p.set_name)
        if non_none_sets:
            raise ValueError(
                f"set_name=None with multi-analyst data. "
                f"Found analyst sets: {sorted(non_none_sets)}. "
                f"Pass set_name=<name> to select one."
            )

    for p in players:
        if p.pos != "QB":
            continue
        if set_name is not None and p.set_name != set_name:
            continue
        if p.team not in NFL_TEAMS:
            # Not a real franchise - e.g. "FA" for a free agent/unrostered QB
            # in the vendor's projection set. A phantom 33rd TQB here would
            # shift every real franchise's ordinal rank downstream.
            continue
        by_team[p.team].append(p)

    out = []
    for team, qbs in by_team.items():
        stats = {}
        for field in PASSING_STATS:
            total = sum(q.stats.get(field, 0.0) for q in qbs)
            if total or any(field in q.stats for q in qbs):
                stats[field] = total
        games = min(MAX_GAMES, sum(q.games for q in qbs))
        out.append(PlayerProjection(
            name=team, team=team, pos="TQB",
            source=qbs[0].source, source_year=qbs[0].source_year,
            games=games, stats=stats, raw_name=team,
            set_name=set_name,
        ))
    out.sort(key=lambda t: t.team)
    return out

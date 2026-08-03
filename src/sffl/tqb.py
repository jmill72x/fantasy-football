"""Build Team QB units by summing a franchise's quarterbacks.

The league starts one TQB per team - the cumulative totals of every quarterback
on an NFL franchise. No vendor models this slot, so we construct it.
"""

from collections import defaultdict

from sffl.schema import PlayerProjection

PASSING_STATS = ("pass_att", "pass_cmp", "pass_yds", "pass_td", "pass_int",
                 "pass_2pt", "rush_yds", "rush_td", "rush_2pt")

MAX_GAMES = 17


def build_tqb(lg, players, set_name=None):
    """Return one TQB PlayerProjection per franchise found in `players`."""
    by_team = defaultdict(list)
    for p in players:
        if p.pos != "QB":
            continue
        if set_name is not None and p.set_name != set_name:
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

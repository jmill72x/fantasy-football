"""Turn a valued pool into render-ready rows.

Both artifacts render from this one list, so the PDF and the Excel can never
disagree about what a player is worth or which tier he sits in.

Tiers are natural breaks in dollar value within a position group, not fixed
bands. The question that matters at the table is "if I miss this player, what
does the next one cost" - which is exactly where the gaps are. A gap of $0 is
not a real break, so it never manufactures a tier boundary - see
assign_tiers() for the flat-priced-pool case (K, DST) this rules out.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional

import yaml

from sffl.value import _pool_of

DEFAULT_BYES = "leagues/nfl-byes-2026.yaml"
N_TIERS = 6


@dataclass
class BoardRow(object):
    rank: int
    name: str
    team: str
    bye: Optional[int]
    pos: str
    tier: int
    avg_pts: float
    my_dollars: float
    est_price: Optional[float]


def load_byes(path=DEFAULT_BYES):
    """Canonical team code -> bye week."""
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    out = {}  # type: Dict[str, int]
    for team, week in (raw.get("byes") or {}).items():
        out[str(team).strip().upper()] = int(week)
    return out


def assign_tiers(players, n_tiers=N_TIERS):
    """Write stats['_tier'], per position group, splitting at the largest gaps.

    Only strictly positive gaps are eligible cut points. A pool priced flat
    (K, DST are all $1) has no positive gaps at all, so it must fall out as
    one tier rather than being sliced at arbitrary $0 "gaps" - taking the
    top n_tiers-1 gaps unconditionally, without this filter, would do exactly
    that and was caught by test_a_flat_priced_pool_is_all_one_tier.
    """
    groups = defaultdict(list)
    for p in players:
        groups[_pool_of(p.pos)].append(p)

    for _, members in groups.items():
        members.sort(key=lambda p: -p.stats["_dollars"])
        if len(members) <= n_tiers:
            for i, p in enumerate(members):
                p.stats["_tier"] = i + 1
            continue

        gaps = []
        for i in range(1, len(members)):
            drop = members[i - 1].stats["_dollars"] - members[i].stats["_dollars"]
            if drop > 0:
                # -i breaks ties toward the higher-dollar boundary, so the
                # result does not depend on sort stability
                gaps.append((drop, -i))
        gaps.sort(reverse=True)
        cuts = sorted(-i for _, i in gaps[: n_tiers - 1])

        tier = 1
        cut_set = set(cuts)
        for i, p in enumerate(members):
            if i in cut_set:
                tier += 1
            p.stats["_tier"] = tier


def build_rows(lg, pool, byes):
    """Ranked, render-ready rows. Sorted by MY$ descending."""
    missing = [p.name for p in pool if "_dollars" not in p.stats]
    if missing:
        raise ValueError(
            "%d player(s) have no '_dollars'; run the value pipeline first "
            "(e.g. %s)" % (len(missing), ", ".join(sorted(missing)[:3])))

    unknown = sorted(set(p.team for p in pool if p.team not in byes))
    if unknown:
        raise ValueError(
            "no bye week for team code(s) %s; add them to the bye file rather "
            "than rendering a blank bye" % ", ".join(unknown))

    assign_tiers(pool)
    ordered = sorted(pool, key=lambda p: -p.stats["_dollars"])

    rows = []  # type: List[BoardRow]
    for i, p in enumerate(ordered, 1):
        rows.append(BoardRow(
            rank=i,
            name=p.name,
            team=p.team,
            bye=byes[p.team],
            pos=p.pos,
            tier=int(p.stats["_tier"]),
            avg_pts=(p.stats["_season_points"] / p.games) if p.games else 0.0,
            my_dollars=p.stats["_dollars"],
            est_price=p.stats.get("_est_price"),
        ))
    return rows

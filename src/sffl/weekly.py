"""Load real weekly stat lines collected from the league site.

One row per player-week. Weeks a player did not appear are absent from the file
rather than written as zeros, so a bye never drags a per-game mean downward.
"""

import csv
from dataclasses import dataclass, field
from typing import Dict, List

META = ("player_id", "name", "team", "pos", "week", "cbs_fpts")


@dataclass
class WeeklyLine(object):
    player_id: str
    name: str
    team: str
    pos: str
    week: int
    cbs_fpts: float
    stats: Dict[str, float] = field(default_factory=dict)


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0


def load_weekly(path):
    out = []  # type: List[WeeklyLine]
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            stats = {}
            for key, val in row.items():
                if key in META or key is None:
                    continue
                stats[key] = _num(val)
            out.append(WeeklyLine(
                player_id=str(row["player_id"]).strip(),
                name=str(row["name"]).strip(),
                team=str(row["team"]).strip(),
                pos=str(row["pos"]).strip().upper(),
                week=int(_num(row["week"])),
                cbs_fpts=_num(row["cbs_fpts"]),
                stats=stats,
            ))
    return out

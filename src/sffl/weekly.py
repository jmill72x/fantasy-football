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


def _num(v, context=""):
    """Convert value to float. Return 0.0 only for blank/None. Raise for garbage.

    Args:
        v: Value to parse (None, empty string, or numeric string)
        context: Error context (column name, player_id, week, row number)

    Returns:
        float: 0.0 for blank/None, otherwise parsed value

    Raises:
        ValueError: If value is non-blank and not numeric
    """
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return 0.0
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        msg = f"cannot parse '{v}' as float"
        if context:
            msg = f"{context}: {msg}"
        raise ValueError(msg)


def load_weekly(path):
    out = []  # type: List[WeeklyLine]
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row_num, row in enumerate(reader, start=2):  # CSV rows start at 2 (after header)
            player_id = str(row["player_id"]).strip()

            # Parse week first (needed for error context)
            week_raw = row["week"]
            if week_raw is None or (isinstance(week_raw, str) and week_raw.strip() == ""):
                raise ValueError(f"player_id={player_id}, row {row_num}: week is blank")
            try:
                week = int(float(str(week_raw).strip()))
            except (TypeError, ValueError):
                raise ValueError(
                    f"player_id={player_id}, row {row_num}: week '{week_raw}' is not a valid integer"
                )

            # Parse metadata fields
            name = str(row["name"]).strip()
            team = str(row["team"]).strip()
            pos = str(row["pos"]).strip().upper()

            # Parse cbs_fpts
            cbs_fpts = _num(
                row["cbs_fpts"],
                context=f"player_id={player_id}, week={week}, column=cbs_fpts, row {row_num}"
            )

            # Parse stats
            stats = {}
            for key, val in row.items():
                if key in META or key is None:
                    continue
                stats[key] = _num(
                    val,
                    context=f"player_id={player_id}, week={week}, column={key}, row {row_num}"
                )

            out.append(WeeklyLine(
                player_id=player_id,
                name=name,
                team=team,
                pos=pos,
                week=week,
                cbs_fpts=cbs_fpts,
                stats=stats,
            ))
    return out

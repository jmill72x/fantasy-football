"""Read a vendor CSV into canonical records, driven entirely by a YAML profile.

Adding a source is a new YAML file, not new code.
"""

import csv
from typing import Dict, List

import yaml

from sffl.identity import normalize_team, player_key
from sffl.schema import PlayerProjection

# Everything except these is treated as a stat to be parsed as a float.
META = ("name", "team", "pos", "games", "set_name")


class SourceProfile(object):
    def __init__(self, raw):
        self.name = raw["name"]
        self.files = raw.get("files", ["*.csv"])
        self.by_index = bool(raw.get("by_index", False))
        self.skip_rows = int(raw.get("skip_rows", 1))
        self.columns = raw["columns"]  # type: Dict[str, object]
        self.filters = raw.get("filters", {})
        self.capabilities = raw.get("capabilities", {})


def load_profile(path):
    with open(path) as fh:
        return SourceProfile(yaml.safe_load(fh))


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0


def _cell(row, spec, by_index):
    if by_index:
        idx = int(spec)
        return row[idx] if idx < len(row) else ""
    return row.get(spec, "")


def read_extract(profile, csv_path, year):
    """Return a list of PlayerProjection from one vendor CSV."""
    out = []  # type: List[PlayerProjection]
    with open(csv_path, newline="") as fh:
        if profile.by_index:
            reader = csv.reader(fh)
            rows = list(reader)[profile.skip_rows:]
        else:
            rows = list(csv.DictReader(fh))

    cols = profile.columns
    for row in rows:
        raw_name = str(_cell(row, cols["name"], profile.by_index)).strip()
        if not raw_name:
            continue

        keep = True
        for field, allowed in profile.filters.items():
            val = str(_cell(row, cols[field], profile.by_index)).strip()
            if val not in allowed:
                keep = False
                break
        if not keep:
            continue

        pos_raw = str(_cell(row, cols["pos"], profile.by_index)).strip()
        pos = player_key("", "", pos_raw).split("|")[2]
        team = normalize_team(str(_cell(row, cols["team"], profile.by_index)))
        games = _num(_cell(row, cols["games"], profile.by_index))

        stats = {}
        for field, spec in cols.items():
            if field in META:
                continue
            stats[field] = _num(_cell(row, spec, profile.by_index))

        set_name = None
        if "set_name" in cols:
            set_name = str(_cell(row, cols["set_name"], profile.by_index)).strip() or None

        out.append(PlayerProjection(
            name=raw_name, team=team, pos=pos, source=profile.name,
            source_year=year, games=games, stats=stats,
            raw_name=raw_name, set_name=set_name,
        ))
    return out

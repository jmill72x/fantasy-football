"""Read a vendor CSV into canonical records, driven entirely by a YAML profile.

Adding a source is a new YAML file, not new code.
"""

import csv
from typing import Dict, List

import yaml

from sffl.identity import normalize_team, player_key
from sffl.schema import PlayerProjection
from sffl.scoring import STAT_KEYS

# Everything except these is treated as a stat to be parsed as a float.
META = ("name", "team", "pos", "games", "set_name")


class SourceProfile(object):
    def __init__(self, raw):
        self.name = raw["name"]
        self.files = raw.get("files", ["*.csv"])
        self.by_index = bool(raw.get("by_index", False))
        self.skip_rows = int(raw.get("skip_rows", 1))
        # Optional, and only meaningful with by_index: how many columns the
        # export is expected to have. See read_extract for why.
        self.expect_columns = raw.get("expect_columns")
        if self.expect_columns is not None:
            self.expect_columns = int(self.expect_columns)
        self.columns = raw["columns"]  # type: Dict[str, object]
        self.filters = raw.get("filters", {})
        self.capabilities = raw.get("capabilities", {})


def load_profile(path):
    with open(path) as fh:
        raw = yaml.safe_load(fh)

    columns = raw.get("columns", {})
    unknown = sorted(
        field for field in columns if field not in META and field not in STAT_KEYS
    )
    if unknown:
        raise ValueError(
            "%s declares column key(s) score_game does not read: %s. "
            "Either fix the spelling to match sffl.scoring.STAT_KEYS, or the "
            "stat is meta and belongs in profiles.META." % (path, ", ".join(unknown))
        )

    return SourceProfile(raw)


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


def _check_width(profile, csv_path, all_rows):
    """Refuse an index-mapped export whose column count has moved.

    A by_index profile reads stats by POSITION, so a vendor adding or removing
    one column shifts every stat after it and the run still completes: names,
    teams and games look right, and the yardage is somebody else's. There is no
    error to notice, only a plausible wrong board.

    Width is checked rather than the header text because the header text does
    move harmlessly - Draft Sharks renamed "3D Proj" to "DS Proj" during the
    2026 preseason while the layout stayed identical, and a hash would have
    cried wolf. The cost of that choice is honest: a pure REORDER with the
    count unchanged is not detectable here, so a refreshed extract still wants
    a spot-check of one known player's stat line.
    """
    if profile.expect_columns is None or not all_rows:
        return
    width = len(all_rows[0])
    if width != profile.expect_columns:
        raise ValueError(
            "%s has %d columns; profile '%s' maps stats by POSITION and "
            "expects %d. A shifted layout does not fail loudly - it silently "
            "reads the wrong stat into every field. Re-check the export and "
            "update `expect_columns` in the profile only after confirming the "
            "new positions." % (csv_path, width, profile.name,
                                profile.expect_columns))


def read_extract(profile, csv_path, year):
    """Return a list of PlayerProjection from one vendor CSV."""
    out = []  # type: List[PlayerProjection]
    with open(csv_path, newline="") as fh:
        if profile.by_index:
            reader = csv.reader(fh)
            all_rows = list(reader)
            _check_width(profile, csv_path, all_rows)
            rows = all_rows[profile.skip_rows:]
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

"""Parse the CBS league site's weekly projections table from saved page text.

NO NETWORK I/O. The page is fetched by an operator (browser tools) and saved;
this module parses the file. That keeps every test a fixture test and keeps the
parser honest about a layout it cannot control.
"""

import re
import yaml

from sffl.identity import normalize_team
from sffl.schema import PlayerProjection

DEFAULT_PROFILE = "sources/cbs-weekly.yaml"

# "W (9/16) Harold Fannin Jr. TE • CLE @JAC ..." - availability, name,
# position, bullet, team, then the rest.
_LINE = re.compile(
    r"^\s*(?P<avail>[A-Z]+\s*\([^)]*\)|[A-Z]+)\s+"
    r"(?P<name>.+?)\s+"
    r"(?P<pos>TQB|QB|RB|WR|TE|K|DST)\s+"
    r"[•\-]\s+"
    r"(?P<team>[A-Z]{2,3})\s+"
    r"(?P<rest>.+)$"
)


def _load_groups(profile_path):
    with open(profile_path) as fh:
        raw = yaml.safe_load(fh) or {}
    return raw.get("groups", {})


def parse(path, group, week, profile_path=DEFAULT_PROFILE, season=2026):
    """Rows from one saved weekly-projections page, as PlayerProjection.

    Raises ValueError on a stat block whose width has moved - the layout is
    positional, so a changed column count silently reads the wrong stat into
    every field.
    """
    groups = _load_groups(profile_path)
    if group not in groups:
        raise ValueError(
            "unknown group %r; %s defines %s"
            % (group, profile_path, sorted(groups)))
    fields = groups[group]["stats"]
    expect_tokens = groups[group].get("expect_tokens")

    out = []
    with open(path) as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue
            m = _LINE.match(line)
            if not m:
                continue
            tokens = m.group("rest").split()
            if expect_tokens is not None and len(tokens) != expect_tokens:
                raise ValueError(
                    "%s: %r has %d tokens after the team code, expected %d - "
                    "the layout is positional and a shifted column count "
                    "reads the wrong stat into every field, even though the "
                    "trailing slice below would still return a plausible "
                    "block of the right WIDTH"
                    % (path, m.group("name"), len(tokens), expect_tokens))
            block = tokens[-len(fields):]
            if len(block) != len(fields):
                raise ValueError(
                    "%s: stat block for %r has %d columns, expected %d - the "
                    "layout is positional and a shift reads the wrong stat "
                    "into every field"
                    % (path, m.group("name"), len(block), len(fields)))
            stats = {}
            for field_name, token in zip(fields, block):
                if field_name == "_":
                    continue
                try:
                    stats[field_name] = float(token)
                except ValueError:
                    raise ValueError(
                        "%s: %r has non-numeric %s %r"
                        % (path, m.group("name"), field_name, token))
            out.append(PlayerProjection(
                name=m.group("name").strip(),
                team=normalize_team(m.group("team")),
                pos=m.group("pos"),
                source="cbs-weekly",
                source_year=season,
                games=1.0,
                stats=stats,
                raw_name=m.group("name").strip(),
            ))
    return out

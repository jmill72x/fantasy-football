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
# position, bullet, team, then the rest. `avail` is "FA" (free agent), "W"
# or "W (9/16)" (waiver-claimable, with the date the claim clears), or a
# bare owning-FANTASY-team abbreviation (a player another manager already
# rosters) - see `classify_avail` below, which sorts a captured value into
# "available"/"owned"/unclassified for callers that need to tell them apart
# (F3: parse() used to capture this column and throw it away, so the waiver
# ranking could not distinguish a free agent from another team's starter).
#
# The bare-letters alternative is deliberately NOT an open `[A-Z]+`: a row
# missing its leading status token entirely - e.g. "DJ Moore WR • CHI ..." -
# would otherwise have its own two-initial first name ("DJ") swallowed as if
# it WERE a status token, silently attributing the real player's stats to a
# fabricated "Moore" while the true "DJ Moore" printed as "no projection"
# (F4). Requiring the bare form to be an explicit "FA"/"W" or at least three
# letters means a line missing its status token no longer matches at all -
# so it is caught loudly below, by the unmatched-line count, instead of
# silently parsing under the wrong name.
_LINE = re.compile(
    r"^\s*(?P<avail>[A-Z]+\s*\([^)]*\)|FA|W|[A-Z]{3,})\s+"
    r"(?P<name>.+?)\s+"
    r"(?P<pos>TQB|QB|RB|WR|TE|K|DST)\s+"
    r"[•\-]\s+"
    r"(?P<team>[A-Z]{2,3})\s+"
    r"(?P<rest>.+)$"
)

_AVAIL_WAIVER = re.compile(r"^W(\s*\(.*\))?$")
_AVAIL_TEAM = re.compile(r"^[A-Z]{3,}$")


def classify_avail(avail):
    """Sort a raw `avail` token into "available", "owned", or None.

    "available" covers a genuine free agent ("FA") or a waiver-claimable
    player ("W" or "W (9/16)") - both fair game for a waiver ranking.
    "owned" is a bare, letters-only token of at least three characters with
    no parenthetical: on CBS's ALL PLAYERS view that shape is another
    manager's roster abbreviation, not a status, and F3 is exactly the bug
    of ranking that case as if it were claimable.

    Anything else - a shape this page has not been observed to produce, such
    as an injury-status parenthetical that is not "W (...)" - returns None
    rather than guessing. The caller must refuse to rank it, not assume
    either bucket; see F3's "do not guess" requirement.
    """
    if avail == "FA" or _AVAIL_WAIVER.match(avail):
        return "available"
    if _AVAIL_TEAM.match(avail):
        return "owned"
    return None


def _load_groups(profile_path):
    with open(profile_path) as fh:
        raw = yaml.safe_load(fh) or {}
    return raw.get("groups", {})


def parse(path, group, week, profile_path=DEFAULT_PROFILE, season=2026):
    """Rows from one saved weekly-projections page, as PlayerProjection.

    Raises ValueError on a stat block whose width has moved - the layout is
    positional, so a changed column count silently reads the wrong stat into
    every field.

    Also raises (F4) if any line looks like a player row - a reasonable
    signal being that it contains " • " - but does not match `_LINE` at all,
    naming the count and the first offending line. A line that fails to
    match this way is not necessarily "not a player row": the observed real
    case ("DJ Moore WR • CHI ...", missing its leading avail token) is a
    genuine player row that the regex would otherwise misread under the
    WRONG NAME once the avail group is loose enough to match it by accident.
    Reading a page PARTIALLY - silently dropping the lines that do not fit -
    is worse than refusing it outright, so every such line is collected and
    reported together rather than skipped one at a time.
    """
    groups = _load_groups(profile_path)
    if group not in groups:
        raise ValueError(
            "unknown group %r; %s defines %s"
            % (group, profile_path, sorted(groups)))
    fields = groups[group]["stats"]
    expect_tokens = groups[group].get("expect_tokens")

    out = []
    unmatched = []
    with open(path) as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue
            m = _LINE.match(line)
            if not m:
                if " • " in line:
                    unmatched.append(line)
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
                avail=m.group("avail").strip(),
            ))

    if unmatched:
        raise ValueError(
            "%s: %d line(s) contain %r (look like a player row) but do not "
            "match the expected layout - a page that cannot be read RELIABLY "
            "is worse than one refused outright, since a line that fails to "
            "match here can also silently mis-match under the WRONG NAME "
            "rather than simply vanish (see F4). First offending line: %r"
            % (path, len(unmatched), " • ", unmatched[0]))

    return out

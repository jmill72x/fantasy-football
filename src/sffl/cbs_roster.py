"""Parse Jeff's CBS team page into the roster it carries.

NO NETWORK I/O - `sffl.capture` fetches, this parses, exactly as
`cbs_weekly.parse` does. That keeps every test a fixture test.

THE REAL PAGE IS TAB-DELIMITED, and a player row is spread across several
lines: the row line itself carries position, identity, and opponent; the
kickoff time and the stat block trail on the lines that follow. A row line
looks like (tabs shown as literal characters here, `\\xa0` elsewhere in the
page is a stray non-breaking space, not part of a row):

    \tTQB\tChargers TQB . LAC\tARI\t
    \tWR\tJa'Marr Chase WR . CIN \tTB\t
    \tRB\tTreVeyon Henderson RB . NE \t@SEA\t

Field 1 is the position column. Field 2 is `NAME POS . TEAM`, where TEAM
sometimes carries a TRAILING SPACE - that's where an injury glyph renders in
the live page; it is not part of the team code. Field 3 is the opponent,
optionally prefixed with `@` for an away game. `_ROW` is anchored on the
leading tab and the position code appearing twice (column 1 and inside
column 2) so page furniture - nav labels, the column-header row, stat-block
continuation lines, the `RESERVES` marker, the footer - cannot match: none
of those lines start with a tab immediately followed by a bare position
code.

WHY AN EMPTY RESULT RAISES. Downstream, an empty roster is not an error
state - it is a perfectly valid input meaning "Jeff owns nobody", which
optimises to an empty lineup and ranks every free agent as a worthwhile
claim. `_cmd_week` already raises rather than accept that from a roster
FILE; a captured roster must clear the same bar. The same logic applies to
`parse_lineup` and the `RESERVES` marker: guessing where the bench starts
when the marker is missing would silently misreport bench players as
starters, so it refuses instead.
"""

import re

_POS = r"TQB|QB|RB|WR|TE|K|DST"

# "\tWR\tJa'Marr Chase WR . CIN \tTB\t" - the position column, then
# "NAME POS . TEAM" (TEAM may carry a trailing space where an injury glyph
# sits in the live page), then the opponent. Anchored on a leading tab and a
# bare position code so page furniture cannot match.
_ROW = re.compile(
    r"^\t(?:%s)\t"
    r"(?P<name>[A-Za-z0-9.'\- ]+?)\s+"
    r"(?:%s)"
    r"\s*[•-]\s*"
    r"[A-Z]{2,3}"
    r" ?\t"
    r"@?[A-Z]{2,3}\t?$" % (_POS, _POS)
)

_RESERVES_MARKER = "RESERVES"


def _iter_lines(path):
    with open(path) as fh:
        for raw_line in fh:
            yield raw_line.rstrip("\n")


def _empty_roster_error(path):
    return ValueError(
        "%s: 0 player rows matched - refusing to return an empty roster. "
        "Downstream an empty roster is a VALID input meaning 'Jeff owns "
        "nobody': it optimises to an empty lineup and ranks every free "
        "agent as a claim. Either the capture is a login page (see "
        "sffl.capture.SessionExpired) or CBS changed the team-page "
        "layout." % path
    )


def parse_roster(path):
    """Player display names from a captured CBS team page, in page order.

    Starters and reserves together, duplicates removed. Raises ValueError
    if no player rows matched at all - see the module docstring for why an
    empty roster must never be returned silently.
    """
    names = []
    seen = set()
    for line in _iter_lines(path):
        m = _ROW.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        if name in seen:
            continue
        seen.add(name)
        names.append(name)

    if not names:
        raise _empty_roster_error(path)
    return names


def parse_lineup(path):
    """(starters, reserves) - the page's current lineup split.

    Player names are split on the literal `RESERVES` line the page uses to
    separate the starting lineup from the bench. Raises ValueError if that
    marker is missing (refusing to guess where the bench starts) or if no
    player rows matched on either side of it.
    """
    starters = []
    reserves = []
    seen_starters = set()
    seen_reserves = set()
    seen_marker = False
    names, seen = starters, seen_starters

    for line in _iter_lines(path):
        if line == _RESERVES_MARKER:
            seen_marker = True
            names, seen = reserves, seen_reserves
            continue
        m = _ROW.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        if name in seen:
            continue
        seen.add(name)
        names.append(name)

    if not seen_marker:
        raise ValueError(
            "%s: no RESERVES marker found - refusing to guess where the "
            "bench starts. A wrong split would silently report bench "
            "players as starters." % path
        )
    if not starters and not reserves:
        raise _empty_roster_error(path)
    return starters, reserves

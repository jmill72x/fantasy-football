"""Parse Jeff's CBS team page into the roster it carries.

NO NETWORK I/O - `sffl.capture` fetches, this parses, exactly as
`cbs_weekly.parse` does. That keeps every test a fixture test.

THE REAL PAGE IS TAB-DELIMITED, and a player row is spread across several
lines: the row line itself carries position, identity, and opponent; the
kickoff time and the stat block trail on the lines that follow. A row line
looks like (tabs shown as literal characters here, `\\xa0` elsewhere in the
page is a stray non-breaking space, not part of a row):

    id=1974\t\tTQB\tChargers TQB . LAC\tARI\t
    id=2966320\t\tWR\tJa'Marr Chase WR . CIN \tTB\t
    \tRB\tTreVeyon Henderson RB . NE \t@SEA\t

A row `sffl.capture.capture` could pair with a CBS `playerpage/<id>` link
(see that module) carries an EXTRA leading `id=<digits>\t` segment, ahead
of the row's own leading tab, as shown on both Chargers' and Chase's lines
above. THIS INCLUDES TQB/DST TEAM-AGGREGATE ROWS, not just individuals -
verified live 2026-08-30: CBS gives each team's TQB unit and DST unit its
OWN synthetic `playerpage/<id>` (the Chargers' TQB unit is 1974, its DST
unit a DIFFERENT 1924 - not a shared team id), a genuine surprise against
an earlier assumption in this task's own brief. A row truly carries none
only when it is page furniture, or from a page saved before this existed
(Henderson's line above). `_iter_lines` strips this prefix (onto
`player_id`) before `_ROW` ever sees the line, so `_ROW` itself never
needs to know it exists.

TWO ROW SHAPES ON TODAY'S PAGE (2026-10-20). A player with a game this week
renders his GAME TIME cell on a line of its own, so his row is three lines -
the row line, the kickoff time, then the stat block - and `capture`'s id
prefix lands on the LAST of them (`_prefix_ids` puts it at the start of the
row's last non-blank line), not on the row line:

    \tWR\tPat Example WR . SEA \t@MIA\t
    Sun 1:00pm EDT
    id=9000001\t\t8\t43.5\t...

A player ON BYE has no kickoff time, so his whole row - opponent BYE, then the
stat block - is ONE line, and the id prefix stays on it:

    id=9000002\t\tWR\tLee Sample WR . LAC \tBYE\t\t7\t\t---\t...

`_ROW` used to require the row line to END after the opponent, so every
bye-week row failed to match and the player silently vanished from the parsed
roster (the 10-16 digest left out two; a bye starter could never be flagged).
It now accepts anything after the opponent's own tab, which keeps every row it
matched before exactly as it was.

THE PLAYING-WEEK ROW'S ID IS READ BACK OFF ITS STATS LINE (2026-10-21).
Until then a row with a game parsed with NO id - on 10-20 only the bye rows
had one - and every roster ↔ projections join fell back to the (name, team,
pos) composite. Why it went unseen: the capture's first anchor rule (08-30)
put the prefix on the row line, the shape `tests/fixtures/cbs_team_page.txt`
was built in; review round 2 moved it to the row's last non-blank line the
same day (right for the projections pages' leading "Add" and blank cells),
which on this page is the stats line. `_iter_lines` now gives an id-less row
line the id of the first id-carrying line below it, and only when that line
is the same row's own: the search stops at the next line that starts like a
row (`_ROW_START`, even one `_ROW` cannot read, and a bye row's own id line
is one), at any line with a row's bullet (since 2026-11-11), at the
RESERVES marker or the table's footer, and after `_ID_LOOKAHEAD` (3) lines. So an id can never cross from one row to another; a
row whose stats line carries no id keeps "" and the composite join, as
before. Fixed here rather than in `capture`, so every roster page already
saved (the data repo's weekly units) reads its ids too, and the eight
projection pages' prefixing is untouched.

Field 1 is the position column. Field 2 is `NAME POS . TEAM`, where TEAM
sometimes carries a TRAILING SPACE - that's where an injury glyph renders in
the live page; it is not part of the team code. Field 3 is the opponent,
optionally prefixed with `@` for an away game. `_ROW` is anchored on the
leading tab and the position code appearing twice (column 1 and inside
column 2) so page furniture - nav labels, the column-header row, stat-block
continuation lines, the `RESERVES` marker, the footer - cannot match: none
of those lines start with a tab immediately followed by a bare position
code.

A PAGE IT CANNOT READ RELIABLY IS REFUSED, NOT READ IN PART (F4, since
2026-11-24 - board c30a4d89). Every parser here reads through `_read_rows`,
which raises `RosterUnreadable` (a ValueError) for a line that looks like a
player row (it starts like one, or carries a row's bullet) but `_ROW` cannot
read, for a name that swallowed part of its cell, and for a row count the
page's own "ACTIVE: n RESERVE: m" footer disagrees with. Until then such a
line was skipped: the player left the roster, the lineup and the injury check
with no warning (the 11-24 multi-position row did exactly that). It is the
rule `cbs_weekly.parse` has had since 08-28, for the same reason: a roster
missing or misnaming a player gives confidently wrong advice, and the digest
says so instead (`alert.compose`'s `roster_unreadable`). An EMPTY starting
slot ("\tTE\tEMPTY\t...", seen on 11-24) is read as nobody.

WHY AN EMPTY RESULT RAISES. Downstream, an empty roster is not an error
state - it is a perfectly valid input meaning "Jeff owns nobody", which
optimises to an empty lineup and ranks every free agent as a worthwhile
claim. `_cmd_week` already raises rather than accept that from a roster
FILE; a captured roster must clear the same bar. The same logic applies to
`parse_lineup` and the `RESERVES` marker: guessing where the bench starts
when the marker is missing would silently misreport bench players as
starters, so it refuses instead.

SAME DISPLAY NAME, DIFFERENT ROW. `parse_roster`/`parse_lineup`/
`parse_positions` all dedup PER NAME ALONE (`if name in seen: continue` /
`positions.setdefault`) because that is the overwhelmingly common, correct
case: a real individual only occupies one roster row. It is NOT correct for
a TQB/DST "team aggregate" row, where the display name is the NFL TEAM'S
NICKNAME (see `sffl.cli._merge_projection_groups`, which hits the identical
shape on the projections side) - nothing stops a manager from rostering the
SAME real team for both the TQB slot and the DST slot ("Chargers" TQB and
"Chargers" DST are both entirely legitimate, independent picks), and CBS's
page then carries two rows that share a display name but are genuinely
different roster entries. `parse_lineup`/`parse_positions` silently
discarded the SECOND such row's slot the instant its name collided with the
first's - not merely left unevaluated, but never counted as present AT
ALL - which is how a real, rostered DST pick vanished and `best_lineup`
rendered its slot `-- UNFILLED` at exit 0 with no signal anywhere, live-
reproduced 2026-08-30. `find_name_position_collisions` (below) was this
project's FIRST fix for it - detect the collision, refuse to trust
`parse_positions`' first-wins answer for that name, report it as
unresolved. `parse_lineup_rows` (below) is the SECOND, more complete fix:
it never collapses by name alone in the first place, so a caller
(`sffl.cli._cmd_alert`) using it has BOTH rows, each correctly labelled,
and needs no collision detection for this case at all - each is resolved
against its own projection independently and CORRECTLY, not merely
flagged as ambiguous. `find_name_position_collisions` is retained (it is
directly tested and still correct on its own narrower terms) but is no
longer `_cmd_alert`'s primary defense against this specific hazard.

THE COMPOSITE KEY IS A HEURISTIC, NOT A STABLE ID - BUT IT IS NOW ONLY THE
FALLBACK. `parse_lineup_rows` returns (name, slot, team, player_id) -
`_cmd_alert` joins this against `PlayerProjection`s via
`identity.resolve_key`, which prefers a real CBS `player_id` (see below)
whenever one is present on BOTH sides and falls back to `player_key`'s
(name, team, pos) composite only when it is not. The composite triple is
still a very strong disambiguator on its own (the Chargers TQB/DST case,
and a real NFL case of two different players named Mike Williams at WR on
different teams, are both fully resolved by it even without an id) but IT
IS NOT PROVABLY UNIQUE: nothing stops two same-named players at the same
position on the SAME team from existing in CBS's data (a practice-squad
churn artifact, a data-entry duplicate, or a genuine same-team same-name
same-position pairing), and a key that cannot be proven unique must never
silently resolve a collision by keeping one row and dropping the other -
see `sffl.cli._merge_projection_groups` and `_cmd_alert`'s own by_key
construction, both of which detect and LOUDLY report any row that still
collides after this key is applied (an id colliding with another id counts
just as much as a composite collision), rather than assuming either
heuristic holds.

THE DURABLE FIX - CBS's OWN stable player IDs, from a `playerpage/<id>`
link - IS NOW IN PLACE FOR CBS ↔ CBS MATCHING. `sffl.capture.capture` pairs
each row it can with its own `playerpage/<id>` link and prefixes the row's
saved text with `id=<id>\t` (see that module); `_iter_lines` here strips
and threads it onto each row's `player_id`. This closes the gap for
roster ↔ projections joins - which is what `identity.resolve_key` is for -
but NOT for CBS ↔ StatsDeck injury matching: StatsDeck's feed uses nflverse
ids (a different namespace entirely), so `sffl.injuries.for_roster` stays
name-based, and correctly so - see that module's own docstring. A row with
no `playerpage` link at all (page furniture, or a page saved before this
existed) falls back to the (name, slot, team) composite, exactly as before
this existed - genuinely rare on a live CBS page now: verified 2026-08-30,
even TQB/DST team-aggregate rows carry their own synthetic id.
"""

import re
from collections import namedtuple

from sffl.cbs_weekly import _NAME_SWALLOWED_POSITION, _STATUS_TAGS

_POS = r"TQB|QB|RB|WR|TE|K|DST"
# A position cell may list two codes, comma-joined and primary first
# ("RB,WR", first seen 2026-11-24). Before this such a row silently fell out
# of every roster parser. The FIRST code is the slot a dual-eligible player
# is kept under, the same rule as `cbs_weekly._POS_GROUP` (its comment says
# why), so the (name, slot, team) fallback key still joins the two pages.
_POS_LIST = r"(?:%s)(?:,(?:%s))*" % (_POS, _POS)

# "\tWR\tJa'Marr Chase WR . CIN \tTB\t" - the position column, then
# "NAME POS . TEAM" (TEAM may carry a trailing space where an injury glyph
# sits in the live page), then the opponent. Anchored on a leading tab and a
# bare position code so page furniture cannot match. `team` IS captured (not
# just matched) - see `parse_lineup_rows` and `RosterRow` below, which need
# it to build the same (name, pos, team) identity `identity.player_key`
# already gives every other vendor source in this project.
#
# THE NAME is letters (any alphabet: `[^\W_]` is a Unicode letter or digit),
# digits, ".", "'", "-" and spaces. ASCII-only until 2026-11-24, which was
# harmless only while an unreadable row was silently dropped: since F4 below a
# row it cannot read refuses the whole page, and `cbs_weekly`'s name cell
# already takes any character, so an accented name ("José") must read here
# too. A comma still cannot (see `_NAME_SWALLOWED_POSITION`).
#
# AFTER THE OPPONENT: nothing, a lone tab, or a tab and the rest of the row.
# The last is a bye-week row, which is one line with its stat block on it -
# see the module docstring's "TWO ROW SHAPES". Before 2026-10-20 this ended
# `\t?$`, which dropped every player on bye.
_ROW = re.compile(
    r"^\t(?P<slot>%s)(?:,(?:%s))*\t"
    r"(?P<name>(?:[^\W_]|[.'\- ])+?)\s+"
    r"%s"
    r"\s*[•-]\s*"
    r"(?P<team>[A-Z]{2,3})"
    r" ?\t"
    r"@?[A-Z]{2,3}(?:\t.*)?$" % (_POS, _POS, _POS_LIST)
)

_RESERVES_MARKER = "RESERVES"

# An OPTIONAL leading "id=<digits>\t" prefix, put there by
# `sffl.capture.capture` when it could pair a row with a CBS
# `playerpage/<id>` link - see `sffl.cbs_weekly._ID_PREFIX`, the identical
# format on the projections side. Stripped in `_iter_lines`, before `_ROW`
# ever sees the line, so every existing `_ROW` match is unaffected by its
# presence - only `parse_lineup_rows` (below) actually threads the id
# through onto a `RosterRow`; every other function here discards it, same
# as it always discarded everything past what `_ROW` itself captures.
_ID_PREFIX = re.compile(r"^id=(?P<id>\d+)\t")

# A line that STARTS a roster row (its id prefix already stripped): a tab, a
# bare position code, a tab. Looser than `_ROW` on purpose - any name, any
# rest - because it marks where one row's text ends and the next one's
# begins: a row line `_ROW` cannot read (a name with a character it does not
# allow) must still stop `_continuation_id` from handing that row's id to the
# row above it. A stats line (`\t8\t43.5\t...`) never matches: a number, not
# a position code, follows its first tab.
_ROW_START = re.compile(r"^\t%s\t" % _POS_LIST)

# How many lines below an id-less row line its own id may sit. The live
# shape needs two (the kickoff time, then the stats line, measured on every
# saved roster page of 2026-10-19 to 10-24); the third is room for a
# game-time cell that renders on two lines (a game in progress has never been
# captured). The row-start, row-bullet and end-of-table stops below are what
# keep an id on its own row; this bound keeps the search short. 4 until
# 2026-11-11, when Ultron's review (board 732f74ba) showed it reaching the
# next row's line across a blank.
_ID_LOOKAHEAD = 3

# The bullet in a row's "NAME POS • TEAM" cell. Only a row line carries it (a
# kickoff time or a stats line never does), so a line with it is another
# row's even when `_ROW_START` cannot read its slot.
_ROW_BULLET = "\u2022"

# The line under the last reserve's row: "ACTIVE: 8 RESERVE: 5".
_FOOTER_PREFIX = "ACTIVE:"
# Its two counts: players in the starting lineup and on the bench. Checked
# against the rows read (see `_read_rows`); every saved real page agrees
# (17 of 17, 2026-10-19 to 11-24), an EMPTY slot not counted.
_FOOTER_COUNTS = re.compile(r"^ACTIVE:\s*(\d+)\s+RESERVE:\s*(\d+)\b")

# A starting slot with nobody in it: "\tTE\tEMPTY\t\t\t...". Seen on the
# 11-24 page (a TE slot left open). It starts like a row, so it is named
# here as the one such line that is not a player row and not unreadable.
_EMPTY_SLOT = re.compile(r"^\t%s\tEMPTY(?:\t.*)?$" % _POS_LIST)

# A matched name ending in a status tag ("Pat Example Q" out of "Pat Example
# Q WR • SEA"): the roster page shows designations as icons, never text, so
# a tag here means the cell changed shape and the name has swallowed it.
_NAME_SWALLOWED_TAG = re.compile(r"\s(?:%s)$" % "|".join(_STATUS_TAGS))


class RosterUnreadable(ValueError):
    """The team page has a line that looks like a player row but cannot be
    read, or fewer rows than its own footer counts (F4, the same rule as
    `cbs_weekly.parse`). A ValueError, so every caller that refuses a bad
    page still refuses this one; `sffl.cli._cmd_alert` tells it apart to
    say the page could not be read, not that the login failed."""

# name/slot/team/player_id. `team` is RAW off the page - it is NOT run
# through `identity.normalize_team` here (a page-parsing module has no
# opinion on identity normalization; `parse_lineup_rows`'s CALLERS do that,
# exactly where they build the join key against a `PlayerProjection`, whose
# OWN `.team` field is likewise normalized at parse time by
# `cbs_weekly.parse` - see `sffl.identity.resolve_key`, the shared join-key
# function both sides target). `player_id` is CBS's own stable id lifted
# from the row's `playerpage/<id>` link, "" when the row carried none (page
# furniture, or a page saved before this existed - a TQB/DST team-aggregate
# row gets its OWN id too, verified live 2026-08-30) - defaulted so every
# pre-existing `RosterRow(name, slot, team)` construction
# (this project's own tests included) still holds.
RosterRow = namedtuple("RosterRow", "name slot team player_id",
                       defaults=("",))


def _iter_lines(path):
    """Yield (player_id, line) - `line` with any leading id prefix removed.

    `player_id` is the line's own prefix, or - for a roster row line with
    none of its own - the id `capture` put on that row's stats line below it
    (see `_continuation_id` and the module docstring's "THE PLAYING-WEEK
    ROW'S ID"). It is "" for every other line without a prefix: every line
    on a page saved before `sffl.capture.capture` grew this feature, and
    every non-player line (nav, headers, RESERVES) on a page saved after,
    since only a row `capture()` could pair with a `playerpage/<id>` link
    ever gets one.
    """
    lines = []
    with open(path) as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            m = _ID_PREFIX.match(line)
            if m:
                lines.append((m.group("id"), line[m.end():]))
            else:
                lines.append(("", line))
    for i, (player_id, line) in enumerate(lines):
        if not player_id and _ROW_START.match(line):
            player_id = _continuation_id(lines, i)
        yield player_id, line


def _ends_table(line):
    """True for a line no row's text runs past: RESERVES, or the footer."""
    return line == _RESERVES_MARKER or line.startswith(_FOOTER_PREFIX)


def _starts_another_row(line):
    """True for a line that belongs to the next row: one that starts like a
    row, or any line with a row's bullet (a row `_ROW_START` cannot read)."""
    return bool(_ROW_START.match(line)) or _ROW_BULLET in line


def _continuation_id(lines, i):
    """The id `capture` put below the id-less row line `lines[i]`, or "".

    `lines` is `_iter_lines`' list of (player_id, prefix-stripped line). The
    first line below `i` that carries an id is this row's stats line - unless
    something that ends this row's text comes first: a line that starts like
    a row (`_ROW_START`) or carries a row's bullet (a bye row's line, id and
    all, is the NEXT row's, so it stops the search without being taken), the
    RESERVES marker or the footer. Never more than `_ID_LOOKAHEAD` lines
    down. A row whose own id
    line is missing (`_prefix_ids` could not place it) therefore gets "",
    never a neighbour's id.
    """
    for j in range(i + 1, min(len(lines), i + 1 + _ID_LOOKAHEAD)):
        player_id, line = lines[j]
        if _starts_another_row(line) or _ends_table(line):
            return ""
        if player_id:
            return player_id
    return ""


def _empty_roster_error(path):
    return ValueError(
        "%s: 0 player rows matched - refusing to return an empty roster. "
        "Downstream an empty roster is a VALID input meaning 'Jeff owns "
        "nobody': it optimises to an empty lineup and ranks every free "
        "agent as a claim. Either the capture is a login page (see "
        "sffl.capture.SessionExpired) or CBS changed the team-page "
        "layout." % path
    )


# One parsed player row: whether it sits below the RESERVES marker, its CBS
# id ("" when none) and the three fields `_ROW` reads.
_Row = namedtuple("_Row", "in_reserves player_id name slot team")


def _read_rows(path):
    """(rows, seen_marker): every player row on the page as a `_Row`, in
    page order, and whether the RESERVES marker was seen.

    EVERY public parser here reads the page through this, so none of them
    can drop a row the others keep. It refuses (`RosterUnreadable`, F4) a
    page it cannot read RELIABLY, rather than return part of it:

      * a line that looks like a player row - it starts like one
        (`_ROW_START`) or carries a row's bullet - but `_ROW` cannot read.
        Until 2026-11-24 such a line was skipped, so its player vanished
        from the roster, the lineup and the injury check with no warning
        (the multi-position row of that day was one). An EMPTY starting
        slot (`_EMPTY_SLOT`) is the one row-like line that is neither;
      * a row whose name has swallowed part of the position cell or a
        status tag ("Pat Example RB" out of "Pat Example RB WR • SEA"): it
        would be filed under a wrong name, which is worse than vanishing;
      * fewer or more rows than the page's own footer counts ("ACTIVE: 8
        RESERVE: 5"), section by section, when the footer is there: the
        backstop for a row shape neither test above recognises. Rows are
        counted once per (name, slot, team), as `parse_lineup_rows` keeps
        them.

    Every problem on the page is collected and reported together.
    """
    rows = []
    problems = []
    seen_marker = False
    footer = None
    for player_id, line in _iter_lines(path):
        if line == _RESERVES_MARKER:
            seen_marker = True
            continue
        if footer is None and line.startswith(_FOOTER_PREFIX):
            footer = _FOOTER_COUNTS.match(line)
            continue
        m = _ROW.match(line)
        if not m:
            if ((_ROW_START.match(line) or _ROW_BULLET in line)
                    and not _EMPTY_SLOT.match(line)):
                problems.append("unreadable row %r" % line)
            continue
        name = m.group("name").strip()
        if (_NAME_SWALLOWED_POSITION.search(name)
                or _NAME_SWALLOWED_TAG.search(name)):
            problems.append("name %r swallowed part of its cell in %r"
                            % (name, line))
            continue
        rows.append(_Row(seen_marker, player_id, name, m.group("slot"),
                         m.group("team")))

    if footer and not problems:
        active, reserve = int(footer.group(1)), int(footer.group(2))
        starters = set((r.name, r.slot, r.team) for r in rows
                       if not r.in_reserves)
        reserves = set((r.name, r.slot, r.team) for r in rows
                       if r.in_reserves)
        if seen_marker:
            counts, expect = (len(starters), len(reserves)), (active, reserve)
        else:
            counts, expect = (len(starters),), (active + reserve,)
        if counts != expect:
            problems.append(
                "the footer %r counts %s player(s) but %s row(s) were read"
                % (footer.group(0), "+".join(map(str, expect)),
                   "+".join(map(str, counts))))

    if problems:
        raise RosterUnreadable(
            "%s: the roster page cannot be read reliably - %d problem(s), "
            "so no roster is returned rather than one missing or misnaming "
            "a player (F4). First: %s"
            % (path, len(problems), problems[0]))
    return rows, seen_marker


def parse_roster(path):
    """Player display names from a captured CBS team page, in page order.

    Starters and reserves together, duplicates removed. Raises ValueError
    if no player rows matched at all - see the module docstring for why an
    empty roster must never be returned silently.
    """
    names = []
    seen = set()
    for row in _read_rows(path)[0]:
        if row.name in seen:
            continue
        seen.add(row.name)
        names.append(row.name)

    if not names:
        raise _empty_roster_error(path)
    return names


def parse_positions(path):
    """{display name: position code} for every player row on the page.

    The position column is right there in column 1 of every row, and the
    alert needs it to tell two very different things apart: a starter with
    no projection because his POSITION is not in the projections page we
    capture (a known scope limitation - the group is RB/WR/TE only, so a
    TQB, K or DST is never scored) versus a starter whose position IS
    captured and who still has no projection (a data problem). Conflating
    those costs a real signal, and the alternative - `parse_lineup`
    returning names only - leaves the caller guessing from the name alone.

    Returned as a separate function rather than folded into `parse_lineup`
    so that parser's (starters, reserves) contract, which several callers
    and tests depend on, does not change shape.
    """
    positions = {}
    for row in _read_rows(path)[0]:
        positions.setdefault(row.name, row.slot)
    return positions


def find_name_position_collisions(path):
    """{display name: sorted [slot, slot, ...]} for every name that appears
    in MORE THAN ONE DISTINCT position on this page - EMPTY in the
    overwhelming common case where no such name exists.

    See the module docstring's "SAME DISPLAY NAME, DIFFERENT ROW" note for
    why this exists: `parse_roster`/`parse_lineup`/`parse_positions` all
    collapse a name collision by keeping only the FIRST row's slot, which
    is correct for the ordinary case (the same real individual listed
    twice by page-rendering quirk) but WRONG for two genuinely different
    roster entries that merely share a display name (an NFL team rostered
    for both TQB and DST). This function is the only place that still sees
    BOTH rows: it scans every player row on the page (starters and
    reserves together - a collision in either section is equally real) and
    reports any name whose rows do not all agree on `slot`.

    A caller that trusts `parse_positions`' answer for a name in this
    dict's keys is trusting an arbitrary "whichever row came first" choice
    for a name that is provably ambiguous - `sffl.cli._cmd_alert` calls
    this first and routes any name found here into an explicit, loud
    report instead (see `ROSTER_NAME_AMBIGUOUS` in `sffl.alert`), rather
    than silently scoring (or silently losing) one of the two real entries.
    """
    slots_by_name = {}
    for row in _read_rows(path)[0]:
        slots_by_name.setdefault(row.name, set()).add(row.slot)
    return dict((name, sorted(slots)) for name, slots in slots_by_name.items()
               if len(slots) > 1)


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
    rows, seen_marker = _read_rows(path)

    for row in rows:
        names, seen = ((reserves, seen_reserves) if row.in_reserves
                       else (starters, seen_starters))
        if row.name in seen:
            continue
        seen.add(row.name)
        names.append(row.name)

    if not seen_marker:
        raise ValueError(
            "%s: no RESERVES marker found - refusing to guess where the "
            "bench starts. A wrong split would silently report bench "
            "players as starters." % path
        )
    if not starters and not reserves:
        raise _empty_roster_error(path)
    return starters, reserves


def parse_lineup_rows(path):
    """(starters, reserves) as `RosterRow(name, slot, team, player_id)`
    tuples - the FULL-FIDELITY counterpart to `parse_lineup`, used by
    `_cmd_alert`.

    `parse_lineup`/`parse_positions` collapse a row the moment its bare NAME
    collides with an earlier one - correct for the ordinary case (a real
    individual only occupies one roster row) but WRONG whenever the same
    display name legitimately names two different roster entries: CBS's TQB
    and DST pages both use the NFL TEAM NICKNAME as a row's "player name"
    (nothing stops a manager from rostering the SAME real team for both
    slots - "Chargers" TQB and "Chargers" DST are both genuine, independent
    picks), and separately, two DIFFERENT REAL PLAYERS can share a name at
    the same position on different NFL teams (this has actually happened in
    the NFL - two players both named Mike Williams, both WRs, on different
    teams, in the same season). `parse_lineup`'s collapse-by-name silently
    lost the second row's SLOT in the first case and would silently lose
    the second player's TEAM (and so his whole identity) in the second -
    reproduced live for the first case, on 2026-08-30, when a roster
    carrying "Chargers" for both TQB and DST rendered its DST slot
    `-- UNFILLED` at exit 0 with no mention anywhere.

    This function collapses a row ONLY when NAME, SLOT, AND TEAM all agree
    - the one combination that genuinely means "the same entity, rendered
    twice" (a page-layout repeat), never two different real entries. Each
    `RosterRow` keeps its own name AND slot AND team, so a caller can match
    it against a `PlayerProjection` using `identity.resolve_key` - the SAME
    id-first, composite-fallback join every other CBS ↔ CBS lookup in this
    project now uses - see `_cmd_alert`.

    EACH ROW ALSO CARRIES `player_id` (CBS's own stable id, "" when the row
    has none - page furniture, or a page saved before this existed; a
    TQB/DST team-aggregate row gets its OWN id too, verified live
    2026-08-30). This IS a genuinely unique key wherever both sides of a
    join have one; the
    (name, slot/pos, team) composite is the documented fallback for rows
    that don't - see the module docstring's "THE DURABLE FIX" note and
    `identity.resolve_key`.

    DEDUP KEY IS (name, slot, team) ONLY, NOT `player_id` - deliberately,
    per review round 2. The docstring above says a row collapses "ONLY when
    NAME, SLOT, AND TEAM all agree"; `player_id` never entered that
    definition, so it must not silently widen it. If it did (dedup on the
    full 4-tuple), the SAME page-layout repeat this function exists to
    collapse could survive as two rows whenever only one of the two
    renderings paired with its `playerpage/<id>` link (a real, if
    unobserved, capture-timing possibility - `_prefix_ids` pairs by text
    match in document order, and a repeated `<tr>` need not repeat
    identically in every detail) - re-introducing exactly the kind of
    silent double-count this function's whole docstring is about avoiding.
    Whichever occurrence carries a real id WINS the merge (an id is more
    informative than its absence, never less) - it does not matter whether
    the id-bearing or the id-less rendering is seen first.
    """
    starters = []
    reserves = []
    seen_starters = {}   # (name, slot, team) -> index into `rows`
    seen_reserves = {}
    page_rows, seen_marker = _read_rows(path)

    for page_row in page_rows:
        rows, seen = ((reserves, seen_reserves) if page_row.in_reserves
                      else (starters, seen_starters))
        player_id = page_row.player_id
        key = (page_row.name, page_row.slot, page_row.team)
        row = RosterRow(key[0], key[1], key[2], player_id)
        if key in seen:
            # Same entity, rendered twice - a page-layout repeat. Keep
            # whichever occurrence carries a real id; the id-less one adds
            # no information once we know its (name, slot, team) already
            # matched an earlier row.
            if player_id and not rows[seen[key]].player_id:
                rows[seen[key]] = row
            continue
        seen[key] = len(rows)
        rows.append(row)

    if not seen_marker:
        raise ValueError(
            "%s: no RESERVES marker found - refusing to guess where the "
            "bench starts. A wrong split would silently report bench "
            "players as starters." % path
        )
    if not starters and not reserves:
        raise _empty_roster_error(path)
    return starters, reserves

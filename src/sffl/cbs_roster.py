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

_POS = r"TQB|QB|RB|WR|TE|K|DST"

# "\tWR\tJa'Marr Chase WR . CIN \tTB\t" - the position column, then
# "NAME POS . TEAM" (TEAM may carry a trailing space where an injury glyph
# sits in the live page), then the opponent. Anchored on a leading tab and a
# bare position code so page furniture cannot match. `team` IS captured (not
# just matched) - see `parse_lineup_rows` and `RosterRow` below, which need
# it to build the same (name, pos, team) identity `identity.player_key`
# already gives every other vendor source in this project.
_ROW = re.compile(
    r"^\t(?P<slot>%s)\t"
    r"(?P<name>[A-Za-z0-9.'\- ]+?)\s+"
    r"(?:%s)"
    r"\s*[•-]\s*"
    r"(?P<team>[A-Z]{2,3})"
    r" ?\t"
    r"@?[A-Z]{2,3}\t?$" % (_POS, _POS)
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

    `player_id` is "" for every line that carried no such prefix - which is
    every line on a page saved before `sffl.capture.capture` grew this
    feature, and every non-player line (nav, headers, RESERVES) on a page
    saved after, since only a row `capture()` could pair with a
    `playerpage/<id>` link ever gets one.
    """
    with open(path) as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            m = _ID_PREFIX.match(line)
            if m:
                yield m.group("id"), line[m.end():]
            else:
                yield "", line


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
    for _player_id, line in _iter_lines(path):
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
    for _player_id, line in _iter_lines(path):
        m = _ROW.match(line)
        if not m:
            continue
        positions.setdefault(m.group("name").strip(), m.group("slot"))
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
    for _player_id, line in _iter_lines(path):
        m = _ROW.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        slots_by_name.setdefault(name, set()).add(m.group("slot"))
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
    seen_marker = False
    names, seen = starters, seen_starters

    for _player_id, line in _iter_lines(path):
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
    """
    starters = []
    reserves = []
    seen_starters = set()
    seen_reserves = set()
    seen_marker = False
    rows, seen = starters, seen_starters

    for player_id, line in _iter_lines(path):
        if line == _RESERVES_MARKER:
            seen_marker = True
            rows, seen = reserves, seen_reserves
            continue
        m = _ROW.match(line)
        if not m:
            continue
        row = RosterRow(m.group("name").strip(), m.group("slot"),
                        m.group("team"), player_id)
        if row in seen:
            continue
        seen.add(row)
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

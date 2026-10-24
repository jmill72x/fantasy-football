"""Normalize an injury feed into records this project can render.

PURE. Two writers produce the file this module reads, both in the same
`{"report": [...], "intel": [...]}` shape: `ops/fetch_injuries.sh` (StatsDeck's
`get_injuries`, through one `claude -p` call - the live path until the switch)
and `sffl injuries-fetch` (`sffl.direct_injuries`: nflverse, Sleeper and ESPN,
built 2026-10-20 to replace it). No test touches either source.

WHAT THIS MODULE MUST NOT DO. StatsDeck is connected to a DIFFERENT league
(Yahoo, half-PPR), so only its league-agnostic NFL data is safe to use here -
injury status, practice participation, news. Its fantasy points are computed
under the wrong rules and are never carried across. Nothing below reads a
points field, and nothing should be added that does.

THE REAL FEED SHAPE (captured 2026-08-29 via a direct `get_injuries` call,
BEFORE this module existed - see
.superpowers/sdd/2026-08-29-in-season-automation/REAL-get_injuries-payload.json).
StatsDeck returns two separate arrays, `report` (the official nflverse injury
report) and `intel` (dated news/intel), never a single flat list, and never a
per-row string saying "official". `source` ON A ROW IS AN OUTLET NAME
("sleeper_feed", "web_digest"), not a bucket. `load()` derives the bucket
(`"official"` / `"intel"`) from WHICH ARRAY a row came from and stores the
row's own label separately as `outlet`.

THE OFFICIAL-ROW MAPPING IS VERIFIED (it was provisional until the season
started). StatsDeck's real `report` rows, every week since 2026-09, are
nflverse's injury report renamed: `game_status` ("Not listed" for a player
with no game designation), `practice`, `injury`, `secondary`, `position`, and
no per-row date. `status` therefore falls back to `report_status` and
`game_status`, the same way `detail` falls back from `notes`. The direct
fetcher writes `status`, `practice` and `detail` itself, plus `as_of` (the
time nflverse published its file) and `cbs_id`. An official row that still has
no status is NEVER rendered as blank: `alert._status_text` prints it as an
explicit unknown, so a broken mapping shows up as an obviously wrong message
rather than as good news.

`source` IS LOAD-BEARING. The official injury report is the record; intel
supplements it and never overrides it. The two are kept as separate rows so
the renderer can show both with their dates when they disagree, rather than
adjudicating between them.

`tier` IS CORROBORATION STRENGTH, NEVER INJURY SEVERITY. It says how sure
StatsDeck's intel pipeline is that a report is real (e.g. "corroborated" vs
an unconfirmed single-outlet mention), not how bad the injury is. It must
never be rendered as, or read as, a severity signal.

`practice` IS NEVER PARSED OUT OF `notes`. Practice information sometimes
appears only as prose inside `notes` ("did not practice Wednesday..."), but
a regex over free text would invent a fact StatsDeck never structured. This
field is populated only when the row itself carries a `practice` key.

`previous_status` + `status_since` ARE THE ONLY CHANGE SIGNAL AVAILABLE, and
this module keeps no history of its own - without these two, Friday's and
Sunday's alerts would say the same thing about the same player, which trains
the reader to ignore both. They are carried verbatim from the file and never
derived here by comparing rows or parsing prose. StatsDeck's intel rows carry
its own tracking; the direct fetcher derives them from its own previous
snapshot ("first seen by this pipeline at <time>"). Do not delete these as
"unused" without checking alert.py.

`cbs_id` IS THE JOIN KEY WHEN THE ROW HAS ONE. The direct fetcher maps every
source's id to CBS's through ffverse's `db_playerids.csv`, so `for_roster`
can match a rostered player exactly instead of by name - see its docstring.
StatsDeck rows carry no CBS id and keep the name match they always had.
"""

import json
from collections import namedtuple

from sffl.identity import normalize_name

Report = namedtuple(
    "Report",
    "name team status practice reported_date detail source outlet tier "
    "status_since previous_status cbs_id position as_of",
)
# Every field after `source` defaults to "" so existing 7-field positional
# construction (name, team, status, practice, reported_date, detail, source) -
# as used elsewhere in this codebase before these fields were added - keeps
# working unchanged. `cbs_id`, `position` and `as_of` (2026-10-20) are empty
# on every StatsDeck row.
Report.__new__.__defaults__ = ("", "", "", "", "", "", "")


def _row_to_report(row, bucket):
    """One feed row -> a Report tagged with its bucket ("official"/"intel").

    Raises rather than guessing when a row has no recognizable player-name
    key: a silently blank name would read as "everyone is healthy" for a
    roster of unmatched rows, which is worse than failing loudly.
    """
    name = row.get("player") or row.get("name")
    if name is None or not str(name).strip():
        raise ValueError(
            "injury row has no 'player' or 'name' key - keys present: %s"
            % sorted(row.keys())
        )

    # `notes` first: that's the real feed's field. `detail`/`note` stay as
    # fallbacks for any other shape this module is ever pointed at.
    detail = row.get("notes")
    if detail is None:
        detail = row.get("detail") or row.get("note")

    # STATUS, with the same fallbacks `detail` gets, and for the same reason:
    # StatsDeck's real official rows spell it `game_status`, nflverse's own
    # column is `report_status`, and a field this missed would blank EVERY
    # official row, which the renderer would then print as a player with no
    # designation. That is exactly the failure `notes` vs `detail` already
    # produced once.
    status = row.get("status")
    if status is None or not str(status).strip():
        status = row.get("report_status") or row.get("game_status")

    # StatsDeck's official rows carry no outlet label; its outlet names
    # ("sleeper_feed", "web_digest") only appear on intel rows. The direct
    # fetcher labels its official rows "nflverse", which is kept.
    outlet = row.get("source") or ""

    return Report(
        name=str(name).strip(),
        team=(row.get("team") or "").strip(),
        status=(status or "").strip(),
        # Populated only when the row itself has a `practice` key - never
        # inferred from `notes` prose.
        practice=(row.get("practice") or "").strip(),
        reported_date=(row.get("reported_date") or "").strip(),
        detail=(detail or "").strip(),
        source=bucket,
        outlet=outlet.strip(),
        tier=(row.get("tier") or "").strip(),
        # The only change signal the feed gives us for free - see the
        # module docstring. Carried verbatim; never derived here.
        status_since=(row.get("status_since") or "").strip(),
        previous_status=(row.get("previous_status") or "").strip(),
        cbs_id=str(row.get("cbs_id") or "").strip(),
        position=(row.get("position") or "").strip(),
        as_of=(row.get("as_of") or "").strip(),
    )


def rows_to_reports(rows, bucket):
    """Feed-shaped dicts -> Reports, for rows built in-process (CBS's own
    designations, read from the capture) rather than loaded from a file."""
    return [_row_to_report(row, bucket) for row in rows]


def load(path):
    """Every row in a saved `get_injuries` payload, as Report tuples.

    Expects the top-level shape `{"report": [...], "intel": [...]}` written
    by `ops/fetch_injuries.sh` - the two arrays StatsDeck itself returns,
    each row untouched. Either key may be absent or empty (the official
    report is empty in the preseason); neither array's rows are optional
    once present.
    """
    with open(path) as fh:
        raw = json.load(fh)
    out = []
    for row in raw.get("report", []):
        out.append(_row_to_report(row, "official"))
    for row in raw.get("intel", []):
        out.append(_row_to_report(row, "intel"))
    return out


def source_notes(path):
    """Digest lines from the direct fetcher's `meta`, each ready to print.

    `sffl injuries-fetch` records each source's outcome under `meta.sources`.
    A source that failed, was skipped or is switched off (ESPN after a block)
    gets a "!! ... unavailable this run" line rather than reading as a quiet
    week, and the Sleeper statuses' age is always said (with "!!" past a day),
    since a cached copy can be the previous good one. StatsDeck's files have no
    `meta`, so this returns [] for them.
    """
    with open(path) as fh:
        raw = json.load(fh)
    meta = raw.get("meta") if isinstance(raw, dict) else None
    sources = meta.get("sources") if isinstance(meta, dict) else None
    if not isinstance(sources, dict):
        return []
    notes = []
    for name, info in sorted(sources.items()):
        if isinstance(info, dict) and not info.get("ok", True):
            error = info.get("error")
            error = " ".join(error.split())[:300] if isinstance(error, str) else ""
            notes.append("!! %s unavailable this run: %s"
                         % (name, error or "unknown error"))
    sleeper = sources.get("sleeper")
    if isinstance(sleeper, dict) and sleeper.get("ok"):
        age = sleeper.get("age_hours")
        when = sleeper.get("fetched_at")
        if isinstance(age, (int, float)) and isinstance(when, str):
            notes.append("%sSleeper statuses as of %s (%.0f h old)"
                         % ("!! " if age > 24 else "",
                            when[:16].replace("T", " "), age))
    return notes


def for_roster(reports, roster_names, roster_rows=None):
    """The rows naming a player on the roster, in roster order.

    TWO MODES, chosen by the caller.

    `roster_rows=None` (StatsDeck's file, whose rows carry no CBS id): matched
    on `normalize_name` alone, because the two pages disagree about
    punctuation - "Ja'Marr Chase" on one, "JaMarr Chase" on the other - and a
    literal comparison would silently report a clean bill of health for an
    injured starter. This is the live path until the switch, unchanged.

    `roster_rows` given (`cbs_roster.RosterRow`s - name, slot, team,
    player_id): see `_for_roster_by_id`. The CBS id comes first, then name
    and team, so two real players who share a name can no longer swap news,
    and a Team QB unit gets its quarterbacks' lines - name matching never
    could, since "49ers TQB" names nobody.
    """
    if roster_rows is not None:
        return _for_roster_by_id(reports, roster_rows)
    by_key = {}
    for r in reports:
        by_key.setdefault(normalize_name(r.name), []).append(r)
    out = []
    # `roster_names` CAN now contain repeats (Task 3b): `_cmd_alert` builds
    # it from `RosterRow`s, which - since `parse_lineup_rows` stopped
    # collapsing by name alone - legitimately carries the same display name
    # twice for the Chargers TQB/DST shape. Deduping the NAMES iterated here
    # (not `by_key`, and not the reports themselves) keeps a matching
    # `Report` from being emitted twice for one roster - harmless today
    # (a team defense is never issued an individual injury designation, per
    # this function's own docstring) but no longer structurally impossible,
    # and a caller appending both copies straight into a digest is exactly
    # the kind of silent doubling this project's other fixes have been
    # about closing.
    seen_names = set()
    for name in roster_names:
        key = normalize_name(name)
        if key in seen_names:
            continue
        seen_names.add(key)
        out.extend(by_key.get(key, []))
    return out


def _for_roster_by_id(reports, roster_rows):
    """Match by CBS id first, then name and team. See `for_roster`.

    - A rostered player with a CBS id gets every row carrying that id, plus
      rows WITHOUT a CBS id (the crosswalk had no entry: a new signing, a
      practice-squad call-up) that match his normalized name AND team, or his
      name alone when the row has no team. A row WITH a CBS id is never matched
      to him by name: its id already says which player it is.
    - A rostered player whose own id was not captured gets every row matching
      his name and team, id or not. Rare since 2026-10-21: the roster page
      puts a playing week's game time on its own line, so `capture`'s id
      prefix lands on the row's stats line, and `cbs_roster` now reads it
      back from there (before, only bye-week rows carried an id; measured
      2026-10-20).
    - A Team QB unit (slot TQB) gets its NFL team's quarterbacks' rows, by the
      row's position and team.
    - A defense (slot DST) gets none: a team defense is never designated.

    Each row is emitted once, in roster order.
    """
    from sffl.identity import normalize_team

    by_id, by_name_team, by_name, qbs = {}, {}, {}, {}
    any_by_name_team = {}
    for r in reports:
        key = (normalize_name(r.name), normalize_team(r.team))
        if r.team:
            any_by_name_team.setdefault(key, []).append(r)
        if r.cbs_id:
            by_id.setdefault(r.cbs_id, []).append(r)
        elif r.team:
            by_name_team.setdefault(key, []).append(r)
        else:
            by_name.setdefault(normalize_name(r.name), []).append(r)
        if r.position.upper() == "QB" and r.team:
            qbs.setdefault(normalize_team(r.team), []).append(r)

    out, seen = [], set()

    def take(rows):
        for r in rows:
            if id(r) not in seen:
                seen.add(id(r))
                out.append(r)

    for row in roster_rows:
        slot = (row.slot or "").upper()
        team = normalize_team(row.team)
        if slot == "TQB":
            take(qbs.get(team, []))
            continue
        if slot == "DST":
            continue
        name = normalize_name(row.name)
        if row.player_id:
            take(by_id.get(str(row.player_id), []))
            take(by_name_team.get((name, team), []))
        else:
            take(any_by_name_team.get((name, team), []))
        take(by_name.get(name, []))
    return out


# Intel is news about the NEXT game. StatsDeck's intel feed is a rolling
# window (measured 2026-10-02: items dated 09-08 through 10-02; by 2026-10-20
# it was capped at 100 rows, about ten days), ESPN's feed keeps a player's
# last comment for weeks, and for a player nobody has written about lately the
# newest item IS the old one. Without an age limit the digest kept showing
# it: a Week 4 Friday alert told Jeff McConkey was "trending toward suiting
# up in Week 2" and Bowers "could return in Week 3" - while Bowers sat in
# the optimal lineup at FLEX1. Stale intel is not merely noise; it actively
# contradicts the lineup printed under it.
#
# One league week, because that is one game cycle: anything older is about
# a game that has already been played.
INTEL_MAX_AGE_DAYS = 7


def fresh_intel(reports, today, max_age_days=INTEL_MAX_AGE_DAYS):
    """(kept, n_dropped): `reports` with intel older than `max_age_days` removed.

    OFFICIAL rows are never dropped - the official report is the record, and
    CBS/nflverse rows usually carry no date to age anyway.

    An intel row with NO date is KEPT. Its age is unknown, and silently
    hiding it would be a claim this code cannot make. Every intel row in the
    2026-10-02 payload was dated, so this is a fallback, not the common case.

    `today` is passed in, never read from the clock here, so this stays as
    testable as the rest of the module.
    """
    import datetime
    kept, dropped = [], 0
    for r in reports:
        if r.source == "official" or not r.reported_date:
            kept.append(r)
            continue
        try:
            d = datetime.datetime.strptime(r.reported_date[:10], "%Y-%m-%d").date()
        except ValueError:
            kept.append(r)            # unparseable date: same as no date
            continue
        if (today - d).days > max_age_days:
            dropped += 1
        else:
            kept.append(r)
    return kept, dropped

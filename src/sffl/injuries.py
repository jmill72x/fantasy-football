"""Normalize StatsDeck's injury feed into records this project can render.

PURE. `ops/fetch_injuries.sh` performs the one MCP call and writes raw JSON;
this module reads that file. No test touches StatsDeck.

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

PROVISIONAL: at capture time `report` was EMPTY - StatsDeck's own docs say
that's expected in the preseason - so the official-row mapping below has
never been exercised against a real official row. It is written defensively
(same field names as an intel row, since nflverse injury-report rows are
expected to share `player`/`team`/`status`/`notes`/`reported_date`) but is
UNVERIFIED until the season starts on 2026-09-09. Re-confirm it against a
real `report` row then.

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
"""

import json
from collections import namedtuple

from sffl.identity import normalize_name

Report = namedtuple(
    "Report",
    "name team status practice reported_date detail source outlet tier",
)
# `outlet` and `tier` default to "" so existing 7-field positional
# construction (name, team, status, practice, reported_date, detail,
# source) - as used elsewhere in this codebase before these two fields were
# added - keeps working unchanged.
Report.__new__.__defaults__ = ("", "")


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

    # Official rows never carry their own outlet label; StatsDeck's outlet
    # names ("sleeper_feed", "web_digest") only appear on intel rows.
    outlet = "" if bucket == "official" else (row.get("source") or "")

    return Report(
        name=str(name).strip(),
        team=(row.get("team") or "").strip(),
        status=(row.get("status") or "").strip(),
        # Populated only when the row itself has a `practice` key - never
        # inferred from `notes` prose.
        practice=(row.get("practice") or "").strip(),
        reported_date=(row.get("reported_date") or "").strip(),
        detail=(detail or "").strip(),
        source=bucket,
        outlet=outlet.strip(),
        tier=(row.get("tier") or "").strip(),
    )


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


def for_roster(reports, roster_names):
    """The rows naming a player on `roster_names`, in roster order.

    Matched on `normalize_name` because the two pages disagree about
    punctuation - "Ja'Marr Chase" on one, "JaMarr Chase" on the other - and a
    literal comparison would silently report a clean bill of health for an
    injured starter.
    """
    by_key = {}
    for r in reports:
        by_key.setdefault(normalize_name(r.name), []).append(r)
    out = []
    for name in roster_names:
        out.extend(by_key.get(normalize_name(name), []))
    return out

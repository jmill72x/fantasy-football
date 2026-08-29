"""Normalize StatsDeck's injury feed into records this project can render.

PURE. `ops/fetch_injuries.sh` performs the one MCP call and writes raw JSON;
this module reads that file. No test touches StatsDeck.

WHAT THIS MODULE MUST NOT DO. StatsDeck is connected to a DIFFERENT league
(Yahoo, half-PPR), so only its league-agnostic NFL data is safe to use here -
injury status, practice participation, news. Its fantasy points are computed
under the wrong rules and are never carried across. Nothing below reads a
points field, and nothing should be added that does.

`source` IS LOAD-BEARING. The official injury report is the record; intel
supplements it and never overrides it. The two are kept as separate rows so
the renderer can show both with their dates when they disagree, rather than
adjudicating between them.
"""

import json
from collections import namedtuple

from sffl.identity import normalize_name

Report = namedtuple("Report", "name team status practice reported_date detail source")


def load(path):
    """Every row in a saved `get_injuries` payload, as Report tuples."""
    with open(path) as fh:
        raw = json.load(fh)
    rows = raw.get("injuries", raw if isinstance(raw, list) else [])
    out = []
    for row in rows:
        out.append(Report(
            name=(row.get("player") or row.get("name") or "").strip(),
            team=(row.get("team") or "").strip(),
            status=(row.get("status") or "").strip(),
            practice=(row.get("practice") or "").strip(),
            reported_date=(row.get("reported_date") or "").strip(),
            detail=(row.get("detail") or row.get("note") or "").strip(),
            source=(row.get("source") or "official").strip(),
        ))
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

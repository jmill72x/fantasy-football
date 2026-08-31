"""Load real weekly stat lines collected from the league site.

One row per player-week. Weeks a player did not appear are absent from the file
rather than written as zeros, so a bye never drags a per-game mean downward.

DUPLICATE-ENTITY COLLAPSE HAPPENS HERE, AT LOAD, ON PURPOSE. CBS has, on
several occasions, captured the same real player/team-unit under two
different `player_id`s within one file, with byte-identical week-by-week
stats under both. `calibrate_eval.player_folds` splits fit/holdout sets by
`player_id` precisely so a player's own weeks can never sit in both sets -
but that guard cannot see this: the two ids are genuinely distinct, so the
splitter happily separates them into different folds, and the held-out
id's identical twin sits right there in the fit set. Interpolation then
draws its line straight through the twin's point and "predicts" the
held-out id almost exactly - a leak that flatters whichever curve most
resembles raw interpolation (see calibrate_eval's own module docstring).

`load_weekly` is the ONE place every caller - `poc/build_calibration.py`,
`poc/compare_calibration_methods.py`, `poc/measure_dst_ranking.py`,
`calibrate_eval`'s tests - goes through to get weekly rows off disk. There
is no separate "raw" loader for a future script to reach for instead, so
folding the collapse into `load_weekly` itself (rather than a helper a
caller has to remember to call) is what makes this leak structurally
impossible to reintroduce, not just fixed for today's four files.

THE COLLAPSE IS LOUD, NOT SILENT. Two ids are collapsed only when their
COMPLETE week-by-week stat history is identical (same weeks, same
cbs_fpts, same every stat column) - see `_duplicate_id_groups`. That is
deliberately NOT "same name": two real players who happen to share a name
(a real case in this league - two same-named WRs on different teams) have
different weekly lines and must never be merged; the test never even looks
at name/team/pos. Every collapse that does happen is reported by name via
`DuplicateEntityWarning` AND a direct stderr print, naming the file, the
display name, and every id involved - a bare count would hide exactly the
kind of thing this exists to surface.
"""

import csv
import sys
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

META = ("player_id", "name", "team", "pos", "week", "cbs_fpts")


class DuplicateEntityWarning(UserWarning):
    """Two player_ids in one weekly file share a byte-identical stat history.

    Raised by `load_weekly` when it collapses such a pair (see the module
    docstring for why this matters to cross-validated calibration).
    """


@dataclass
class WeeklyLine(object):
    player_id: str
    name: str
    team: str
    pos: str
    week: int
    cbs_fpts: float
    stats: Dict[str, float] = field(default_factory=dict)


def _num(v, context=""):
    """Convert value to float. Return 0.0 only for blank/None. Raise for garbage.

    Args:
        v: Value to parse (None, empty string, or numeric string)
        context: Error context (column name, player_id, week, row number)

    Returns:
        float: 0.0 for blank/None, otherwise parsed value

    Raises:
        ValueError: If value is non-blank and not numeric
    """
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return 0.0
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        msg = f"cannot parse '{v}' as float"
        if context:
            msg = f"{context}: {msg}"
        raise ValueError(msg)


def load_weekly(path):
    out = []  # type: List[WeeklyLine]
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row_num, row in enumerate(reader, start=2):  # CSV rows start at 2 (after header)
            player_id = str(row["player_id"]).strip()

            # Parse week first (needed for error context)
            week_raw = row["week"]
            if week_raw is None or (isinstance(week_raw, str) and week_raw.strip() == ""):
                raise ValueError(f"player_id={player_id}, row {row_num}: week is blank")
            try:
                week = int(float(str(week_raw).strip()))
            except (TypeError, ValueError):
                raise ValueError(
                    f"player_id={player_id}, row {row_num}: week '{week_raw}' is not a valid integer"
                )

            # Parse metadata fields
            name = str(row["name"]).strip()
            team = str(row["team"]).strip()
            pos = str(row["pos"]).strip().upper()

            # Parse cbs_fpts
            cbs_fpts = _num(
                row["cbs_fpts"],
                context=f"player_id={player_id}, week={week}, column=cbs_fpts, row {row_num}"
            )

            # Parse stats
            stats = {}
            for key, val in row.items():
                if key in META or key is None:
                    continue
                stats[key] = _num(
                    val,
                    context=f"player_id={player_id}, week={week}, column={key}, row {row_num}"
                )

            out.append(WeeklyLine(
                player_id=player_id,
                name=name,
                team=team,
                pos=pos,
                week=week,
                cbs_fpts=cbs_fpts,
                stats=stats,
            ))
    return _collapse_duplicate_entities(out, path)


def _line_signature(line):
    """The part of a `WeeklyLine` that identifies a played week's OUTCOME -
    week number, cbs_fpts, and every stat column - deliberately excluding
    name/team/pos. Two ids are the same entity only if every week they
    played produced the identical outcome; what CBS happened to print as
    that entity's name is not part of the test (see the module docstring).
    """
    return (line.week, line.cbs_fpts, tuple(sorted(line.stats.items())))


def _duplicate_id_groups(lines):
    """Group `player_id`s whose COMPLETE week-by-week stat history is
    identical. Returns a list of id-lists, one list per group of >= 2 ids
    that share a history; ids with a unique history are omitted entirely.
    """
    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)

    by_signature = defaultdict(list)
    for pid, weeks in by_player.items():
        signature = tuple(sorted(_line_signature(w) for w in weeks))
        by_signature[signature].append(pid)

    return [ids for ids in by_signature.values() if len(ids) > 1]


def _collapse_duplicate_entities(lines, path):
    """Collapse ids that are the SAME ENTITY (identical week-by-week stat
    history) down to one, so a fit/holdout split can never separate one
    player's own weeks into two different folds. See the module docstring
    for why this belongs here rather than in a helper a caller could skip.

    Deterministic: within a duplicate group, the id that appears FIRST in
    the file (by row order) is kept; the other id(s)' rows are dropped
    (dropping is equivalent to merging here, since a genuine duplicate's
    history is byte-identical - there is no complementary information to
    combine). Every collapse is reported by name, not just counted: a
    `DuplicateEntityWarning` (so anything running under `-W`/pytest sees
    it) and a direct `stderr` print (so a plain script run sees it even if
    warnings are filtered).
    """
    dup_groups = _duplicate_id_groups(lines)
    if not dup_groups:
        return lines

    first_seen = {}
    for i, ln in enumerate(lines):
        first_seen.setdefault(ln.player_id, i)

    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)

    drop_ids = set()
    for ids in dup_groups:
        keep = min(ids, key=lambda pid: first_seen[pid])
        dropped = sorted(pid for pid in ids if pid != keep)
        sample = by_player[keep][0]
        message = (
            "DUPLICATE ENTITY collapsed in {0}: {1!r} ({2}, {3}) - id(s) {4} "
            "carry a byte-identical {5}-week stat history to id {6!r} and "
            "were DROPPED, so a fit/holdout split can never put this "
            "player's own weeks on both sides.".format(
                path, sample.name, sample.team, sample.pos,
                dropped, len(by_player[keep]), keep))
        warnings.warn(message, DuplicateEntityWarning, stacklevel=3)
        print("  ** {0} **".format(message), file=sys.stderr)
        drop_ids.update(dropped)

    return [ln for ln in lines if ln.player_id not in drop_ids]

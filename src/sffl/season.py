"""Which NFL season a run is for, and the season-bound values that must match it.

Three values in this repo belong to one season and are moved by hand each year
(docs/operations/preseason-runbook.md, "Season-bound values"):

- the LEAGUE PROFILE: `DEFAULT_LEAGUE` (src/sffl/cli.py) or `--league`; its
  season is the file's own `season:` key;
- the BYE FILE: `DEFAULT_BYES` (src/sffl/render/rows.py) or `--byes`, read by
  `render` and `plan`; its season is the file's own `season:` key (or, if it has
  none, a year in its file name - see `file_season`);
- the ALERT'S WEEK-1 DATE: `WEEK1` in ops/run_alert.sh, which passes it to
  `sffl alert --week1`; its season is the date's (`season_for`).

THE SEASON A DATE BELONGS TO (`season_for`): from March 1 on, that calendar
year's; in January and February, the previous year's - those months are the
previous season's playoffs and wind-down, and the NFL's new league year starts
in March. So all of January 2027 (weeks 17 and 18, STRIPES's last playoff week,
the 2027-01-12 results run) is the 2026 season, and 2027-03-01 is the first day
of the 2027 one. Moved here 2026-10-21 from `sffl.direct_injuries`, which picks
nflverse's season file by the same rule, so the repo has one rule, not two.

STALE, exactly: a season-bound value is STALE when the season it is for is
OLDER than the season the run is for. The run's season is the command's
`--year` when it has one (ingest, value, render, plan, fit-market); otherwise
it is the season of today's date (alert, week, trade, collect). The same check
reports a value NEWER than the run's season ("AHEAD": a 2027 value in a 2026
run - say, the January results run after the defaults moved early), because it
is the same mistake the other way round. A value that names no season is not
checked.

WHERE IT SHOWS. Every command that uses one of these values prints a WARNING
line for each one out of season. `sffl alert` also puts a banner at the TOP of
the pushed digest and exits non-zero (DEGRADED), so a forgotten step in an
unattended run reaches the phone, not just the log; `render` also puts it on
the workbook's Key & Intel sheet, the page that goes to the draft table.
Nothing refuses to run: a run for another season on purpose (a rehearsal with
last year's files) still works, and says so. Every 2026 run is silent: the
three values are all 2026's, and so is every date from 2026-03-01 to
2027-02-28. `sffl lineup`, which writes to CBS, is deliberately not checked:
Jeff runs it himself, and this change leaves the write path alone.
"""

import datetime
import os
import re
from collections import namedtuple


def season_for(day):
    """The NFL season a date belongs to: January and February are the
    previous season's playoffs."""
    return day.year if day.month >= 3 else day.year - 1


def today():
    """Today's date. One seam, so a test can say what day it is."""
    return datetime.date.today()


def run_season(year=None, day=None):
    """(season, basis): the season this run is for, and why, in words.

    `year` (a command's `--year`) wins when given; otherwise the season of
    `day`, default today (`season_for`).
    """
    if year:
        return int(year), "--year %d" % int(year)
    day = day or today()
    return season_for(day), "by today's date, %s" % day.isoformat()


def file_season(path):
    """The season a season-bound YAML file says it is for, or None.

    Its own top-level `season:` key; failing that, a year (20xx) in its file
    name (`nfl-byes-2027.yaml`). The key wins when both are there, so a copied
    file whose key was never updated reads as last season's - which is the
    mistake this exists to catch. A file that cannot be read gives None here:
    the loader that reads it for real reports that.
    """
    # Imported here, not at the top: `sffl.direct_injuries` imports this
    # module for `season_for` and parses its third-party data with the
    # standard library only, so its imports stay that way.
    import yaml

    raw = None
    try:
        with open(path) as fh:
            raw = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        pass
    if isinstance(raw, dict) and raw.get("season") is not None:
        try:
            return int(raw["season"])
        except (TypeError, ValueError):
            pass
    m = re.search(r"(?<!\d)(20\d\d)(?!\d)", os.path.basename(str(path)))
    return int(m.group(1)) if m else None


# Per value: how to fix it, and the preseason runbook step that does.
_FIX = {
    "league profile": ("use the %d profile (--league, or DEFAULT_LEAGUE in "
                       "src/sffl/cli.py)", 2),
    "bye file": ("use the %d bye file (--byes, or DEFAULT_BYES in "
                 "src/sffl/render/rows.py)", 3),
    "week-1 date": ("set WEEK1 in ops/run_alert.sh to the Wednesday %d's "
                    "week 1 begins - the week number is computed from it, so "
                    "this run's is wrong", 13),
}


class Mismatch(namedtuple("Mismatch",
                          "value source value_season run_season basis")):
    """One season-bound value whose season is not the run's.

    value: "league profile", "bye file" or "week-1 date".
    source: where it came from, as someone would look for it (a path, or the
      date and the script line).
    """

    @property
    def stale(self):
        """True when the value is older than the run's season."""
        return self.value_season < self.run_season

    @property
    def step(self):
        """The preseason runbook step that sets this value."""
        return _FIX[self.value][1]

    def fix(self):
        return _FIX[self.value][0] % self.run_season


def check(value, source, value_season, run, basis):
    """A `Mismatch` when `value_season` is not `run`, else None.

    `value` is one of the three names above. `value_season` None (the value
    names no season) is not a mismatch: there is nothing to compare."""
    if value not in _FIX:
        raise ValueError("unknown season-bound value %r" % value)
    if value_season is None or int(value_season) == int(run):
        return None
    return Mismatch(value, str(source), int(value_season), int(run), basis)


def title(m):
    """STALE SEASON VALUE when the value is older than the run's season,
    SEASON VALUE AHEAD when it is newer."""
    return "STALE SEASON VALUE" if m.stale else "SEASON VALUE AHEAD"


def detail(m):
    """What, whose season, and the fix, in one sentence or two."""
    return ("The %s %s is for the %d season, but this run is for %d (%s). "
            "Fix: %s (preseason runbook, step %d)."
            % (m.value, m.source, m.value_season, m.run_season, m.basis,
               m.fix(), m.step))


def line(m):
    """One line for a log: `title` and `detail` together."""
    return "%s: %s" % (title(m), detail(m))


def _headline(mismatches):
    if all(m.stale for m in mismatches):
        return "STALE SEASON VALUES"
    return "SEASON VALUES FROM ANOTHER SEASON"


# What a value from another season does to a digest, where it is not obvious.
_CONSEQUENCE = {"week-1 date": ": the week number is wrong"}


def banner(mismatches):
    """The lines that open a digest whose season-bound values are out of
    season. One short line per value, never hard-wrapped (the phone re-wraps);
    the full fix is in the run's log, from `line`."""
    run, basis = mismatches[0].run_season, mismatches[0].basis
    lines = ["!! %s - this run is for the %d season (%s), but:"
             % (_headline(mismatches), run, basis)]
    for m in mismatches:
        lines.append("  - the %s %s is the %d season's%s (preseason runbook, "
                     "step %d)."
                     % (m.value, m.source, m.value_season,
                        _CONSEQUENCE.get(m.value, ""), m.step))
    lines.append("  Everything below may use another season's values.")
    return lines


def board_note(mismatches):
    """One sentence for the Key & Intel sheet of a board built with them."""
    run = mismatches[0].run_season
    parts = ["the %s is the %d season's" % (m.value, m.value_season)
             for m in mismatches]
    steps = sorted(set(m.step for m in mismatches))
    return ("!! %s: %s, not this %d board's - re-render with this season's "
            "(preseason runbook, step%s %s)."
            % (_headline(mismatches), "; ".join(parts), run,
               "s" if len(steps) > 1 else "",
               " and ".join(str(s) for s in steps)))

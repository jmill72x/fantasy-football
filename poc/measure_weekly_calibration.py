"""How far the calibrated weekly expectation moves from CBS's banded estimate.

CBS bands a point estimate; E[band(X)] != band(E[X]). The spec measured +4.88
across eight hand-picked low-projection lines, which is not evidence of a
general improvement - those were chosen because band edges bite hardest there.
This measures a whole saved page.

    PYTHONPATH=src ./.venv/bin/python poc/measure_weekly_calibration.py [PAGE]

With no PAGE it reads the REAL 8-row week-1 page, which is kept in the private
data repo (REAL_PAGE below), not in this public repo. The tracked
tests/fixtures/cbs_weekly_rbwrte.txt has the same layout and the same league
scores, but its stat lines are constructed (2026-10-19), so the calibrated
column it produces is illustrative only and must not be quoted as a result.
"""

import os
import sys

from sffl.calibrate import load_curves
from sffl.cbs_weekly import parse
from sffl.league import load_league
from sffl.pool import score_week
from sffl.scoring import score_game


def main(path):
    lg = load_league("leagues/sffl/2026.yaml")
    curves = load_curves("calibration/2025.yaml")
    rows = parse(path, group="RB-WR-TE", week=1, season=lg.season)
    naive_total = calibrated_total = 0.0
    moved = 0
    print("%-24s %8s %12s %8s" % ("PLAYER", "CBS", "calibrated", "diff"))
    for p in sorted(rows, key=lambda r: -score_week(lg, r, curves)):
        naive = score_game(lg, p.stats, p.pos)
        cal = score_week(lg, p, curves)
        naive_total += naive
        calibrated_total += cal
        if abs(cal - naive) >= 0.5:
            moved += 1
        print("%-24s %8.2f %12.2f %+8.2f" % (p.name[:23], naive, cal, cal - naive))
    print("\n  n=%d   CBS total %.2f   calibrated %.2f   diff %+.2f"
          % (len(rows), naive_total, calibrated_total,
             calibrated_total - naive_total))
    print("  players moved by >= 0.5 pts: %d of %d" % (moved, len(rows)))
    print("\n  A large average diff is NOT the claim. What matters for a start/sit"
          "\n  or waiver decision is whether it changes the ORDER of two players.")


REAL_PAGE = os.path.expanduser(
    "~/Projects/fantasy-football-data/2026/cbs/snapshot-2026-10-19/"
    "test-fixtures/cbs_weekly_rbwrte.txt")
FIXTURE = "tests/fixtures/cbs_weekly_rbwrte.txt"


if __name__ == "__main__":
    if len(sys.argv) > 1:
        page = sys.argv[1]
    elif os.path.exists(REAL_PAGE):
        page = REAL_PAGE
    else:
        page = FIXTURE
        print("NOTE: the private data repo is not here, so this reads the "
              "CONSTRUCTED fixture - its calibrated figures are illustrative, "
              "not a measurement.\n")
    main(page)

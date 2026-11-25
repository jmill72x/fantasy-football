"""The canonical record every source is normalized into."""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class PlayerProjection(object):
    name: str                       # normalized display name
    team: str                       # canonical abbreviation
    pos: str                        # QB RB WR TE K DST
    source: str                     # draftsharks | footballguys | ...
    source_year: int
    games: float
    stats: Dict[str, float] = field(default_factory=dict)
    raw_name: str = ""              # exactly as the vendor wrote it
    set_name: Optional[str] = None  # for sources with multiple analyst sets
    avail: str = ""                 # raw roster-availability token, when the
                                     # source's page carries one (FA/waiver/
                                     # owning-team) - see sffl.cbs_weekly
    status: str = ""                # raw injury designation from the source's
                                     # page (Q/D/O/IR/PUP/SUSP/NA), "" when the
                                     # player carries none - see sffl.cbs_weekly
    week: int = 0                   # the NFL week this projection is FOR, when
                                     # the source is a weekly page - 0 for a
                                     # season-long projection, which has no
                                     # week. Carried so a caller can check
                                     # that the page it got is the week it
                                     # asked for: `cbs_weekly.parse` took a
                                     # `week` argument and dropped it on the
                                     # floor until 2026-08-31, so nothing
                                     # downstream could tell week 3's saved
                                     # page from week 4's.
    opp: str = ""                   # raw opponent cell from a weekly page
                                     # ("@LAC", "SEA"), "" when the source
                                     # carries none. Kept RAW, with the "@",
                                     # because its job is cross-page
                                     # comparison (see
                                     # `cbs_weekly.week_conflicts`) and the
                                     # home/away marker makes that stricter,
                                     # not looser.
    bye: int = 0                    # the player's team's bye week, off a
                                     # weekly page's BYE column; 0 when the
                                     # source carries none. Needed to count
                                     # a player's REMAINING games for a
                                     # rest-of-season valuation - a bye that
                                     # has not happened yet is one fewer game
                                     # he will actually play.
    player_id: str = ""             # CBS's own stable player id, lifted from
                                     # a `playerpage/<id>` link on the row
                                     # that produced this record - "" when the
                                     # source's page carries no such link (a
                                     # non-CBS vendor, or a CBS row that is a
                                     # team aggregate rather than an
                                     # individual - see sffl.capture and
                                     # sffl.cbs_weekly). NOT a cross-vendor
                                     # id: only CBS ↔ CBS rows ever share this
                                     # namespace - see identity.resolve_key.
    positions: Tuple[str, ...] = ()  # EVERY position the source lists the
                                     # player under, primary first, when it
                                     # lists more than one ("RB,WR" on a CBS
                                     # row, first seen 2026-11-24); () for
                                     # the ordinary one-position row, so every
                                     # existing record is unchanged. `pos`
                                     # stays the primary code: identity,
                                     # scoring and the roster join key on it.
                                     # Only lineup eligibility reads this -
                                     # see `eligible` and sffl.lineup.

    def eligible(self):
        """The positions this player may start at: `positions`, or (pos,)."""
        return self.positions or (self.pos,)

    def key(self):
        from sffl.identity import resolve_key
        return resolve_key(self.player_id, self.name, self.team, self.pos)

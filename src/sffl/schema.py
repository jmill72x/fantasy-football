"""The canonical record every source is normalized into."""

from dataclasses import dataclass, field
from typing import Dict, Optional


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

    def key(self):
        from sffl.identity import resolve_key
        return resolve_key(self.player_id, self.name, self.team, self.pos)

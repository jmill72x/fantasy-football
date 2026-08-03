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

    def key(self):
        from sffl.identity import player_key
        return player_key(self.name, self.team, self.pos)

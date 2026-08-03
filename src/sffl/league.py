"""Load the league profile. Every scoring band and roster rule lives in YAML."""

from typing import Dict, List, Tuple

import yaml


class LeagueProfile(object):
    def __init__(self, raw):
        self.raw = raw
        self.name = raw["name"]
        self.season = int(raw["season"])
        self.teams = int(raw["teams"])
        self.budget = int(raw["budget"])
        self.roster_size = int(raw["roster_size"])
        self.starters = int(raw["starters"])
        self.flex_slots = int(raw["flex_slots"])
        # Games an NFL franchise plays. The denominator for any unit that is
        # a franchise rather than a person - Team QB in particular.
        self.season_games = int(raw["season_games"])
        self.silent_auction = raw.get("silent_auction", {})
        self.points = raw["points"]
        self.sack_rule = raw["sack_rule"]
        self.bands = {}  # type: Dict[str, List[Tuple[int, int, int]]]
        for key, rows in raw["bands"].items():
            self.bands[key] = [(int(a), int(b), int(c)) for a, b, c in rows]

    def total_capital(self):
        return self.teams * self.budget

    def total_spots(self):
        return self.teams * self.roster_size

    def surplus(self):
        """Money above the $1 minimum every roster spot costs."""
        return self.total_capital() - self.total_spots()


def load_league(path):
    with open(path) as fh:
        return LeagueProfile(yaml.safe_load(fh))

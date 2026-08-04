"""Load the league profile. Every scoring band and roster rule lives in YAML."""

from typing import Dict, List, Tuple

import yaml

from sffl.value import POOLS


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
        self.flat_priced_pools = {}  # type: Dict[str, float]
        for pool_name, price in (raw.get("flat_priced_pools") or {}).items():
            name = str(pool_name).strip().upper()
            if name not in POOLS:
                raise ValueError(
                    "flat_priced_pools names %r, which is not a valid pool; "
                    "expected one of %s" % (pool_name, sorted(POOLS)))
            price = float(price)
            # surplus() assumes every roster spot costs exactly $1 before the
            # VORP-proportional split; a flat price other than $1 would
            # silently overspend (or underspend) the league budget by
            # teams * roster_size * (price - 1) with no error anywhere. Raise
            # rather than teach surplus() to account for it, since every
            # flat-priced pool this league has ever used is $1 and a future
            # non-$1 price is exactly the kind of change that deserves a
            # deliberate code change, not silent acceptance.
            if price != 1.0:
                raise ValueError(
                    "flat_priced_pools[%r] = %r, but only a flat price of "
                    "exactly 1 is supported - surplus() assumes every roster "
                    "spot costs $1 before the VORP split, so any other flat "
                    "price would silently overspend or underspend the "
                    "league budget" % (pool_name, price))
            self.flat_priced_pools[name] = price

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

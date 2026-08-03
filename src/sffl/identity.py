"""Resolve player identity across sources.

Three layers, in order: deterministic normalization, an alias file, then fuzzy
matching with a review queue. This module is layer one.
"""

import html
import re

import yaml
from rapidfuzz import fuzz, process

SUFFIXES = ("jr", "sr", "ii", "iii", "iv", "v")

# Canonical team codes. Sources disagree; this picks a winner.
TEAM_ALIASES = {
    "JAX": "JAC",
    "LVR": "LV", "OAK": "LV",
    "WSH": "WAS", "WFT": "WAS",
    "LA": "LAR", "STL": "LAR",
    "SD": "LAC",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
    "TAM": "TB",
    "NWE": "NE",
    "NOR": "NO",
    "GNB": "GB",
    "KAN": "KC",
    "SFO": "SF",
}

# The 32 real NFL franchises, in canonical form (post-TEAM_ALIASES). Used to
# reject non-franchise team codes - free agents ("FA"), unrostered/retired
# placeholders, and similar vendor bookkeeping - from anything that must map
# one-to-one onto a real team, such as Team QB units.
NFL_TEAMS = frozenset({
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAC", "KC", "LAC", "LAR", "LV", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WAS",
})


def normalize_name(s):
    """Lowercase, strip punctuation and generational suffixes, collapse spaces."""
    if s is None:
        return ""
    s = html.unescape(s)
    s = s.strip().lower()
    s = s.replace("'", "").replace("'", "")
    s = re.sub(r"[\-_]", " ", s)
    s = s.replace(".", "")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    parts = [p for p in s.split() if p]
    while parts and parts[-1] in SUFFIXES:
        parts.pop()
    return " ".join(parts)


def normalize_team(s):
    """Return the canonical abbreviation for a team code."""
    if not s:
        return ""
    t = s.strip().upper()
    return TEAM_ALIASES.get(t, t)


def player_key(name, team, pos):
    """Stable join key. Position is uppercased; DEF/D/DST all fold to DST."""
    p = (pos or "").strip().upper()
    if p in ("DEF", "D", "D/ST", "DST", "TD"):
        p = "DST"
    if p in ("PK",):
        p = "K"
    return "%s|%s|%s" % (normalize_name(name), normalize_team(team), p)


FUZZY_ACCEPT = 92.0   # rapidfuzz WRatio; below this we ask rather than guess


class Resolver(object):
    """Resolve a vendor's spelling to a canonical player key.

    Order: exact (after normalization) -> alias file -> fuzzy match within the
    same team and position. Anything left over lands in `unresolved` with its
    best candidates, so a human confirms once and the alias file absorbs it.
    """

    def __init__(self, alias_path=None):
        self.aliases = {}
        if alias_path:
            with open(alias_path) as fh:
                raw = yaml.safe_load(fh) or {}
            for vendor, canonical in (raw.get("players") or {}).items():
                self.aliases[normalize_name(vendor)] = normalize_name(canonical)
        self.known = set()
        self.unresolved = []

    def register(self, keys):
        for k in keys:
            self.known.add(k)

    def _candidates(self, team, pos):
        suffix = "|%s|%s" % (normalize_team(team), player_key("", "", pos).split("|")[2])
        return [k for k in self.known if k.endswith(suffix)]

    def resolve(self, name, team, pos):
        key = player_key(name, team, pos)
        if key in self.known:
            return key

        aliased = self.aliases.get(normalize_name(name))
        if aliased:
            key2 = player_key(aliased, team, pos)
            if key2 in self.known:
                return key2

        pool = self._candidates(team, pos)
        if pool:
            target = normalize_name(name)
            best = process.extractOne(
                target, [p.split("|")[0] for p in pool], scorer=fuzz.WRatio
            )
            if best and best[1] >= FUZZY_ACCEPT:
                return pool[best[2]]
            scored = [(pool[i], s) for _, s, i in
                      process.extract(target, [p.split("|")[0] for p in pool],
                                      scorer=fuzz.WRatio, limit=3)]
        else:
            scored = []

        self.unresolved.append((name, team, pos, scored))
        return None

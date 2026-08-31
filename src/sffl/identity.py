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
    """Composite join key: (name, team, pos), heuristic, NOT provably unique.

    Position is uppercased; DEF/D/DST all fold to DST. `"TD"` folds to DST
    too - NOT a typo for `"D/ST"` (investigated via `git log -S`, not
    guessed): `sources/footballguys.yaml`'s `filters.pos` list carries a
    lowercase `"td"` as THAT VENDOR's own position code for a team defense
    row (alongside `"qb"`, `"rb"`, `"wr"`, `"te"`), which reaches this
    function uppercased. Removing this fold would silently zero out every
    Footballguys defense's key. Load-bearing; left alone.

    This is the FALLBACK path - see `resolve_key`, which every real caller
    in this project should actually use. A composite of visible fields can
    never be proven unique (nothing stops two same-named players at the
    same position on the same team), which is exactly why `resolve_key`
    prefers a real CBS player id whenever one is available and only falls
    back to this.
    """
    p = (pos or "").strip().upper()
    if p in ("DEF", "D", "D/ST", "DST", "TD"):
        p = "DST"
    if p in ("PK",):
        p = "K"
    return "%s|%s|%s" % (normalize_name(name), normalize_team(team), p)


def resolve_key(player_id, name, team, pos):
    """The join key this project should actually use: a real CBS player id
    when one is present, `player_key`'s (name, team, pos) heuristic
    otherwise.

    CBS's roster and CBS ↔ CBS position-group projection pages both carry a
    stable numeric id per individual player (lifted from a `playerpage/<id>`
    link - see `sffl.capture` and `sffl.cbs_weekly`/`sffl.cbs_roster`). That
    id, when both sides of a join have it, is a GENUINELY unique key - unlike
    the composite, nothing about it depends on how CBS chose to spell a name
    or abbreviate a team this week. It does NOT help any other join: no
    non-CBS vendor (draftsharks, footballguys, StatsDeck's injury feed) ever
    populates `player_id`, so those rows always fall through to the composite
    key here, exactly as they always have.

    The id is namespaced (`"id:<n>"`) so it can never collide with a
    composite key's `"name|team|pos"` shape - a row with an id and a row
    without one can never accidentally compare equal just because one
    happens to look like the other's string.
    """
    if player_id:
        return "id:%s" % player_id
    return player_key(name, team, pos)


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

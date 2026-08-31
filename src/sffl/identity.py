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
    """A SINGLE key per row: a real CBS player id when one is present,
    `player_key`'s (name, team, pos) heuristic otherwise.

    CORRECTED, Task 3b review round 1: earlier prose in this project
    (including this docstring) called this a "both sides of a join have
    it" mechanism. IT IS NOT - it is a per-row key choice with no
    awareness of what the OTHER side of a comparison has. That is exactly
    correct for a SYMMETRIC, single-source use - deduplicating one set of
    rows against itself (`sffl.cli._merge_projection_groups`, `_cmd_alert`'s
    own `by_key` residual-duplicate check) - because there is no separate
    "other side" to fall back against there: every row in the set is
    measured the same way.

    IT IS THE WRONG TOOL for an ASYMMETRIC cross-source join - matching one
    set of rows (e.g. CBS roster rows) against a DIFFERENT set (e.g. CBS
    projection rows) - because the two sides can legitimately disagree
    about whether an id is available AT ALL: one page's capture can lose
    its ids independently of another's. Using `resolve_key` for that
    reproduced, live, a prohibited outcome: roster rows carrying real ids
    matched against projection rows that this run carried none of - EVERY
    lookup computed an `"id:<n>"` key, nothing in the projections index was
    ever stored under such a key (every projection fell back to a
    composite key of its own, since `resolve_key` never computes a
    composite once a row has an id), so NOTHING matched anything - BEST
    LINEUP 0.00 pts, every slot UNFILLED, exit 0, no DEGRADED banner. See
    `IdentityIndex` below, which is the correct tool for that case and is
    what `_cmd_alert`'s roster ↔ projections join now uses instead.

    The id is namespaced (`"id:<n>"`) so it can never collide with a
    composite key's `"name|team|pos"` shape - a row with an id and a row
    without one can never accidentally compare equal just because one
    happens to look like the other's string.
    """
    if player_id:
        return "id:%s" % player_id
    return player_key(name, team, pos)


# Sentinel stored in `IdentityIndex._by_composite` the moment a SECOND,
# DIFFERENT row claims a composite key already claimed by another - see
# `IdentityIndex.add`. Never returned to a caller; `IdentityIndex.get`
# translates it back to "not found."
_AMBIGUOUS = object()


class IdentityIndex(object):
    """A CBS ↔ CBS lookup table for an ASYMMETRIC cross-source join:
    id-first, with a genuine TWO-STEP fallback to the (name, team, pos)
    composite - NOT `resolve_key`'s single per-row key choice (see its own
    docstring for why that is the wrong tool here, and the prohibited
    outcome using it produced).

    Every row is added under BOTH its id (when it has one) AND its
    composite key, so a lookup succeeds via WHICHEVER key the CALLER
    happens to supply, regardless of which key the STORED row happens to
    have. That is what makes this robust to an asymmetric id loss on
    EITHER side: a roster row with an id still finds a projection that
    lost its ids this run (the reproduced case), and - symmetrically - a
    roster row that lost ITS id still finds a projection that still has
    one, via that projection's own composite entry.

    A composite key claimed by more than one DIFFERENT row is retired the
    moment a second claimant appears (mapped internally to `_AMBIGUOUS`) -
    silently picking one of two genuinely ambiguous rows would be exactly
    the guess this project refuses to make elsewhere (see `player_key`'s
    own docstring), so a composite-only lookup for that key finds nothing
    - an honest "unresolved," not a coin flip. This never weakens an id
    lookup: two different rows with different ids are never ambiguous by
    id, so each is still found correctly via its OWN id regardless of
    what happened to its composite entry (see `_cmd_alert`'s test for two
    same-name/team/position rows told apart only by their ids - this is
    exactly the case the ordering of `get` below protects).

    Callers are expected to have already deduplicated their own rows by
    `resolve_key` (e.g. `_cmd_alert`'s `by_key`) before calling `add` -
    this class does not detect or report an id COLLISION (two DIFFERENT
    rows sharing the identical id); that is a different, already-handled
    concern, and `add` here deliberately keeps the FIRST row seen under a
    given id (mirroring `by_key`'s own "keep the first, drop the second"
    convention) rather than silently overwriting it with a later one.
    """

    def __init__(self):
        self._by_id = {}
        self._by_composite = {}

    def add(self, player_id, name, team, pos, value):
        """Index `value`, identified by `(player_id, name, team, pos)`."""
        if player_id and player_id not in self._by_id:
            self._by_id[player_id] = value
        composite = player_key(name, team, pos)
        if composite in self._by_composite:
            self._by_composite[composite] = _AMBIGUOUS
        else:
            self._by_composite[composite] = value

    def get(self, player_id, name, team, pos):
        """The matching value, or `None` - id first, composite fallback.

        Never guesses among ambiguous composite claimants (see the class
        docstring): such a key resolves to `None`, exactly like a key
        nothing was ever added under.
        """
        if player_id and player_id in self._by_id:
            return self._by_id[player_id]
        composite = player_key(name, team, pos)
        found = self._by_composite.get(composite)
        return found if found is not _AMBIGUOUS else None


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

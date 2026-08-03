"""Resolve player identity across sources.

Three layers, in order: deterministic normalization, an alias file, then fuzzy
matching with a review queue. This module is layer one.
"""

import re

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


def normalize_name(s):
    """Lowercase, strip punctuation and generational suffixes, collapse spaces."""
    if s is None:
        return ""
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

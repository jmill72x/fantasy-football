# Scoring Foundation & Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command turns any vendor's projection export into a scored, league-correct SFFL player pool, including Team QB units built from individual quarterbacks.

**Architecture:** A YAML league profile holds every scoring band and roster rule. A pure scoring module applies those bands to a stat line. Vendor CSVs are normalized into one canonical record via data-only source profiles, with player identity resolved through normalization, an alias file, and fuzzy matching that fails loudly. Team QB units are aggregated from per-quarterback stat lines, so no vendor needs to support the slot.

**Tech Stack:** Python 3.9, pytest, PyYAML, rapidfuzz.

## Global Constraints

- **Python 3.9.6 is the only interpreter available.** No `match` statements, no PEP 604 (`int | None`) annotations at runtime. Use `typing.Optional`/`List`/`Dict`, or `from __future__ import annotations`.
- **All work happens in a project venv at `.venv/`** — already gitignored. Never install into system Python.
- **`data/extracts/` is gitignored** and holds licensed vendor data. Never commit files from it. Test fixtures must be small hand-written excerpts committed to `tests/fixtures/`, not copies of vendor files.
- **Scoring is banded, not per-unit.** Every band table is a list of `(low, high, points)` tuples, inclusive on both ends. A value outside every band scores 0.
- **Sacks:** 0 below 3, then 3 points at exactly 3, then +1 per sack after. Verified against real CBS output; do not "fix" it.
- **WR and TE are one position** for valuation. Keep the source's label for display, but never treat them as separate pools.
- **Unmatched players must raise or be reported. Never silently drop a player.**

---

### Task 1: Project scaffolding and league profile

**Files:**
- Create: `pyproject.toml`
- Create: `src/sffl/__init__.py`
- Create: `src/sffl/league.py`
- Create: `leagues/sffl/2026.yaml`
- Test: `tests/test_league.py`

**Interfaces:**
- Consumes: nothing
- Produces: `load_league(path: str) -> LeagueProfile`. `LeagueProfile` has attributes `teams: int`, `budget: int`, `roster_size: int`, `flex_slots: int`, `bands: Dict[str, List[Tuple[int,int,int]]]`, `points: Dict[str, float]`.

- [ ] **Step 1: Create the venv and install dependencies**

```bash
cd /Users/jeff/Projects/fantasy-football
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet pytest PyYAML rapidfuzz
./.venv/bin/python -c "import pytest, yaml, rapidfuzz; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "sffl"
version = "0.1.0"
description = "Auction cheatsheet pipeline for the Stripes Fantasy Football League"
requires-python = ">=3.9"
dependencies = ["PyYAML>=6.0", "rapidfuzz>=3.0"]

[project.optional-dependencies]
dev = ["pytest>=7.0"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 3: Create `leagues/sffl/2026.yaml`**

```yaml
# STRIPES FANTASY FOOTBALL LEAGUE - 2026
# Every band is [low, high, points], inclusive both ends. Outside all bands = 0.
name: STRIPES FANTASY FOOTBALL LEAGUE
season: 2026
teams: 12
budget: 110
roster_size: 13
starters: 8
flex_slots: 5          # RB/WR/TE, floor of 1 RB and 1 WR/TE
silent_auction:
  bid_floor: 26
  bump_charged_only_on_winning_tie: true

bands:
  pass_yds:  [[150, 250, 2], [251, 350, 4], [351, 450, 5], [451, 9999, 7]]
  pass_cmp:  [[15, 19, 2], [20, 24, 3], [25, 29, 4], [30, 34, 5], [35, 39, 6], [40, 99, 7]]
  rush_yds:  [[50, 74, 2], [75, 99, 3], [100, 124, 4], [125, 149, 5], [150, 174, 6],
              [175, 199, 7], [200, 224, 8], [225, 249, 9], [250, 9999, 10]]
  rec_yds:   [[50, 74, 1], [75, 99, 2], [100, 124, 3], [125, 149, 4], [150, 174, 5],
              [175, 199, 6], [200, 9999, 7]]
  rec_ct:    [[5, 6, 2], [7, 8, 3], [9, 10, 4], [11, 12, 6], [13, 99, 7]]
  def_pa:    [[0, 2, 6], [3, 5, 5], [6, 6, 4], [7, 9, 3], [10, 13, 2], [14, 14, 1], [15, 99, 0]]
  def_ya:    [[0, 150, 6], [151, 250, 4], [251, 299, 3], [300, 350, 2],
              [351, 399, 0], [400, 499, -1], [500, 9999, -2]]

points:
  pass_td: 5
  pass_td_long_bonus: 1      # 36+ yards
  pass_int: -1
  pass_2pt: 2
  rush_td: 3
  rush_td_mid_bonus: 2       # 3-35 yards
  rush_td_long_bonus: 5      # 36+ yards
  rush_2pt: 2
  rec_td: 5
  rec_td_mid_bonus: 1        # 36-74 yards
  rec_td_long_bonus: 3       # 75+ yards
  rec_2pt: 2
  off_fum_rec_td: 4
  xp_made: 1
  fg_under_30: 2
  fg_30_39: 3
  fg_40_49: 4
  fg_50_59: 5
  fg_60_plus: 8
  fg_missed: -1
  def_td: 6
  def_safety: 4
  def_int: 1
  def_fum_rec: 1
  def_st_2pt: 2
  def_st_1pt_safety: 1

# Sacks: 0 below 3, 3 points at exactly 3, +1 per sack after.
# Verified against real CBS output (poc/verify_dst_scoring.py). Do not change.
sack_rule:
  threshold: 3
  threshold_points: 3
  per_sack_after: 1
```

- [ ] **Step 4: Write the failing test**

Create `tests/test_league.py`:

```python
from sffl.league import load_league

PROFILE = "leagues/sffl/2026.yaml"


def test_loads_structure():
    lg = load_league(PROFILE)
    assert lg.teams == 12
    assert lg.budget == 110
    assert lg.roster_size == 13
    assert lg.flex_slots == 5


def test_total_capital_and_surplus():
    lg = load_league(PROFILE)
    assert lg.total_capital() == 1320
    assert lg.total_spots() == 156
    assert lg.surplus() == 1164


def test_bands_are_tuples_of_three_ints():
    lg = load_league(PROFILE)
    for name, table in lg.bands.items():
        for row in table:
            assert len(row) == 3, name
            assert all(isinstance(v, int) for v in row), name


def test_sack_rule_present():
    lg = load_league(PROFILE)
    assert lg.sack_rule["threshold"] == 3
    assert lg.sack_rule["threshold_points"] == 3
    assert lg.sack_rule["per_sack_after"] == 1
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_league.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl'`

- [ ] **Step 6: Implement the loader**

Create `src/sffl/__init__.py` as an empty file, then `src/sffl/league.py`:

```python
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
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_league.py -v`
Expected: 4 passed

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/sffl/__init__.py src/sffl/league.py leagues/sffl/2026.yaml tests/test_league.py
git commit -m "feat: league profile with all SFFL scoring bands as data"
```

---

### Task 2: Scoring engine

**Files:**
- Create: `src/sffl/scoring.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `load_league`, `LeagueProfile` from Task 1.
- Produces:
  - `band_points(table: List[Tuple[int,int,int]], value: float) -> int`
  - `sack_points(rule: Dict, n: float) -> float`
  - `score_game(lg: LeagueProfile, stats: Dict[str, float]) -> float` — `stats` keys are
    `pass_yds pass_cmp pass_td pass_int pass_2pt rush_yds rush_td rush_2pt rec_yds rec_ct
    rec_td rec_2pt xp_made fg_u30 fg_30_39 fg_40_49 fg_50_59 fg_60 fg_missed def_pa def_ya
    def_sack def_int def_fum_rec def_td def_safety`. All optional, default 0.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scoring.py`:

```python
import pytest

from sffl.league import load_league
from sffl.scoring import band_points, sack_points, score_game

PROFILE = "leagues/sffl/2026.yaml"


@pytest.fixture(scope="module")
def lg():
    return load_league(PROFILE)


def test_band_boundaries_inclusive(lg):
    t = lg.bands["rec_yds"]
    assert band_points(t, 49) == 0     # below the floor
    assert band_points(t, 50) == 1     # first band, lower edge
    assert band_points(t, 74) == 1     # first band, upper edge
    assert band_points(t, 75) == 2     # next band
    assert band_points(t, 200) == 7
    assert band_points(t, 999) == 7


def test_reception_floor(lg):
    t = lg.bands["rec_ct"]
    assert band_points(t, 4) == 0
    assert band_points(t, 5) == 2
    assert band_points(t, 13) == 7


def test_sack_rule(lg):
    r = lg.sack_rule
    assert sack_points(r, 0) == 0
    assert sack_points(r, 2) == 0
    assert sack_points(r, 3) == 3
    assert sack_points(r, 4) == 4
    assert sack_points(r, 7) == 7


# Golden file: Eagles DST 2025 weeks 13-17, stat lines and the points CBS awarded.
DST_GOLDEN = [
    (dict(def_pa=24, def_ya=425, def_int=1, def_sack=2), 0),
    (dict(def_pa=22, def_ya=275, def_int=1, def_fum_rec=2, def_sack=7), 13),
    (dict(def_pa=0, def_ya=75, def_int=1, def_sack=4), 17),
    (dict(def_pa=18, def_ya=220, def_int=1, def_sack=2), 5),
    (dict(def_pa=12, def_ya=331, def_fum_rec=1, def_sack=5), 10),
]


@pytest.mark.parametrize("stats,expected", DST_GOLDEN)
def test_dst_matches_real_cbs_output(lg, stats, expected):
    assert score_game(lg, stats) == expected


def test_receiving_game(lg):
    # 6 catches (band 5-6 = 2), 85 yards (band 75-99 = 2)
    assert score_game(lg, dict(rec_ct=6, rec_yds=85)) == 4


def test_below_all_floors_scores_zero(lg):
    assert score_game(lg, dict(rec_ct=3, rec_yds=40, rush_yds=30)) == 0


def test_kicking(lg):
    # 2 XP + one 45-yarder (4) + one 55-yarder (5) + one miss (-1)
    assert score_game(lg, dict(xp_made=2, fg_40_49=1, fg_50_59=1, fg_missed=1)) == 10
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.scoring'`

- [ ] **Step 3: Implement the scoring engine**

Create `src/sffl/scoring.py`:

```python
"""Apply SFFL banded scoring to a single game stat line.

Bands are inclusive on both ends. A value outside every band scores 0, which is
how the league's hard floors work: under 50 receiving yards is worth nothing.
"""


def band_points(table, value):
    """Return the points for `value` in a [(low, high, points), ...] table."""
    for low, high, pts in table:
        if low <= value <= high:
            return pts
    return 0


def sack_points(rule, n):
    """Sacks score 0 below the threshold, then a flat award, then +1 each after.

    Verified against real CBS output: a 4-sack game scored 4, not 7, so the
    threshold award subsumes the first three sacks rather than adding to them.
    """
    if n < rule["threshold"]:
        return 0
    return rule["threshold_points"] + (n - rule["threshold"]) * rule["per_sack_after"]


def score_game(lg, stats):
    """Total SFFL points for one game's stat line."""
    g = stats.get
    p = lg.points
    total = 0.0

    total += band_points(lg.bands["pass_yds"], g("pass_yds", 0))
    total += band_points(lg.bands["pass_cmp"], g("pass_cmp", 0))
    total += g("pass_td", 0) * p["pass_td"]
    total += g("pass_int", 0) * p["pass_int"]
    total += g("pass_2pt", 0) * p["pass_2pt"]

    total += band_points(lg.bands["rush_yds"], g("rush_yds", 0))
    total += g("rush_td", 0) * p["rush_td"]
    total += g("rush_2pt", 0) * p["rush_2pt"]

    total += band_points(lg.bands["rec_yds"], g("rec_yds", 0))
    total += band_points(lg.bands["rec_ct"], g("rec_ct", 0))
    total += g("rec_td", 0) * p["rec_td"]
    total += g("rec_2pt", 0) * p["rec_2pt"]

    total += g("xp_made", 0) * p["xp_made"]
    total += g("fg_u30", 0) * p["fg_under_30"]
    total += g("fg_30_39", 0) * p["fg_30_39"]
    total += g("fg_40_49", 0) * p["fg_40_49"]
    total += g("fg_50_59", 0) * p["fg_50_59"]
    total += g("fg_60", 0) * p["fg_60_plus"]
    total += g("fg_missed", 0) * p["fg_missed"]

    if "def_pa" in stats or "def_ya" in stats:
        total += band_points(lg.bands["def_pa"], g("def_pa", 0))
        total += band_points(lg.bands["def_ya"], g("def_ya", 0))
        total += sack_points(lg.sack_rule, g("def_sack", 0))
        total += g("def_int", 0) * p["def_int"]
        total += g("def_fum_rec", 0) * p["def_fum_rec"]
        total += g("def_td", 0) * p["def_td"]
        total += g("def_safety", 0) * p["def_safety"]

    return total
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_scoring.py -v`
Expected: 11 passed (5 of them the parametrized DST golden cases)

- [ ] **Step 5: Commit**

```bash
git add src/sffl/scoring.py tests/test_scoring.py
git commit -m "feat: banded scoring engine, verified against real CBS DST output"
```

---

### Task 3: Canonical schema and name normalization

**Files:**
- Create: `src/sffl/schema.py`
- Create: `src/sffl/identity.py`
- Test: `tests/test_identity.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PlayerProjection` dataclass with fields `name, team, pos, source, source_year, games, stats (Dict[str,float]), raw_name`
  - `normalize_name(s: str) -> str`
  - `normalize_team(s: str) -> str`
  - `player_key(name: str, team: str, pos: str) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_identity.py`:

```python
from sffl.identity import normalize_name, normalize_team, player_key


def test_strips_suffixes():
    assert normalize_name("Marvin Harrison Jr.") == "marvin harrison"
    assert normalize_name("Kenneth Walker III") == "kenneth walker"
    assert normalize_name("Aaron Jones Sr.") == "aaron jones"
    assert normalize_name("Michael Penix Jr.") == "michael penix"


def test_folds_punctuation_and_case():
    assert normalize_name("Ja'Marr Chase") == "jamarr chase"
    assert normalize_name("De'Von Achane") == "devon achane"
    assert normalize_name("T.J. Hockenson") == "tj hockenson"
    assert normalize_name("  Amon-Ra  St. Brown ") == "amon ra st brown"


def test_canonical_teams():
    assert normalize_team("JAX") == "JAC"
    assert normalize_team("JAC") == "JAC"
    assert normalize_team("LVR") == "LV"
    assert normalize_team("LV") == "LV"
    assert normalize_team("WSH") == "WAS"
    assert normalize_team("wsh") == "WAS"
    assert normalize_team("") == ""


def test_player_key_is_stable_across_sources():
    # Draft Sharks says "Cameron Ward / TEN"; Footballguys says "Cam Ward / TEN".
    # Normalization alone does NOT unify these - that is the alias layer's job.
    a = player_key("Trevor Lawrence", "JAC", "QB")
    b = player_key("Trevor Lawrence", "JAX", "qb")
    assert a == b == "trevor lawrence|JAC|QB"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_identity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.identity'`

- [ ] **Step 3: Implement the schema**

Create `src/sffl/schema.py`:

```python
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
```

- [ ] **Step 4: Implement normalization**

Create `src/sffl/identity.py`:

```python
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
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[.\-_]", " ", s)
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_identity.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/sffl/schema.py src/sffl/identity.py tests/test_identity.py
git commit -m "feat: canonical schema and deterministic name/team normalization"
```

---

### Task 4: Alias file and fuzzy matching with a review queue

**Files:**
- Create: `identity/aliases.yaml`
- Modify: `src/sffl/identity.py` (append a `Resolver` class)
- Test: `tests/test_resolver.py`

**Interfaces:**
- Consumes: `normalize_name`, `normalize_team`, `player_key` from Task 3.
- Produces: `Resolver(alias_path: str)` with
  - `.resolve(name: str, team: str, pos: str) -> str` returning a canonical key
  - `.register(keys: Iterable[str])` to seed the known universe
  - `.unresolved: List[Tuple[str, str, str, List[Tuple[str, float]]]]` — each entry is
    `(name, team, pos, candidates)` where candidates are `(key, score)` pairs

- [ ] **Step 1: Create `identity/aliases.yaml`**

```yaml
# Hand-maintained player name aliases. Grows every year; this file is the asset.
# Left side is the vendor's spelling, right side the canonical spelling.
# Team and position are matched separately, so only the name goes here.
players:
  "Cam Ward": "Cameron Ward"
  "Jamaar Chase": "Ja'Marr Chase"
  "Jaamyr Gibbs": "Jahmyr Gibbs"
  "Tyreke Hill": "Tyreek Hill"
  "Tua Tagovioloa": "Tua Tagovailoa"
  "Marvin Harrson Jr": "Marvin Harrison Jr."
  "TJ Hochenson": "T.J. Hockenson"
  "Cam Skatebo": "Cam Skattebo"
  "Aaron Rogers": "Aaron Rodgers"
  "Jokobi Meyers": "Jakobi Meyers"
  "Tyler Algier": "Tyler Allgeier"
  "Marvin Mimms Jr": "Marvin Mims Jr."
  "Chase Maclaughlin": "Chase McLaughlin"
  "Davon Achane": "De'Von Achane"
  "Terry Maclaurin": "Terry McLaurin"
  "Brandonaiyuk": "Brandon Aiyuk"
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_resolver.py`:

```python
from sffl.identity import Resolver, player_key

ALIASES = "identity/aliases.yaml"


def make():
    r = Resolver(ALIASES)
    r.register([
        player_key("Cameron Ward", "TEN", "QB"),
        player_key("Ja'Marr Chase", "CIN", "WR"),
        player_key("Jahmyr Gibbs", "DET", "RB"),
        player_key("Brandon Aiyuk", "SF", "WR"),
    ])
    return r


def test_exact_match_after_normalization():
    r = make()
    assert r.resolve("Ja'Marr Chase", "CIN", "WR") == player_key("Ja'Marr Chase", "CIN", "WR")


def test_alias_file_resolves_cam_ward():
    r = make()
    assert r.resolve("Cam Ward", "TEN", "qb") == player_key("Cameron Ward", "TEN", "QB")


def test_alias_handles_missing_space():
    r = make()
    assert r.resolve("BRANDONAIYUK", "SF", "WR") == player_key("Brandon Aiyuk", "SF", "WR")


def test_fuzzy_match_catches_a_typo():
    r = make()
    got = r.resolve("Jahmyr Gibs", "DET", "RB")
    assert got == player_key("Jahmyr Gibbs", "DET", "RB")


def test_unknown_player_is_reported_not_dropped():
    r = make()
    got = r.resolve("Completely Unknown Person", "XXX", "WR")
    assert got is None
    assert len(r.unresolved) == 1
    name, team, pos, candidates = r.unresolved[0]
    assert name == "Completely Unknown Person"
    assert isinstance(candidates, list)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_resolver.py -v`
Expected: FAIL with `ImportError: cannot import name 'Resolver'`

- [ ] **Step 4: Append the `Resolver` to `src/sffl/identity.py`**

Add these imports at the top of the file, after the existing `import re`:

```python
import yaml
from rapidfuzz import fuzz, process
```

Then append to the end of the file:

```python
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_resolver.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add identity/aliases.yaml src/sffl/identity.py tests/test_resolver.py
git commit -m "feat: alias file and fuzzy resolver that reports rather than drops"
```

---

### Task 5: Source profiles and the Draft Sharks adapter

**Files:**
- Create: `src/sffl/ingest/__init__.py`
- Create: `src/sffl/ingest/profiles.py`
- Create: `sources/draftsharks.yaml`
- Create: `tests/fixtures/draftsharks_sample.csv`
- Test: `tests/test_ingest_ds.py`

**Interfaces:**
- Consumes: `PlayerProjection` (Task 3).
- Produces:
  - `load_profile(path: str) -> SourceProfile` with `.name`, `.year_from_path`, `.columns` (dict of canonical stat -> index or header name), `.by_index: bool`, `.filters: dict`
  - `read_extract(profile: SourceProfile, csv_path: str, year: int) -> List[PlayerProjection]`

**Why index-based mapping exists:** the Draft Sharks export reuses header names
across stat groups (`Total`, `YDs`, `TDs` each appear multiple times), so a
name-keyed reader silently collapses columns. Profiles therefore support
positional mapping.

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/draftsharks_sample.csv` — a hand-written excerpt with the
real header shape and four rows, one per position family:

```csv
Rank,Team,Player,"Fantasy Position",Games,"3D Proj",Total,Att.,Comp,YDs,TDs,Int,Total,YDs,TDs,Total,Rec,YDs,TDs,Total,"PR YDs","KR YDs",TDs,Total,XPs,"FGs < 30",30-39,40-49,50-59,60+,Total,"Opp Pts","Opp Yds",Sacks,INTs,"Fum Rec",TDs,Total,Solo,Assists,Sacks,"Pass Defended",Ints,"Forced Fumble","Fum Rec",TDs,"3D Value"
1,BUF,"Josh Allen",QB,17,382,262.62,516.8,348.5,3981.4,28.39,10.2,116.28,598.4,10.54,0,0,0,0,0,0,0,,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,63
2,DET,"Jahmyr Gibbs",RB,17,285,0,0,0,0,0,0,198.05,1249.5,12.75,82.62,71.4,591.6,3.91,0,0,0,,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,100
3,CIN,"Ja'Marr Chase",WR,17,300,0,0,0,0,0,0,5.1,34,0.34,255,125.8,1587,9.2,0,0,0,,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,95
4,PHI,"Eagles",DEF,17,120,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,,0,0,0,0,0,0,110,310,4930,42,14,9,3,0,0,0,0,0,0,0,0,0,0,40
```

- [ ] **Step 2: Create `sources/draftsharks.yaml`**

```yaml
name: draftsharks
files: ["rankings*.csv"]
by_index: true          # header names repeat across stat groups
skip_rows: 1
columns:
  team: 1
  name: 2
  pos: 3
  games: 4
  pass_att: 7
  pass_cmp: 8
  pass_yds: 9
  pass_td: 10
  pass_int: 11
  rush_yds: 13
  rush_td: 14
  rec_ct: 16
  rec_yds: 17
  rec_td: 18
  xp_made: 24
  fg_u30: 25
  fg_30_39: 26
  fg_40_49: 27
  fg_50_59: 28
  fg_60: 29
  def_pa: 31
  def_ya: 32
  def_sack: 33
  def_int: 34
  def_fum_rec: 35
  def_td: 36
capabilities:
  provides_fg_distance_bands: true
  provides_two_point: false
  provides_def_safety: false
  multi_set: false
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_ingest_ds.py`:

```python
from sffl.ingest.profiles import load_profile, read_extract

PROFILE = "sources/draftsharks.yaml"
FIXTURE = "tests/fixtures/draftsharks_sample.csv"


def test_profile_is_index_based():
    p = load_profile(PROFILE)
    assert p.name == "draftsharks"
    assert p.by_index is True
    assert p.columns["pass_cmp"] == 8


def test_reads_all_rows():
    rows = read_extract(load_profile(PROFILE), FIXTURE, 2026)
    assert len(rows) == 4
    assert {r.pos for r in rows} == {"QB", "RB", "WR", "DST"}


def test_quarterback_stats_land_in_the_right_slots():
    rows = read_extract(load_profile(PROFILE), FIXTURE, 2026)
    allen = [r for r in rows if r.name == "Josh Allen"][0]
    assert allen.team == "BUF"
    assert allen.games == 17
    assert allen.stats["pass_yds"] == 3981.4
    assert allen.stats["pass_cmp"] == 348.5
    assert allen.stats["rush_yds"] == 598.4
    assert round(allen.stats["rush_td"], 2) == 10.54


def test_defense_position_is_canonicalized():
    rows = read_extract(load_profile(PROFILE), FIXTURE, 2026)
    d = [r for r in rows if r.pos == "DST"][0]
    assert d.stats["def_pa"] == 310
    assert d.stats["def_sack"] == 42


def test_blank_cells_become_zero_not_crash():
    rows = read_extract(load_profile(PROFILE), FIXTURE, 2026)
    for r in rows:
        for v in r.stats.values():
            assert isinstance(v, float)
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_ingest_ds.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.ingest'`

- [ ] **Step 5: Implement the profile loader and reader**

Create `src/sffl/ingest/__init__.py` as an empty file, then `src/sffl/ingest/profiles.py`:

```python
"""Read a vendor CSV into canonical records, driven entirely by a YAML profile.

Adding a source is a new YAML file, not new code.
"""

import csv
from typing import Dict, List

import yaml

from sffl.identity import normalize_team, player_key
from sffl.schema import PlayerProjection

# Everything except these is treated as a stat to be parsed as a float.
META = ("name", "team", "pos", "games", "set_name")


class SourceProfile(object):
    def __init__(self, raw):
        self.name = raw["name"]
        self.files = raw.get("files", ["*.csv"])
        self.by_index = bool(raw.get("by_index", False))
        self.skip_rows = int(raw.get("skip_rows", 1))
        self.columns = raw["columns"]  # type: Dict[str, object]
        self.filters = raw.get("filters", {})
        self.capabilities = raw.get("capabilities", {})


def load_profile(path):
    with open(path) as fh:
        return SourceProfile(yaml.safe_load(fh))


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0


def _cell(row, spec, by_index):
    if by_index:
        idx = int(spec)
        return row[idx] if idx < len(row) else ""
    return row.get(spec, "")


def read_extract(profile, csv_path, year):
    """Return a list of PlayerProjection from one vendor CSV."""
    out = []  # type: List[PlayerProjection]
    with open(csv_path, newline="") as fh:
        if profile.by_index:
            reader = csv.reader(fh)
            rows = list(reader)[profile.skip_rows:]
        else:
            rows = list(csv.DictReader(fh))

    cols = profile.columns
    for row in rows:
        raw_name = str(_cell(row, cols["name"], profile.by_index)).strip()
        if not raw_name:
            continue

        keep = True
        for field, allowed in profile.filters.items():
            val = str(_cell(row, cols[field], profile.by_index)).strip()
            if val not in allowed:
                keep = False
                break
        if not keep:
            continue

        pos_raw = str(_cell(row, cols["pos"], profile.by_index)).strip()
        pos = player_key("", "", pos_raw).split("|")[2]
        team = normalize_team(str(_cell(row, cols["team"], profile.by_index)))
        games = _num(_cell(row, cols["games"], profile.by_index))

        stats = {}
        for field, spec in cols.items():
            if field in META:
                continue
            stats[field] = _num(_cell(row, spec, profile.by_index))

        set_name = None
        if "set_name" in cols:
            set_name = str(_cell(row, cols["set_name"], profile.by_index)).strip() or None

        out.append(PlayerProjection(
            name=raw_name, team=team, pos=pos, source=profile.name,
            source_year=year, games=games, stats=stats,
            raw_name=raw_name, set_name=set_name,
        ))
    return out
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_ingest_ds.py -v`
Expected: 5 passed

- [ ] **Step 7: Verify against the real extract**

```bash
./.venv/bin/python -c "
from sffl.ingest.profiles import load_profile, read_extract
import collections
rows = read_extract(load_profile('sources/draftsharks.yaml'),
                    'data/extracts/Draft Sharks/2026/rankings (1).csv', 2026)
print(len(rows), 'players')
print(dict(collections.Counter(r.pos for r in rows)))
a = [r for r in rows if r.name == 'Josh Allen'][0]
print('Allen pass_yds', a.stats['pass_yds'], 'rush_yds', a.stats['rush_yds'])
"
```

Expected: `553 players`, positions `{'RB': 130, 'WR': 204, 'QB': 42, 'TE': 108, 'K': 37, 'DST': 32}`, and `Allen pass_yds 3981.4 rush_yds 598.4`.

- [ ] **Step 8: Commit**

```bash
git add src/sffl/ingest sources/draftsharks.yaml tests/fixtures/draftsharks_sample.csv tests/test_ingest_ds.py
git commit -m "feat: YAML-driven source profiles and Draft Sharks adapter"
```

---

### Task 6: Footballguys adapter with multi-set support

**Files:**
- Create: `sources/footballguys.yaml`
- Create: `tests/fixtures/footballguys_sample.csv`
- Test: `tests/test_ingest_fbg.py`

**Interfaces:**
- Consumes: `load_profile`, `read_extract` from Task 5. No code changes — this task
  proves the profile mechanism handles a structurally different vendor.
- Produces: nothing new; adds `sources/footballguys.yaml`.

**Why this matters:** the Footballguys file holds 18 projection sets stacked in one
CSV, keyed by `set-name`. Each set is an independent analyst. Filtering to one set
is a profile concern, and the spread across sets is the variance signal the value
engine will use later.

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/footballguys_sample.csv`:

```csv
id,name,pos,team,set-id,set-name,ssn-gms,pass-2pt,pass-att,pass-cmp,pass-int,pass-td,pass-yds,rush-2pt,rush-car,rush-td,rush-yds,rec-2pt,rec-rec,rec-tgt,rec-td,rec-yds,kck-xpc,kck-fgc,tmd-fmr,tmd-int,tmd-pa,tmd-sck,tmd-saf,tmd-td,tmd-ya
AlleJo00,Josh Allen,qb,BUF,66513,Consensus,16.1,1.2,520.0,349.0,10.1,29.0,4010.0,0.4,120.0,10.2,610.0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
AlleJo00,Josh Allen,qb,BUF,66483,Dan Hindery,16.5,1.0,533.0,360.0,9.4,31.0,4180.0,0.5,128.0,11.1,690.0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
WardCa00,Cam Ward,qb,TEN,66513,Consensus,16.0,0.8,540.0,338.0,13.0,22.0,3800.0,0.2,60.0,2.0,230.0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
ChasJa00,Ja'Marr Chase,wr,CIN,66513,Consensus,16.4,0.6,0,0,0,0,0,0.1,4.0,0.2,26.0,0.7,120.0,175.0,9.0,1550.0,0,0,0,0,0,0,0,0,0
EaglPh00,Eagles,td,PHI,66513,Consensus,17.0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,9.0,14.0,318.0,44.0,1.0,3.0,5010.0
```

- [ ] **Step 2: Create `sources/footballguys.yaml`**

```yaml
name: footballguys
files: ["projection-set-*.csv"]
by_index: false
columns:
  name: name
  team: team
  pos: pos
  games: ssn-gms
  set_name: set-name
  pass_att: pass-att
  pass_cmp: pass-cmp
  pass_yds: pass-yds
  pass_td: pass-td
  pass_int: pass-int
  pass_2pt: pass-2pt
  rush_yds: rush-yds
  rush_td: rush-td
  rush_2pt: rush-2pt
  rec_ct: rec-rec
  rec_yds: rec-yds
  rec_td: rec-td
  rec_2pt: rec-2pt
  xp_made: kck-xpc
  def_pa: tmd-pa
  def_ya: tmd-ya
  def_sack: tmd-sck
  def_int: tmd-int
  def_fum_rec: tmd-fmr
  def_td: tmd-td
  def_safety: tmd-saf
filters:
  pos: ["qb", "rb", "wr", "te", "pk", "td"]   # drop IDP rows
capabilities:
  provides_fg_distance_bands: false           # only fgc, no distance split
  provides_two_point: true
  provides_def_safety: true
  multi_set: true
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_ingest_fbg.py`:

```python
from sffl.ingest.profiles import load_profile, read_extract

PROFILE = "sources/footballguys.yaml"
FIXTURE = "tests/fixtures/footballguys_sample.csv"


def rows():
    return read_extract(load_profile(PROFILE), FIXTURE, 2026)


def test_profile_is_name_based():
    p = load_profile(PROFILE)
    assert p.by_index is False
    assert p.columns["pass_cmp"] == "pass-cmp"
    assert p.capabilities["multi_set"] is True


def test_reads_every_set_row():
    r = rows()
    assert len(r) == 5
    assert {x.set_name for x in r} == {"Consensus", "Dan Hindery"}


def test_same_player_appears_once_per_set():
    allen = [x for x in rows() if x.name == "Josh Allen"]
    assert len(allen) == 2
    by_set = {x.set_name: x.stats["rush_yds"] for x in allen}
    assert by_set["Consensus"] == 610.0
    assert by_set["Dan Hindery"] == 690.0


def test_lowercase_positions_are_canonicalized():
    r = rows()
    assert {x.pos for x in r} == {"QB", "WR", "DST"}


def test_two_point_conversions_are_captured():
    allen = [x for x in rows() if x.name == "Josh Allen"
             and x.set_name == "Consensus"][0]
    assert allen.stats["pass_2pt"] == 1.2
    assert allen.stats["rush_2pt"] == 0.4


def test_defense_safety_is_captured():
    d = [x for x in rows() if x.pos == "DST"][0]
    assert d.stats["def_safety"] == 1.0
    assert d.stats["def_ya"] == 5010.0
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_ingest_fbg.py -v`
Expected: FAIL — `sources/footballguys.yaml` filters and `set_name` handling are new,
so `test_reads_every_set_row` and `test_two_point_conversions_are_captured` fail.

- [ ] **Step 5: Confirm no code change is needed**

If any test fails for a reason other than a typo in the YAML, the profile mechanism
is not general enough — fix `src/sffl/ingest/profiles.py`, do not special-case
Footballguys. The point of this task is that a new vendor costs a YAML file.

- [ ] **Step 6: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_ingest_fbg.py -v`
Expected: 6 passed

- [ ] **Step 7: Verify against the real extract**

```bash
./.venv/bin/python -c "
from sffl.ingest.profiles import load_profile, read_extract
import collections
rows = read_extract(load_profile('sources/footballguys.yaml'),
                    'data/extracts/Footballguys/2026/projection-set-preseason-all-2026.csv', 2026)
print(len(rows), 'rows')
print('sets:', len({r.set_name for r in rows}))
print(dict(collections.Counter(r.pos for r in rows)))
"
```

Expected: roughly 2800–3000 rows (IDP filtered out), around 18 sets, positions limited
to `QB RB WR TE K DST`.

- [ ] **Step 8: Commit**

```bash
git add sources/footballguys.yaml tests/fixtures/footballguys_sample.csv tests/test_ingest_fbg.py
git commit -m "feat: Footballguys adapter with multi-analyst set support"
```

---

### Task 7: Team QB aggregation

**Files:**
- Create: `src/sffl/tqb.py`
- Test: `tests/test_tqb.py`

**Interfaces:**
- Consumes: `PlayerProjection` (Task 3), `score_game` and `LeagueProfile` (Tasks 1–2).
- Produces: `build_tqb(lg, players, set_name=None) -> List[PlayerProjection]` returning
  one `PlayerProjection` per franchise with `pos == "TQB"`, `name == team`, and
  `stats` summed across that franchise's quarterbacks.

**Why:** no vendor needs to support the TQB slot. Summing per-quarterback stat lines
by franchise produces it from any source.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tqb.py`:

```python
from sffl.league import load_league
from sffl.schema import PlayerProjection
from sffl.tqb import build_tqb

LG = load_league("leagues/sffl/2026.yaml")


def qb(name, team, games, pass_yds, pass_cmp, pass_td, rush_yds, set_name=None):
    return PlayerProjection(
        name=name, team=team, pos="QB", source="test", source_year=2026,
        games=games,
        stats=dict(pass_yds=pass_yds, pass_cmp=pass_cmp, pass_td=pass_td,
                   pass_int=0.0, rush_yds=rush_yds, rush_td=0.0),
        raw_name=name, set_name=set_name,
    )


def test_single_qb_franchise():
    out = build_tqb(LG, [qb("Joe Burrow", "CIN", 17, 4690, 428, 37, 145)])
    assert len(out) == 1
    t = out[0]
    assert t.pos == "TQB"
    assert t.name == "CIN"
    assert t.team == "CIN"
    assert t.stats["pass_yds"] == 4690


def test_multi_qb_franchise_sums_stats():
    out = build_tqb(LG, [
        qb("Deshaun Watson", "CLE", 9, 1920, 177, 11, 161),
        qb("Shedeur Sanders", "CLE", 6, 1280, 113, 7, 67),
        qb("Dillon Gabriel", "CLE", 1, 205, 19, 1, 10),
    ])
    assert len(out) == 1
    t = out[0]
    assert t.stats["pass_yds"] == 3405
    assert t.stats["pass_cmp"] == 309
    assert t.games == 16      # summed franchise starts, capped at 17


def test_games_capped_at_seventeen():
    out = build_tqb(LG, [
        qb("A", "NYJ", 12, 3000, 250, 20, 100),
        qb("B", "NYJ", 9, 2000, 170, 12, 50),
    ])
    assert out[0].games == 17


def test_only_the_requested_set_is_used():
    players = [
        qb("Josh Allen", "BUF", 17, 4010, 349, 29, 610, set_name="Consensus"),
        qb("Josh Allen", "BUF", 17, 4180, 360, 31, 690, set_name="Dan Hindery"),
    ]
    out = build_tqb(LG, players, set_name="Dan Hindery")
    assert len(out) == 1
    assert out[0].stats["rush_yds"] == 690


def test_non_quarterbacks_are_ignored():
    players = [
        qb("Joe Burrow", "CIN", 17, 4690, 428, 37, 145),
        PlayerProjection(name="Ja'Marr Chase", team="CIN", pos="WR", source="test",
                         source_year=2026, games=17, stats=dict(rec_yds=1587),
                         raw_name="Ja'Marr Chase"),
    ]
    out = build_tqb(LG, players)
    assert len(out) == 1
    assert "rec_yds" not in out[0].stats
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_tqb.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.tqb'`

- [ ] **Step 3: Implement TQB aggregation**

Create `src/sffl/tqb.py`:

```python
"""Build Team QB units by summing a franchise's quarterbacks.

The league starts one TQB per team - the cumulative totals of every quarterback
on an NFL franchise. No vendor models this slot, so we construct it.
"""

from collections import defaultdict

from sffl.schema import PlayerProjection

PASSING_STATS = ("pass_att", "pass_cmp", "pass_yds", "pass_td", "pass_int",
                 "pass_2pt", "rush_yds", "rush_td", "rush_2pt")

MAX_GAMES = 17


def build_tqb(lg, players, set_name=None):
    """Return one TQB PlayerProjection per franchise found in `players`."""
    by_team = defaultdict(list)
    for p in players:
        if p.pos != "QB":
            continue
        if set_name is not None and p.set_name != set_name:
            continue
        by_team[p.team].append(p)

    out = []
    for team, qbs in by_team.items():
        stats = {}
        for field in PASSING_STATS:
            total = sum(q.stats.get(field, 0.0) for q in qbs)
            if total or any(field in q.stats for q in qbs):
                stats[field] = total
        games = min(MAX_GAMES, sum(q.games for q in qbs))
        out.append(PlayerProjection(
            name=team, team=team, pos="TQB",
            source=qbs[0].source, source_year=qbs[0].source_year,
            games=games, stats=stats, raw_name=team,
            set_name=set_name,
        ))
    out.sort(key=lambda t: t.team)
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_tqb.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/sffl/tqb.py tests/test_tqb.py
git commit -m "feat: build Team QB units by aggregating franchise quarterbacks"
```

---

### Task 8: CLI producing a scored player pool

**Files:**
- Create: `src/sffl/pool.py`
- Create: `src/sffl/cli.py`
- Test: `tests/test_pool.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces:
  - `score_season(lg, player) -> float` — per-game averaged season points, with the
    approximation documented in the docstring
  - `build_pool(lg, profile_path, csv_path, year, set_name=None) -> List[PlayerProjection]`
    where each record gains `stats["_season_points"]`
  - `python -m sffl.cli ingest --source sources/X.yaml --file PATH --year 2026 [--set NAME] [--out CSV]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pool.py`:

```python
from sffl.league import load_league
from sffl.pool import build_pool, score_season
from sffl.schema import PlayerProjection

LG = load_league("leagues/sffl/2026.yaml")
DS_PROFILE = "sources/draftsharks.yaml"
DS_FIXTURE = "tests/fixtures/draftsharks_sample.csv"


def test_score_season_averages_to_per_game_then_bands():
    # 1700 receiving yards over 17 games = 100/game -> band 100-124 = 3 pts
    # 102 catches over 17 = 6/game -> band 5-6 = 2 pts
    p = PlayerProjection(name="X", team="CIN", pos="WR", source="t", source_year=2026,
                         games=17, stats=dict(rec_yds=1700, rec_ct=102), raw_name="X")
    assert score_season(LG, p) == (3 + 2) * 17


def test_zero_games_does_not_divide_by_zero():
    p = PlayerProjection(name="Y", team="CIN", pos="WR", source="t", source_year=2026,
                         games=0, stats=dict(rec_yds=0), raw_name="Y")
    assert score_season(LG, p) == 0.0


def test_build_pool_scores_every_player_and_adds_tqb():
    pool = build_pool(LG, DS_PROFILE, DS_FIXTURE, 2026)
    assert all("_season_points" in p.stats for p in pool)
    assert any(p.pos == "TQB" for p in pool)
    tqb = [p for p in pool if p.pos == "TQB"]
    assert [t.name for t in tqb] == ["BUF"]


def test_individual_quarterbacks_are_removed_from_the_pool():
    pool = build_pool(LG, DS_PROFILE, DS_FIXTURE, 2026)
    assert not any(p.pos == "QB" for p in pool), \
        "individual QBs are not draftable in this league"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_pool.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.pool'`

- [ ] **Step 3: Implement the pool builder**

Create `src/sffl/pool.py`:

```python
"""Turn a vendor extract into a scored, league-correct player pool."""

from sffl.ingest.profiles import load_profile, read_extract
from sffl.scoring import score_game
from sffl.tqb import build_tqb


def score_season(lg, player):
    """Season points from a season stat line.

    APPROXIMATION, and a biased one. Bands apply to each week's line, so we
    average to a per-game line, band that, and multiply back up. Averaging
    collapses the variance the bands reward and erases production that sits
    below a floor in the mean but clears it in individual weeks - Josh Allen's
    ~35 rushing yards per game scores zero here despite weeks well over 50.
    Replace this with a weekly distribution model once weekly data exists.
    """
    if not player.games:
        return 0.0
    per_game = {}
    for field, total in player.stats.items():
        if field.startswith("_"):
            continue
        per_game[field] = total / player.games
    return score_game(lg, per_game) * player.games


def build_pool(lg, profile_path, csv_path, year, set_name=None):
    """Read one extract, drop individual QBs, add TQB units, score everything."""
    profile = load_profile(profile_path)
    rows = read_extract(profile, csv_path, year)
    if set_name is not None:
        rows = [r for r in rows if r.set_name == set_name]

    tqb = build_tqb(lg, rows, set_name=set_name)
    pool = [r for r in rows if r.pos != "QB"] + tqb

    for p in pool:
        p.stats["_season_points"] = score_season(lg, p)
    pool.sort(key=lambda p: -p.stats["_season_points"])
    return pool
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_pool.py -v`
Expected: 4 passed

- [ ] **Step 5: Implement the CLI**

Create `src/sffl/cli.py`:

```python
"""Command line entry point.

    python -m sffl.cli ingest --source sources/draftsharks.yaml \
        --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026
"""

import argparse
import csv
import sys

from sffl.league import load_league
from sffl.pool import build_pool

DEFAULT_LEAGUE = "leagues/sffl/2026.yaml"


def cmd_ingest(args):
    lg = load_league(args.league)
    pool = build_pool(lg, args.source, args.file, args.year, args.set)

    by_pos = {}
    for p in pool:
        by_pos[p.pos] = by_pos.get(p.pos, 0) + 1
    print("%d players from %s" % (len(pool), args.source))
    print("  " + "  ".join("%s=%d" % kv for kv in sorted(by_pos.items())))
    print("\ntop 15 by SFFL season points:")
    for i, p in enumerate(pool[:15], 1):
        print("  %2d. %7.1f  %-4s %s" % (i, p.stats["_season_points"], p.pos, p.name))

    if args.out:
        with open(args.out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["name", "team", "pos", "games", "season_points", "source", "set"])
            for p in pool:
                w.writerow([p.name, p.team, p.pos, p.games,
                            round(p.stats["_season_points"], 2),
                            p.source, p.set_name or ""])
        print("\nwrote %s" % args.out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sffl")
    sub = ap.add_subparsers(dest="cmd")

    ing = sub.add_parser("ingest", help="read a vendor extract into a scored pool")
    ing.add_argument("--source", required=True)
    ing.add_argument("--file", required=True)
    ing.add_argument("--year", type=int, required=True)
    ing.add_argument("--set", default=None, help="analyst set, for multi-set sources")
    ing.add_argument("--league", default=DEFAULT_LEAGUE)
    ing.add_argument("--out", default=None)
    ing.set_defaults(func=cmd_ingest)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run the CLI against both real extracts**

```bash
./.venv/bin/python -m sffl.cli ingest --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026

./.venv/bin/python -m sffl.cli ingest --source sources/footballguys.yaml \
  --file "data/extracts/Footballguys/2026/projection-set-preseason-all-2026.csv" \
  --year 2026 --set Consensus
```

Expected: both print a player count, a position breakdown including `TQB=32` (or close,
depending on how many franchises the set covers), and a top-15 list with no individual
quarterbacks in it.

- [ ] **Step 7: Run the whole suite**

Run: `./.venv/bin/pytest -v`
Expected: all tests pass, no failures.

- [ ] **Step 8: Commit**

```bash
git add src/sffl/pool.py src/sffl/cli.py tests/test_pool.py
git commit -m "feat: CLI producing a scored league-correct player pool"
```

---

## Self-Review

**Spec coverage.** League profile → Task 1. Banded scoring including the verified sack
rule → Task 2. Canonical schema → Task 3. Identity resolution with normalization,
aliases, fuzzy matching, and a review queue → Tasks 3–4. Source profiles as data with
file globs and capability flags → Task 5. Multi-file/multi-set handling → Task 6. TQB
as a team unit → Task 7. Graceful degradation via capability flags → declared in Tasks
5–6, consumed by the value engine in the next plan.

**Deliberately deferred to later plans:** VORP-to-dollars and replacement level, the
consensus-and-spread calculation across analyst sets, both renderers, and the silent
auction planner. The `capabilities` blocks and `set_name` field exist so those plans
have what they need.

**Known gap carried forward:** `score_season` is the documented biased approximation.
It is isolated in one function with one docstring so the weekly-distribution model
replaces it without touching ingest, identity, or TQB.

**Type consistency check.** `PlayerProjection` field names are used identically in
Tasks 3, 5, 6, 7, 8. `player_key` returns `name|TEAM|POS` throughout. Band tables are
`(low, high, points)` tuples in Tasks 1, 2, and the YAML. Stat keys in
`sources/*.yaml` match the `stats` keys `score_game` reads in Task 2 — verified field
by field: `pass_yds pass_cmp pass_td pass_int pass_2pt rush_yds rush_td rush_2pt
rec_yds rec_ct rec_td rec_2pt xp_made fg_u30 fg_30_39 fg_40_49 fg_50_59 fg_60
fg_missed def_pa def_ya def_sack def_int def_fum_rec def_td def_safety`.

# Value Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a scored player pool into auction dollar values that are calibrated against how banded scoring actually behaves week to week, and against what this league actually paid.

**Architecture:** Weekly 2025 stat lines produce an empirical expectation curve per banded stat — for a given per-game mean, what did banded weekly scoring really yield. Those curves replace the biased `band(mean)` approximation. Projections from multiple analyst sets are merged into a consensus plus a spread. Replacement level is chosen by fitting both candidate policies against 156 real 2025 prices rather than by preference, and VORP is converted to dollars against the league's actual capital.

**Tech Stack:** Python 3.9, pytest, PyYAML, rapidfuzz.

## Global Constraints

- **Python 3.9.6 only.** No `match`, no PEP 604 (`int | None`) annotations. Use `typing.Optional`/`List`/`Dict`.
- **Use the project venv** at `.venv/`. Invoke as `./.venv/bin/pytest` and `./.venv/bin/python`. `sffl` is not pip-installed; ad-hoc commands need `PYTHONPATH=src`.
- **`data/extracts/` and `data/weekly/` are gitignored** — vendor and CBS data. Never commit a file from either. Test fixtures are small hand-written excerpts in `tests/fixtures/`.
- **Wrong numbers must never be produced silently.** Prefer raising over guessing.
- **Never mix seasons.** 2024 CBS points were computed under different scoring rules; only 2025 data may calibrate 2026 values.
- **Touchdown values are NOT symmetric across positions** — goal-line rushing scores 3 where a short receiving TD scores 5; 36-74 yard rushing scores 8 where receiving scores 6. Do not assume parity anywhere.
- **The scoring engine is validated and must not be modified.** `score_game` matched real CBS output across ~250 weekly observations. This plan calls it; it does not change it.

## File Structure

| File | Responsibility |
|---|---|
| `src/sffl/weekly.py` | Load `data/weekly/2025/*.csv` into weekly records |
| `src/sffl/calibrate.py` | Build empirical expectation curves per banded stat; persist to YAML |
| `src/sffl/pool.py` (modify) | `score_season` gains a calibrated path |
| `src/sffl/consensus.py` | Merge multiple sources/analyst sets into consensus + spread |
| `src/sffl/value.py` | Replacement level, VORP, VORP-to-dollars |
| `src/sffl/fit.py` | Score a replacement policy against observed prices |
| `src/sffl/cli.py` (modify) | Add the `value` command |
| `calibration/2025.yaml` | Generated expectation curves, committed (derived, not raw CBS data) |

---

### Task 1: Weekly data loader

**Files:**
- Create: `src/sffl/weekly.py`
- Create: `tests/fixtures/weekly_sample.csv`
- Test: `tests/test_weekly.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `load_weekly(path) -> List[WeeklyLine]`. `WeeklyLine` is a dataclass with
  `player_id: str`, `name: str`, `team: str`, `pos: str`, `week: int`,
  `stats: Dict[str, float]`, `cbs_fpts: float`.

**Data contract.** Collection is an operational step run separately through the browser.
Files land at `data/weekly/2025/<pos>.csv` with a header of exactly:

```
player_id,name,team,pos,week,cbs_fpts,pass_cmp,pass_yds,pass_td,pass_int,
rush_yds,rush_td,rec_ct,rec_yds,rec_td,xp_made,fg_u30,fg_30_39,fg_40_49,
fg_50_59,fg_60,fg_missed,def_pa,def_ya,def_sack,def_int,def_fum_rec,def_td,def_safety
```

Every stat column name is a key `score_game` reads. Blank cells mean zero. A row is one
player-week. Bye weeks and inactive weeks are omitted entirely, not written as zeros —
a player who did not play must not drag his mean down.

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/weekly_sample.csv`:

```csv
player_id,name,team,pos,week,cbs_fpts,pass_cmp,pass_yds,pass_td,pass_int,rush_yds,rush_td,rec_ct,rec_yds,rec_td,xp_made,fg_u30,fg_30_39,fg_40_49,fg_50_59,fg_60,fg_missed,def_pa,def_ya,def_sack,def_int,def_fum_rec,def_td,def_safety
2185957,Saquon Barkley,PHI,RB,3,0,0,0,0,0,46,0,4,9,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
2185957,Saquon Barkley,PHI,RB,8,19,0,0,0,0,150,1,4,24,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0
2185957,Saquon Barkley,PHI,RB,13,2,0,0,0,0,56,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
2966320,Ja'Marr Chase,CIN,WR,8,8,0,0,0,0,0,0,12,91,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
2966320,Ja'Marr Chase,CIN,WR,11,0,0,0,0,0,0,0,3,30,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_weekly.py`:

```python
from sffl.weekly import load_weekly

FIXTURE = "tests/fixtures/weekly_sample.csv"


def test_reads_every_row():
    rows = load_weekly(FIXTURE)
    assert len(rows) == 5


def test_parses_identity_and_week():
    rows = load_weekly(FIXTURE)
    r = rows[0]
    assert r.player_id == "2185957"
    assert r.name == "Saquon Barkley"
    assert r.team == "PHI"
    assert r.pos == "RB"
    assert r.week == 3
    assert r.cbs_fpts == 0.0


def test_stats_are_floats_keyed_by_scoring_vocabulary():
    rows = load_weekly(FIXTURE)
    barkley_wk8 = [r for r in rows if r.player_id == "2185957" and r.week == 8][0]
    assert barkley_wk8.stats["rush_yds"] == 150.0
    assert barkley_wk8.stats["rec_ct"] == 4.0
    assert barkley_wk8.stats["rec_td"] == 1.0
    assert barkley_wk8.cbs_fpts == 19.0
    assert all(isinstance(v, float) for v in barkley_wk8.stats.values())


def test_cbs_fpts_is_not_inside_stats():
    # cbs_fpts is ground truth for comparison, never an input to scoring
    rows = load_weekly(FIXTURE)
    assert "cbs_fpts" not in rows[0].stats
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_weekly.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.weekly'`

- [ ] **Step 4: Implement the loader**

Create `src/sffl/weekly.py`:

```python
"""Load real weekly stat lines collected from the league site.

One row per player-week. Weeks a player did not appear are absent from the file
rather than written as zeros, so a bye never drags a per-game mean downward.
"""

import csv
from dataclasses import dataclass, field
from typing import Dict, List

META = ("player_id", "name", "team", "pos", "week", "cbs_fpts")


@dataclass
class WeeklyLine(object):
    player_id: str
    name: str
    team: str
    pos: str
    week: int
    cbs_fpts: float
    stats: Dict[str, float] = field(default_factory=dict)


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0


def load_weekly(path):
    out = []  # type: List[WeeklyLine]
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            stats = {}
            for key, val in row.items():
                if key in META or key is None:
                    continue
                stats[key] = _num(val)
            out.append(WeeklyLine(
                player_id=str(row["player_id"]).strip(),
                name=str(row["name"]).strip(),
                team=str(row["team"]).strip(),
                pos=str(row["pos"]).strip().upper(),
                week=int(_num(row["week"])),
                cbs_fpts=_num(row["cbs_fpts"]),
                stats=stats,
            ))
    return out
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_weekly.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/sffl/weekly.py tests/test_weekly.py tests/fixtures/weekly_sample.csv
git commit -m "feat: loader for real weekly stat lines"
```

---

### Task 2: Empirical expectation curves

**Files:**
- Create: `src/sffl/calibrate.py`
- Test: `tests/test_calibrate.py`

**Interfaces:**
- Consumes: `load_weekly`, `WeeklyLine` (Task 1); `load_league`, `band_points` from the
  existing `sffl.league` and `sffl.scoring`.
- Produces:
  - `build_curves(lg, lines, buckets=None) -> Dict[str, List[Tuple[float, float]]]`
    mapping a banded stat name to a sorted list of `(per_game_mean, expected_points)`.
  - `expected_points(curve, mean) -> float` — linear interpolation between the two
    nearest points, clamped at both ends.
  - `save_curves(curves, path)` and `load_curves(path)` using YAML.

**Why this exists.** `score_season` currently computes `band(mean) * games`. The correct
quantity is `E[band(weekly)] * games`. Those differ because the bands are non-linear:
a player averaging 35 rushing yards scores zero under the approximation but clears the
50-yard floor in individual weeks. The curve measures that difference directly from real
data instead of assuming a distribution.

- [ ] **Step 1: Write the failing test**

Create `tests/test_calibrate.py`:

```python
import pytest

from sffl.calibrate import build_curves, expected_points, save_curves, load_curves
from sffl.league import load_league
from sffl.weekly import WeeklyLine

LG = load_league("leagues/sffl/2026.yaml")


def line(pid, week, **stats):
    return WeeklyLine(player_id=pid, name=pid, team="XXX", pos="RB",
                      week=week, cbs_fpts=0.0, stats=dict(stats))


def test_curve_captures_value_the_approximation_throws_away():
    # A player averaging 40 rushing yards per game: two weeks at 0, two at 80.
    # band(40) == 0, so the naive approximation scores him ZERO.
    # But band(80) == 3 in two of four weeks, so E[band] == 1.5.
    lines = [line("a", 1, rush_yds=0), line("a", 2, rush_yds=0),
             line("a", 3, rush_yds=80), line("a", 4, rush_yds=80)]
    curves = build_curves(LG, lines)
    got = expected_points(curves["rush_yds"], 40.0)
    assert got == pytest.approx(1.5)


def test_steady_player_matches_the_naive_approximation():
    # Every week identical, so averaging loses nothing and E[band] == band(mean).
    lines = [line("b", w, rush_yds=80) for w in range(1, 5)]
    curves = build_curves(LG, lines)
    assert expected_points(curves["rush_yds"], 80.0) == pytest.approx(3.0)


def test_interpolates_between_observed_means():
    lines = ([line("a", w, rush_yds=60) for w in range(1, 5)]
             + [line("b", w, rush_yds=100) for w in range(1, 5)])
    curves = build_curves(LG, lines)
    lo = expected_points(curves["rush_yds"], 60.0)
    hi = expected_points(curves["rush_yds"], 100.0)
    mid = expected_points(curves["rush_yds"], 80.0)
    assert lo < mid < hi


def test_clamps_outside_the_observed_range():
    lines = [line("a", w, rush_yds=60) for w in range(1, 5)]
    curves = build_curves(LG, lines)
    assert expected_points(curves["rush_yds"], 0.0) == pytest.approx(2.0)
    assert expected_points(curves["rush_yds"], 9999.0) == pytest.approx(2.0)


def test_round_trips_through_yaml(tmp_path):
    lines = [line("a", w, rush_yds=80) for w in range(1, 5)]
    curves = build_curves(LG, lines)
    p = str(tmp_path / "curves.yaml")
    save_curves(curves, p)
    back = load_curves(p)
    assert expected_points(back["rush_yds"], 80.0) == pytest.approx(3.0)


def test_players_with_too_few_weeks_are_excluded():
    lines = [line("short", 1, rush_yds=80)]
    curves = build_curves(LG, lines, min_weeks=4)
    assert curves.get("rush_yds", []) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_calibrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.calibrate'`

- [ ] **Step 3: Implement the curves**

Create `src/sffl/calibrate.py`:

```python
"""Measure what banded scoring really yields, instead of assuming.

score_season approximates a season by banding the per-game mean. The honest
quantity is the EXPECTED banded value across a player's actual weeks. For every
banded stat this module builds a curve from real weekly data:

    per-game mean  ->  mean of band(weekly value) across that player's weeks

Consumers interpolate the curve instead of calling band_points on the mean.
"""

from collections import defaultdict
from typing import Dict, List, Tuple

import yaml

from sffl.scoring import band_points

MIN_WEEKS = 4


def build_curves(lg, lines, min_weeks=MIN_WEEKS):
    """Return {stat: [(mean, expected_points), ...]} sorted by mean."""
    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)

    points = defaultdict(list)  # type: Dict[str, List[Tuple[float, float]]]
    for _, weeks in by_player.items():
        if len(weeks) < min_weeks:
            continue
        for stat, table in lg.bands.items():
            vals = [w.stats.get(stat, 0.0) for w in weeks]
            mean = sum(vals) / len(vals)
            expected = sum(band_points(table, v) for v in vals) / len(vals)
            points[stat].append((mean, expected))

    curves = {}
    for stat, pairs in points.items():
        merged = defaultdict(list)
        for mean, exp in pairs:
            merged[round(mean, 3)].append(exp)
        curves[stat] = sorted((m, sum(v) / len(v)) for m, v in merged.items())
    for stat in lg.bands:
        curves.setdefault(stat, [])
    return curves


def expected_points(curve, mean):
    """Linear interpolation over the curve, clamped at both ends."""
    if not curve:
        return 0.0
    if mean <= curve[0][0]:
        return curve[0][1]
    if mean >= curve[-1][0]:
        return curve[-1][1]
    for i in range(1, len(curve)):
        x0, y0 = curve[i - 1]
        x1, y1 = curve[i]
        if x0 <= mean <= x1:
            if x1 == x0:
                return y1
            t = (mean - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return curve[-1][1]


def save_curves(curves, path):
    payload = {k: [[float(m), float(e)] for m, e in v] for k, v in curves.items()}
    with open(path, "w") as fh:
        yaml.safe_dump(payload, fh, default_flow_style=False, sort_keys=True)


def load_curves(path):
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    return {k: [(float(m), float(e)) for m, e in v] for k, v in raw.items()}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_calibrate.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/sffl/calibrate.py tests/test_calibrate.py
git commit -m "feat: empirical expectation curves replacing the banding approximation"
```

---

### Task 3: Calibrated season scoring

**Files:**
- Modify: `src/sffl/pool.py`
- Test: `tests/test_pool.py` (append)

**Interfaces:**
- Consumes: `expected_points`, `load_curves` (Task 2); existing `score_season`.
- Produces: `score_season_calibrated(lg, player, curves) -> float`. The existing
  `score_season` keeps its current behaviour and signature so the two can be compared.

**Behaviour.** For every banded stat, use `expected_points(curves[stat], per_game_mean)`
instead of `band_points(table, per_game_mean)`. Non-banded categories — touchdowns,
interceptions, extra points, field goals by distance — are linear in the count and need
no correction, so they pass through exactly as before. Sacks use the threshold rule and
are NOT banded, so they are corrected via a curve only if `def_sack` appears in
`lg.bands`; it does not, so sacks keep their current treatment and the limitation stays
documented.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pool.py`:

```python
from sffl.pool import score_season_calibrated


def test_calibrated_scoring_recovers_value_the_naive_path_zeroes():
    # A quarterback averaging 35 rushing yards per game scores ZERO rushing under
    # the naive path, because band(35) == 0. A curve built from a player who
    # alternated 0 and 70 yards says the true expectation is 1.0 per game.
    lg = LG
    curves = {"rush_yds": [(35.0, 1.0)]}
    p = PlayerProjection(name="QB", team="BUF", pos="TQB", source="t",
                         source_year=2026, games=17,
                         stats=dict(rush_yds=595.0), raw_name="QB")
    naive = score_season(lg, p)
    cal = score_season_calibrated(lg, p, curves)
    assert naive == 0.0
    assert cal == pytest.approx(17.0)


def test_calibrated_leaves_linear_categories_untouched():
    lg = LG
    curves = {}
    p = PlayerProjection(name="K", team="DAL", pos="K", source="t",
                         source_year=2026, games=17,
                         stats=dict(xp_made=34.0, fg_40_49=17.0), raw_name="K")
    # 34 XP at 1 + 17 FG at 4 = 102, and no banded stat is involved
    assert score_season_calibrated(lg, p, curves) == pytest.approx(102.0)


def test_calibrated_equals_naive_when_curve_matches_the_band():
    lg = LG
    curves = {"rec_yds": [(100.0, 3.0)]}
    p = PlayerProjection(name="WR", team="CIN", pos="WR", source="t",
                         source_year=2026, games=17,
                         stats=dict(rec_yds=1700.0), raw_name="WR")
    assert score_season_calibrated(lg, p, curves) == pytest.approx(score_season(lg, p))
```

Add `import pytest` at the top of the file if it is not already there.

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_pool.py -v`
Expected: FAIL with `ImportError: cannot import name 'score_season_calibrated'`

- [ ] **Step 3: Implement calibrated scoring**

Add to `src/sffl/pool.py`:

```python
from sffl.calibrate import expected_points
from sffl.scoring import band_points


def score_season_calibrated(lg, player, curves):
    """Season points using empirical expectation curves for banded stats.

    Replaces band(per-game mean) with E[band(weekly)] measured from real data.
    Linear categories - touchdowns, interceptions, extra points, field goals by
    distance - are unaffected by averaging and pass through unchanged.

    KNOWN LIMITATION: sacks use a threshold rule rather than a band table, so
    they are not corrected here. A defense averaging 2.5 sacks per game still
    scores zero sack points across the season. See the spec.
    """
    if not player.games:
        return 0.0

    per_game = {}
    for field_name, total in player.stats.items():
        if field_name.startswith("_"):
            continue
        per_game[field_name] = total / player.games

    banded_total = 0.0
    for stat in lg.bands:
        mean = per_game.get(stat, 0.0)
        curve = curves.get(stat)
        if curve:
            banded_total += expected_points(curve, mean)
        else:
            banded_total += band_points(lg.bands[stat], mean)

    linear = dict(per_game)
    for stat in lg.bands:
        linear.pop(stat, None)
    linear_total = score_game(lg, linear, player.pos)

    return (banded_total + linear_total) * player.games
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_pool.py -v`
Expected: all pass, including the three new tests

- [ ] **Step 5: Commit**

```bash
git add src/sffl/pool.py tests/test_pool.py
git commit -m "feat: calibrated season scoring using empirical curves"
```

---

### Task 4: Consensus and spread across sources

**Files:**
- Create: `src/sffl/consensus.py`
- Test: `tests/test_consensus.py`

**Interfaces:**
- Consumes: `PlayerProjection` from `sffl.schema`; `Resolver` from `sffl.identity`.
- Produces: `merge(projections, resolver=None) -> List[PlayerProjection]` where each
  returned record carries `stats["_n_sources"]`, and `stats["_spread_<stat>"]` giving the
  population standard deviation of that stat across sources. The consensus value of each
  stat is the mean across sources.

**Why the spread matters.** The scoring bands are convex — a big week pays
super-linearly — so a player the analysts disagree about carries option value his mean
does not express. No vendor publishes this. Surfacing it is a genuine edge.

- [ ] **Step 1: Write the failing test**

Create `tests/test_consensus.py`:

```python
import pytest

from sffl.consensus import merge
from sffl.schema import PlayerProjection


def proj(name, source, set_name, **stats):
    return PlayerProjection(name=name, team="BUF", pos="TQB", source=source,
                            source_year=2026, games=17, stats=dict(stats),
                            raw_name=name, set_name=set_name)


def test_averages_across_sources():
    out = merge([proj("Josh Allen", "fbg", "Consensus", rush_yds=610.0),
                 proj("Josh Allen", "fbg", "Hindery", rush_yds=690.0)])
    assert len(out) == 1
    assert out[0].stats["rush_yds"] == pytest.approx(650.0)
    assert out[0].stats["_n_sources"] == 2


def test_records_the_spread():
    out = merge([proj("Josh Allen", "fbg", "Consensus", rush_yds=610.0),
                 proj("Josh Allen", "fbg", "Hindery", rush_yds=690.0)])
    assert out[0].stats["_spread_rush_yds"] == pytest.approx(40.0)


def test_single_source_has_zero_spread():
    out = merge([proj("Josh Allen", "fbg", "Consensus", rush_yds=610.0)])
    assert out[0].stats["_spread_rush_yds"] == pytest.approx(0.0)
    assert out[0].stats["_n_sources"] == 1


def test_missing_stat_in_one_source_counts_as_absent_not_zero():
    # Only one source reports rec_yds; averaging must not halve it.
    out = merge([proj("Josh Allen", "fbg", "A", rush_yds=600.0, rec_yds=40.0),
                 proj("Josh Allen", "fbg", "B", rush_yds=600.0)])
    assert out[0].stats["rec_yds"] == pytest.approx(40.0)


def test_different_players_are_kept_apart():
    out = merge([proj("Josh Allen", "fbg", "A", rush_yds=600.0),
                 proj("Lamar Jackson", "fbg", "A", rush_yds=800.0)])
    assert len(out) == 2


def test_games_is_averaged_too():
    a = proj("Josh Allen", "fbg", "A", rush_yds=600.0)
    b = proj("Josh Allen", "fbg", "B", rush_yds=600.0)
    b.games = 15
    out = merge([a, b])
    assert out[0].games == pytest.approx(16.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_consensus.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.consensus'`

- [ ] **Step 3: Implement the merge**

Create `src/sffl/consensus.py`:

```python
"""Merge several analysts' projections into one consensus record plus a spread.

The spread is kept deliberately. Scoring bands are convex, so disagreement about
a player carries information his mean does not - and no vendor publishes it.
"""

from collections import defaultdict
from typing import List

from sffl.schema import PlayerProjection


def _stdev(values):
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return var ** 0.5


def merge(projections, resolver=None):
    """Group by player key and average each stat across the sources that report it."""
    groups = defaultdict(list)
    for p in projections:
        key = p.key() if resolver is None else (
            resolver.resolve(p.name, p.team, p.pos) or p.key())
        groups[key].append(p)

    out = []  # type: List[PlayerProjection]
    for _, members in groups.items():
        first = members[0]
        by_stat = defaultdict(list)
        for m in members:
            for stat, val in m.stats.items():
                if stat.startswith("_"):
                    continue
                by_stat[stat].append(val)

        stats = {}
        for stat, vals in by_stat.items():
            stats[stat] = sum(vals) / len(vals)
            stats["_spread_" + stat] = _stdev(vals)
        stats["_n_sources"] = float(len(members))

        out.append(PlayerProjection(
            name=first.name, team=first.team, pos=first.pos,
            source="consensus", source_year=first.source_year,
            games=sum(m.games for m in members) / len(members),
            stats=stats, raw_name=first.raw_name, set_name=None,
        ))
    out.sort(key=lambda p: p.name)
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_consensus.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/sffl/consensus.py tests/test_consensus.py
git commit -m "feat: multi-source consensus with spread preserved"
```

---

### Task 5: Replacement level and VORP

**Files:**
- Create: `src/sffl/value.py`
- Test: `tests/test_value.py`

**Interfaces:**
- Consumes: `LeagueProfile` (`lg.teams`, `lg.flex_slots`, `lg.roster_size`).
- Produces:
  - `replacement_levels(lg, pool, policy) -> Dict[str, float]` mapping each of
    `"TQB"`, `"FLEX"`, `"K"`, `"DST"` to a points threshold. `policy` is either
    `"starter"` or `"draftable"`.
  - `assign_vorp(lg, pool, levels) -> None` — writes `stats["_vorp"]` on every record.

**The two policies.**
- `"starter"` — replacement is the last player who would start league-wide. TQB, K and
  DST each have `lg.teams` starters, so replacement is the `teams`-th best plus one.
  The flex pool has `lg.teams * lg.flex_slots` starters.
- `"draftable"` — replacement is the last player actually rostered, `lg.teams *
  lg.roster_size` deep overall, allocated to each pool in proportion to its starter
  share.

**The flex pool is RB, WR and TE together.** WR and TE are one position in this league;
never split them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_value.py`:

```python
import pytest

from sffl.league import load_league
from sffl.schema import PlayerProjection
from sffl.value import replacement_levels, assign_vorp

LG = load_league("leagues/sffl/2026.yaml")


def player(name, pos, pts):
    return PlayerProjection(name=name, team="XXX", pos=pos, source="t",
                            source_year=2026, games=17,
                            stats={"_season_points": float(pts)}, raw_name=name)


def build_pool():
    pool = []
    # 100 flex players scoring 200 down to 3
    for i in range(100):
        pool.append(player("flex%d" % i, "RB" if i % 2 else "WR", 200 - 2 * i))
    # 32 team QBs scoring 300 down to 145
    for i in range(32):
        pool.append(player("tqb%d" % i, "TQB", 300 - 5 * i))
    # 32 kickers and 32 defenses
    for i in range(32):
        pool.append(player("k%d" % i, "K", 150 - i))
        pool.append(player("d%d" % i, "DST", 120 - i))
    return pool


def test_starter_policy_uses_starting_demand():
    lv = replacement_levels(LG, build_pool(), "starter")
    # 12 teams start one TQB each, so replacement is the 13th best TQB
    assert lv["TQB"] == pytest.approx(300 - 5 * 12)
    # 12 teams * 5 flex slots = 60 starters, so replacement is the 61st best
    assert lv["FLEX"] == pytest.approx(200 - 2 * 60)


def test_draftable_policy_reaches_deeper_than_starter():
    starter = replacement_levels(LG, build_pool(), "starter")
    draftable = replacement_levels(LG, build_pool(), "draftable")
    assert draftable["FLEX"] < starter["FLEX"]


def test_wr_and_te_share_one_flex_pool():
    pool = [player("wr", "WR", 100), player("te", "TE", 90), player("rb", "RB", 80)]
    lv = replacement_levels(LG, pool, "starter")
    assert "WR" not in lv and "TE" not in lv and "RB" not in lv
    assert "FLEX" in lv


def test_vorp_is_points_above_replacement_and_never_negative():
    pool = build_pool()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    top = max(pool, key=lambda p: p.stats["_vorp"])
    assert top.stats["_vorp"] > 0
    assert all(p.stats["_vorp"] >= 0 for p in pool)


def test_unknown_policy_raises():
    with pytest.raises(ValueError):
        replacement_levels(LG, build_pool(), "vibes")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_value.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.value'`

- [ ] **Step 3: Implement replacement level and VORP**

Create `src/sffl/value.py`:

```python
"""Replacement level and value over replacement.

RB, WR and TE form ONE pool - they are the same position in this league and
compete for the same five flexible lineup slots. TQB, K and DST each have exactly
one starting slot per team.
"""

FLEX = ("RB", "WR", "TE")
POOLS = ("TQB", "FLEX", "K", "DST")


def _pool_of(pos):
    return "FLEX" if pos in FLEX else pos


def _sorted_points(pool, name):
    vals = [p.stats.get("_season_points", 0.0) for p in pool if _pool_of(p.pos) == name]
    return sorted(vals, reverse=True)


def _starter_counts(lg):
    return {"TQB": lg.teams, "FLEX": lg.teams * lg.flex_slots,
            "K": lg.teams, "DST": lg.teams}


def replacement_levels(lg, pool, policy):
    """Points threshold below which a player is freely available."""
    if policy not in ("starter", "draftable"):
        raise ValueError(
            "unknown replacement policy %r; expected 'starter' or 'draftable'" % policy)

    starters = _starter_counts(lg)
    if policy == "starter":
        depths = dict(starters)
    else:
        total_starters = sum(starters.values())
        drafted = lg.teams * lg.roster_size
        depths = {}
        for name, n in starters.items():
            depths[name] = int(round(drafted * (float(n) / total_starters)))

    levels = {}
    for name in POOLS:
        pts = _sorted_points(pool, name)
        idx = depths[name]
        levels[name] = pts[idx] if idx < len(pts) else (pts[-1] if pts else 0.0)
    return levels


def assign_vorp(lg, pool, levels):
    """Write stats['_vorp'] on every record. Never negative."""
    for p in pool:
        base = levels.get(_pool_of(p.pos), 0.0)
        p.stats["_vorp"] = max(0.0, p.stats.get("_season_points", 0.0) - base)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_value.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/sffl/value.py tests/test_value.py
git commit -m "feat: replacement level policies and VORP over one merged flex pool"
```

---

### Task 6: VORP to auction dollars

**Files:**
- Modify: `src/sffl/value.py`
- Test: `tests/test_value.py` (append)

**Interfaces:**
- Consumes: `assign_vorp` (Task 5), `lg.total_capital()`, `lg.total_spots()`,
  `lg.surplus()`.
- Produces: `assign_dollars(lg, pool) -> float` — writes `stats["_dollars"]` on every
  record and returns the dollars-per-VORP-point rate.

**The arithmetic.** Total capital is `teams * budget` = $1,320. Every one of the
`teams * roster_size` = 156 roster spots costs at least $1, so $156 is committed and
`surplus()` = $1,164 is distributed in proportion to VORP. A player's value is
`1 + vorp * rate`. Players with zero VORP are worth exactly $1.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_value.py`:

```python
from sffl.value import assign_dollars


def test_dollars_exhaust_the_league_budget():
    pool = build_pool()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    assign_dollars(LG, pool)
    # every roster spot costs at least $1, and the surplus is fully distributed
    spent = sum(sorted((p.stats["_dollars"] for p in pool), reverse=True)[:LG.total_spots()])
    assert spent == pytest.approx(LG.total_capital(), abs=1.0)


def test_zero_vorp_players_cost_one_dollar():
    pool = build_pool()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    assign_dollars(LG, pool)
    replacement = [p for p in pool if p.stats["_vorp"] == 0.0]
    assert replacement, "expected some players at or below replacement"
    assert all(p.stats["_dollars"] == pytest.approx(1.0) for p in replacement)


def test_rate_is_positive_and_returned():
    pool = build_pool()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    rate = assign_dollars(LG, pool)
    assert rate > 0


def test_a_pool_with_no_vorp_does_not_divide_by_zero():
    pool = [player("x", "RB", 0)]
    assign_vorp(LG, pool, {"FLEX": 0.0})
    rate = assign_dollars(LG, pool)
    assert rate == 0.0
    assert pool[0].stats["_dollars"] == pytest.approx(1.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_value.py -v`
Expected: FAIL with `ImportError: cannot import name 'assign_dollars'`

- [ ] **Step 3: Implement the dollar conversion**

Add to `src/sffl/value.py`:

```python
def assign_dollars(lg, pool):
    """Distribute the league's surplus in proportion to VORP.

    Every roster spot costs at least $1, so teams * roster_size dollars are
    committed before anything else. What remains is allocated by VORP share.
    Returns the dollars-per-VORP-point rate.
    """
    total_vorp = sum(p.stats.get("_vorp", 0.0) for p in pool)
    rate = (lg.surplus() / total_vorp) if total_vorp > 0 else 0.0
    for p in pool:
        p.stats["_dollars"] = 1.0 + p.stats.get("_vorp", 0.0) * rate
    return rate
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_value.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/sffl/value.py tests/test_value.py
git commit -m "feat: VORP to auction dollars against real league capital"
```

---

### Task 7: Fit the replacement policy against real prices

**Files:**
- Create: `src/sffl/fit.py`
- Create: `tests/fixtures/prices_sample.csv`
- Test: `tests/test_fit.py`

**Interfaces:**
- Consumes: `replacement_levels`, `assign_vorp`, `assign_dollars` (Tasks 5-6);
  `Resolver` from `sffl.identity`.
- Produces:
  - `load_prices(path) -> Dict[str, float]` mapping a player key to the price paid.
  - `score_fit(lg, pool, prices, policy, resolver=None) -> Dict[str, float]` returning
    `{"policy":…, "n": …, "mae": …, "rmse": …, "top10_mae": …}`.
  - `choose_policy(lg, pool, prices, resolver=None) -> Tuple[str, List[Dict]]` returning
    the better policy name and both reports.

**Why this task exists.** The spec left replacement level as an open question. It is now
answerable: `data/league/auction-rosters-2025.csv` holds 156 real prices. Whichever
policy reproduces them better wins, and the fit quality is reported either way so a poor
fit is visible rather than hidden.

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/prices_sample.csv`:

```csv
franchise,pick_order,player_as_written,price
SGT HULKA'S BIG TOES,1,JAMAAR CHASE,43
SGT HULKA'S BIG TOES,5,CHASE BROWN,25
STUPID MUTANTS,1,BIJAN ROBINSON,41
EM 50s,1,CHRISTIAN MCCAFFREY,34
BRAVO COMPANY,1,NICO COLLINS,26
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_fit.py`:

```python
import pytest

from sffl.fit import load_prices, score_fit, choose_policy
from sffl.league import load_league
from sffl.schema import PlayerProjection

LG = load_league("leagues/sffl/2026.yaml")
PRICES = "tests/fixtures/prices_sample.csv"


def player(name, pos, pts):
    return PlayerProjection(name=name, team="XXX", pos=pos, source="t",
                            source_year=2026, games=17,
                            stats={"_season_points": float(pts)}, raw_name=name)


def test_load_prices_normalizes_hand_typed_names():
    prices = load_prices(PRICES)
    # the roster sheet misspells Ja'Marr Chase as "JAMAAR CHASE"
    assert any("chase" in k for k in prices)
    assert len(prices) == 5


def test_score_fit_reports_error_metrics():
    pool = [player("Ja'Marr Chase", "WR", 200), player("Chase Brown", "RB", 120)]
    rep = score_fit(LG, pool, load_prices(PRICES), "starter")
    assert rep["policy"] == "starter"
    assert rep["n"] >= 1
    assert rep["mae"] >= 0
    assert rep["rmse"] >= rep["mae"] * 0.0


def test_score_fit_rejects_an_unknown_policy():
    pool = [player("Ja'Marr Chase", "WR", 200)]
    with pytest.raises(ValueError):
        score_fit(LG, pool, load_prices(PRICES), "vibes")


def test_choose_policy_returns_one_of_the_two_and_both_reports():
    pool = [player("Ja'Marr Chase", "WR", 200), player("Chase Brown", "RB", 120),
            player("Bijan Robinson", "RB", 180), player("Nico Collins", "WR", 90)]
    best, reports = choose_policy(LG, pool, load_prices(PRICES))
    assert best in ("starter", "draftable")
    assert len(reports) == 2
    assert {r["policy"] for r in reports} == {"starter", "draftable"}


def test_players_with_no_observed_price_are_excluded_from_the_fit():
    pool = [player("Ja'Marr Chase", "WR", 200), player("Nobody At All", "WR", 150)]
    rep = score_fit(LG, pool, load_prices(PRICES), "starter")
    assert rep["n"] == 1
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_fit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.fit'`

- [ ] **Step 4: Implement the fit**

Create `src/sffl/fit.py`:

```python
"""Choose the replacement-level policy by fitting against real auction prices.

The league paid 156 real prices in 2025. Rather than picking a policy by
preference, score both against what actually happened and report the error so a
poor fit is visible.
"""

import csv
from typing import Dict, List, Tuple

from sffl.identity import normalize_name
from sffl.value import assign_dollars, assign_vorp, replacement_levels

POLICIES = ("starter", "draftable")


def load_prices(path):
    """Map normalized player name -> price paid."""
    out = {}  # type: Dict[str, float]
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            name = normalize_name(row["player_as_written"])
            if name:
                out[name] = float(row["price"])
    return out


def score_fit(lg, pool, prices, policy, resolver=None):
    """Value the pool under `policy` and compare to observed prices."""
    if policy not in POLICIES:
        raise ValueError("unknown replacement policy %r" % policy)

    levels = replacement_levels(lg, pool, policy)
    assign_vorp(lg, pool, levels)
    assign_dollars(lg, pool)

    pairs = []
    for p in pool:
        key = normalize_name(p.name)
        if key in prices:
            pairs.append((p.stats["_dollars"], prices[key]))

    if not pairs:
        return {"policy": policy, "n": 0, "mae": float("inf"),
                "rmse": float("inf"), "top10_mae": float("inf")}

    errs = [abs(model - actual) for model, actual in pairs]
    sq = [(model - actual) ** 2 for model, actual in pairs]
    top = sorted(pairs, key=lambda t: -t[1])[:10]
    top_errs = [abs(m - a) for m, a in top]

    return {
        "policy": policy,
        "n": len(pairs),
        "mae": sum(errs) / len(errs),
        "rmse": (sum(sq) / len(sq)) ** 0.5,
        "top10_mae": sum(top_errs) / len(top_errs),
    }


def choose_policy(lg, pool, prices, resolver=None):
    """Return the policy with the lower top-10 error, plus both reports.

    Top-10 error is the tiebreaker rather than overall error because the
    expensive players are where a mispriced board actually costs money.
    """
    reports = [score_fit(lg, pool, prices, p, resolver) for p in POLICIES]
    best = min(reports, key=lambda r: (r["top10_mae"], r["mae"]))
    return best["policy"], reports
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_fit.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/sffl/fit.py tests/test_fit.py tests/fixtures/prices_sample.csv
git commit -m "feat: choose replacement policy by fitting real 2025 prices"
```

---

### Task 8: The `value` CLI command

**Files:**
- Modify: `src/sffl/cli.py`
- Test: `tests/test_cli_value.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7 plus the existing `build_pool`.
- Produces: `python -m sffl.cli value --source SRC --file PATH --year YEAR
  [--set NAME] [--curves PATH] [--policy starter|draftable|fit] [--prices PATH]
  [--out CSV]`

**Behaviour.** Builds the pool, optionally applies calibration curves, assigns VORP and
dollars, and prints the top 25 with their dollar value and spread. With
`--policy fit` it requires `--prices` and reports both fits before choosing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_value.py`:

```python
from sffl.cli import main

DS = "sources/draftsharks.yaml"
FIXTURE = "tests/fixtures/draftsharks_sample.csv"


def test_value_command_runs_and_returns_zero(capsys):
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "starter"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "$" in out


def test_fit_policy_requires_prices(capsys):
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "fit"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "--prices" in out


def test_value_writes_a_csv(tmp_path):
    path = str(tmp_path / "board.csv")
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "starter", "--out", path])
    assert rc == 0
    with open(path) as fh:
        header = fh.readline()
    assert "dollars" in header
    assert "spread" in header
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_cli_value.py -v`
Expected: FAIL — `value` is not a known subcommand

- [ ] **Step 3: Implement the command**

Add to `src/sffl/cli.py`:

```python
from sffl.calibrate import load_curves
from sffl.fit import choose_policy, load_prices, score_fit
from sffl.pool import score_season_calibrated
from sffl.value import assign_dollars, assign_vorp, replacement_levels


def cmd_value(args):
    lg = load_league(args.league)
    pool = build_pool(lg, args.source, args.file, args.year, args.set)

    if args.curves:
        curves = load_curves(args.curves)
        for p in pool:
            p.stats["_season_points"] = score_season_calibrated(lg, p, curves)
        pool.sort(key=lambda p: -p.stats["_season_points"])

    policy = args.policy
    if policy == "fit":
        if not args.prices:
            print("error: --policy fit requires --prices with observed auction prices")
            return 1
        prices = load_prices(args.prices)
        policy, reports = choose_policy(lg, pool, prices)
        for r in reports:
            print("  %-10s n=%-4d mae=$%.2f rmse=$%.2f top10_mae=$%.2f"
                  % (r["policy"], r["n"], r["mae"], r["rmse"], r["top10_mae"]))
        print("  chosen: %s\n" % policy)

    levels = replacement_levels(lg, pool, policy)
    assign_vorp(lg, pool, levels)
    rate = assign_dollars(lg, pool)

    print("replacement level (%s policy):" % policy)
    for name in sorted(levels):
        print("  %-5s %8.1f pts" % (name, levels[name]))
    print("  $%.4f per VORP point\n" % rate)

    pool.sort(key=lambda p: -p.stats["_dollars"])
    print("top 25 by value:")
    for i, p in enumerate(pool[:25], 1):
        spread = p.stats.get("_spread_rec_yds", 0.0) + p.stats.get("_spread_rush_yds", 0.0)
        print("  %2d. $%5.1f  %-4s %-24s vorp %6.1f  spread %5.1f"
              % (i, p.stats["_dollars"], p.pos, p.name[:24], p.stats["_vorp"], spread))

    if args.out:
        with open(args.out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["name", "team", "pos", "games", "season_points",
                        "vorp", "dollars", "spread", "n_sources"])
            for p in pool:
                spread = (p.stats.get("_spread_rec_yds", 0.0)
                          + p.stats.get("_spread_rush_yds", 0.0))
                w.writerow([p.name, p.team, p.pos, p.games,
                            round(p.stats.get("_season_points", 0.0), 2),
                            round(p.stats.get("_vorp", 0.0), 2),
                            round(p.stats.get("_dollars", 0.0), 2),
                            round(spread, 2),
                            int(p.stats.get("_n_sources", 1))])
        print("\nwrote %s" % args.out)
    return 0
```

And register it inside `main`, immediately after the existing `ingest` parser:

```python
    val = sub.add_parser("value", help="assign auction dollar values")
    val.add_argument("--source", required=True)
    val.add_argument("--file", required=True)
    val.add_argument("--year", type=int, required=True)
    val.add_argument("--set", default=None)
    val.add_argument("--league", default=DEFAULT_LEAGUE)
    val.add_argument("--curves", default=None,
                     help="calibration curves YAML from `sffl.calibrate`")
    val.add_argument("--policy", default="starter",
                     choices=["starter", "draftable", "fit"])
    val.add_argument("--prices", default=None,
                     help="observed auction prices CSV; required with --policy fit")
    val.add_argument("--out", default=None)
    val.set_defaults(func=cmd_value)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_cli_value.py -v`
Expected: 3 passed

- [ ] **Step 5: Run against real data**

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli value \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026 \
  --policy fit --prices data/league/auction-rosters-2025.csv
```

Expected: both fit reports print, a policy is chosen, replacement levels and a top-25
board follow. Record the actual numbers in the report — do not tune anything to match an
expectation.

- [ ] **Step 6: Run the whole suite**

Run: `./.venv/bin/pytest -q`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/sffl/cli.py tests/test_cli_value.py
git commit -m "feat: value command producing a priced auction board"
```

---

## Self-Review

**Spec coverage.** Value engine emitting a dollar value → Tasks 5-6. Replacement level
chosen empirically rather than by preference → Task 7, which closes the last open
question in the spec. Consensus across analyst sets with the spread preserved → Task 4.
The averaging bias, previously the largest known flaw → Tasks 1-3, replaced with
measured expectation curves. WR/TE as one pool → enforced in `value.py` and tested.

**Deliberately out of scope.** The silent auction planner is its own plan. Both
renderers are their own plan. Neither is blocked by this work; both consume
`_dollars` and `_spread_*`.

**Known limitation carried forward.** Sacks use a threshold rule rather than a band
table, so `score_season_calibrated` does not correct them — a defense averaging 2.5
sacks per game still scores zero sack points across a season. This is documented in the
function docstring and pinned by the existing characterization test. Fixing it needs a
threshold-aware curve, which is a follow-up.

**Operational dependency.** Tasks 2-3 need `data/weekly/2025/*.csv`, collected
separately through the browser. Task 1 defines the exact contract, and every other task
runs without that data — only the calibration curves need it. If collection slips, Tasks
4-8 still land and `--curves` simply goes unused.

**Type consistency.** `PlayerProjection.stats` keys used across tasks: `_season_points`
(set by `build_pool`, read by `value.py`), `_vorp` (set by `assign_vorp`, read by
`assign_dollars` and `fit.py`), `_dollars` (set by `assign_dollars`, read by `fit.py`
and the CLI), `_spread_<stat>` and `_n_sources` (set by `consensus.merge`, read by the
CLI). Pool names are exactly `"TQB"`, `"FLEX"`, `"K"`, `"DST"` in Tasks 5-8. Policy
strings are exactly `"starter"` and `"draftable"` everywhere, with `"fit"` accepted only
at the CLI.

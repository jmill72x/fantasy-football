# In-Season Core (read-only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sffl week --waivers` and `--start-sit` answer, in this league's banded scoring, which free agent most improves Jeff's starting lineup and whether his current lineup is optimal.

**Architecture:** A pure optimizer (`lineup.py`) over candidates scored by a weekly analogue of the existing calibrated scorer. Projections and rosters are parsed from saved CBS page text — no module performs network I/O, so every parser is testable against a fixture. Waivers is the general case; start/sit is the same optimizer with the candidate pool restricted to owned players.

**Tech Stack:** Python 3.9.6, PyYAML, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-27-in-season-tooling-design.md`

## Global Constraints

- **Python 3.9.6 only.** No `match` statements, no PEP 604 (`int | None`) annotations. Use `Optional[int]`.
- **Use the venv:** `./.venv/bin/pytest`, `./.venv/bin/python`. `sffl` is not pip-installed, so ad-hoc scripts need `PYTHONPATH=src`.
- **`src/sffl/scoring.py` MUST NOT be modified.** It is validated against ~250 real CBS weekly observations.
- **The repo is public.** `data/extracts/` and `data/weekly/` are gitignored. Any new path holding vendor projections, CBS stat lines, or roster composition must be added to `.gitignore` in the same commit that first writes it.
- **A zero is not a no-op for `def_pa`/`def_ya`.** Both band the value `0` at their MAXIMUM (6 points). Any loop over `lg.bands` that is not position-gated pays every receiver and kicker a phantom shutout. This bug has been introduced three times in this codebase. Gate on `calibrate.STAT_POSITIONS`.
- **`band_points` FLOORS, `expected_points` CLAMPS.** Below the lowest observed value `band_points` returns 0 while `expected_points` returns the curve's lowest anchor. Swapping one for the other without a position gate paid every non-passer 72 phantom season points.
- **No module in this plan performs network I/O.** Parsers take text or a path. Fetching is a separate operator step.
- **No test may write to the real CBS league.** This plan is read-only; nothing in it submits anything.

---

## File Structure

| file | responsibility |
|---|---|
| `leagues/sffl/2026.yaml` | gains an explicit `lineup:` slot list (modified) |
| `src/sffl/league.py` | parses and validates `lineup:` (modified) |
| `src/sffl/pool.py` | gains `score_week` beside `score_season_calibrated` (modified) |
| `src/sffl/lineup.py` | **new** — `Candidate`, `best_lineup`, `delta`. Pure, no I/O |
| `sources/cbs-weekly.yaml` | **new** — per-position column maps for the CBS weekly projections table |
| `src/sffl/cbs_weekly.py` | **new** — parse saved CBS page text into `PlayerProjection` |
| `src/sffl/cli.py` | gains the `week` command (modified) |

`lineup.py` is deliberately free of `PlayerProjection`: it takes plain `Candidate` tuples so the optimizer can be tested exhaustively with no fixtures, no league data, and no scoring.

---

### Task 1: Explicit lineup slots in the league profile

The league YAML records `starters: 8` and `flex_slots: 5` — counts, not slots. An optimizer needs slots.

**Files:**
- Modify: `leagues/sffl/2026.yaml`
- Modify: `src/sffl/league.py`
- Test: `tests/test_league.py`

**Interfaces:**
- Produces: `League.lineup` — a `List[Tuple[str, Tuple[str, ...]]]` of `(slot_label, eligible_positions)`, in the order written in the YAML.

- [ ] **Step 1: Write the failing test**

```python
def test_the_lineup_slots_are_explicit_and_ordered():
    lg = load_league("leagues/sffl/2026.yaml")
    assert lg.lineup == [
        ("TQB", ("TQB",)),
        ("RB", ("RB",)),
        ("WR/TE", ("WR", "TE")),
        ("FLEX1", ("RB", "WR", "TE")),
        ("FLEX2", ("RB", "WR", "TE")),
        ("FLEX3", ("RB", "WR", "TE")),
        ("K", ("K",)),
        ("DST", ("DST",)),
    ]


def test_the_slot_list_must_agree_with_the_starter_and_flex_counts():
    """starters and flex_slots existed first and are used by the auction path.
    Two sources of truth for the same fact drift; this makes them fail loudly."""
    lg = load_league("leagues/sffl/2026.yaml")
    assert len(lg.lineup) == lg.starters
    flex = [s for s, elig in lg.lineup if set(elig) & {"RB", "WR", "TE"}]
    assert len(flex) == lg.flex_slots


def test_a_lineup_slot_naming_an_unknown_position_is_rejected(tmp_path):
    raw = open("leagues/sffl/2026.yaml").read()
    raw = raw.replace('- {slot: "K", eligible: ["K"]}',
                      '- {slot: "K", eligible: ["PUNTER"]}')
    bad = tmp_path / "bad.yaml"
    bad.write_text(raw)
    with pytest.raises(ValueError, match="PUNTER"):
        load_league(str(bad))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_league.py -k lineup -v`
Expected: FAIL with `AttributeError: 'League' object has no attribute 'lineup'`

- [ ] **Step 3: Add the slot list to the league profile**

Insert directly below `flex_slots: 5` in `leagues/sffl/2026.yaml`:

```yaml
# The weekly starting lineup, slot by slot. `starters` and `flex_slots` above
# are the counts the auction path uses; this is the same fact as an ordered
# list, which is what an optimizer needs. league.py asserts the two agree.
#
# The RB and WR/TE slots ARE the floors - there is no separate floor setting.
# A slot that only accepts RB forces one RB into the lineup by construction.
lineup:
  - {slot: "TQB",   eligible: ["TQB"]}
  - {slot: "RB",    eligible: ["RB"]}
  - {slot: "WR/TE", eligible: ["WR", "TE"]}
  - {slot: "FLEX1", eligible: ["RB", "WR", "TE"]}
  - {slot: "FLEX2", eligible: ["RB", "WR", "TE"]}
  - {slot: "FLEX3", eligible: ["RB", "WR", "TE"]}
  - {slot: "K",     eligible: ["K"]}
  - {slot: "DST",   eligible: ["DST"]}
```

- [ ] **Step 4: Parse and validate it**

In `src/sffl/league.py`, after `self.flex_slots = int(raw["flex_slots"])`:

```python
        # Ordered (slot_label, eligible_positions). See the YAML comment for
        # why this exists alongside starters/flex_slots.
        self.lineup = []  # type: List[Tuple[str, Tuple[str, ...]]]
        known = {"TQB", "QB", "RB", "WR", "TE", "K", "DST"}
        for entry in raw.get("lineup", []):
            slot = str(entry["slot"])
            elig = tuple(str(p) for p in entry["eligible"])
            unknown = [p for p in elig if p not in known]
            if unknown:
                raise ValueError(
                    "lineup slot %r lists unknown position(s) %s; expected "
                    "some of %s" % (slot, unknown, sorted(known)))
            self.lineup.append((slot, elig))
        if self.lineup:
            if len(self.lineup) != self.starters:
                raise ValueError(
                    "lineup has %d slots but starters is %d; they describe the "
                    "same fact and must agree"
                    % (len(self.lineup), self.starters))
            flex = [s for s, e in self.lineup if set(e) & {"RB", "WR", "TE"}]
            if len(flex) != self.flex_slots:
                raise ValueError(
                    "lineup has %d RB/WR/TE-eligible slots but flex_slots is "
                    "%d" % (len(flex), self.flex_slots))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_league.py -v && ./.venv/bin/pytest -q`
Expected: PASS, and the full suite still green (341 tests before this task).

- [ ] **Step 6: Commit**

```bash
git add leagues/sffl/2026.yaml src/sffl/league.py tests/test_league.py
git commit -m "feat(league): explicit weekly lineup slots"
```

---

### Task 2: `score_week` — the weekly calibrated scorer

The edge this whole project rests on. CBS bands a point estimate; `E[band(X)] != band(E[X])`. `calibration/2025.yaml` maps per-game mean to expected points, and **a weekly projection IS a per-game mean**, so the curves apply directly at `games=1`.

**Files:**
- Modify: `src/sffl/pool.py`
- Test: `tests/test_pool.py`

**Interfaces:**
- Consumes: `calibrate.load_curves(path)`, `calibrate.expected_points(curve, mean)`, `calibrate.STAT_POSITIONS`, `scoring.score_game(lg, stats, pos)`, `scoring.band_points(table, value)`.
- Produces: `pool.score_week(lg, player, curves)` -> `float`. `player` is a `PlayerProjection` whose `stats` hold **one week's** projected values (not season totals). `curves` may be `None`, in which case the naive banded score is returned unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_score_week_with_no_curves_is_exactly_score_game():
    """Without curves there is nothing to calibrate, so the weekly scorer must
    not drift from the validated engine by even a rounding step."""
    lg = load_league(LEAGUE)
    p = PlayerProjection(name="Test WR", team="GB", pos="WR", source="t",
                         source_year=2026, games=1.0,
                         stats={"rec_ct": 4.4, "rec_yds": 59.7, "rec_td": 0.5})
    assert score_week(lg, p, None) == score_game(lg, p.stats, "WR")


def test_score_week_pays_a_projection_sitting_just_under_a_band_edge():
    """The whole point. 4.4 receptions is under the 5-reception band, so the
    naive band pays 0 - but a player projected at 4.4 clears 5 in plenty of
    weeks and has a real expectation."""
    lg = load_league(LEAGUE)
    curves = load_curves("calibration/2025.yaml")
    p = PlayerProjection(name="Test WR", team="GB", pos="WR", source="t",
                         source_year=2026, games=1.0, stats={"rec_ct": 4.4})
    naive = score_game(lg, p.stats, "WR")
    assert naive == 0.0
    assert score_week(lg, p, curves) > 0.5


def test_score_week_does_not_pay_a_receiver_for_a_shutout_he_never_played():
    """def_pa and def_ya band 0 at their MAXIMUM. An ungated loop pays every
    non-defense 12 points a game. This has been introduced three times."""
    lg = load_league(LEAGUE)
    curves = load_curves("calibration/2025.yaml")
    wr = PlayerProjection(name="Test WR", team="GB", pos="WR", source="t",
                          source_year=2026, games=1.0,
                          stats={"rec_ct": 4.4, "def_pa": 0.0, "def_ya": 0.0})
    assert score_week(lg, wr, curves) < 5.0


def test_score_week_does_not_pay_a_kicker_from_a_passing_curve():
    """expected_points CLAMPS below the lowest anchor where band_points FLOORS.
    pass_yds curves are built from QB weeks only, so their lowest anchor is far
    above zero; asking one about a kicker's 0.0 pays phantom points."""
    lg = load_league(LEAGUE)
    curves = load_curves("calibration/2025.yaml")
    k = PlayerProjection(name="Test K", team="GB", pos="K", source="t",
                         source_year=2026, games=1.0,
                         stats={"xp_made": 2.0, "pass_yds": 0.0})
    naive = score_game(lg, k.stats, "K")
    assert score_week(lg, k, curves) == naive
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_pool.py -k score_week -v`
Expected: FAIL with `ImportError: cannot import name 'score_week'`

- [ ] **Step 3: Implement it**

Add to `src/sffl/pool.py`, directly below `score_season_calibrated`:

```python
def score_week(lg, player, curves):
    """Expected points for ONE week from a projected stat line.

    `player.stats` holds a single week's projection, not a season total, so
    unlike `score_season_calibrated` there is no division by games and no
    multiplication back up.

    WHY THIS IS NOT JUST score_game. CBS already applies this league's bands to
    its weekly projections and agrees with `score_game` to within a cent. But it
    bands a POINT ESTIMATE, and `E[band(X)] != band(E[X])`: a player projected
    at 4.4 receptions is scored 0 for receptions, when he clears 5 in plenty of
    weeks. The curves map per-game mean -> expected points, and a weekly
    projection IS a per-game mean, so they apply directly here.

    The gating below is identical to `score_season_calibrated`'s and exists for
    the same two reasons - see its docstring. Do not simplify either gate away.
    """
    if curves is None:
        return score_game(lg, player.stats, pos=player.pos)

    line = dict((k, v) for k, v in player.stats.items()
                if not k.startswith("_"))

    applicable = _ALWAYS_BANDED
    if player.pos == "DST":
        applicable = _ALWAYS_BANDED + ("def_pa", "def_ya")

    full = score_game(lg, line, pos=player.pos)

    naive_banded = 0.0
    calibrated_banded = 0.0
    for stat in applicable:
        value = line.get(stat, 0.0)
        naive_banded += band_points(lg.bands[stat], value)
        curve = curves.get(stat)
        if curve and player.pos in STAT_POSITIONS.get(stat, ()):
            calibrated_banded += expected_points(curve, value)
        else:
            calibrated_banded += band_points(lg.bands[stat], value)

    return (full - naive_banded) + calibrated_banded
```

No new imports are needed. Verified 2026-08-28: `pool.py` already has
`STAT_POSITIONS` and `expected_points` (line 3), `band_points` and `score_game`
(line 5), and defines `_ALWAYS_BANDED` at line 11 — all from
`score_season_calibrated`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_pool.py -v && ./.venv/bin/pytest -q`
Expected: PASS, full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/sffl/pool.py tests/test_pool.py
git commit -m "feat(pool): score_week - calibrated expectation for one week"
```

---

### Task 3: `lineup.py` — the optimizer

**Files:**
- Create: `src/sffl/lineup.py`
- Test: `tests/test_lineup.py`

**Interfaces:**
- Consumes: `League.lineup` from Task 1.
- Produces:
  - `lineup.Candidate` — `namedtuple("Candidate", "name pos points")`
  - `lineup.best_lineup(lg, candidates)` -> `LineupResult`, a `namedtuple("LineupResult", "slots total")` where `slots` is `List[Tuple[str, Optional[Candidate]]]` in league slot order and `total` is a `float`
  - `lineup.delta(lg, roster, addition)` -> `float`

- [ ] **Step 1: Write the failing tests**

```python
import itertools
import pytest
from sffl.league import load_league
from sffl.lineup import Candidate, best_lineup, delta

LG = load_league("leagues/sffl/2026.yaml")


def c(name, pos, pts):
    return Candidate(name=name, pos=pos, points=float(pts))


def full_roster():
    """Eight startable players, one per slot, plus flex depth."""
    return [c("qb", "TQB", 20), c("rb1", "RB", 12), c("rb2", "RB", 9),
            c("wr1", "WR", 15), c("wr2", "WR", 11), c("te1", "TE", 8),
            c("k", "K", 7), c("d", "DST", 6)]


def test_single_position_slots_take_their_best():
    r = best_lineup(LG, full_roster() + [c("qb2", "TQB", 25)])
    slots = dict(r.slots)
    assert slots["TQB"].name == "qb2"
    assert slots["K"].name == "k"
    assert slots["DST"].name == "d"


def test_the_rb_slot_forces_a_running_back_even_when_receivers_score_more():
    """The RB slot IS the floor. Five receivers outscoring every back must not
    produce a lineup with no RB in it."""
    roster = [c("qb", "TQB", 20), c("k", "K", 7), c("d", "DST", 6),
              c("rb1", "RB", 2),
              c("wr1", "WR", 20), c("wr2", "WR", 19), c("wr3", "WR", 18),
              c("wr4", "WR", 17), c("wr5", "WR", 16)]
    r = best_lineup(LG, roster)
    picked = [x.name for _s, x in r.slots if x]
    assert "rb1" in picked
    assert "wr5" not in picked          # the worst receiver is displaced


def test_the_wr_te_slot_forces_a_receiver_when_backs_score_more():
    roster = [c("qb", "TQB", 20), c("k", "K", 7), c("d", "DST", 6),
              c("te1", "TE", 2),
              c("rb1", "RB", 20), c("rb2", "RB", 19), c("rb3", "RB", 18),
              c("rb4", "RB", 17), c("rb5", "RB", 16)]
    r = best_lineup(LG, roster)
    picked = [x.name for _s, x in r.slots if x]
    assert "te1" in picked


def test_both_floors_bind_at_once():
    roster = [c("rb1", "RB", 1), c("te1", "TE", 1)] + [
        c("wr%d" % i, "WR", 10 + i) for i in range(5)]
    r = best_lineup(LG, roster)
    picked = [x.name for _s, x in r.slots if x]
    assert "rb1" in picked and "te1" in picked


def test_the_fast_path_agrees_with_brute_force_on_every_legal_combination():
    """A greedy repair that is subtly wrong produces a plausible lineup and
    silently costs points every week. Brute-force the flex pool and confirm."""
    flex = [c("p%d" % i, ("RB", "WR", "TE")[i % 3], 20 - i) for i in range(9)]
    fixed = [c("qb", "TQB", 20), c("k", "K", 7), c("d", "DST", 6)]
    best = 0.0
    for combo in itertools.combinations(flex, 5):
        poss = [x.pos for x in combo]
        if "RB" not in poss:
            continue
        if not ({"WR", "TE"} & set(poss)):
            continue
        best = max(best, sum(x.points for x in combo))
    r = best_lineup(LG, fixed + flex)
    assert r.total == pytest.approx(best + 33.0)   # 20 + 7 + 6 fixed slots


def test_a_roster_too_short_leaves_slots_empty_rather_than_inventing_players():
    r = best_lineup(LG, [c("rb1", "RB", 12)])
    slots = dict(r.slots)
    assert slots["RB"].name == "rb1"
    assert slots["TQB"] is None
    assert r.total == pytest.approx(12.0)


def test_an_empty_candidate_list_scores_zero_and_does_not_raise():
    r = best_lineup(LG, [])
    assert r.total == 0.0
    assert all(x is None for _s, x in r.slots)


def test_ties_break_deterministically_by_name():
    """Two runs must not disagree about an identical roster, or the 'what
    changed since last week' diff reports phantom changes."""
    a = best_lineup(LG, [c("bbb", "RB", 5), c("aaa", "RB", 5)])
    b = best_lineup(LG, [c("aaa", "RB", 5), c("bbb", "RB", 5)])
    assert [x.name for _s, x in a.slots if x] == [x.name for _s, x in b.slots if x]


def test_delta_is_the_improvement_a_player_makes_to_the_optimal_lineup():
    roster = full_roster()
    base = best_lineup(LG, roster).total
    better_rb = c("stud", "RB", 30)
    assert delta(LG, roster, better_rb) == pytest.approx(
        best_lineup(LG, roster + [better_rb]).total - base)
    assert delta(LG, roster, better_rb) > 0


def test_delta_is_zero_for_a_player_who_would_not_crack_the_lineup():
    """A bench stash improves nothing this week, and the waiver output must be
    able to tell that apart from a claim that starts."""
    roster = full_roster()
    assert delta(LG, roster, c("scrub", "RB", 0.1)) == pytest.approx(0.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_lineup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.lineup'`

- [ ] **Step 3: Implement the optimizer**

Create `src/sffl/lineup.py`:

```python
"""The best legal starting lineup, and what one more player would add to it.

PURE ON PURPOSE. This module takes `Candidate` tuples rather than
`PlayerProjection`, performs no I/O, and knows nothing about scoring. It is the
piece with real logic in it, so it must be exhaustively testable with no
fixtures and no network - see the brute-force test.

WHY THE OPTIMUM IS A SUBSET, NOT AN ASSIGNMENT. The flex-eligible slots
(RB, WR/TE, FLEX x3) are interchangeable: every legal lineup uses exactly five
players from the RB/WR/TE pool with at least one RB and at least one WR or TE,
and its total is the sum of their points. The slot LABELS do not affect the
total, so maximizing over assignments is the same as choosing the best legal
five-player subset. That is why a subset search is exact here and not a
heuristic.
"""

from collections import namedtuple

Candidate = namedtuple("Candidate", "name pos points")
LineupResult = namedtuple("LineupResult", "slots total")

_FLEX = ("RB", "WR", "TE")


def _sorted(cands):
    """Highest points first, name ascending as the tiebreak.

    Deterministic ties matter: the weekly diff reports what changed since the
    last run, and two runs that disagree about an identical roster would report
    changes that did not happen.
    """
    return sorted(cands, key=lambda x: (-x.points, x.name))


def _best_flex_five(cands, n, need):
    """Best `n`-player subset of the flex pool meeting the `need` floors.

    `need` maps a label to the set of positions that satisfies it, e.g.
    {"rb": {"RB"}, "wrte": {"WR", "TE"}}.
    """
    ranked = _sorted(cands)
    chosen = list(ranked[:n])
    for _label, positions in sorted(need.items()):
        if any(x.pos in positions for x in chosen):
            continue
        replacement = next((x for x in ranked
                            if x.pos in positions and x not in chosen), None)
        if replacement is None:
            continue
        # Drop the cheapest chosen player who is not the sole satisfier of
        # another floor, so repairing one floor cannot break another.
        droppable = []
        for x in chosen:
            others = [c for c in chosen if c is not x]
            if all(any(o.pos in p for o in others)
                   for _l, p in need.items() if any(c.pos in p for c in chosen)):
                droppable.append(x)
        if not droppable:
            droppable = list(chosen)
        worst = _sorted(droppable)[-1]
        chosen[chosen.index(worst)] = replacement
    return chosen


def best_lineup(lg, candidates):
    """The highest-scoring legal lineup, as (slots, total).

    `slots` is in league order and carries None for any slot the roster cannot
    fill - an unfillable slot is reported, never silently skipped and never
    filled with an ineligible player.
    """
    remaining = list(candidates)
    flex_slots = [(s, e) for s, e in lg.lineup if set(e) & set(_FLEX)]
    fixed_slots = [(s, e) for s, e in lg.lineup if not set(e) & set(_FLEX)]

    filled = {}
    for slot, elig in fixed_slots:
        pick = next((x for x in _sorted(remaining) if x.pos in elig), None)
        filled[slot] = pick
        if pick is not None:
            remaining.remove(pick)

    pool = [x for x in remaining if x.pos in _FLEX]
    need = {}
    for slot, elig in flex_slots:
        if set(elig) != set(_FLEX):
            need[slot] = set(elig)
    picked = _best_flex_five(pool, len(flex_slots), need)

    picked_sorted = _sorted(picked)
    for slot, elig in flex_slots:
        pick = next((x for x in picked_sorted if x.pos in elig), None)
        filled[slot] = pick
        if pick is not None:
            picked_sorted.remove(pick)

    slots = [(s, filled.get(s)) for s, _e in lg.lineup]
    total = sum(x.points for _s, x in slots if x is not None)
    return LineupResult(slots=slots, total=total)


def delta(lg, roster, addition):
    """How much `addition` would improve the optimal lineup. Never negative."""
    base = best_lineup(lg, roster).total
    with_add = best_lineup(lg, list(roster) + [addition]).total
    return max(0.0, with_add - base)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_lineup.py -v && ./.venv/bin/pytest -q`
Expected: PASS. If the brute-force test fails, the repair in `_best_flex_five` is wrong — fix the implementation, never the test.

- [ ] **Step 5: Commit**

```bash
git add src/sffl/lineup.py tests/test_lineup.py
git commit -m "feat(lineup): exact best-legal-lineup optimizer and marginal delta"
```

---

### Task 4: Parse the CBS weekly projections table

CBS renders the table as text; `get_page_text` returns one line per player. Fetching is an operator step — this task parses a saved file.

Sample line, verified from the live league site on 2026-08-28:

```
W (9/16) Harold Fannin Jr. TE • CLE @JAC 22 11 86 63 8 0.4 0.8 2.0 0.1 7.7 5.2 46.5 8.9 0.5 0.1 4.81
```

Reading right to left the stat block is fixed for the RB-WR-TE view: `rush_att rush_yds rush_avg rush_td tgt rec_ct rec_yds rec_avg rec_td fum_lost fpts`. Reading left to right the identity is `avail`, `name`, `pos`, `•`, `team`. Between them sit `OPP OVP BYE ROST START EXPERT`, and **`EXPERT` can be the non-numeric `N/R`** — which is why the stat block is taken from the right rather than by counting from the left.

**Files:**
- Create: `sources/cbs-weekly.yaml`
- Create: `src/sffl/cbs_weekly.py`
- Create: `tests/fixtures/cbs_weekly_rbwrte.txt`
- Test: `tests/test_cbs_weekly.py`

**Interfaces:**
- Produces: `cbs_weekly.parse(path, group, week, profile_path="sources/cbs-weekly.yaml")` -> `List[PlayerProjection]`, each with `games=1.0`, `source="cbs-weekly"`, `source_year` from the league season, and `stats` keyed by the same field names the auction path uses (`rush_yds`, `rec_ct`, `rec_yds`, `rec_td`, ...) plus `fum_lost`.

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/cbs_weekly_rbwrte.txt` with exactly these five lines (real projections captured 2026-08-28; no licensed vendor content, these are CBS's own public league-view numbers for free agents):

```
W (9/16) Harold Fannin Jr. TE • CLE @JAC 22 11 86 63 8 0.4 0.8 2.0 0.1 7.7 5.2 46.5 8.9 0.5 0.1 4.81
W (9/16) Isaiah Likely TE • NYG DAL 13 8 50 25 9 0.0 0.0 0.0 0.0 6.0 4.4 59.7 13.6 0.5 0.1 3.51
W (9/16) Elic Ayomanor WR • TEN NYJ 13 9 10 1 N/R 0.0 0.0 0.0 0.0 5.1 2.6 36.0 13.8 0.5 0.0 2.51
W (9/16) Braelon Allen RB • NYJ @TEN 17 13 25 1 55 9.5 36.8 3.9 0.4 1.4 0.9 7.9 8.8 0.1 0.2 1.70
W (9/16) Tyrone Tracy Jr. RB • NYG DAL 31 8 75 26 58 7.9 36.6 4.6 0.2 2.6 1.9 16.0 8.4 0.1 0.1 1.10
```

- [ ] **Step 2: Write the failing tests**

```python
import pytest
from sffl.cbs_weekly import parse

FIXTURE = "tests/fixtures/cbs_weekly_rbwrte.txt"


def by_name(rows):
    return dict((r.name, r) for r in rows)


def test_every_line_parses_and_nothing_is_silently_dropped():
    rows = parse(FIXTURE, group="RB-WR-TE", week=1)
    assert len(rows) == 5


def test_stats_land_in_the_right_slots():
    r = by_name(parse(FIXTURE, group="RB-WR-TE", week=1))["Braelon Allen"]
    assert r.pos == "RB" and r.team == "NYJ"
    assert r.stats["rush_yds"] == 36.8
    assert r.stats["rush_td"] == 0.4
    assert r.stats["rec_ct"] == 0.9
    assert r.stats["rec_yds"] == 7.9
    assert r.stats["fum_lost"] == 0.2


def test_a_non_numeric_expert_rank_does_not_shift_the_stat_block():
    """EXPERT is 'N/R' for unranked players. Counting fields from the LEFT
    would shift every stat after it by one and produce a plausible wrong line."""
    r = by_name(parse(FIXTURE, group="RB-WR-TE", week=1))["Elic Ayomanor"]
    assert r.stats["rec_ct"] == 2.6
    assert r.stats["rec_yds"] == 36.0
    assert r.stats["rush_yds"] == 0.0


def test_a_multi_word_suffixed_name_parses():
    rows = by_name(parse(FIXTURE, group="RB-WR-TE", week=1))
    assert "Harold Fannin Jr." in rows
    assert "Tyrone Tracy Jr." in rows


def test_every_row_is_one_week_not_a_season():
    for r in parse(FIXTURE, group="RB-WR-TE", week=1):
        assert r.games == 1.0


def test_a_line_whose_stat_block_is_the_wrong_width_raises(tmp_path):
    """The layout is positional. A changed column count must fail loudly, the
    same discipline `expect_columns` enforces on the auction extracts."""
    bad = tmp_path / "bad.txt"
    bad.write_text("W (9/16) Someone Short RB • NYJ @TEN 17 13 25 1 55 9.5 36.8\n")
    with pytest.raises(ValueError, match="expected 11"):
        parse(str(bad), group="RB-WR-TE", week=1)


def test_an_unknown_group_names_the_groups_that_exist(tmp_path):
    with pytest.raises(ValueError, match="RB-WR-TE"):
        parse(FIXTURE, group="PUNTERS", week=1)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_cbs_weekly.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.cbs_weekly'`

- [ ] **Step 4: Write the column profile**

Create `sources/cbs-weekly.yaml`:

```yaml
# Column maps for the CBS league site's weekly projections table
# (Players -> PROJECTIONS -> TIMEFRAME: WEEK n (PROJ)).
#
# READ RIGHT TO LEFT. The identity prefix is parsed by regex from the left, but
# the stat block is taken from the RIGHT because EXPERT - which sits between
# them - is "N/R" for unranked players. Counting from the left would shift
# every stat after it by one and produce a plausible wrong line.
#
# `stats` lists the trailing fields in order. A name of `_` is a column the
# scoring engine does not use (averages, the site's own FPTS).
groups:
  RB-WR-TE:
    stats: [rush_att, rush_yds, _, rush_td, tgt, rec_ct, rec_yds, _, rec_td,
            fum_lost, _]
```

- [ ] **Step 5: Implement the parser**

Create `src/sffl/cbs_weekly.py`:

```python
"""Parse the CBS league site's weekly projections table from saved page text.

NO NETWORK I/O. The page is fetched by an operator (browser tools) and saved;
this module parses the file. That keeps every test a fixture test and keeps the
parser honest about a layout it cannot control.
"""

import re
import yaml

from sffl.identity import normalize_team
from sffl.schema import PlayerProjection

DEFAULT_PROFILE = "sources/cbs-weekly.yaml"

# "W (9/16) Harold Fannin Jr. TE • CLE @JAC ..." - availability, name,
# position, bullet, team, then the rest.
_LINE = re.compile(
    r"^\s*(?P<avail>[A-Z]+\s*\([^)]*\)|[A-Z]+)\s+"
    r"(?P<name>.+?)\s+"
    r"(?P<pos>TQB|QB|RB|WR|TE|K|DST)\s+"
    r"[•\-]\s+"
    r"(?P<team>[A-Z]{2,3})\s+"
    r"(?P<rest>.+)$"
)


def _load_groups(profile_path):
    with open(profile_path) as fh:
        raw = yaml.safe_load(fh) or {}
    return raw.get("groups", {})


def parse(path, group, week, profile_path=DEFAULT_PROFILE, season=2026):
    """Rows from one saved weekly-projections page, as PlayerProjection.

    Raises ValueError on a stat block whose width has moved - the layout is
    positional, so a changed column count silently reads the wrong stat into
    every field.
    """
    groups = _load_groups(profile_path)
    if group not in groups:
        raise ValueError(
            "unknown group %r; %s defines %s"
            % (group, profile_path, sorted(groups)))
    fields = groups[group]["stats"]

    out = []
    with open(path) as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue
            m = _LINE.match(line)
            if not m:
                continue
            tokens = m.group("rest").split()
            block = tokens[-len(fields):]
            if len(block) != len(fields):
                raise ValueError(
                    "%s: stat block for %r has %d columns, expected %d - the "
                    "layout is positional and a shift reads the wrong stat "
                    "into every field"
                    % (path, m.group("name"), len(block), len(fields)))
            stats = {}
            for field_name, token in zip(fields, block):
                if field_name == "_":
                    continue
                try:
                    stats[field_name] = float(token)
                except ValueError:
                    raise ValueError(
                        "%s: %r has non-numeric %s %r"
                        % (path, m.group("name"), field_name, token))
            out.append(PlayerProjection(
                name=m.group("name").strip(),
                team=normalize_team(m.group("team")),
                pos=m.group("pos"),
                source="cbs-weekly",
                source_year=season,
                games=1.0,
                stats=stats,
                raw_name=m.group("name").strip(),
            ))
    return out
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_cbs_weekly.py -v && ./.venv/bin/pytest -q`
Expected: PASS, full suite green.

- [ ] **Step 7: Commit**

```bash
git add sources/cbs-weekly.yaml src/sffl/cbs_weekly.py \
        tests/test_cbs_weekly.py tests/fixtures/cbs_weekly_rbwrte.txt
git commit -m "feat(cbs): parse the league site's weekly projections table"
```

---

### Task 5: `sffl week --waivers`

The general case. Wires Tasks 1-4 together.

**Files:**
- Modify: `src/sffl/cli.py`
- Test: `tests/test_cli_week.py`

**Interfaces:**
- Consumes: `cbs_weekly.parse`, `pool.score_week`, `lineup.Candidate/best_lineup/delta`, `calibrate.load_curves`, `league.load_league`.
- Produces: CLI `sffl week --projections <file> --group RB-WR-TE --week N --roster <file> [--curves <file>] [--waivers] [--start-sit] [--top N]`.

`--roster` is a text file of one player name per line — Jeff's current roster, saved from the league site the same way projections are. Names resolve through `sffl.identity`.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from sffl.cli import main

PROJ = "tests/fixtures/cbs_weekly_rbwrte.txt"


def roster_file(tmp_path, names):
    p = tmp_path / "roster.txt"
    p.write_text("\n".join(names) + "\n")
    return str(p)


def test_waivers_ranks_free_agents_by_what_they_add_to_the_lineup(tmp_path, capsys):
    r = roster_file(tmp_path, ["Tyrone Tracy Jr."])
    rc = main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
               "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert rc == 0
    # Fannin projects highest of the free agents and must lead the ranking.
    assert "Harold Fannin Jr." in out
    assert out.index("Harold Fannin Jr.") < out.index("Braelon Allen")


def test_waivers_names_the_slot_a_claim_would_fill(tmp_path, capsys):
    """A claim that cracks the lineup is a different recommendation from a
    bench stash, and the output must not present them identically."""
    r = roster_file(tmp_path, ["Tyrone Tracy Jr."])
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
          "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert "SLOT" in out
    assert "bench" in out.lower()


def test_a_roster_name_absent_from_the_projections_is_named_not_zeroed(tmp_path, capsys):
    """Scoring a missing player as 0 silently benches him."""
    r = roster_file(tmp_path, ["Tyrone Tracy Jr.", "Nonexistent Player"])
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
          "--week", "1", "--roster", r, "--waivers"])
    out = capsys.readouterr().out
    assert "Nonexistent Player" in out
    assert "no projection" in out.lower()


def test_an_empty_roster_file_raises_rather_than_claiming_everyone(tmp_path):
    r = roster_file(tmp_path, [])
    with pytest.raises(SystemExit, match="roster is empty"):
        main(["week", "--projections", PROJ, "--group", "RB-WR-TE",
              "--week", "1", "--roster", r, "--waivers"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_cli_week.py -v`
Expected: FAIL with `invalid choice: 'week'`

- [ ] **Step 3: Add the command**

In `src/sffl/cli.py`, register the parser beside the existing `plan` parser:

```python
    wk = sub.add_parser("week", help="weekly waiver and start/sit decisions")
    wk.add_argument("--projections", required=True,
                    help="saved CBS weekly projections page text")
    wk.add_argument("--group", default="RB-WR-TE")
    wk.add_argument("--week", type=int, required=True)
    wk.add_argument("--roster", required=True,
                    help="one owned player name per line")
    wk.add_argument("--league", default=DEFAULT_LEAGUE)
    wk.add_argument("--curves", default=None,
                    help="calibration curves YAML; without it the naive band "
                         "is used and the main edge over CBS is lost")
    wk.add_argument("--waivers", action="store_true")
    wk.add_argument("--start-sit", action="store_true")
    wk.add_argument("--top", type=int, default=10)
```

And the handler:

```python
def _cmd_week(args):
    from sffl.cbs_weekly import parse as parse_weekly
    from sffl.identity import normalize_name
    from sffl.lineup import Candidate, best_lineup, delta
    from sffl.pool import score_week

    lg = load_league(args.league)
    curves = load_curves(args.curves) if args.curves else None
    projections = parse_weekly(args.projections, group=args.group,
                               week=args.week, season=lg.season)

    owned_raw = [l.strip() for l in open(args.roster) if l.strip()]
    if not owned_raw:
        raise SystemExit("roster is empty (%s); an empty roster optimises to "
                         "an empty lineup and would recommend claiming "
                         "everyone" % args.roster)
    owned = set(normalize_name(n) for n in owned_raw)

    by_key = {}
    for p in projections:
        by_key[normalize_name(p.name)] = p

    missing = [n for n in owned_raw if normalize_name(n) not in by_key]
    for name in missing:
        print("  no projection for %s - excluded from the lineup, NOT scored "
              "as zero" % name)

    def cand(p):
        return Candidate(name=p.name, pos=p.pos,
                         points=score_week(lg, p, curves))

    roster = [cand(by_key[k]) for k in owned if k in by_key]
    free = [cand(p) for k, p in by_key.items() if k not in owned]

    base = best_lineup(lg, roster)
    print("\n  best legal lineup: %.2f pts" % base.total)
    for slot, pick in base.slots:
        print("    %-6s %s" % (slot, pick.name if pick else "(unfilled)"))

    if args.waivers or not (args.waivers or args.start_sit):
        ranked = sorted(free, key=lambda c: -delta(lg, roster, c))
        print("\n  WAIVER TARGETS      %-8s %-6s %s" % ("+PTS", "SLOT", "PLAYER"))
        for c in ranked[:args.top]:
            d = delta(lg, roster, c)
            after = best_lineup(lg, roster + [c])
            slot = next((s for s, p in after.slots if p and p.name == c.name),
                        None)
            where = slot if slot else "bench"
            print("    %-8.2f %-6s %s (%s)" % (d, where, c.name, c.pos))
    return 0
```

Wire `_cmd_week` into the dispatch table alongside the other commands.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_cli_week.py -v && ./.venv/bin/pytest -q`
Expected: PASS, full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/sffl/cli.py tests/test_cli_week.py
git commit -m "feat(cli): sffl week --waivers"
```

---

### Task 6: `sffl week --start-sit`

The restricted case: the same optimizer with the candidate pool limited to owned players. Reports only where the optimum differs from the lineup currently set.

**Files:**
- Modify: `src/sffl/cli.py`
- Test: `tests/test_cli_week.py`

**Interfaces:**
- Consumes: everything from Task 5.
- Produces: `--start-sit` output, and a new `--current` flag naming the lineup currently set on CBS (one player name per line) so the diff has something to compare against.

- [ ] **Step 1: Write the failing test**

```python
def test_start_sit_is_silent_when_the_current_lineup_is_already_optimal(tmp_path, capsys):
    r = roster_file(tmp_path, ["Harold Fannin Jr.", "Braelon Allen"])
    cur = tmp_path / "current.txt"
    cur.write_text("Harold Fannin Jr.\nBraelon Allen\n")
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE", "--week", "1",
          "--roster", r, "--current", str(cur), "--start-sit"])
    out = capsys.readouterr().out
    assert "already optimal" in out.lower()


def test_start_sit_names_both_sides_of_a_swap(tmp_path, capsys):
    r = roster_file(tmp_path, ["Harold Fannin Jr.", "Isaiah Likely",
                               "Braelon Allen", "Tyrone Tracy Jr."])
    cur = tmp_path / "current.txt"
    cur.write_text("Tyrone Tracy Jr.\nIsaiah Likely\n")   # weaker of each pair
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE", "--week", "1",
          "--roster", r, "--current", str(cur), "--start-sit"])
    out = capsys.readouterr().out
    assert "START" in out and "SIT" in out
    assert "Harold Fannin Jr." in out
    assert "Tyrone Tracy Jr." in out


def test_start_sit_without_a_current_lineup_prints_the_optimum_and_says_so(tmp_path, capsys):
    r = roster_file(tmp_path, ["Harold Fannin Jr.", "Braelon Allen"])
    main(["week", "--projections", PROJ, "--group", "RB-WR-TE", "--week", "1",
          "--roster", r, "--start-sit"])
    out = capsys.readouterr().out
    assert "no current lineup" in out.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_cli_week.py -k start_sit -v`
Expected: FAIL with `unrecognized arguments: --current`

- [ ] **Step 3: Implement it**

Add the flag beside the others in the `week` parser:

```python
    wk.add_argument("--current", default=None,
                    help="the lineup currently set on CBS, one name per line; "
                         "without it the optimum is printed with no diff")
```

And in `_cmd_week`, after the waiver block:

```python
    if args.start_sit:
        optimal = set(p.name for _s, p in base.slots if p)
        if not args.current:
            print("\n  no current lineup supplied - printing the optimum only")
        else:
            current = set(l.strip() for l in open(args.current) if l.strip())
            start = sorted(optimal - current)
            sit = sorted(current - optimal)
            if not start and not sit:
                print("\n  lineup is already optimal - no changes")
            else:
                print("\n  START           SIT")
                for i in range(max(len(start), len(sit))):
                    a = start[i] if i < len(start) else ""
                    b = sit[i] if i < len(sit) else ""
                    print("    %-15s %s" % (a, b))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_cli_week.py -v && ./.venv/bin/pytest -q`
Expected: PASS, full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/sffl/cli.py tests/test_cli_week.py
git commit -m "feat(cli): sffl week --start-sit"
```

---

### Task 7: Prove the calibration edge on a full week, and document the run

The spec claims the calibrated expectation beats CBS's banded point estimate, measured at +4.88 across eight hand-picked low-projection lines. **That is not evidence of a general improvement** — those lines were chosen because band edges bite there. This task measures it across a whole position group and records the honest answer, whatever it is.

**Files:**
- Create: `poc/measure_weekly_calibration.py`
- Modify: `NEXT.md`

**Interfaces:**
- Consumes: `cbs_weekly.parse`, `pool.score_week`, `scoring.score_game`.
- Produces: a printed comparison; no library code depends on it.

- [ ] **Step 1: Write the measurement script**

Create `poc/measure_weekly_calibration.py`:

```python
"""How far the calibrated weekly expectation moves from CBS's banded estimate.

CBS bands a point estimate; E[band(X)] != band(E[X]). The spec measured +4.88
across eight hand-picked low-projection lines, which is not evidence of a
general improvement - those were chosen because band edges bite hardest there.
This measures a whole saved page.

    PYTHONPATH=src ./.venv/bin/python poc/measure_weekly_calibration.py \
        tests/fixtures/cbs_weekly_rbwrte.txt
"""

import sys

from sffl.calibrate import load_curves
from sffl.cbs_weekly import parse
from sffl.league import load_league
from sffl.pool import score_week
from sffl.scoring import score_game


def main(path):
    lg = load_league("leagues/sffl/2026.yaml")
    curves = load_curves("calibration/2025.yaml")
    rows = parse(path, group="RB-WR-TE", week=1, season=lg.season)
    naive_total = calibrated_total = 0.0
    moved = 0
    print("%-24s %8s %12s %8s" % ("PLAYER", "CBS", "calibrated", "diff"))
    for p in sorted(rows, key=lambda r: -score_week(lg, r, curves)):
        naive = score_game(lg, p.stats, p.pos)
        cal = score_week(lg, p, curves)
        naive_total += naive
        calibrated_total += cal
        if abs(cal - naive) >= 0.5:
            moved += 1
        print("%-24s %8.2f %12.2f %+8.2f" % (p.name[:23], naive, cal, cal - naive))
    print("\n  n=%d   CBS total %.2f   calibrated %.2f   diff %+.2f"
          % (len(rows), naive_total, calibrated_total,
             calibrated_total - naive_total))
    print("  players moved by >= 0.5 pts: %d of %d" % (moved, len(rows)))
    print("\n  A large average diff is NOT the claim. What matters for a start/sit"
          "\n  or waiver decision is whether it changes the ORDER of two players.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1
         else "tests/fixtures/cbs_weekly_rbwrte.txt")
```

- [ ] **Step 2: Run it and read the output**

Run: `PYTHONPATH=src ./.venv/bin/python poc/measure_weekly_calibration.py`
Expected: a table and a total. There is no pass/fail — the output is the finding.

- [ ] **Step 3: Record the honest result in NEXT.md**

Append a short section to `NEXT.md` under a heading `## Weekly calibration — measured`, stating the `n`, the two totals, the difference, how many players moved by at least half a point, and **whether any pair changed order**. If the effect is small, say so plainly; the spec's claim rests on this number and a null result is the useful outcome, not a failure.

- [ ] **Step 4: Commit**

```bash
git add poc/measure_weekly_calibration.py NEXT.md
git commit -m "test: measure the weekly calibration edge across a full page"
```

---

## Self-Review

**Spec coverage.** Lineup slots (Task 1), weekly calibrated scoring (Task 2), the optimizer and marginal delta (Task 3), the CBS weekly parser (Task 4), waivers as the general case with the slot named (Task 5), start/sit as the restricted case (Task 6), and the honesty check on the calibration claim (Task 7). Not covered here, deliberately, and deferred to a second plan: the **write path** (waiver submission, lineup setting), **ntfy + launchd delivery**, **`--trade`**, and the **state file** for "what changed since the last run" — all of which need the write path proven first.

**Placeholder scan.** No TBD/TODO. Every step carries the code or the exact command.

**Type consistency.** `Candidate(name, pos, points)` and `LineupResult(slots, total)` are defined in Task 3 and used unchanged in Tasks 5 and 6. `score_week(lg, player, curves)` is defined in Task 2 and called in Tasks 5, 6 and 7. `parse(path, group, week, profile_path, season)` is defined in Task 4 and called with `season=lg.season` in Tasks 5 and 7. `League.lineup` is produced in Task 1 and consumed in Task 3.

**Known gap, stated rather than hidden.** `sources/cbs-weekly.yaml` defines only the `RB-WR-TE` group. Those are the five flex slots and every waiver decision that matters, and TQB/K/DST slots are constant across a waiver comparison so they cancel in the delta. Adding the other groups is a one-entry-per-group edit to the same YAML with no Python change — which is the point of the profile — but it is not in this plan.

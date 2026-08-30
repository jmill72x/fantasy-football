# Regularised Calibration Curves — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find out — with a pre-registered gate — whether a regularised curve fitted from all available weekly data beats the shipped 48-player interpolation, per stat, and adopt it only where it does.

**Architecture:** Two new curve builders beside the existing one in `src/sffl/calibrate.py`, and a cross-validated measurement harness in `poc/` that judges all three by the same yardstick. Nothing in `calibration/2025.yaml` changes unless a candidate wins its stat outright.

**Tech Stack:** Python 3.9.6, pure stdlib (no numpy, no scipy — neither is installed), pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-regularised-calibration-curves.md`

## Global Constraints

- **Python 3.9.6 only.** No `match`, no PEP 604 annotations. **No numpy, no scipy** — they are not installed and must not be added. Everything in pure stdlib.
- **Use the venv:** `./.venv/bin/pytest`, `./.venv/bin/python`. `sffl` is not pip-installed; ad-hoc scripts need `PYTHONPATH=src`.
- **This repo is PUBLIC.** `data/weekly/` and `data/extracts/` are gitignored real data. Read them; never commit them, and never paste their rows into a tracked file. Aggregate numbers in a report are fine.
- **Do NOT modify `src/sffl/scoring.py`.** It is validated against ~250 real observations. The curves change; the scoring does not.
- **Do NOT modify `src/sffl/market.py`.**
- **Never use pre-2025 data.** The league's rules changed between 2024 and 2025.
- **`calibration/2025.yaml` does not change** unless a candidate wins under the gate. If it does, that is a deliberate reviewed commit, never a silent regeneration.
- Full suite is **625 passing**. Report the count after each task.

## The pre-registered hypothesis — fixed before any number is computed

**Sparse stats improve with more data; dense stats degrade.**

The shipped curves come from 48 players, but that pools very differently per stat:
`rush_yds` has 36 players, while `pass_yds`, `pass_cmp`, `def_pa` and `def_ya` have **four
each**. Adding the held-back data was tried once and judged "worse on 6 of 7 stats" — but
that verdict was aggregate, and interpolating 40 anchors is a different regime from
interpolating 3.

Held-back data available: `TQB.full.csv` 544 rows / **32 players**, `DST.full.csv` 374 / **22**,
`WR.full.csv` 491 / **29**, `TE.full.csv` 204 / **12**. So `pass_*` can reach 36 players and
`def_*` 26.

**Report every stat separately. Never collapse the result to a single count** — that is
precisely what hid the split last time.

---

## Task 1: The measurement harness, and proof that it is trustworthy

**Files:**
- Create: `src/sffl/calibrate_eval.py`
- Create: `tests/test_calibrate_eval.py`

**Interfaces:**
- Produces:
  - `calibrate_eval.player_folds(lines, k=5)` → `list` of `k` sets of player_ids, deterministic, disjoint.
  - `calibrate_eval.realized(lg, weeks, stat)` → `float` — a player's true `mean(band(weekly))` for one stat, the ground truth.
  - `calibrate_eval.cross_validate(lg, lines, builder, k=5, min_weeks=4)` → `dict` `{stat: {"mae": float, "n": int}}`, where `builder(lg, lines)` is any of the three curve builders.

**THE VALIDITY GATE, and it comes first.** Before any comparison is trustworthy, the
harness must reproduce what already ships. Build curves from the existing build set
(`data/weekly/2025/{DST,K,RB,TQB,WR}.csv`) with the EXISTING `calibrate.build_curves` and
assert the result equals `calibration/2025.yaml` exactly. If it does not, the harness or
the understanding is wrong and **every downstream number is meaningless**. Stop and report
rather than proceeding.

**THE LEAK THAT WOULD INVALIDATE EVERYTHING:** a player must never appear in both the fit
and the holdout set. His own season would then be interpolated into his own prediction and
every candidate would look excellent. Split by PLAYER, never by row.

- [ ] **Step 1: Write the failing test**

Create `tests/test_calibrate_eval.py`:

```python
import pytest

from sffl.calibrate_eval import cross_validate, player_folds, realized
from sffl.league import load_league
from sffl.weekly import load_weekly


def _line(pid, pos, week, **stats):
    from sffl.weekly import WeeklyLine
    return WeeklyLine(player_id=pid, name=pid, pos=pos, week=week,
                      season=2025, stats=dict(stats))


def test_folds_are_disjoint_and_cover_every_player():
    lines = [_line("p%d" % i, "RB", w, rush_yds=10.0 * i)
             for i in range(20) for w in range(1, 6)]
    folds = player_folds(lines, k=5)
    assert len(folds) == 5
    allp = set()
    for f in folds:
        assert not (allp & f), "a player appears in two folds - that is the leak"
        allp |= f
    assert allp == {"p%d" % i for i in range(20)}


def test_folds_are_deterministic():
    lines = [_line("p%d" % i, "RB", w) for i in range(20) for w in range(1, 6)]
    assert player_folds(lines, k=5) == player_folds(lines, k=5)


def test_realized_is_the_mean_of_the_banded_weeks_not_the_band_of_the_mean():
    # The whole reason curves exist: E[band(X)] != band(E[X]).
    lg = load_league("leagues/sffl/2026.yaml")
    weeks = [_line("p", "RB", 1, rush_yds=0.0), _line("p", "RB", 2, rush_yds=100.0)]
    from sffl.scoring import band_points
    got = realized(lg, weeks, "rush_yds")
    mean_of_banded = (band_points(lg.bands["rush_yds"], 0.0)
                      + band_points(lg.bands["rush_yds"], 100.0)) / 2.0
    banded_mean = band_points(lg.bands["rush_yds"], 50.0)
    assert got == mean_of_banded
    assert got != banded_mean


def test_cross_validate_never_scores_a_player_against_a_curve_built_from_him():
    # The leak this harness exists to prevent. A builder that memorises its
    # input would score perfectly if the split were by row.
    lg = load_league("leagues/sffl/2026.yaml")
    seen = {}

    def spy_builder(lg_, lines_):
        seen["fit_players"] = {l.player_id for l in lines_}
        from sffl.calibrate import build_curves
        return build_curves(lg_, lines_)

    lines = [_line("p%d" % i, "RB", w, rush_yds=5.0 * i)
             for i in range(20) for w in range(1, 6)]
    cross_validate(lg, lines, spy_builder, k=5)
    # The last fold's fit set must exclude that fold's holdout players.
    assert len(seen["fit_players"]) < 20


def test_the_harness_reproduces_the_shipped_curves():
    # THE VALIDITY GATE. If rebuilding the build set does not reproduce what
    # ships, the harness misunderstands the pipeline and every comparison
    # below it is meaningless.
    import os
    if not os.path.isdir("data/weekly/2025"):
        pytest.skip("weekly data not present (gitignored)")
    from sffl.calibrate import build_curves, load_curves
    lg = load_league("leagues/sffl/2026.yaml")
    lines = []
    for pos in ("DST", "K", "RB", "TQB", "WR"):
        p = "data/weekly/2025/%s.csv" % pos
        if os.path.exists(p):
            lines.extend(load_weekly(p))
    built = build_curves(lg, lines)
    shipped = load_curves("calibration/2025.yaml")
    for stat in shipped:
        assert len(built[stat]) == len(shipped[stat]), stat
        for (m1, e1), (m2, e2) in zip(built[stat], shipped[stat]):
            assert abs(m1 - m2) < 1e-9 and abs(e1 - e2) < 1e-9, stat
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_calibrate_eval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sffl.calibrate_eval'`

- [ ] **Step 3: Check `sffl.weekly`'s actual API first**

`WeeklyLine`'s real field names and `load_weekly`'s signature are the authority — read
`src/sffl/weekly.py` and adapt the test helper above to match. Do NOT invent fields. If the
shape differs from the helper, fix the helper, not the module.

- [ ] **Step 4: Write the implementation**

Create `src/sffl/calibrate_eval.py`:

```python
"""Judge a calibration curve honestly: cross-validated, by player, per stat.

WHY THIS EXISTS. The shipped curves interpolate straight lines through one
point per player. Adding more players was tried once and judged "worse on 6 of
7 stats" - but that verdict was AGGREGATE, and the aggregate is dominated by the
stats that already had 36 players. `def_pa` has four. Those are different
regimes and a count of stats cannot tell them apart, so this module reports
every stat separately and never collapses them.

THE LEAK IT EXISTS TO PREVENT. A player's weeks must never be in both the fit
and the holdout set: interpolation would then draw its line straight through
his own point and predict him almost exactly. Splitting is by PLAYER, always.

WHY K-FOLD RATHER THAN ONE HOLDOUT. With 26 defenses, a single 20% holdout
judges on five players and the answer moves with the split. K-fold uses every
player as holdout exactly once, which at these sample sizes is the difference
between a measurement and an anecdote.
"""

from collections import defaultdict

from sffl.scoring import band_points

DEFAULT_K = 5
MIN_WEEKS = 4


def player_folds(lines, k=DEFAULT_K):
    """Deterministic disjoint player-id folds. Sorted, then dealt round-robin.

    Deterministic on purpose: a random split makes a rerun disagree with itself,
    and this measurement decides whether a curve ships.
    """
    players = sorted({ln.player_id for ln in lines})
    folds = [set() for _ in range(k)]
    for i, pid in enumerate(players):
        folds[i % k].add(pid)
    return folds


def realized(lg, weeks, stat):
    """A player's TRUE expected banded value: mean(band(week)), not band(mean).

    This is the quantity the curve is trying to predict, and the reason the
    curves exist at all - E[band(X)] != band(E[X]).
    """
    table = lg.bands[stat]
    vals = [w.stats.get(stat, 0.0) for w in weeks]
    return sum(band_points(table, v) for v in vals) / len(vals)


def cross_validate(lg, lines, builder, k=DEFAULT_K, min_weeks=MIN_WEEKS):
    """Per-stat MAE of `builder`'s curves, cross-validated by player.

    `builder(lg, lines)` returns {stat: [(mean, expected), ...]}.
    Returns {stat: {"mae": float, "n": int}} - n is how many held-out player
    predictions the MAE is over, which is as important as the MAE itself when
    a stat has four players.
    """
    from sffl.calibrate import STAT_POSITIONS, expected_points

    by_player = defaultdict(list)
    for ln in lines:
        by_player[ln.player_id].append(ln)

    errs = defaultdict(list)
    for fold in player_folds(lines, k):
        fit_lines = [ln for ln in lines if ln.player_id not in fold]
        curves = builder(lg, fit_lines)
        for pid in fold:
            weeks = by_player[pid]
            if len(weeks) < min_weeks:
                continue
            pos = weeks[0].pos
            for stat in lg.bands:
                if pos not in STAT_POSITIONS[stat]:
                    continue
                curve = curves.get(stat) or []
                if not curve:
                    continue
                vals = [w.stats.get(stat, 0.0) for w in weeks]
                mean = sum(vals) / len(vals)
                errs[stat].append(
                    abs(expected_points(curve, mean) - realized(lg, weeks, stat)))

    return dict((s, {"mae": sum(e) / len(e), "n": len(e)})
                for s, e in errs.items() if e)
```

- [ ] **Step 5: Run the tests**

Run: `./.venv/bin/pytest tests/test_calibrate_eval.py -v`
Expected: all pass. **If `test_the_harness_reproduces_the_shipped_curves` fails, STOP and report** — that is the validity gate and nothing downstream means anything without it.

- [ ] **Step 6: Commit**

```bash
git add src/sffl/calibrate_eval.py tests/test_calibrate_eval.py
git commit -m "feat(calibrate): a cross-validated, per-stat, leak-proof curve harness

Splits by PLAYER, never by row - a player's weeks in both the fit and the
holdout set would let interpolation draw its line through his own point
and predict him almost exactly.

K-fold rather than one holdout because with 26 defenses a single 20% split
judges on five players and the answer moves with the split.

Reports every stat separately and never collapses them: the previous
verdict on this question was an aggregate dominated by the stats that
already had 36 players, while def_pa has four."
```

---

## Task 2: Candidate A — isotonic regression

**Files:**
- Modify: `src/sffl/calibrate.py`
- Create: `tests/test_calibrate_isotonic.py`

**Interfaces:**
- Produces: `calibrate.build_curves_isotonic(lg, lines, min_weeks=MIN_WEEKS)` → same shape as `build_curves`.

**The idea:** identical input to today (one point per player), but instead of interpolating
through every point, fit a monotone step function by Pooled Adjacent Violators.
Monotonicity is the regulariser — the curve cannot chase a non-monotone wiggle, which is
exactly the noise the held-back README describes. `band()` is non-decreasing, so the true
relationship is non-decreasing; a fitted curve that respects that is strictly better
informed than one that does not.

- [ ] **Step 1: Write the failing test**

```python
from sffl.calibrate import _pava, build_curves_isotonic


def test_pava_leaves_an_already_monotone_sequence_alone():
    assert _pava([(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]) == [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]


def test_pava_pools_a_violation_into_its_average():
    got = _pava([(1.0, 3.0), (2.0, 1.0)])
    assert [y for _x, y in got] == [2.0, 2.0]


def test_pava_output_is_never_decreasing():
    import random
    rnd = random.Random(0)
    pts = sorted((float(i), rnd.uniform(0, 10)) for i in range(50))
    ys = [y for _x, y in _pava(pts)]
    assert all(ys[i] <= ys[i + 1] + 1e-12 for i in range(len(ys) - 1))


def test_isotonic_curves_are_monotone_for_every_stat():
    import os
    import pytest
    if not os.path.isdir("data/weekly/2025"):
        pytest.skip("weekly data not present (gitignored)")
    from sffl.league import load_league
    from sffl.weekly import load_weekly
    lg = load_league("leagues/sffl/2026.yaml")
    lines = []
    for pos in ("DST", "K", "RB", "TQB", "WR"):
        p = "data/weekly/2025/%s.csv" % pos
        if os.path.exists(p):
            lines.extend(load_weekly(p))
    for stat, curve in build_curves_isotonic(lg, lines).items():
        ys = [y for _x, y in curve]
        assert all(ys[i] <= ys[i + 1] + 1e-9 for i in range(len(ys) - 1)), stat
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/pytest tests/test_calibrate_isotonic.py -v`
Expected: FAIL — `cannot import name '_pava'`

- [ ] **Step 3: Implement**

Add to `src/sffl/calibrate.py`:

```python
def _pava(points):
    """Pooled Adjacent Violators: the least-squares monotone fit to `points`.

    `points` is [(x, y), ...] sorted by x. Returns the same x's with a
    non-decreasing y. Where the input violates monotonicity, the violating run
    is replaced by its average - which is exactly the regularisation this is
    for: a dip caused by one player's noisy season gets pooled with its
    neighbours instead of being drawn through.

    Pure stdlib; numpy and scipy are not installed and must not be added.
    """
    blocks = []  # (sum_y, weight, last_x_index)
    for i, (_x, y) in enumerate(points):
        blocks.append([float(y), 1.0, i])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s2, w2, _ = blocks.pop()
            blocks[-1][0] += s2
            blocks[-1][1] += w2
            blocks[-1][2] = i
    out = []
    idx = 0
    for total, weight, _last in blocks:
        avg = total / weight
        for _ in range(int(weight)):
            out.append((points[idx][0], avg))
            idx += 1
    return out


def build_curves_isotonic(lg, lines, min_weeks=MIN_WEEKS):
    """Same input as build_curves, but fitted monotone rather than interpolated.

    WHY. build_curves draws straight lines through every player's point, so each
    additional player gives the curve one more noisy season to chase - which is
    why adding the held-back data made it worse. Monotonicity is a regulariser
    that costs nothing in truth: band() is non-decreasing, so E[band(X)] is
    non-decreasing in E[X], and a curve that respects that cannot follow a dip
    that only noise produced.
    """
    raw = build_curves(lg, lines, min_weeks)
    return dict((stat, _pava(pairs) if pairs else []) for stat, pairs in raw.items())
```

- [ ] **Step 4: Run the tests, then the suite**

Run: `./.venv/bin/pytest tests/test_calibrate_isotonic.py -v` then `./.venv/bin/pytest -q`

- [ ] **Step 5: Commit**

```bash
git add src/sffl/calibrate.py tests/test_calibrate_isotonic.py
git commit -m "feat(calibrate): isotonic curve builder, monotonicity as the regulariser

Same one-point-per-player input as today, but fitted monotone by pooled
adjacent violators rather than interpolated through every point. band() is
non-decreasing, so E[band(X)] is non-decreasing in E[X] - a curve that
respects that cannot follow a dip only one noisy season produced.

Whether it actually beats interpolation is measured, not assumed."
```

---

## Task 3: Candidate B — pooled weekly integration

**Files:**
- Modify: `src/sffl/calibrate.py`
- Create: `tests/test_calibrate_pooled.py`

**Interfaces:**
- Produces: `calibrate.build_curves_pooled(lg, lines, min_weeks=MIN_WEEKS, grid=None)` → same shape.

**The idea, and why it is the one that should benefit from more data.** We are not
estimating an arbitrary function. `band()` is known exactly. The only unknown is how a
player's weekly value scatters around his own mean. So:

1. For every player and every week, compute the multiplicative residual `r = value / mean`
   (skip players whose mean is 0 — no scatter to learn from).
2. **Pool those residuals across all players** into one empirical distribution. That
   distribution is estimated from every weekly row, so more rows sharpen it rather than
   adding anchors to chase.
3. For a grid of means `m`, compute `E[band(X) | m] ≈ mean over pooled residuals of
   band(m · r)`.

The result is smooth, non-decreasing (because `band()` is and `r > 0`), and uses 1,428 rows
to estimate a shape rather than 48 points to define a function.

**A real limitation to handle honestly:** a multiplicative residual assumes scatter scales
with the mean. That is reasonable for yardage and poor near zero. Compute residuals only
from players with a mean above a small floor, and say in the report what fraction of
players that excluded. Do not silently drop them.

- [ ] **Step 1: Write the failing test**

```python
from sffl.calibrate import _pooled_residuals, build_curves_pooled


def _line(pid, pos, week, **stats):
    from sffl.weekly import WeeklyLine
    return WeeklyLine(player_id=pid, name=pid, pos=pos, week=week,
                      season=2025, stats=dict(stats))


def test_residuals_are_centred_on_one_for_a_stable_player():
    lines = [_line("p", "RB", w, rush_yds=100.0) for w in range(1, 6)]
    rs = _pooled_residuals(lines, "rush_yds")
    assert all(abs(r - 1.0) < 1e-9 for r in rs)


def test_residuals_pool_across_players_regardless_of_scale():
    # A player averaging 20 and one averaging 200, each varying +/-50%,
    # must contribute the SAME residuals - that is what makes pooling valid.
    a = [_line("a", "RB", 1, rush_yds=10.0), _line("a", "RB", 2, rush_yds=30.0)]
    b = [_line("b", "RB", 1, rush_yds=100.0), _line("b", "RB", 2, rush_yds=300.0)]
    assert sorted(_pooled_residuals(a, "rush_yds")) == sorted(_pooled_residuals(b, "rush_yds"))


def test_pooled_curve_is_non_decreasing():
    lines = []
    for i in range(1, 11):
        for w in range(1, 6):
            lines.append(_line("p%d" % i, "RB", w, rush_yds=10.0 * i * (0.5 + 0.2 * w)))
    from sffl.league import load_league
    lg = load_league("leagues/sffl/2026.yaml")
    curve = build_curves_pooled(lg, lines)["rush_yds"]
    ys = [y for _x, y in curve]
    assert all(ys[i] <= ys[i + 1] + 1e-9 for i in range(len(ys) - 1))


def test_a_zero_mean_player_contributes_no_residuals():
    lines = [_line("z", "RB", w, rush_yds=0.0) for w in range(1, 6)]
    assert _pooled_residuals(lines, "rush_yds") == []
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — `cannot import name '_pooled_residuals'`

- [ ] **Step 3: Implement**

Write `_pooled_residuals(lines, stat, min_mean=1e-6)` and `build_curves_pooled` following
the description above. Choose the grid from the observed range of player means for that
stat — do not hardcode a range, and record the grid density you chose and why in your
report. Keep the docstring's explanation of why pooling residuals is what lets more data
help.

- [ ] **Step 4: Run tests and the suite**

- [ ] **Step 5: Commit**

---

## Task 4: Run the experiment

**Files:**
- Create: `poc/compare_calibration_methods.py`

**This task produces a MEASUREMENT, not a change.** Nothing in `calibration/2025.yaml`
moves here.

- [ ] **Step 1: Write the comparison script**

`poc/compare_calibration_methods.py` must, for each of the three builders
(`build_curves`, `build_curves_isotonic`, `build_curves_pooled`) and each of two datasets
(build-set-only, and build-set-plus-held-back):

- run `cross_validate` and print **a per-stat table**: stat, n held-out predictions, MAE
  for each builder, and which wins;
- print the player count per stat in each dataset, so a reader can see which regime each
  stat is in;
- never print a single aggregate "X of 7" verdict.

- [ ] **Step 2: Run it and record the numbers**

Run it and put the full table in your report. **Do not adopt anything yet.**

- [ ] **Step 3: Measure the price fit for any candidate that wins a stat**

For each candidate that beats the baseline on held-out MAE for at least one stat, build a
full curve set using that method for its winning stats and interpolation elsewhere, write
it to a SCRATCH path (not `calibration/2025.yaml`), and run the market fit with it:

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli fit-market \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2026/rankings-2026-08-23.csv" \
  --year 2026 --curves /tmp/candidate.yaml \
  --prices data/league/auction-rosters-2026.csv \
  --tqb-starters identity/tqb-2026-starters.yaml \
  --out /tmp/candidate-market.yaml
```

Compare `top10_mae`, `top10_bias` and `top10_cost` against the shipped
`market/2026.yaml` diagnostics (`mae 4.3392`, `top10_mae 10.0638`, `top10_bias 5.1042`).

- [ ] **Step 4: Write the verdict**

State, per stat, which method wins on held-out MAE and what it does to the price fit.
**Recommend adoption only where a candidate wins BOTH.** A tie is a loss.

If nothing wins, say so plainly — that is a legitimate and useful result, and it is what
the next task records.

- [ ] **Step 5: Commit the script only**

```bash
git add poc/compare_calibration_methods.py
git commit -m "poc: compare calibration methods, per stat, cross-validated

Produces a measurement, not a change. Reports every stat separately
because the previous verdict on this question was an aggregate dominated
by the stats that already had enough data."
```

---

## Task 5: Adopt what won, record what did not

**Files:**
- Modify: `calibration/2025.yaml` **only if a candidate won**
- Modify: `poc/build_calibration.py` (record the per-stat method)
- Modify: `NEXT.md`
- Modify: `data/weekly/2025/_held_back/README.md`

- [ ] **Step 1: If a candidate won its stat, regenerate the curves**

Update `poc/build_calibration.py` so each stat is built by whichever method won it, and
regenerate `calibration/2025.yaml`. **The file must record which method produced each
stat's curve** — a curve whose provenance is unknown is the failure this project keeps
finding. Add it as a comment block or a sibling metadata key; say which you chose.

- [ ] **Step 2: Verify the board**

Re-run the market fit with the new curves and report the diagnostics against the shipped
ones. If the price fit worsened for a stat you adopted, that stat fails the gate — revert
it and say so.

- [ ] **Step 3: Record the result either way**

Update `NEXT.md` and the held-back `README.md` with the per-stat table and the verdict.
**If nothing won, this is the entire task** — and it is worth doing properly, because the
existing README is exactly what stopped this session from blindly repeating a dead end.

- [ ] **Step 4: Commit**

---

## Self-Review

**1. Spec coverage.** Harness + leak test + validity gate (Task 1); isotonic (2); pooled
integration (3); per-stat cross-validated comparison and price fit (4); per-stat adoption
with recorded provenance, or a recorded null result (5).

**2. Placeholder scan.** Task 3 Step 3 deliberately does not spell out `build_curves_pooled`'s
body — the grid choice depends on the observed range and the implementer must justify it.
Task 4 has no expected numbers by design: pre-registering the hypothesis while leaving the
numbers to be measured is the point.

**3. Type consistency.** All three builders share `(lg, lines, min_weeks) -> {stat: [(mean,
expected)]}`, which is what `cross_validate` and `expected_points` already consume.

**4. Known risk.** Everything depends on `data/weekly/2025/` being present; it is gitignored.
Task 1's validity-gate test skips if absent, and the experiment cannot run without it.

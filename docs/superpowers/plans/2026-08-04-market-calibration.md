# Market Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a second number on the board — what a player will actually cost in this league — beside what the model says he is worth, so the gap between them is visible at the table.

**Architecture:** The value model distributes the league's surplus in proportion to VORP, which assumes points are fungible currency. A real auction is budget-constrained, so the top compresses and the $1 tail is bid up. Measured against 154 real 2025 prices the distortion is monotonic, which means it can be fitted and removed. A log-log least-squares fit gives a power curve `price = a * dollars^b` with `b < 1`; renormalising the result so the board still totals the league's capital yields `_est_price` alongside the existing `_dollars`. `_dollars` keeps its current meaning and is not touched.

**Tech Stack:** Python 3.9, pytest, PyYAML. **No new dependencies** — the fit is a closed-form two-variable OLS; `numpy` and `scipy` are deliberately not used and are not installed.

## Global Constraints

- **Python 3.9.6 only.** No `match` statements, no PEP 604 (`int | None`) annotations. Use `typing.Optional`/`List`/`Dict`/`Tuple`.
- **Use the project venv** at `.venv/`. Invoke as `./.venv/bin/pytest` and `./.venv/bin/python`. `sffl` is not pip-installed; ad-hoc commands need `PYTHONPATH=src`.
- **`data/extracts/` and `data/weekly/` are gitignored** — licensed vendor and CBS data, and this repo is PUBLIC. Never commit a file from either, and never paste extract contents or real-run player names into a committed file. `data/league/` IS tracked. Tests must not depend on gitignored data.
- **Wrong numbers must never be produced silently.** Prefer raising over guessing.
- **Never mix seasons.** The fit is trained on 2025 prices and applied to 2026 projections. That is the best evidence available, but it assumes the room bids similarly year over year — say so wherever the number surfaces.
- **WR and TE are ONE position.** Pool names are exactly `"TQB"`, `"FLEX"`, `"K"`, `"DST"`.
- **`src/sffl/scoring.py` is validated against ~250 real CBS observations and must NOT be modified.**
- **K and DST price flat at $1** via `lg.flat_priced_pools` and contribute no VORP. Their expected price is also $1 — do not let the fit move them.

## Observed ground truth (do not re-derive)

Bias of `_dollars` against the 154 matched 2025 prices, by model dollar band. Highest price ever paid in this league is **$43**; the model's top three are $54.2, $53.7, $47.0.

| model band | n | model avg | actually paid | bias |
|---|---|---|---|---|
| $30+ | 13 | $40.1 | $26.9 | **+$13.2** |
| $20-30 | 10 | $22.9 | $15.5 | +$7.4 |
| $10-20 | 19 | $14.7 | $14.3 | +$0.5 |
| $5-10 | 7 | $8.8 | $13.0 | -$4.2 |
| $2-5 | 13 | $3.5 | $7.8 | -$4.3 |
| $1-2 | 92 | $1.0 | $3.6 | -$2.6 |

The board already totals exactly `total_capital()` = $1,320. The total is right; the distribution is too steep.

## File Structure

| File | Responsibility |
|---|---|
| `src/sffl/market.py` | Fit the price curve from observed prices; assign `_est_price` |
| `src/sffl/cli.py` (modify) | Compute the curve when `--prices` is given; print EST$ and the bias table; add `est_price` to the CSV |

---

### Task 1: Fit the market price curve

**Files:**
- Create: `src/sffl/market.py`
- Test: `tests/test_market.py`

**Interfaces:**
- Consumes: `lg.flat_priced_pools`, `lg.total_capital()`, `lg.total_spots()`; `sffl.value._pool_of`.
- Produces:
  - `fit_price_curve(pairs) -> Tuple[float, float]` — `pairs` is a list of `(model_dollars, observed_price)`. Returns `(a, b)` for `price = a * dollars ** b`.
  - `expected_price(curve, dollars) -> float` — the raw curve value, floored at 1.0.
  - `assign_expected_prices(lg, pool, curve) -> float` — writes `stats["_est_price"]` on every record and returns the renormalisation factor.

**The maths, in full.** Fit in log space, where the power law is linear. With `x_i = ln(model_i)` and `y_i = ln(actual_i)`:

```
b     = (n*Sxy - Sx*Sy) / (n*Sxx - Sx*Sx)
ln(a) = (Sy - b*Sx) / n
```

`model_dollars` is always >= 1 and observed prices are always >= 1, so no log of zero or a negative arises. `b < 1` is the compression we expect; `b > 0` is required for monotonicity — a curve where a better player costs less is nonsense and must raise.

**Renormalisation.** The raw curve does not respect the league's capital. Every one of `total_spots()` roster spots costs at least $1, so scale only the surplus above $1: `est = 1 + k * (raw - 1)`, with `k` chosen so the top `total_spots()` estimates sum to `total_capital()`. Because the curve is monotone, the top `total_spots()` by estimate are the same players as the top `total_spots()` by `_dollars`, so the selection is stable.

- [ ] **Step 1: Write the failing test**

Create `tests/test_market.py`:

```python
import pytest

from sffl.league import load_league
from sffl.market import assign_expected_prices, expected_price, fit_price_curve
from sffl.schema import PlayerProjection

LG = load_league("leagues/sffl/2026.yaml")


def player(name, pos, dollars):
    return PlayerProjection(name=name, team="XXX", pos=pos, source="t",
                            source_year=2026, games=17,
                            stats={"_dollars": float(dollars)}, raw_name=name)


def test_fit_recovers_a_known_power_curve():
    # price = 2 * dollars ** 0.5, sampled exactly - the fit must recover it
    pairs = [(d, 2.0 * d ** 0.5) for d in (1.0, 4.0, 9.0, 16.0, 25.0, 36.0)]
    a, b = fit_price_curve(pairs)
    assert a == pytest.approx(2.0, rel=1e-6)
    assert b == pytest.approx(0.5, rel=1e-6)


def test_fit_finds_compression_in_biased_data():
    # model overpays the top and underpays the bottom, like the real board
    pairs = [(1.0, 3.6), (3.5, 7.8), (8.8, 13.0), (14.7, 14.3),
             (22.9, 15.5), (40.1, 26.9)]
    a, b = fit_price_curve(pairs)
    assert 0.0 < b < 1.0, "expected compression, got exponent %r" % b


def test_expected_price_is_monotone_and_floored_at_one_dollar():
    curve = fit_price_curve([(1.0, 3.6), (10.0, 12.0), (40.0, 27.0)])
    assert expected_price(curve, 1.0) >= 1.0
    assert expected_price(curve, 5.0) < expected_price(curve, 20.0)


def test_too_few_observations_raises():
    with pytest.raises(ValueError) as e:
        fit_price_curve([(1.0, 2.0), (3.0, 4.0)])
    assert "observation" in str(e.value).lower()


def test_a_curve_that_would_price_better_players_lower_raises():
    # deliberately inverted data - a real market never does this
    pairs = [(1.0, 40.0), (10.0, 20.0), (20.0, 10.0), (40.0, 2.0),
             (5.0, 30.0), (30.0, 5.0)]
    with pytest.raises(ValueError) as e:
        fit_price_curve(pairs)
    assert "monoton" in str(e.value).lower()


def test_identical_model_values_cannot_be_fitted():
    with pytest.raises(ValueError):
        fit_price_curve([(5.0, 2.0)] * 8)


def build_board():
    """156 rostered spots' worth of players, plus filler below replacement."""
    pool = [player("flex%d" % i, "RB" if i % 2 else "WR", 50.0 - 0.3 * i)
            for i in range(120)]
    pool += [player("tqb%d" % i, "TQB", 40.0 - 1.0 * i) for i in range(12)]
    pool += [player("k%d" % i, "K", 1.0) for i in range(12)]
    pool += [player("d%d" % i, "DST", 1.0) for i in range(12)]
    return pool


def test_expected_prices_exhaust_the_league_capital():
    pool = build_board()
    curve = fit_price_curve([(1.0, 3.6), (10.0, 12.0), (25.0, 17.0),
                             (40.0, 27.0), (5.0, 9.0), (18.0, 15.0)])
    assign_expected_prices(LG, pool, curve)
    spent = sum(sorted((p.stats["_est_price"] for p in pool),
                       reverse=True)[:LG.total_spots()])
    assert spent == pytest.approx(LG.total_capital(), abs=1.0)


def test_flat_priced_pools_keep_their_flat_price():
    pool = build_board()
    curve = fit_price_curve([(1.0, 3.6), (10.0, 12.0), (25.0, 17.0),
                             (40.0, 27.0), (5.0, 9.0), (18.0, 15.0)])
    assign_expected_prices(LG, pool, curve)
    for p in pool:
        if p.pos in ("K", "DST"):
            assert p.stats["_est_price"] == pytest.approx(1.0), p.name


def test_every_estimate_is_at_least_a_dollar():
    pool = build_board()
    curve = fit_price_curve([(1.0, 3.6), (10.0, 12.0), (25.0, 17.0),
                             (40.0, 27.0), (5.0, 9.0), (18.0, 15.0)])
    assign_expected_prices(LG, pool, curve)
    assert all(p.stats["_est_price"] >= 1.0 for p in pool)


def test_estimates_preserve_the_models_ordering():
    pool = build_board()
    curve = fit_price_curve([(1.0, 3.6), (10.0, 12.0), (25.0, 17.0),
                             (40.0, 27.0), (5.0, 9.0), (18.0, 15.0)])
    assign_expected_prices(LG, pool, curve)
    flex = [p for p in pool if p.pos in ("RB", "WR", "TE")]
    flex.sort(key=lambda p: -p.stats["_dollars"])
    ests = [p.stats["_est_price"] for p in flex]
    assert ests == sorted(ests, reverse=True)


def test_missing_dollars_raises_rather_than_defaulting():
    pool = build_board()
    del pool[0].stats["_dollars"]
    curve = fit_price_curve([(1.0, 3.6), (10.0, 12.0), (25.0, 17.0),
                             (40.0, 27.0), (5.0, 9.0), (18.0, 15.0)])
    with pytest.raises(ValueError) as e:
        assign_expected_prices(LG, pool, curve)
    assert "_dollars" in str(e.value)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_market.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sffl.market'`

- [ ] **Step 3: Implement the module**

Create `src/sffl/market.py`:

```python
"""Fit what this league actually pays, given what the model says a player is worth.

`value.assign_dollars` distributes the surplus in proportion to VORP, which
assumes points are fungible currency. A real auction is budget constrained -
nobody spends $54 on one player and still fills thirteen roster spots - and
every owner must fill a bench, so the top compresses and the $1 tail is bid up.

Measured against 154 real 2025 prices the distortion is monotonic: the model
overpays the $30+ band by $13.2 and underpays the $2-5 band by $4.3, while the
board total stays exactly right. Monotonic means fittable. A power curve
`price = a * dollars ** b` with b < 1 has precisely that shape, and fitting it
in log space makes it an ordinary least-squares line.

`_dollars` KEEPS its meaning - what a player is worth against replacement.
`_est_price` is what the room will charge. The gap between them is the edge.

FITTED ON 2025 PRICES, APPLIED TO 2026 PROJECTIONS. That is the best evidence
available, but it assumes the room bids next year the way it bid last year.
"""

import math
from typing import Dict, List, Tuple

from sffl.value import _pool_of

MIN_OBSERVATIONS = 8


def fit_price_curve(pairs):
    """Least-squares fit of price = a * dollars**b, in log space.

    `pairs` is [(model_dollars, observed_price), ...]. Both sides are always
    >= 1 on real data, so no log of zero or a negative arises.
    """
    if len(pairs) < MIN_OBSERVATIONS:
        raise ValueError(
            "need at least %d observations to fit a price curve, got %d"
            % (MIN_OBSERVATIONS, len(pairs)))

    xs = [math.log(float(m)) for m, _ in pairs]
    ys = [math.log(float(a)) for _, a in pairs]
    n = float(len(pairs))
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))

    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        raise ValueError(
            "cannot fit a price curve: every observation has the same model "
            "dollar value, so the curve's slope is undefined")

    b = (n * sxy - sx * sy) / denom
    a = math.exp((sy - b * sx) / n)

    if b <= 0.0:
        raise ValueError(
            "fitted exponent %.4f is not monotonic increasing; a better player "
            "would cost less, which no real auction does. Check the observed "
            "prices joined to the right players." % b)
    return (a, b)


def expected_price(curve, dollars):
    """Raw curve value for one model dollar figure, floored at $1."""
    a, b = curve
    return max(1.0, a * (float(dollars) ** b))


def assign_expected_prices(lg, pool, curve):
    """Write stats['_est_price'] on every record. Returns the scale factor.

    The raw curve knows nothing about this league's capital, so only the
    surplus above the $1 every roster spot costs is scaled:

        est = 1 + k * (raw - 1)

    with k chosen so the top `total_spots()` estimates sum to
    `total_capital()`. The curve is monotone, so those are the same players as
    the top `total_spots()` by `_dollars` and the selection is stable.
    """
    missing = [p.name for p in pool if "_dollars" not in p.stats]
    if missing:
        raise ValueError(
            "%d player(s) have no '_dollars'; call value.assign_dollars first "
            "(e.g. %s)" % (len(missing), ", ".join(sorted(missing)[:3])))

    raw = {}  # type: Dict[int, float]
    for p in pool:
        flat = lg.flat_priced_pools.get(_pool_of(p.pos))
        if flat is not None:
            raw[id(p)] = float(flat)
        else:
            raw[id(p)] = expected_price(curve, p.stats["_dollars"])

    top = sorted(raw.values(), reverse=True)[:lg.total_spots()]
    surplus_raw = sum(v - 1.0 for v in top)
    k = (lg.surplus() / surplus_raw) if surplus_raw > 0 else 0.0

    for p in pool:
        flat = lg.flat_priced_pools.get(_pool_of(p.pos))
        if flat is not None:
            p.stats["_est_price"] = float(flat)
        else:
            p.stats["_est_price"] = 1.0 + k * (raw[id(p)] - 1.0)
    return k
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_market.py -v`
Expected: 11 passed

- [ ] **Step 5: Run the whole suite**

Run: `./.venv/bin/pytest -q`
Expected: all pass, 148 before this task.

- [ ] **Step 6: Commit**

```bash
git add src/sffl/market.py tests/test_market.py
git commit -m "feat: fit the league's price curve from observed auction prices"
```

---

### Task 2: Surface EST$ on the board and prove the bias is gone

**Files:**
- Modify: `src/sffl/cli.py`
- Test: `tests/test_cli_value.py` (append)

**Interfaces:**
- Consumes: `fit_price_curve`, `assign_expected_prices` (Task 1); the existing `load_prices`, `score_fit`, `choose_policy`.
- Produces: `_est_price` on every record when `--prices` is supplied; an `EST$` column in the printed top 25 and an `est_price` column in the CSV; a bias-by-band table comparing `_dollars` and `_est_price` against observed prices.

**Behaviour.** `--prices` is already required for `--policy fit`. When it is supplied under ANY policy, build the pairs from players whose price is known, fit the curve, and assign `_est_price`. Without `--prices` there is nothing to fit against, so `_est_price` is not written and the column shows blank — never `0.0`, and never a copy of `_dollars`, either of which would read as a measurement.

**The bias table is the point of this task.** It is how we know the calibration worked rather than merely ran.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_value.py`:

```python
PRICES = "tests/fixtures/prices_sample.csv"


def test_est_price_column_appears_when_prices_are_supplied(tmp_path):
    path = str(tmp_path / "board.csv")
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "starter", "--prices", PRICES, "--out", path])
    assert rc == 0
    with open(path) as fh:
        header = fh.readline()
    assert "est_price" in header


def test_est_price_is_blank_without_prices(tmp_path):
    path = str(tmp_path / "board.csv")
    rc = main(["value", "--source", DS, "--file", FIXTURE, "--year", "2026",
               "--policy", "starter", "--out", path])
    assert rc == 0
    with open(path) as fh:
        lines = fh.read().splitlines()
    header = lines[0].split(",")
    idx = header.index("est_price")
    # every data row leaves it empty rather than reporting a fabricated 0 or a
    # copy of dollars
    assert all(row.split(",")[idx] == "" for row in lines[1:])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_cli_value.py -v`
Expected: FAIL — `est_price` is not in the header.

- [ ] **Step 3: Wire it into the CLI**

In `src/sffl/cli.py`, import the new module:

```python
from sffl.market import assign_expected_prices, fit_price_curve
```

After `assign_dollars` runs and before the board is printed, fit and assign when prices are available:

```python
    curve = None
    if args.prices:
        priced = [(p.stats["_dollars"], prices[normalize_name(p.name)])
                  for p in pool if normalize_name(p.name) in prices]
        curve = fit_price_curve(priced)
        assign_expected_prices(lg, pool, curve)
        print("  market curve: price = %.3f * value^%.3f  "
              "(fitted on %d observed 2025 prices)\n"
              % (curve[0], curve[1], len(priced)))
```

`prices` must be loaded whenever `--prices` is given, not only under `--policy fit`. Move the `load_prices` call accordingly, and keep `--policy fit`'s existing requirement that `--prices` be present.

Add `EST$` to the printed board line beside `MY$`, and `est_price` to the CSV header and rows — writing `""` when `curve is None`.

Then print the bias table, which is the evidence this task exists to produce:

```python
    if curve is not None:
        print("\nbias against observed prices, by model dollar band:")
        print("  %-10s %4s %9s %9s %9s" % ("band", "n", "MY$ bias", "EST$ bias", "actual"))
        bands = [(30, 1e9, "$30+"), (20, 30, "$20-30"), (10, 20, "$10-20"),
                 (5, 10, "$5-10"), (2, 5, "$2-5"), (0, 2, "$1-2")]
        for lo, hi, label in bands:
            rows = [p for p in pool
                    if normalize_name(p.name) in prices
                    and lo <= p.stats["_dollars"] < hi]
            if not rows:
                continue
            actual = [prices[normalize_name(p.name)] for p in rows]
            mybias = sum(p.stats["_dollars"] for p in rows) / len(rows) \
                - sum(actual) / len(actual)
            estbias = sum(p.stats["_est_price"] for p in rows) / len(rows) \
                - sum(actual) / len(actual)
            print("  %-10s %4d %+9.1f %+9.1f %9.1f"
                  % (label, len(rows), mybias, estbias, sum(actual) / len(actual)))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_cli_value.py -v`
Expected: all pass.

- [ ] **Step 5: Run the whole suite**

Run: `./.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 6: Verify against real data**

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli value \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026 \
  --policy fit --prices data/league/auction-rosters-2025.csv \
  --curves calibration/2025.yaml
```

Record in your report: the fitted `a` and `b`, the full bias table, and the top 25 with both columns. **The EST$ bias column must be materially smaller than the MY$ bias column in the $30+ and $20-30 bands** — that is the whole point. Report the actual numbers; do not tune anything to reach a target. If EST$ is not better, say so plainly and stop.

Also record the top EST$ figure. The highest price this league has ever paid is $43; a calibrated top estimate should land near that, not near $54.

- [ ] **Step 7: Commit**

```bash
git add src/sffl/cli.py tests/test_cli_value.py
git commit -m "feat: show the expected auction price beside the model's value"
```

---

## Self-Review

**Spec coverage.** "MY$ = what he is worth, EST$ = what he will cost, both on the board" → Tasks 1 and 2. Fitting from this league's own capital and prices rather than a vendor's assumed $200 cap → Task 1's renormalisation against `total_capital()`. Making it visible whether the calibration worked → Task 2's bias table.

**Deliberately out of scope.** The renderers are their own plan; they consume `_est_price` exactly as they consume `_dollars`. The TQB fit gap (mae $8.98, structured residuals) is a separate modelling question and is not addressed here — market calibration compresses every pool uniformly and will not fix a position-specific bias.

**Known limitation carried forward.** The curve is fitted on 2025 prices and applied to 2026 projections; it assumes the room bids similarly year over year. It is also a single global curve, so it cannot correct a pool that is biased differently from the rest — TQB in particular. Both are stated in the module docstring.

**Type consistency.** `_est_price` is a float on `PlayerProjection.stats`, alongside `_dollars`, `_vorp`, `_season_points`. `fit_price_curve` returns a plain `(a, b)` tuple; `expected_price` and `assign_expected_prices` both take that tuple as `curve`. Pool names are exactly `"TQB"`, `"FLEX"`, `"K"`, `"DST"` and `_pool_of` is applied before every `flat_priced_pools` lookup.

# Market Model Fit/Apply Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split fitting the market curve from applying it, so a pre-auction run can price a board with last season's model of the room instead of being deadlocked into either refusing or silently fitting across seasons.

**Architecture:** A new `market/<season>.yaml` artifact carries the fitted curve, the chosen replacement policy, the evidence behind both, and the diagnostics. A new `sffl fit-market` writes it (year-matched only, refuses anything cross-season it can detect). `sffl value` and `sffl render` gain `--market` to apply it, announcing which season's model is in use. The season guard moves out of the CLI and into `fit.load_prices`, where it cannot be bypassed.

**Tech Stack:** Python 3.9.6, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-market-model-fit-apply-split.md`

## Global Constraints

- **Python 3.9.6 only.** No `match` statements, no PEP 604 (`int | None`) annotations.
- **Use the venv:** `./.venv/bin/pytest`, `./.venv/bin/python`. `sffl` is not pip-installed, so ad-hoc scripts need `PYTHONPATH=src`.
- **This repo is public.** `data/extracts/` and `data/weekly/` are gitignored. Never commit a file from either. `data/league/` IS tracked and league-owned.
- **Do NOT modify `src/sffl/scoring.py`** — validated against ~250 real CBS weekly observations.
- **Do NOT modify `src/sffl/market.py`'s `fit_price_curve` maths.** Its docstring records why the tempting tail-reweighting was rejected: it was tuned against an artifact-era bias that year-matched measurement says does not exist. This plan changes WHEN the fit runs, never HOW.
- **Never validate current scoring against pre-2025 data.** The league's rules changed between 2024 and 2025.
- **The 2026 board must not move.** Fit → persist → apply must reproduce today's `--prices` path exactly. That is the regression test in Task 5 and it governs every earlier task.
- Full suite is **559 passing** at the start of this plan. Report the count after each task.

---

## The three holes this closes

Referenced by task; each gets a test that fails without its fix.

1. **Mismatched prices with a matched map passes silently.** `--year 2026 --prices auction-rosters-2025.csv --tqb-starters tqb-2026-starters.yaml` runs clean and refits the artifact-era curve (`b=0.531` vs the year-matched truth `0.662`), TQB joins degrading 21 → 15. The prices CSV carries no season metadata, so the TQB map is only a proxy. → Task 2.
2. **A starter map with no `season:` key skips the guard entirely** (`_map_season is None`). → Task 2.
3. **The guard exists only in `cli._value_pool`.** Direct `fit.load_prices` callers get the 2025 map forever, unchecked. → Task 2.

---

## File Structure

| path | responsibility | task |
|---|---|---|
| `src/sffl/market_model.py` | **new.** The persisted artifact: save, load, validate. Pure — no fitting, no CLI. | 1 |
| `tests/test_market_model.py` | **new.** | 1 |
| `src/sffl/fit.py` | **modify.** Season guard moves into `load_prices`; prices CSV season column verified. | 2 |
| `data/league/auction-rosters-2026.csv` | **modify.** Gains a `season` column. | 2 |
| `src/sffl/cli.py` | **modify.** New `fit-market` subcommand. | 3 |
| `src/sffl/cli.py` | **modify.** `--market` on `value` and `render`; refuse `--market` with `--prices`; announce the model in use. | 4 |
| `market/2026.yaml` | **new, generated then committed.** The 2026 model. | 5 |
| `tests/test_market_roundtrip.py` | **new.** The byte-identical regression. | 5 |
| `tests/test_fit.py` | **modify.** Correct the fabricated `top10_bias`. | 6 |
| `src/sffl/render/intel.py` | **modify.** Name the market model and its season on the intel page. | 6 |

---

## Task 1: The market-model artifact

**Files:**
- Create: `src/sffl/market_model.py`
- Create: `tests/test_market_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `market_model.MarketModel` — `namedtuple("MarketModel", "season fitted_on curve policy evidence diagnostics")`, where `curve` is `(a, b)` floats.
  - `market_model.save(path, model, overwrite=False)` → `None`; raises `FileExistsError` unless `overwrite`.
  - `market_model.load(path)` → `MarketModel`; raises `ValueError` naming the file and the missing/invalid field.
  - `market_model.describe(model)` → `str`, the one-line announcement.

**Why the float round-trip is load-bearing:** the 2026 board must not move (Task 5). If `a` or `b` loses precision through YAML, applying the persisted curve produces different dollars than fitting it in-process, and the regression fails for a reason that looks like a logic bug. Python's `repr` round-trips floats exactly; verify it rather than assume.

- [ ] **Step 1: Write the failing test**

Create `tests/test_market_model.py`:

```python
import pytest

from sffl.market_model import MarketModel, describe, load, save

MODEL = MarketModel(
    season=2026,
    fitted_on="2026-08-30",
    curve=(2.0512345678901234, 0.6623456789012345),
    policy="starter",
    evidence={"prices_file": "data/league/auction-rosters-2026.csv",
              "prices_rows": 156, "observations": 130,
              "projections_source": "draftsharks", "projections_year": 2026,
              "tqb_starters": "identity/tqb-2026-starters.yaml"},
    diagnostics={"mae": 6.31, "top10_mae": 5.10, "top10_bias": 5.10})


def test_the_curve_round_trips_to_the_exact_same_floats(tmp_path):
    # Load-bearing: the 2026 board must not move when the fit is persisted
    # instead of computed in-process. A lost digit here shows up later as a
    # board that differs for no visible reason.
    p = tmp_path / "m.yaml"
    save(str(p), MODEL)
    got = load(str(p))
    assert got.curve[0] == MODEL.curve[0]
    assert got.curve[1] == MODEL.curve[1]


def test_every_field_round_trips(tmp_path):
    p = tmp_path / "m.yaml"
    save(str(p), MODEL)
    got = load(str(p))
    assert got.season == 2026
    assert got.policy == "starter"
    assert got.evidence["observations"] == 130
    assert got.diagnostics["top10_bias"] == 5.10


def test_saving_over_an_existing_file_is_refused(tmp_path):
    # The artifact is the evidence a board was priced from. A stray re-run
    # must not quietly replace it.
    p = tmp_path / "m.yaml"
    save(str(p), MODEL)
    with pytest.raises(OSError):
        save(str(p), MODEL)


def test_overwrite_is_possible_when_asked_for_explicitly(tmp_path):
    p = tmp_path / "m.yaml"
    save(str(p), MODEL)
    save(str(p), MODEL, overwrite=True)


def test_a_missing_required_field_raises_naming_it(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("season: 2026\npolicy: starter\n")
    with pytest.raises(ValueError) as exc:
        load(str(p))
    assert "curve" in str(exc.value)
    assert "bad.yaml" in str(exc.value)


def test_a_non_monotonic_curve_is_refused_on_load(tmp_path):
    # b <= 0 means a better player costs less, which no auction does. The
    # fitter refuses it; so must the loader, since a hand-edited artifact
    # bypasses the fitter entirely.
    p = tmp_path / "bad.yaml"
    p.write_text(
        "season: 2026\nfitted_on: '2026-08-30'\npolicy: starter\n"
        "curve: {a: 2.0, b: -0.5}\nevidence: {}\ndiagnostics: {}\n")
    with pytest.raises(ValueError) as exc:
        load(str(p))
    assert "monotonic" in str(exc.value).lower()


def test_an_unknown_policy_is_refused_on_load(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "season: 2026\nfitted_on: '2026-08-30'\npolicy: nonsense\n"
        "curve: {a: 2.0, b: 0.6}\nevidence: {}\ndiagnostics: {}\n")
    with pytest.raises(ValueError):
        load(str(p))


def test_describe_names_the_season_and_the_coefficients():
    line = describe(MODEL)
    assert "2026" in line
    assert "0.662" in line
    assert "130" in line
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_market_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sffl.market_model'`

- [ ] **Step 3: Write the implementation**

Create `src/sffl/market_model.py`:

```python
"""The persisted market model: how this room converts value into dollars.

WHY THIS FILE EXISTS. Fitting and applying are two different operations that
were fused into one command, and only FITTING is season-bound. Fitting asks how
the room behaves and needs year-matched prices, which exist only after an
auction. Applying asks what a player will cost and needs only a curve. Fusing
them meant a pre-auction run had to either refuse (guard trips) or silently fit
across seasons (the artifact-era curve returns, b=0.531 against the year-matched
truth of 0.662, TQB joins 21 -> 15, every number looking plausible).

Separating them makes the guard honest: refuse a cross-season FIT, permit a
cross-season APPLY, and say loudly which model is in use and from when. Last
year's model of this room is not a compromise forced by missing data - it is the
correct thing to want, because the room's behaviour is a property of the twelve
people in it, which persists across seasons far better than any player's value.

WHY `evidence` AND `diagnostics` ARE STORED RATHER THAN RE-DERIVED. The failure
this whole split exists to prevent was invisible precisely because nothing
recorded what had been fitted against what. An artifact that cannot answer
"which prices, which projections, how many observations" would reproduce the
original problem in a new place. They are a record of one fitting run, never
recomputed on load, and never used in any calculation.
"""

import os
from collections import namedtuple

import yaml

MarketModel = namedtuple(
    "MarketModel", "season fitted_on curve policy evidence diagnostics")

# Mirrors fit.POLICIES. Duplicated deliberately rather than imported: this
# module must stay free of the fitting path so a pure APPLY never drags in the
# machinery that needs prices.
_KNOWN_POLICIES = ("starter", "draftable")

_REQUIRED = ("season", "fitted_on", "curve", "policy")


def describe(model):
    """One line naming the model in use. Printed on every apply."""
    ev = model.evidence or {}
    return ("using the %d market model (a=%.4f, b=%.4f, n=%s, fitted %s, "
            "policy=%s)"
            % (model.season, model.curve[0], model.curve[1],
               ev.get("observations", "?"), model.fitted_on, model.policy))


def save(path, model, overwrite=False):
    """Write the model. Refuses to clobber an existing file unless told to.

    The artifact is the evidence a board was priced from; a stray re-run must
    not quietly replace it, because the board and its justification would then
    disagree with nothing to show for it.
    """
    if os.path.exists(path) and not overwrite:
        raise OSError(
            "%s already exists; refusing to overwrite the market model a board "
            "may have been priced from. Pass overwrite=True (CLI: --force) if "
            "you really mean to replace it." % path)
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    # float(repr(x)) == x in Python 3, and yaml.safe_dump writes repr for
    # floats, so a and b survive the round trip exactly. That is required:
    # a lost digit moves the board and looks like a logic bug rather than a
    # serialisation one.
    body = {
        "season": int(model.season),
        "fitted_on": str(model.fitted_on),
        "curve": {"a": float(model.curve[0]), "b": float(model.curve[1])},
        "policy": str(model.policy),
        "evidence": dict(model.evidence or {}),
        "diagnostics": dict(model.diagnostics or {}),
    }
    with open(path, "w") as fh:
        yaml.safe_dump(body, fh, default_flow_style=False, sort_keys=True)


def load(path):
    """Read a model, validating what a hand edit could break."""
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}

    missing = [k for k in _REQUIRED if raw.get(k) is None]
    if missing:
        raise ValueError(
            "%s is not a usable market model: missing %s. A model must carry "
            "the season it was fitted from, the date, the curve, and the "
            "replacement policy chosen from the same prices."
            % (path, ", ".join(sorted(missing))))

    curve = raw["curve"] or {}
    if curve.get("a") is None or curve.get("b") is None:
        raise ValueError("%s: curve must carry both 'a' and 'b'" % path)
    a = float(curve["a"])
    b = float(curve["b"])

    # The fitter enforces both of these, but a hand-edited artifact never went
    # through the fitter - and this file is meant to be human-readable, which
    # means human-editable.
    if b <= 0.0:
        raise ValueError(
            "%s: exponent b=%.4f is not monotonic increasing; a better player "
            "would cost less, which no real auction does." % (path, b))
    if a < 1.0:
        raise ValueError(
            "%s: intercept a=%.4f is below the $1 floor, which would clamp "
            "every cheap player to an identical estimate and destroy ordering "
            "among them." % (path, a))

    policy = str(raw["policy"])
    if policy not in _KNOWN_POLICIES:
        raise ValueError(
            "%s: unknown replacement policy %r; expected one of %s"
            % (path, policy, list(_KNOWN_POLICIES)))

    return MarketModel(
        season=int(raw["season"]),
        fitted_on=str(raw["fitted_on"]),
        curve=(a, b),
        policy=policy,
        evidence=dict(raw.get("evidence") or {}),
        diagnostics=dict(raw.get("diagnostics") or {}),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_market_model.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/sffl/market_model.py tests/test_market_model.py
git commit -m "feat(market): the persisted market model artifact

Fitting and applying are two operations fused into one command, and only
fitting is season-bound. This is the thing that lets them separate: the
curve, the replacement policy chosen from the same prices, and the
evidence behind both.

evidence and diagnostics are stored rather than re-derived because the
failure this split exists to prevent was invisible precisely for want of
a record of what had been fitted against what.

Validates on load what a hand edit could break - a non-monotonic exponent
and a sub-\$1 intercept - because the artifact is meant to be readable,
which means editable, and an edited file never went through the fitter."
```

---

## Task 2: The guard moves into `load_prices`

**Files:**
- Modify: `src/sffl/fit.py` (`load_prices`, and a new season check)
- Modify: `data/league/auction-rosters-2026.csv` (add a `season` column)
- Modify: `tests/test_fit.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `fit.load_prices(path, alias_path=DEFAULT_ALIASES, tqb_starters_path=DEFAULT_TQB_STARTERS, season=None)` — **new keyword** `season`. When given, every season signal must agree with it.
  - `fit.prices_season(path)` → `int` or `None` — the season the CSV declares, if it carries a `season` column.

> **CORRECTED 2026-08-30 (docs audit) — this interface is NOT what shipped, and the
> difference is load-bearing, not cosmetic.** The function is
> **`fit.prices_seasons(path)` — PLURAL** — and it returns **every distinct season the CSV
> declares**, in first-seen order, not one `int` or `None`. The singular version specified
> here was implemented, then found to be a real defect and replaced: it returned the FIRST
> non-empty `season` cell and never looked at the rest, so a file whose first row said 2026
> and whose remaining 155 rows said 2025 verified clean, and `fit-market --year 2026` wrote
> an artifact stamped `season: 2026` carrying `a=2.4432 b=0.5308` from 123 observations —
> the artifact-era curve, blessed once and believed by every season after. `src/sffl/fit.py`
> carries the full reasoning on `prices_seasons`' own docstring ("PLURAL, and that is the
> whole contract"). **Do not copy the singular signature, or the two test snippets naming
> `prices_season` further down this plan, into new code.**

**This closes all three holes.** Read the "three holes" section above before starting.

- [ ] **Step 1: Add the season column to the 2026 prices file**

The file currently begins:

```
franchise,pick_order,player_as_written,price
SGT HULKA'S BIG TOES,1,JA'MARR CHASE,42
```

Add `season` as a new LAST column with the value `2026` on every data row, so the header becomes `franchise,pick_order,player_as_written,price,season`. Use a script rather than hand-editing 156 rows, and verify the row count is unchanged afterwards:

```bash
./.venv/bin/python - <<'PY'
import csv
p = "data/league/auction-rosters-2026.csv"
rows = list(csv.DictReader(open(p)))
assert "season" not in rows[0], "already has a season column"
with open(p, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) + ["season"])
    w.writeheader()
    for r in rows:
        r["season"] = 2026
        w.writerow(r)
print("rewrote %d rows" % len(rows))
PY
```

Confirm with `wc -l` before and after that only the header changed shape.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_fit.py`:

```python
def test_prices_season_reads_the_column_when_present():
    from sffl.fit import prices_season
    assert prices_season("data/league/auction-rosters-2026.csv") == 2026


def test_prices_season_is_none_when_the_file_predates_the_column(tmp_path):
    p = tmp_path / "old.csv"
    p.write_text("player_as_written,price\nJA'MARR CHASE,42\n")
    from sffl.fit import prices_season
    assert prices_season(str(p)) is None


def test_loading_prices_from_the_wrong_season_is_refused(tmp_path):
    # HOLE 1: this configuration used to run to completion and silently
    # refit the artifact-era curve. The prices file now states its own
    # season, so the lie is detectable rather than proxied by the TQB map.
    from sffl.fit import load_prices
    p = tmp_path / "prices.csv"
    p.write_text("player_as_written,price,season\nJA'MARR CHASE,42,2025\n")
    with pytest.raises(ValueError) as exc:
        load_prices(str(p), season=2026)
    assert "2025" in str(exc.value) and "2026" in str(exc.value)


def test_a_tqb_map_with_no_season_key_is_refused_when_a_season_is_asserted(tmp_path):
    # HOLE 2: a map with no season: key used to skip the guard entirely.
    from sffl.fit import load_prices
    m = tmp_path / "map.yaml"
    m.write_text("starters:\n  Joe Burrow: CIN\n")
    p = tmp_path / "prices.csv"
    p.write_text("player_as_written,price\nJA'MARR CHASE,42\n")
    with pytest.raises(ValueError) as exc:
        load_prices(str(p), tqb_starters_path=str(m), season=2026)
    assert "season" in str(exc.value).lower()


def test_a_direct_call_gets_the_same_guard_as_the_cli(tmp_path):
    # HOLE 3: the guard used to live only in cli._value_pool, so any other
    # caller bypassed it. It is enforced here now, at the load itself.
    from sffl.fit import DEFAULT_TQB_STARTERS, load_prices
    p = tmp_path / "prices.csv"
    p.write_text("player_as_written,price\nJA'MARR CHASE,42\n")
    with pytest.raises(ValueError):
        load_prices(str(p), tqb_starters_path=DEFAULT_TQB_STARTERS,
                    season=2026)  # the default map is 2025


def test_a_season_matched_load_still_works():
    from sffl.fit import load_prices
    prices = load_prices("data/league/auction-rosters-2026.csv",
                         tqb_starters_path="identity/tqb-2026-starters.yaml",
                         season=2026)
    assert len(prices) > 100


def test_omitting_the_season_keeps_the_old_permissive_behaviour(tmp_path):
    # Callers that genuinely do not know the season (a poc script exploring
    # a file) are not forced to assert one. The guard binds when a season IS
    # asserted, which every production path does.
    from sffl.fit import load_prices
    p = tmp_path / "prices.csv"
    p.write_text("player_as_written,price\nJA'MARR CHASE,42\n")
    assert load_prices(str(p)) is not None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_fit.py -v -k "season or hole or direct"`
Expected: FAIL — `cannot import name 'prices_season'`, and `load_prices() got an unexpected keyword argument 'season'`

- [ ] **Step 4: Write the implementation**

In `src/sffl/fit.py`, add beside `tqb_starters_season`:

```python
def prices_season(path):
    """The season a prices CSV declares, or None if it carries no column.

    The TQB starter map was only ever a PROXY for the prices' season, which is
    why mismatched prices with a matched map used to pass silently - the two
    are independent facts and only one was checked. A prices file that states
    its own season is direct evidence. Files written before the column exists
    return None and are handled by the caller, loudly.
    """
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "season" not in reader.fieldnames:
            return None
        for row in reader:
            value = (row.get("season") or "").strip()
            if value:
                return int(value)
    return None
```

Then change `load_prices`'s signature and add the guard at its top:

```python
def load_prices(path, alias_path=DEFAULT_ALIASES,
                tqb_starters_path=DEFAULT_TQB_STARTERS, season=None):
```

and immediately inside, before anything else:

```python
    # THE GUARD, MOVED HERE FROM cli._value_pool. It lived in the CLI, so any
    # other caller - a poc script, a notebook, a second league - got
    # DEFAULT_TQB_STARTERS (the 2025 map) forever with no check. Pairing one
    # season's prices with another's projections is what produced this
    # project's largest measurement error, and it is invisible in the output:
    # every number looks reasonable. A guard that can be bypassed by calling
    # the function directly is not a guard.
    #
    # It binds only when the caller ASSERTS a season. Production paths all do.
    if season is not None:
        map_season = tqb_starters_season(tqb_starters_path)
        if map_season is None:
            raise ValueError(
                "%s carries no 'season:' key, so it cannot be checked against "
                "the %d prices being loaded. A map with no season used to skip "
                "this check entirely - which is exactly how the wrong map goes "
                "unnoticed, since it does not fail loudly, it silently "
                "mis-joins or drops every Team QB price. Add 'season: <year>' "
                "to the map." % (tqb_starters_path, season))
        if map_season != season:
            raise ValueError(
                "refusing to load %d prices with the %d Team QB starter map "
                "(%s). Quarterbacks change franchises between Augusts, so the "
                "wrong map silently mis-joins or drops every Team QB price."
                % (season, map_season, tqb_starters_path))
        file_season = prices_season(path)
        if file_season is not None and file_season != season:
            raise ValueError(
                "%s declares season %d but %d was asserted. The prices file's "
                "own season column is direct evidence, unlike the TQB map "
                "which is only a proxy - this is the mismatch that used to "
                "pass silently and refit the artifact-era curve."
                % (path, file_season, season))
```

- [ ] **Step 5: Update the CLI's caller to pass the season**

In `src/sffl/cli.py:_value_pool`, the existing inline guard block is now redundant with the one inside `load_prices`. Replace the whole `_map_season` check and the `load_prices(...)` call with a single guarded call that converts the library error into the CLI's `SystemExit`:

```python
    prices = None
    if args.prices:
        # The guard now lives in fit.load_prices, so it cannot be bypassed by
        # a caller that reaches for the function directly. Converted to
        # SystemExit here so the CLI keeps its clean single-line failure.
        try:
            prices = load_prices(args.prices,
                                 tqb_starters_path=args.tqb_starters,
                                 season=args.year)
        except ValueError as exc:
            raise SystemExit(str(exc))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_fit.py -v`
Expected: all pass

- [ ] **Step 7: Run the full suite**

Run: `./.venv/bin/pytest -q`
Expected: all pass. If a pre-existing test breaks, that is a signal — report which and why, and do NOT weaken its assertions to accommodate the change.

- [ ] **Step 8: Commit**

```bash
git add src/sffl/fit.py src/sffl/cli.py tests/test_fit.py data/league/auction-rosters-2026.csv
git commit -m "fix(fit): the season guard moves into load_prices, and prices state their own season

Three holes, all closed here. The guard lived in cli._value_pool, so any
caller reaching for load_prices directly got the 2025 TQB map forever with
no check. A starter map with no season: key skipped the check entirely. And
the prices CSV carried no season metadata at all, so the TQB map was only a
PROXY for the prices' season - which is why mismatched prices with a matched
map ran to completion and silently refit the artifact-era curve.

The prices file now states its own season, which is direct evidence rather
than a proxy. Files predating the column still load, and say so.

The guard binds only when a caller asserts a season; every production path
does, and a poc script exploring an unknown file is not forced to lie."
```

---

## Task 3: `sffl fit-market`

**Files:**
- Modify: `src/sffl/cli.py`
- Create: `tests/test_cli_fit_market.py`

**Interfaces:**
- Consumes: `market_model.MarketModel`/`save` (Task 1); `fit.load_prices(..., season=)` (Task 2).
- Produces: CLI `sffl fit-market --source S --file F --year Y --prices P --tqb-starters T --out market/<Y>.yaml [--force] [--curves C] [--set X] [--league L]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_fit_market.py`:

```python
import os

import pytest

from sffl.cli import main


def _args(tmp_path, **over):
    out = over.pop("out", str(tmp_path / "2026.yaml"))
    argv = ["fit-market",
            "--source", "sources/draftsharks.yaml",
            "--file", over.pop("file", "tests/fixtures/draftsharks_market_fit_sample.csv"),
            "--year", str(over.pop("year", 2026)),
            "--prices", over.pop("prices", "tests/fixtures/prices_market_fit_sample.csv"),
            "--tqb-starters", over.pop("tqb", "identity/tqb-2026-starters.yaml"),
            "--out", out]
    for k, v in over.items():
        argv += ["--" + k.replace("_", "-"), str(v)]
    return argv, out


def test_a_year_matched_fit_writes_a_usable_model(tmp_path):
    from sffl.market_model import load
    argv, out = _args(tmp_path)
    assert main(argv) == 0
    m = load(out)
    assert m.season == 2026
    assert m.curve[1] > 0
    assert m.policy in ("starter", "draftable")
    assert m.evidence["observations"] > 0
    assert m.evidence["projections_year"] == 2026


def test_the_model_records_which_prices_and_projections_it_saw(tmp_path):
    # The failure this split exists to prevent was invisible for want of a
    # record of what was fitted against what.
    from sffl.market_model import load
    argv, out = _args(tmp_path)
    main(argv)
    ev = load(out).evidence
    assert "prices_market_fit_sample.csv" in ev["prices_file"]
    assert ev["tqb_starters"].endswith("tqb-2026-starters.yaml")


def test_a_cross_season_fit_is_refused(tmp_path):
    argv, _ = _args(tmp_path, year=2027)
    with pytest.raises(SystemExit):
        main(argv)


def test_it_refuses_to_overwrite_without_force(tmp_path):
    argv, out = _args(tmp_path)
    assert main(argv) == 0
    with pytest.raises(SystemExit):
        main(argv)


def test_force_allows_a_deliberate_refit(tmp_path):
    argv, out = _args(tmp_path)
    assert main(argv) == 0
    argv2, _ = _args(tmp_path, out=out, force=True)
    # --force is a flag, not a value; rebuild argv by hand.
    argv2 = [a for a in argv2 if a not in ("--force", "True")] + ["--force"]
    assert main(argv2) == 0


def test_nothing_is_written_when_the_fit_is_refused(tmp_path):
    out = str(tmp_path / "never.yaml")
    argv, _ = _args(tmp_path, year=2027, out=out)
    with pytest.raises(SystemExit):
        main(argv)
    assert not os.path.exists(out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_cli_fit_market.py -v`
Expected: FAIL — `invalid choice: 'fit-market'`

- [ ] **Step 3: Write the implementation**

Add to `src/sffl/cli.py`:

```python
def cmd_fit_market(args):
    """Fit this room's price curve and policy from year-matched evidence, and persist them.

    THE ONLY COMMAND THAT FITS. Everything else applies a model this wrote.
    That separation is the point: fitting is season-bound and can only happen
    after an auction, while applying needs nothing but a curve and this year's
    projections. Fusing them is what made a pre-auction run choose between
    refusing outright and silently fitting across seasons.
    """
    import datetime

    from sffl.fit import choose_policy, load_prices, score_fit
    from sffl.market import fit_price_curve
    from sffl.market_model import MarketModel, save
    from sffl.pool import build_pool
    from sffl.value import _pool_of, assign_dollars, assign_vorp, replacement_levels

    lg = load_league(args.league)
    pool = build_pool(lg, args.source, args.file, args.year, args.set)

    if args.curves:
        curves = load_curves(args.curves)
        for p in pool:
            p.stats["_season_points"] = score_season_calibrated(lg, p, curves)
        pool.sort(key=lambda p: -p.stats["_season_points"])

    # season=args.year is what makes this refuse every cross-season
    # combination it can detect - the TQB map's season and the prices file's
    # own season column must both agree with the projections' year.
    try:
        prices = load_prices(args.prices, tqb_starters_path=args.tqb_starters,
                             season=args.year)
    except ValueError as exc:
        raise SystemExit(str(exc))

    policy, reports = choose_policy(lg, pool, prices)
    chosen = [r for r in reports if r["policy"] == policy][0]

    # choose_policy leaves the pool carrying the LAST policy's numbers, not
    # the winner's - see its docstring. Re-run the valuation with the chosen
    # policy before fitting, or the curve is fit against the wrong dollars.
    levels = replacement_levels(lg, pool, policy)
    assign_vorp(lg, pool, levels)
    assign_dollars(lg, pool)

    pairs = []
    for p in pool:
        if lg.flat_priced_pools.get(_pool_of(p.pos)) is not None:
            continue
        key = normalize_name(p.name)
        if key in prices:
            pairs.append((p.stats["_dollars"], prices[key]))

    curve = fit_price_curve(pairs)

    model = MarketModel(
        season=args.year,
        fitted_on=datetime.date.today().isoformat(),
        curve=curve,
        policy=policy,
        evidence={
            "prices_file": args.prices,
            "prices_rows": prices.total_rows,
            "observations": len(pairs),
            "projections_source": args.source,
            "projections_year": args.year,
            "tqb_starters": args.tqb_starters,
        },
        diagnostics={
            "mae": round(chosen["mae"], 4),
            "top10_mae": round(chosen["top10_mae"], 4),
            "top10_bias": round(chosen["top10_bias"], 4),
        },
    )
    save(args.out, model, overwrite=args.force)
    print("wrote %s" % args.out)
    print("  policy chosen from these prices: %s" % policy)
    print("  curve: a=%.4f b=%.4f from %d observations"
          % (curve[0], curve[1], len(pairs)))
    return 0
```

Register the subparser beside the others:

```python
    fm = sub.add_parser("fit-market",
                        help="fit this room's price curve from year-matched "
                             "prices and persist it for future seasons")
    fm.add_argument("--source", required=True)
    fm.add_argument("--file", required=True)
    fm.add_argument("--year", type=int, required=True)
    fm.add_argument("--set", default=None)
    fm.add_argument("--league", default=DEFAULT_LEAGUE)
    fm.add_argument("--curves", default=None)
    fm.add_argument("--prices", required=True,
                    help="observed auction prices FROM THE SAME SEASON as --year")
    fm.add_argument("--tqb-starters", default=DEFAULT_TQB_STARTERS,
                    help="Team QB starter map for --year")
    fm.add_argument("--out", required=True,
                    help="where to write the model, e.g. market/2026.yaml")
    fm.add_argument("--force", action="store_true",
                    help="overwrite an existing model")
    fm.set_defaults(func=cmd_fit_market)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_cli_fit_market.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/sffl/cli.py tests/test_cli_fit_market.py
git commit -m "feat(cli): sffl fit-market, the only command that fits

Fitting is season-bound and can only happen after an auction. Applying
needs nothing but a curve and this year's projections. This command is
the fitting half, and it refuses every cross-season combination it can
detect - the TQB map's season and the prices file's own season column
must both agree with the projections' year.

Re-runs the valuation with the chosen policy before fitting: choose_policy
leaves the pool carrying the LAST policy's numbers rather than the
winner's, so fitting straight after it would fit against the wrong dollars."
```

---

## Task 4: Apply a persisted model

**Files:**
- Modify: `src/sffl/cli.py` (`_value_pool`, `value`/`render` subparsers)
- Create: `tests/test_cli_market_apply.py`

**Interfaces:**
- Consumes: `market_model.load`/`describe` (Task 1).
- Produces: `--market <path>` on `value` and `render`.

**Rules:**
- `--market` and `--prices` together is REFUSED, naming both.
- A cross-season apply is PERMITTED and ANNOUNCED on every run.
- With `--market`, the persisted policy is used and `choose_policy` never runs — so `--policy fit` needs no prices.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_market_apply.py`:

```python
import pytest

from sffl.cli import main


def _write_model(tmp_path, season=2026):
    from sffl.market_model import MarketModel, save
    p = str(tmp_path / "m.yaml")
    save(p, MarketModel(season=season, fitted_on="2026-08-30",
                        curve=(2.05, 0.662), policy="starter",
                        evidence={"observations": 130}, diagnostics={}))
    return p


def _value_argv(model, year=2026):
    return ["value",
            "--source", "sources/draftsharks.yaml",
            "--file", "tests/fixtures/draftsharks_market_fit_sample.csv",
            "--year", str(year), "--market", model]


def test_applying_a_model_prices_the_board(tmp_path, capsys):
    assert main(_value_argv(_write_model(tmp_path))) == 0
    assert "market model" in capsys.readouterr().out


def test_a_cross_season_apply_is_permitted_and_announced(tmp_path, capsys):
    # The whole point: last year's model of the room, applied to this year's
    # projections, is the correct thing to want - but it must never be silent.
    assert main(_value_argv(_write_model(tmp_path, season=2026), year=2027)) == 0
    out = capsys.readouterr().out
    assert "2026" in out and "market model" in out


def test_market_and_prices_together_are_refused(tmp_path):
    argv = _value_argv(_write_model(tmp_path)) + [
        "--prices", "tests/fixtures/prices_market_fit_sample.csv"]
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert "--market" in str(exc.value) and "--prices" in str(exc.value)


def test_policy_fit_needs_no_prices_when_a_model_is_supplied(tmp_path):
    # The deadlock, gone: the persisted policy was chosen from year-matched
    # prices, so a pre-auction run needs no price file at all.
    argv = _value_argv(_write_model(tmp_path)) + ["--policy", "fit"]
    assert main(argv) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_cli_market_apply.py -v`
Expected: FAIL — `unrecognized arguments: --market`

- [ ] **Step 3: Write the implementation**

In `_value_pool`, immediately after the league and pool are built, add the mutual-exclusion check and the apply path:

```python
    market = None
    if getattr(args, "market", None):
        if args.prices:
            raise SystemExit(
                "--market and --prices are mutually exclusive: --market "
                "APPLIES a model fitted earlier, --prices FITS one now. "
                "Passing both is asking to fit and apply in the same run, "
                "which is the confusion this split exists to end. Use "
                "--prices with `sffl fit-market` to produce a model, then "
                "--market to price a board with it.")
        from sffl.market_model import describe
        from sffl.market_model import load as load_market
        market = load_market(args.market)
        # ANNOUNCED EVERY RUN, and loudly when the seasons differ. A curve
        # silently older than the board it prices is the failure this split
        # was built to design out - permitting the cross-season apply is only
        # safe because it is impossible to do accidentally.
        print("  " + describe(market))
        if market.season != args.year:
            print("  NOTE: this is a CROSS-SEASON apply - a %d model pricing "
                  "%d projections. That is intended (last year's model of how "
                  "this room behaves), but it is not a year-matched fit."
                  % (market.season, args.year))
```

Then, where the policy is resolved, prefer the persisted one:

```python
    policy = args.policy
    if market is not None:
        # The persisted policy was chosen from year-matched prices, so a
        # pre-auction run needs no price file to know it.
        policy = market.policy
    elif policy == "fit":
        ...  # existing choose_policy block unchanged
```

And where the curve is fitted, use the persisted curve when one was supplied — leaving the existing `--prices` fitting path untouched for a same-season run:

```python
    if market is not None:
        curve = market.curve
        assign_expected_prices(lg, pool, curve)
    elif prices is not None:
        ...  # existing fit-then-assign block unchanged
```

Add to BOTH the `value` and `render` subparsers:

```python
    val.add_argument("--market", default=None,
                     help="apply a persisted market model (see fit-market); "
                          "mutually exclusive with --prices")
```

(and the identical line for `ren`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_cli_market_apply.py -v`
Expected: 4 passed

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/pytest -q`

- [ ] **Step 6: Commit**

```bash
git add src/sffl/cli.py tests/test_cli_market_apply.py
git commit -m "feat(cli): --market applies a persisted model, and says so

A cross-season apply is permitted - last year's model of how this room
behaves is the correct thing to want, because the room's behaviour is a
property of the twelve people in it. But it is announced on every run,
and marked explicitly when the seasons differ: a curve silently older
than the board it prices is the failure this split was built to prevent.

--market with --prices is refused. One fits, one applies; asking for both
in a single run is the confusion the split exists to end.

With a model supplied, --policy fit needs no prices, because the policy
was chosen from year-matched prices when the model was fitted. That is
the deadlock closing."
```

---

## Task 5: Generate the 2026 model, and prove the board does not move

**Files:**
- Create: `market/2026.yaml` (generated, then committed)
- Create: `tests/test_market_roundtrip.py`

**Interfaces:**
- Consumes: everything above.
- Produces: the committed 2026 model.

**This is the task that proves the split changed only WHEN the fit happens, never any number.**

- [ ] **Step 1: Write the failing regression test**

Create `tests/test_market_roundtrip.py`:

```python
"""Fit -> persist -> apply must reproduce fit-in-process, exactly.

The split is supposed to change WHEN the curve is fitted, not what it is. If
this test fails, either the persisted floats lost precision or the apply path
diverged from the fit path - and both look, from the board, like an
unexplained change in dollars.
"""


def _pool_dollars(argv):
    """Run a valuation and return {player name: (_dollars, _est_price)}."""
    from sffl.cli import main
    import sffl.cli as cli
    captured = {}
    real = cli.assign_expected_prices

    def spy(lg, pool, curve):
        k = real(lg, pool, curve)
        captured["rows"] = dict(
            (p.name, (round(p.stats["_dollars"], 6),
                      round(p.stats["_est_price"], 6))) for p in pool)
        captured["curve"] = curve
        return k

    cli.assign_expected_prices = spy
    try:
        assert main(argv) == 0
    finally:
        cli.assign_expected_prices = real
    return captured


COMMON = ["--source", "sources/draftsharks.yaml",
          "--file", "tests/fixtures/draftsharks_market_fit_sample.csv",
          "--year", "2026"]


def test_persisting_the_fit_does_not_move_the_board(tmp_path):
    out = str(tmp_path / "2026.yaml")
    from sffl.cli import main
    assert main(["fit-market"] + COMMON + [
        "--prices", "tests/fixtures/prices_market_fit_sample.csv",
        "--tqb-starters", "identity/tqb-2026-starters.yaml",
        "--out", out]) == 0

    direct = _pool_dollars(["value"] + COMMON + [
        "--prices", "tests/fixtures/prices_market_fit_sample.csv",
        "--tqb-starters", "identity/tqb-2026-starters.yaml",
        "--policy", "fit"])
    applied = _pool_dollars(["value"] + COMMON + ["--market", out])

    assert applied["curve"] == direct["curve"], "the persisted curve differs"
    assert applied["rows"] == direct["rows"], "the board moved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_market_roundtrip.py -v`
Expected: FAIL until Tasks 1–4 are complete; if they are, this should PASS. **If it fails after Tasks 1–4, stop and report** — either the floats lost precision in YAML or the apply path diverged, and both are exactly what this test exists to catch. Do not "fix" it by loosening the comparison.

- [ ] **Step 3: Generate the real 2026 model**

Run against the real 2026 data:

```bash
./.venv/bin/python -m sffl.cli fit-market \
  --source sources/draftsharks.yaml \
  --file "$(ls data/extracts/Draft\ Sharks/2026/*.csv | head -1)" \
  --year 2026 \
  --curves calibration/2025.yaml \
  --prices data/league/auction-rosters-2026.csv \
  --tqb-starters identity/tqb-2026-starters.yaml \
  --out market/2026.yaml
```

**If `data/extracts/` is unavailable** (it is gitignored licensed vendor data and may not be present), STOP and report that — do not fabricate a model from a fixture and commit it as the real one. The real artifact must come from the real extract.

Then verify the generated file: `b` should be near **0.662** (the year-matched truth). If it comes back near **0.531**, that is the artifact-era curve and something is fitting across seasons — stop and report.

- [ ] **Step 4: Verify the real model against the real board**

Confirm the committed model reproduces the current `--prices` render:

```bash
PYTHONPATH=src ./.venv/bin/python -c "
from sffl.market_model import load
m = load('market/2026.yaml')
print(m.season, m.curve, m.policy, m.evidence['observations'])
"
```

Report the numbers.

- [ ] **Step 5: Commit**

```bash
git add market/2026.yaml tests/test_market_roundtrip.py
git commit -m "feat(market): persist the 2026 model, and prove the board does not move

Fit -> persist -> apply reproduces fit-in-process exactly, including the
curve's floats. The split changes WHEN the fit happens, never what it is,
and this is the test that holds that line - if it ever fails, either the
persisted floats lost precision or the apply path diverged, and both look
from the board like an unexplained change in dollars.

The 2027 pre-auction run can now be done legitimately: apply this model to
2027 projections, with no 2027 price file and no cross-season fit."
```

---

## Task 6: The fabricated `top10_bias`, and the intel page

**Files:**
- Modify: `tests/test_fit.py`
- Modify: `src/sffl/render/intel.py`

**The finding:** `tests/test_fit.py` (~lines 244-251, 276-285) pins "the real 2026 numbers" with starter `top10_bias = -0.25`. **The real value is +5.10** — the −0.25 belongs to the $26+ band of a different table. The decision the tests pin is correct either way, so no board is wrong; but a green test asserting starter's top-10 is unbiased when it over-prices by $5.10 is this codebase's signature failure in miniature.

- [ ] **Step 1: Measure the real numbers**

Do NOT copy the value from this plan. Measure it, from the real 2026 data, and use what you measure:

```bash
PYTHONPATH=src ./.venv/bin/python -c "
from sffl.fit import load_prices, score_fit, top10_cost
from sffl.league import load_league
from sffl.pool import build_pool
import glob
lg = load_league('leagues/sffl/2026.yaml')
f = sorted(glob.glob('data/extracts/Draft Sharks/2026/*.csv'))[0]
pool = build_pool(lg, 'sources/draftsharks.yaml', f, 2026, None)
prices = load_prices('data/league/auction-rosters-2026.csv',
                     tqb_starters_path='identity/tqb-2026-starters.yaml',
                     season=2026)
for p in ('starter', 'draftable'):
    r = score_fit(lg, pool, prices, p)
    print('%-10s n=%d mae=%.4f top10_mae=%.4f top10_bias=%.4f cost=%.4f'
          % (p, r['n'], r['mae'], r['top10_mae'], r['top10_bias'], top10_cost(r)))
"
```

Report every number. **If `data/extracts/` is unavailable, STOP and report** — do not substitute a fixture-derived number for one the test calls "the real 2026 numbers."

- [ ] **Step 2: Correct the test**

Replace the fabricated figures with the measured ones. Add a comment recording where the −0.25 came from, so nobody reintroduces it:

```python
# MEASURED, not quoted. The previous value here (-0.25) was lifted from the
# $26+ band of a different table and asserted that starter's top-10 is
# essentially unbiased. It over-prices by several dollars. The policy
# decision these numbers pin is correct either way - starter wins for any
# bias weight above 0.25 - but a green test asserting a bias that is not
# there is this codebase's signature failure in miniature.
```

If the measured numbers make the assertions awkward to state precisely, prefer asserting the RELATIONSHIP the decision rests on (starter's `top10_cost` is lower than draftable's; draftable's top-10 error is almost entirely systematic) over pinning fragile decimals. State which you chose and why.

- [ ] **Step 3: Run the tests**

Run: `./.venv/bin/pytest tests/test_fit.py -v`
Expected: all pass

- [ ] **Step 4: Name the model on the intel page**

In `src/sffl/render/intel.py`, the workbook's intel page explains where the numbers come from. It must now say which market model priced the board and from which season, because a reader looking at EST$ has no other way to know whether the curve is year-matched or carried over. Follow the module's existing convention: a fact it cannot derive comes back `None` and its sentence says so, rather than quoting a stale number.

Add the model's season, coefficients, observation count, and — when the model's season differs from the board's year — an explicit note that this is a cross-season apply.

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/pytest -q`

- [ ] **Step 6: Commit**

```bash
git add tests/test_fit.py src/sffl/render/intel.py
git commit -m "fix(fit): measure top10_bias instead of quoting a number from another table

tests/test_fit.py pinned starter top10_bias = -0.25 as 'the real 2026
number'. The -0.25 belongs to the \$26+ band of a different table. The
policy decision the tests pin is correct either way, so no board was
wrong - but a green test asserting starter's top-10 is unbiased when it
is not is exactly the failure mode this project keeps finding.

The intel page now names the market model and its season, so a reader
looking at EST\$ can tell whether the curve is year-matched or carried
over from a previous season."
```

---

## Self-Review

**1. Spec coverage.**

| spec requirement | task |
|---|---|
| Persisted artifact with curve, policy, evidence, diagnostics | 1 |
| Refuses to overwrite without an explicit flag | 1, 3 |
| Hole 1 — prices CSV states its own season | 2 |
| Hole 2 — map with no `season:` key refused | 2 |
| Hole 3 — guard inside `load_prices` | 2 |
| `fit-market` refuses cross-season fits | 3 |
| `--market` applies; cross-season apply announced | 4 |
| `--market` + `--prices` refused | 4 |
| `--policy fit` needs no prices with a model | 4 |
| 2026 board must not move | 5 (the governing regression) |
| `top10_bias` corrected | 6 |
| Model named on the intel page | 6 |
| Fit maths unchanged | enforced by Global Constraints and Task 5 |

**2. Placeholder scan.** Two deliberate "measure it, don't copy it" steps — Task 5 Step 3 (the real curve) and Task 6 Step 1 (the real diagnostics). Both carry an explicit STOP-and-report if `data/extracts/` is unavailable, and Task 5 names the number that would indicate a cross-season fit (`b≈0.531`) so a wrong result is recognisable rather than merely unexpected.

**3. Type consistency.** `MarketModel.curve` is `(a, b)` everywhere — produced by `fit_price_curve`, stored by `save`, returned by `load`, consumed by `assign_expected_prices`, which already takes exactly that shape. `load_prices`'s new `season` kwarg is keyword-only in practice and defaults to `None`, so every existing call site keeps working; the one production call site is updated in Task 2 Step 5.

**4. Known risk.** Task 5 and Task 6 both need `data/extracts/`, which is gitignored licensed vendor data. If it is not on the machine, those steps cannot be completed honestly and the plan says to stop rather than substitute fixture data — a fabricated `market/2026.yaml` committed as the real one would be a worse outcome than an unfinished task.

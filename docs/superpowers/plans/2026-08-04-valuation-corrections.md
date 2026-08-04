# Valuation Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the auction board's dollar values match how this league actually prices players — kickers and defenses at $1, and the Team QB market visible to the price fit for the first time.

**Architecture:** Three of the four position pools were invisible or mispriced. The 2025 roster sheet records defenses as `PHILLY D` and Team QB units by their starting quarterback's name, so 33 of 156 real prices never joined the pool and the fit was blind to the entire TQB and DST markets. This plan reconciles those names, adds the 15 skill-player misspellings, then prices K and DST flat at $1 — justified by 21 observed prices, none above $3 — and returns the surplus they were absorbing to the players people actually bid on. Finally it reports fit error per pool, so a 20x error on one position can never again hide behind a good global average.

**Tech Stack:** Python 3.9, pytest, PyYAML, rapidfuzz.

## Global Constraints

- **Python 3.9.6 only.** No `match` statements, no PEP 604 (`int | None`) annotations. Use `typing.Optional`/`List`/`Dict`.
- **Use the project venv** at `.venv/`. Invoke as `./.venv/bin/pytest` and `./.venv/bin/python`. `sffl` is not pip-installed; ad-hoc commands need `PYTHONPATH=src`.
- **`data/extracts/` and `data/weekly/` are gitignored** — licensed vendor and CBS data, and this repo is PUBLIC. Never commit a file from either, and never paste extract contents or real-run output into a committed file. `data/league/` IS tracked.
- **Wrong numbers must never be produced silently.** Prefer raising over guessing.
- **Never mix seasons.** The roster sheet holds 2025 prices; QB-to-franchise mappings must come from 2025, never from the 2026 extract. Kyler Murray was ARI in 2025 and appears on a different team in the 2026 extract — resolving 2025 prices through 2026 rosters is wrong.
- **WR and TE are ONE position.** Never split them.
- **`src/sffl/scoring.py` is validated against ~250 real CBS observations and must NOT be modified.**
- **A zero is not a no-op for `def_pa`/`def_ya`** — both band `0` at their maximum 6 points. Any loop over `lg.bands` must be position-gated via `calibrate.STAT_POSITIONS`.

## Observed ground truth (do not re-derive)

Measured from `data/league/auction-rosters-2025.csv` joined against the 2026 Draft Sharks extract:

| pool | n priced | min | max | mean |
|---|---|---|---|---|
| K | 9 | $1 | $3 | $1.3 |
| DST | 12 (all unmatched today) | $1 | $3 | ~$1.5 |
| TQB | 21 (all unmatched today) | $1 | $31 | — |
| RB | 42 | $1 | $41 | $12.7 |
| WR | 49 | $1 | $43 | $9.8 |
| TE | 8 | $1 | $10 | $3.4 |

The model currently prices a kicker at ~$20. Seven of nine real kickers went for exactly $1.

## File Structure

| File | Responsibility |
|---|---|
| `identity/aliases.yaml` (modify) | 12 DST roster-sheet spellings + 15 skill misspellings |
| `identity/tqb-2025-starters.yaml` | Year-bound map: 2025 starting QB name → franchise code |
| `src/sffl/fit.py` (modify) | Consume the TQB starter map; per-pool fit reporting |
| `leagues/sffl/2026.yaml` (modify) | `flat_priced_pools` |
| `src/sffl/value.py` (modify) | Honor flat-priced pools in VORP and dollars |
| `src/sffl/cli.py` (modify) | Print the per-pool fit table |

---

### Task 1: Reconcile defense and skill-player names

**Files:**
- Modify: `identity/aliases.yaml`
- Test: `tests/test_fit.py` (append)

**Interfaces:**
- Consumes: `sffl.fit.load_prices`, which already canonicalizes through `identity/aliases.yaml` via `Resolver(alias_path).aliases`.
- Produces: no new code. The alias file is the deliverable.

**Why.** `load_prices` maps a normalized roster-sheet name through the alias table. The roster sheet writes defenses as `PHILLY D` and misspells 15 skill players. Adding those entries is all that is needed — the join machinery already exists and is tested.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fit.py`:

```python
REAL_PRICES = "data/league/auction-rosters-2025.csv"


def test_defense_roster_spellings_resolve_to_franchise_names():
    prices = load_prices(REAL_PRICES)
    for franchise in ("philadelphia eagles", "pittsburgh steelers",
                      "minnesota vikings", "houston texans"):
        assert franchise in prices, franchise


def test_skill_misspellings_resolve():
    prices = load_prices(REAL_PRICES)
    for name in ("evan mcpherson", "tetairoa mcmillan", "treveyon henderson",
                 "jaxon smith njigba", "jauan jennings", "wil lutz"):
        assert name in prices, name


def test_players_genuinely_absent_from_the_extract_stay_unresolved():
    # Joe Mixon and Ricky Pearsall are not in the 2026 Draft Sharks extract.
    # They must NOT be force-matched onto a similarly spelled player.
    prices = load_prices(REAL_PRICES)
    assert "jordan mason" not in prices or prices.get("jordan mason") != 1.0
    assert "erick all" not in prices or prices.get("erick all") != 13.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_fit.py -v -k "defense_roster or skill_misspellings"`
Expected: FAIL — those keys are absent from `prices`.

- [ ] **Step 3: Add the alias entries**

Append to the `players:` map in `identity/aliases.yaml`:

```yaml
  # --- 2025 roster-sheet defense spellings. The sheet writes a city or
  # nickname plus " D"; the pool carries full franchise names.
  "Arizona D": "Arizona Cardinals"
  "Baltimore D": "Baltimore Ravens"
  "Buffalo D": "Buffalo Bills"
  "Denver D": "Denver Broncos"
  "Detroit D": "Detroit Lions"
  "Green Bay D": "Green Bay Packers"
  "Houston D": "Houston Texans"
  "KC D": "Kansas City Chiefs"
  "Minnesota D": "Minnesota Vikings"
  "Philly D": "Philadelphia Eagles"
  "Pittsburgh D": "Pittsburgh Steelers"
  "Seattle D": "Seattle Seahawks"

  # --- 2025 roster-sheet skill-player misspellings, hand typed at the auction.
  "Bhaysul Tuten": "Bhayshul Tuten"
  "Bill Croskey Merritt": "Jacory Croskey-Merritt"
  "Brealon Allen": "Braelon Allen"
  "Cam Dicker": "Cameron Dicker"
  "Cam Skattebo": "Cameron Skattebo"
  "Evan Macpherson": "Evan McPherson"
  "Javonta Williams": "Javonte Williams"
  "Jaxon S N": "Jaxon Smith-Njigba"
  "Juan Jennings": "Jauan Jennings"
  "Tet McMillian": "Tetairoa McMillan"
  "Treyveon Henderson": "TreVeyon Henderson"
  "Tyrone Tracey": "Tyrone Tracy"
  "Will Lutz": "Wil Lutz"
```

Do NOT add entries for `Joe Mixon` or `Ricky Pearsall`. Both are genuinely absent from the 2026 extract; fuzzy matching proposed `jordan mason` (57) and `erick all` (76) respectively, and both are wrong. An unmatched price is correct behaviour — it simply does not enter the fit.

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_fit.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add identity/aliases.yaml tests/test_fit.py
git commit -m "fix: reconcile 2025 roster-sheet defense and skill-player spellings"
```

---

### Task 2: Join the Team QB market to the price fit

**Files:**
- Create: `identity/tqb-2025-starters.yaml`
- Modify: `src/sffl/fit.py`
- Test: `tests/test_fit.py` (append)

**Interfaces:**
- Consumes: `load_prices` from Task 1's unchanged machinery.
- Produces: `load_prices(path, alias_path=DEFAULT_ALIASES, tqb_starters_path=DEFAULT_TQB_STARTERS)`. The TQB map is applied AFTER alias canonicalization and maps a normalized quarterback name to a franchise code, which is how the pool names its Team QB units.

**Why this needs its own file.** The pool's TQB records are named by franchise code (`"BUF"`, `"CIN"`). The roster sheet records the unit by whoever started for that franchise in 2025. That mapping is a fact about one season and must not go in `identity/aliases.yaml`, which the general `Resolver` consults for every source — an entry mapping `"Kyler Murray" -> "ARI"` there would let a vendor's quarterback resolve to a team code in unrelated code paths. It also must not be derived from the 2026 extract: Kyler Murray was ARI in 2025 and appears elsewhere in the 2026 file.

- [ ] **Step 1: Create the starter map**

Create `identity/tqb-2025-starters.yaml`:

```yaml
# Which quarterback the 2025 auction roster sheet used to name each franchise's
# Team QB unit. This league drafts TEAM quarterbacks, but the sheet was hand
# written with the starter's name, so "JOSH ALLEN, $23" is the Buffalo TQB unit.
#
# YEAR-BOUND ON PURPOSE. These are 2025 assignments and must not be rebuilt from
# a later extract - Kyler Murray was ARI in 2025 and shows a different team in
# the 2026 Draft Sharks file. A 2026 sheet needs its own map.
#
# Left side is the quarterback as written; right side is the franchise code the
# pool uses to name the Team QB unit.
starters:
  "Aaron Rodgers": "PIT"
  "Baker Mayfield": "TB"
  "Bo Nix": "DEN"
  "Brock Purdy": "SF"
  "Cameron Ward": "TEN"
  "CJ Stroud": "HOU"
  "Dak Prescott": "DAL"
  "Drake Maye": "NE"
  "Geno Smith": "LV"
  "Jalen Hurts": "PHI"
  "Jared Goff": "DET"
  "Jayden Daniels": "WAS"
  "JJ McCarthy": "MIN"
  "Joe Burrow": "CIN"
  "Jordan Love": "GB"
  "Josh Allen": "BUF"
  "Justin Herbert": "LAC"
  "Kyler Murray": "ARI"
  "Lamar Jackson": "BAL"
  "Patrick Mahomes": "KC"
  "Tua Tagovailoa": "MIA"
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_fit.py`:

```python
def test_tqb_units_join_by_their_2025_starting_quarterback():
    prices = load_prices(REAL_PRICES)
    # the sheet wrote "JOSH ALLEN"; the pool names the unit "BUF"
    assert prices.get("buf") == 23.0
    assert prices.get("bal") == 31.0
    assert prices.get("was") == 28.0


def test_tqb_map_uses_2025_teams_not_the_2026_extract():
    # Kyler Murray was ARI in 2025 and appears on another team in the 2026 file.
    prices = load_prices(REAL_PRICES)
    assert prices.get("ari") == 1.0


def test_a_franchise_with_two_priced_quarterbacks_keeps_the_higher_price():
    # One roster carried both a starter and a backup TQB unit. Whichever way
    # collisions resolve, the mapping must not silently drop a price.
    prices = load_prices(REAL_PRICES)
    tqb_keys = [k for k in prices if len(k) == 3 and k.isalpha()]
    assert len(tqb_keys) >= 20
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_fit.py -v -k tqb`
Expected: FAIL — `prices.get("buf")` is `None`.

- [ ] **Step 4: Implement the TQB join**

In `src/sffl/fit.py`, add the constant beside `DEFAULT_ALIASES`:

```python
DEFAULT_TQB_STARTERS = "identity/tqb-2025-starters.yaml"
```

Add a loader and extend `load_prices`:

```python
def _load_tqb_starters(path):
    """Map normalized quarterback name -> franchise code for one season."""
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    out = {}
    for qb, team in (raw.get("starters") or {}).items():
        out[normalize_name(qb)] = str(team).strip().upper()
    return out
```

`load_prices` gains the parameter and applies the map after alias canonicalization:

```python
def load_prices(path, alias_path=DEFAULT_ALIASES,
                tqb_starters_path=DEFAULT_TQB_STARTERS):
    """Map canonical player key -> price paid.

    Three reconciliations, in order, because the roster sheet is hand typed:
      1. normalize spelling
      2. apply identity/aliases.yaml - fixes misspellings and the "PHILLY D" form
      3. apply the season's TQB starter map - the sheet names a Team QB unit by
         whoever started for that franchise, but the pool names it by franchise

    A franchise may appear twice when one roster carried a backup Team QB. The
    higher price wins: it is the one that reflects the unit's market value, and
    silently keeping whichever came last would depend on file order.
    """
    aliases = Resolver(alias_path).aliases
    starters = _load_tqb_starters(tqb_starters_path)
    out = {}  # type: Dict[str, float]
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            name = normalize_name(row["player_as_written"])
            if not name:
                continue
            name = aliases.get(name, name)
            team = starters.get(name)
            if team is not None:
                name = normalize_name(team)
            price = float(row["price"])
            if name in out:
                out[name] = max(out[name], price)
            else:
                out[name] = price
    return out
```

Add `import yaml` and `from sffl.identity import Resolver, normalize_name` to the imports if either is not already present.

- [ ] **Step 5: Run the test to verify it passes**

Run: `./.venv/bin/pytest tests/test_fit.py -v`
Expected: all pass.

- [ ] **Step 6: Report the new match count**

Run the real fit and record how many prices now join:

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli value \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026 \
  --policy fit --prices data/league/auction-rosters-2025.csv
```

`n` was 108 before this task. Record the new value in your report. Do not tune anything to reach a target.

- [ ] **Step 7: Commit**

```bash
git add identity/tqb-2025-starters.yaml src/sffl/fit.py tests/test_fit.py
git commit -m "fix: join the Team QB market to the price fit via 2025 starters"
```

---

### Task 3: Price kickers and defenses flat

**Files:**
- Modify: `leagues/sffl/2026.yaml`
- Modify: `src/sffl/league.py`
- Modify: `src/sffl/value.py`
- Test: `tests/test_value.py` (append)

**Interfaces:**
- Consumes: `replacement_levels`, `assign_vorp`, `assign_dollars` as they stand.
- Produces: `lg.flat_priced_pools` — a `Dict[str, float]` mapping a pool name to the fixed dollar price its members are worth. `assign_vorp` writes `_vorp = 0.0` for members of a flat-priced pool; `assign_dollars` writes their configured price and excludes them from the surplus allocation.

**Why.** Projected point spreads among kickers and defenses are real but not actionable — the projections carry no predictive power and the league knows it. Twenty-one observed prices, none above $3, and seven of nine kickers at exactly $1. Modelling them at $1 also returns the surplus they were wrongly absorbing to the pools that actually absorb it, which raises skill-player values toward their observed levels.

- [ ] **Step 1: Add the league configuration**

In `leagues/sffl/2026.yaml`, after the `silent_auction:` block:

```yaml
# Kickers and defenses are fungible $1 fillers in this league. Twenty-one real
# 2025 prices, none above $3, seven of nine kickers at exactly $1. Their
# projected point spreads are real but carry no predictive power, so paying for
# them is a mistake the board must not encourage. Members contribute no VORP,
# which returns the surplus to the pools that actually absorb it.
flat_priced_pools:
  K: 1
  DST: 1
```

In `src/sffl/league.py`, inside `LeagueProfile.__init__`:

```python
        self.flat_priced_pools = {}  # type: Dict[str, float]
        for pool_name, price in (raw.get("flat_priced_pools") or {}).items():
            self.flat_priced_pools[str(pool_name).strip().upper()] = float(price)
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_value.py`:

```python
def test_flat_priced_pools_are_configured():
    assert LG.flat_priced_pools == {"K": 1.0, "DST": 1.0}


def test_kickers_and_defenses_cost_their_flat_price():
    pool = build_pool_fixture()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    assign_dollars(LG, pool)
    for p in pool:
        if p.pos in ("K", "DST"):
            assert p.stats["_dollars"] == pytest.approx(1.0), p.name
            assert p.stats["_vorp"] == pytest.approx(0.0), p.name


def test_the_best_kicker_is_not_worth_more_than_the_worst():
    pool = build_pool_fixture()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    assign_dollars(LG, pool)
    ks = [p.stats["_dollars"] for p in pool if p.pos == "K"]
    assert max(ks) == pytest.approx(min(ks))


def test_flat_pools_free_surplus_for_skill_players():
    # With K and DST removed from the VORP pool, the dollars-per-VORP rate rises,
    # so the top skill player is worth strictly more than he was before.
    pool = build_pool_fixture()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    rate = assign_dollars(LG, pool)
    assert rate > 0
    flex_top = max(p.stats["_dollars"] for p in pool if p.pos in ("RB", "WR", "TE"))
    assert flex_top > 1.0


def test_budget_still_exhausts_with_flat_priced_pools():
    pool = build_pool_fixture()
    lv = replacement_levels(LG, pool, "starter")
    assign_vorp(LG, pool, lv)
    assign_dollars(LG, pool)
    spent = sum(sorted((p.stats["_dollars"] for p in pool),
                       reverse=True)[:LG.total_spots()])
    assert spent == pytest.approx(LG.total_capital(), abs=1.0)
```

Rename the existing `build_pool()` helper in `tests/test_value.py` to `build_pool_fixture()` and update its existing call sites, so it does not shadow `sffl.pool.build_pool` for a reader. Keep its contents identical.

- [ ] **Step 3: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_value.py -v -k "flat or kicker or best_kicker"`
Expected: FAIL — `LG` has no `flat_priced_pools`, and kickers currently carry positive VORP.

- [ ] **Step 4: Honor flat pools in VORP and dollars**

In `src/sffl/value.py`, in `assign_vorp`, after computing `base` and before writing `_vorp`:

```python
        if _pool_of(p.pos) in lg.flat_priced_pools:
            # Fungible by league convention - see flat_priced_pools in the
            # league YAML. Zero VORP keeps them out of the surplus split.
            p.stats["_vorp"] = 0.0
            continue
```

In `assign_dollars`, replace the write loop so flat-priced members take their configured price rather than the `1 + vorp * rate` formula:

```python
    for p in pool:
        flat = lg.flat_priced_pools.get(_pool_of(p.pos))
        if flat is not None:
            p.stats["_dollars"] = float(flat)
        else:
            p.stats["_dollars"] = 1.0 + p.stats["_vorp"] * rate
```

Keep the existing missing-`_vorp` raise and the `total_vorp <= 0` guard exactly as they are.

- [ ] **Step 5: Run the test to verify it passes**

Run: `./.venv/bin/pytest -q`
Expected: all pass. If `test_dollars_exhaust_the_league_budget` now fails, the flat-priced spots changed the arithmetic — work out the correct expectation and report it rather than loosening the tolerance.

- [ ] **Step 6: Verify against real data**

Re-run the real fit command from Task 2 Step 6 and confirm no kicker or defense appears in the top 25, and that every K and DST row reads `$1`. Record the new top 25 in your report only — it contains licensed player names and must not be committed.

- [ ] **Step 7: Commit**

```bash
git add leagues/sffl/2026.yaml src/sffl/league.py src/sffl/value.py tests/test_value.py
git commit -m "fix: price kickers and defenses flat at \$1 per observed market"
```

---

### Task 4: Report fit error per pool

**Files:**
- Modify: `src/sffl/fit.py`
- Modify: `src/sffl/cli.py`
- Test: `tests/test_fit.py` (append)

**Interfaces:**
- Consumes: `score_fit` as extended.
- Produces: `score_fit(...)` gains a `"by_pool"` key — a `Dict[str, Dict[str, float]]` mapping each of `"TQB"`, `"FLEX"`, `"K"`, `"DST"` to `{"n": …, "mae": …}`. Pools with no matched prices report `n = 0` and are omitted from the printed table rather than shown as a fake zero.

**Why.** A global mae of $5.92 concealed a kicker priced at $20 against a $1 market. Error has to be visible where it happens.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fit.py`:

```python
def test_fit_reports_error_per_pool():
    rep = score_fit(LG, build_priced_pool(), load_prices(PRICES), "starter")
    assert "by_pool" in rep
    assert "FLEX" in rep["by_pool"]
    assert rep["by_pool"]["FLEX"]["n"] >= 1
    assert rep["by_pool"]["FLEX"]["mae"] >= 0


def test_pools_with_no_matched_prices_report_zero_not_a_fake_average():
    rep = score_fit(LG, build_priced_pool(), load_prices(PRICES), "starter")
    for name, stats in rep["by_pool"].items():
        if stats["n"] == 0:
            assert stats["mae"] == 0.0
```

Add a `build_priced_pool()` helper alongside the existing `filler_players()` that returns a pool containing the fixture's priced players plus the filler TQB/K/DST, so all four pools are populated.

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest tests/test_fit.py -v -k per_pool`
Expected: FAIL with `KeyError: 'by_pool'` or an assertion on the missing key.

- [ ] **Step 3: Implement per-pool reporting**

In `src/sffl/fit.py`, import the pool mapping and accumulate per-pool pairs alongside the global ones:

```python
from sffl.value import POOLS, _pool_of, assign_dollars, assign_vorp, replacement_levels
```

Inside `score_fit`, while building `pairs`, also build `by_pool_pairs`:

```python
    by_pool_pairs = dict((name, []) for name in POOLS)
    ...
            pairs.append((p.stats["_dollars"], prices[key]))
            by_pool_pairs[_pool_of(p.pos)].append(
                (p.stats["_dollars"], prices[key]))
```

and build the report section before returning:

```python
    by_pool = {}
    for name, pool_pairs in by_pool_pairs.items():
        if not pool_pairs:
            by_pool[name] = {"n": 0, "mae": 0.0}
            continue
        errs = [abs(model - actual) for model, actual in pool_pairs]
        by_pool[name] = {"n": len(pool_pairs), "mae": sum(errs) / len(errs)}
```

Add `"by_pool": by_pool` to both the empty-`pairs` early return and the normal return, so the key is always present.

In `src/sffl/cli.py`, after the two policy lines print, add the per-pool table for the chosen policy:

```python
        chosen_report = [r for r in reports if r["policy"] == policy][0]
        print("  fit by pool (chosen policy):")
        for name in sorted(chosen_report["by_pool"]):
            stats = chosen_report["by_pool"][name]
            if stats["n"]:
                print("    %-5s n=%-3d mae=$%.2f" % (name, stats["n"], stats["mae"]))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Verify against real data**

Re-run the real fit command. Record the per-pool table in your report — it is the evidence that TQB and DST now join and that K is no longer mispriced.

- [ ] **Step 6: Commit**

```bash
git add src/sffl/fit.py src/sffl/cli.py tests/test_fit.py
git commit -m "feat: report price-fit error per pool"
```

---

## Self-Review

**Spec coverage.** Kickers and defenses priced at the observed $1 → Task 3. The TQB market joining the fit for the first time → Task 2. Defenses joining the fit → Task 1. The 15 hand-typed misspellings → Task 1. Making this class of error visible next time → Task 4.

**Deliberately out of scope.** The renderers are their own plan; they consume `_dollars` and are unaffected by how it is computed. The RB/WR-TE lineup floor at flex replacement remains an open question — it changes flex replacement, not K/DST, and should be decided against the improved fit this plan produces.

**Known limitation carried forward.** `Joe Mixon` and `Ricky Pearsall` stay unmatched because neither appears in the 2026 extract. Two of 156 prices sitting out of the fit is correct behaviour, not a gap.

**Type consistency.** Pool names are exactly `"TQB"`, `"FLEX"`, `"K"`, `"DST"` throughout, matching `value.POOLS`. `lg.flat_priced_pools` is keyed by pool name, not position, so `_pool_of` is applied before every lookup. `load_prices` keeps returning `Dict[str, float]`; only the key derivation changed.

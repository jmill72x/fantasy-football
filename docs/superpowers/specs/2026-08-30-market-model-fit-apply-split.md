# Separate Fitting From Applying: a Persisted Market Model — Design

**Date:** 2026-08-30
**Status:** proposed

## The problem, restated precisely

`--policy fit` and the EST$ curve both need OBSERVED AUCTION PRICES. Before auction
night 2027 there is no 2027 price file. So the pre-auction 2027 run must reach for 2026
prices — and the guard that exists to prevent cross-season contamination makes that
impossible to do honestly:

- Pass the **2026** TQB starter map (correct for 2026 prices) → the guard REFUSES, because
  the map's season does not match `--year 2027`.
- Pass the **2027** map → the guard passes, and you get a silent cross-season fit: the
  artifact-era curve returns (`b = 0.531` against the year-matched truth of `0.662`) and
  TQB joins degrade 21 → 15, with no error and every number looking plausible.

**A year-matched EST$ is therefore only computable AFTER the auction it was meant to
inform.** That is the deadlock.

Three verified holes underneath it:

1. **The prices CSV carries no season metadata at all.** The TQB map is only a PROXY for
   the prices' season, so mismatched prices with a matched map pass silently. This is
   byte-for-byte the configuration that manufactured the phantom +$13.2 top-end bias.
2. **A starter map with no `season:` key skips the guard entirely** (`_map_season is None`).
3. **The guard exists only in `cli._value_pool`.** Direct `fit.load_prices` callers get
   `DEFAULT_TQB_STARTERS` — the 2025 map — forever, unchecked.

## The insight

Fitting and applying are two different operations that have been fused into one command,
and only fitting is season-bound.

**Fitting** asks: *how does this room convert model value into dollars?* It needs
year-matched prices and projections, and it can only be done after an auction.

**Applying** asks: *given that model of the room, what will this player cost?* It needs
only a curve and this year's projections.

What you actually want in 2027 is **last year's model of how this room behaves**, applied
to 2027 projections. That is not a compromise forced by missing data — it is the correct
thing to want. The room's behaviour is a property of the twelve people in it, which
persists across seasons far better than any individual player's value does.

Once the two are separated, the guard becomes honest and easy: **refuse a cross-season
FIT; permit a cross-season APPLY, and say loudly which curve is in use and from when.**

## Decisions I am making

Three calls beyond what `NEXT.md` specified. Each is stated so it can be vetoed.

### Decision 1 — persist the CHOSEN REPLACEMENT POLICY too, not just the curve

`NEXT.md` says "persist the coefficients." But `--prices` feeds TWO consumers: the market
curve AND `choose_policy`, which picks `starter` vs `draftable` replacement levels. Both
hit the same deadlock. Persisting only the curve would fix half the problem and leave
`--policy fit` still demanding a 2027 price file that does not exist.

So the artifact is a **market model**, not a curve: the fitted coefficients, the chosen
replacement policy, and the evidence behind both.

### Decision 2 — add a `season` column to the prices CSV, and verify it

Hole 1 exists because the CSV cannot say what season it is. That is fixable: it is our own
file. `load_prices` gains an optional expected-season argument; when the CSV carries a
`season` column it is VERIFIED, and a mismatch raises. Files without the column keep
working (the existing 2025 and 2026 files), but a run against a column-less file says so,
so the silence is visible rather than assumed.

This is the only change that closes hole 1 properly. The TQB map will always be a proxy;
the prices file stating its own season is direct evidence.

### Decision 3 — the guard moves INTO `fit.load_prices`

Hole 3 is that the guard lives in the CLI. Any other caller — a notebook, a poc script, a
future second league — bypasses it. The check belongs with the loading, where it cannot be
skipped by reaching for the function directly.

## The artifact

`market/2026.yaml`, written once after the 2026 auction, read every pre-auction run after:

```yaml
season: 2026                    # the season these prices came from
fitted_on: "2026-08-30"
curve:
  a: 2.05                       # price = a * dollars ** b
  b: 0.662
policy: starter                 # the replacement policy chosen from these prices
evidence:
  prices_file: data/league/auction-rosters-2026.csv
  prices_rows: 156
  observations: 130             # after excluding flat-priced K/DST
  projections_source: draftsharks
  projections_year: 2026
  tqb_starters: identity/tqb-2026-starters.yaml
diagnostics:                    # recorded, never re-derived
  mae: 6.31
  top10_mae: 5.10
  top10_bias: 5.10
```

**`evidence` and `diagnostics` are not decoration.** The failure this whole change exists
to prevent was invisible precisely because nothing recorded what had been fitted against
what. An artifact that cannot answer "which prices, which projections, how many
observations" would reproduce the original problem in a new place.

## What the commands become

- **`sffl fit-market`** — NEW. Fits and writes the artifact. Requires year-matched prices,
  map, and projections. Refuses any cross-season combination it can detect.
- **`sffl value` / `sffl render`** — gain `--market <artifact>`. Applies a persisted curve
  and policy. A cross-season apply is PERMITTED and ANNOUNCED:
  `using the 2026 market model (a=2.05, b=0.662, n=130, fitted 2026-08-30)`.
- **`--prices` keeps working exactly as today** for a same-season run. Nothing about the
  2026 workflow changes.
- **`--market` and `--prices` together is refused**, naming both — that is the operator
  asking to fit and apply at once, which is the confusion this split exists to end.

## Rules

- **A cross-season FIT is refused.** Year, TQB map season, and (when present) the prices
  CSV's own season column must all agree.
- **A cross-season APPLY is permitted and announced**, every run, in the output and on the
  workbook's intel page. A curve silently older than the board it prices is the failure
  mode being designed out.
- **A starter map with no `season:` key is refused for a FIT.** Not a warning; the whole
  point is that a missing key currently skips the check.
- **The artifact is never silently regenerated.** `fit-market` refuses to overwrite an
  existing file without an explicit flag, so a stray run cannot quietly replace the
  evidence a board was priced from.
- **Nothing about the 2026 board changes.** The curve fitted from 2026 prices, applied to
  2026 projections, must produce byte-identical output to today's `--prices` path. That is
  the regression test.

## Out of scope

- **Re-weighting the fit's tail.** `market.py` records why the tempting reweighting was
  NOT adopted — it was tuned against the artifact-era bias that year-matched measurement
  says does not exist. Unchanged here.
- **Position-specific curves.** One curve, applied globally, as today.
- **The `top10_cost` gaming hole** (no spread or ordering term). Harmless while the
  policies are `starter` and `draftable`; a separate decision.

## Testing

- **The regression that matters:** fit from 2026 prices → persist → apply → assert the
  board is identical to today's single-step `--prices` path. If that does not hold, the
  split changed the numbers, and the split is supposed to change only WHEN the fit happens.
- Each of the three holes gets a test that FAILS without its fix: mismatched prices with a
  matched map; a map with no `season:` key; a direct `load_prices` call bypassing the CLI.
- A cross-season apply announces itself, and the announcement names the artifact's season.
- `fit-market` refuses to overwrite without the explicit flag.

## The separate, smaller item

`tests/test_fit.py` pins starter `top10_bias = -0.25`. **The real value is +5.10** — the
-0.25 belongs to the $26+ band of a different table. The decision the tests pin is correct
either way, so no board is wrong; but a green test asserting starter's top-10 is unbiased
when it over-prices by $5.10 is this codebase's signature failure in miniature. Fix the
numbers against a real run, or drop them. Folded into this work because the `fit-market`
command computes exactly these diagnostics and must record them correctly in the artifact.

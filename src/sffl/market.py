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

One curve is fit globally and applied to every position alike; it cannot
correct a position-specific bias such as TQB's (mae $8.98, worst of any pool -
see NEXT.md), only the board-wide top-heavy/bottom-light shape.

THE CURVE ALSO COMPRESSES THE TOP END'S RANGE, NOT JUST ITS LEVEL. b < 1 makes
the fit concave, so a wide spread of input dollars maps to a narrower spread of
output prices, and the compression is worst exactly where the inputs are most
spread out - the top of the board. On the 2025 fit (a=2.248, b=0.551, fit on
130 observations with flat-priced K/DST excluded - see below), the $30+ band's
*average* bias is an excellent -$0.9, but the individual estimates inside that
band span only ~$23-31 while 2025's actual top prices ranged roughly $28-43:
the single most expensive player still comes in well under what a real top
pick has fetched. Averaging over a band hides this - do not read "$30+ band
bias is small" as "every player in it is well estimated."

Two structural causes, both left as-is rather than fixed here:
  1. The fit weights every observation equally in log space, and 52% (68 of
     130, after excluding flat-priced K/DST) of the real 2025 prices sit in
     the $1-2 band, so ordinary least squares is dominated by getting the
     cheap end right, not the expensive end.
  2. A single smooth monotone curve fundamentally cannot map a wide input
     spread to an equally wide output spread while also being well-behaved
     near the $1 floor; something has to give, and it is the top.
Reweighting the tail is a cheap change, not a rewrite - roughly four lines,
adding weights inside the four closed-form sums `fit_price_curve` already
computes. In-sample checks against the 130 skill observations back that up:
weighting by model dollars (b=0.653) or fitting only on model $>=5 (b=0.720)
both cut MAE at the top (paid>=$25) AND the bottom (paid<=$3) versus the
shipped unweighted OLS - a Pareto improvement, not a trade-off, so the
compression is a property of unweighted OLS on floor-heavy data, not of the
power-law form itself. It is deliberately NOT changed here anyway: that
evidence is in-sample, single-year (2026 projections against 2025 prices),
and this fit is three weeks from pricing a real auction - not enough runway
to trust an unvalidated reweighting over the shipped fit. Revisit with
out-of-sample evidence (a second season of prices) before switching. A
bidder budgeting for a single specific top target should treat EST$ as a
floor on that player's price, not a point estimate.

THE FIT'S INPUT EXCLUDES FLAT-PRICED POOLS (K, DST). Their `_dollars` is
pinned to the league's flat price by policy (see `LeagueProfile.
flat_priced_pools`), not derived from VORP, so every one of them would
contribute a point at x = log(1) = 0 that looks like market evidence about
cheap players but is really just the flat-pricing policy restated. Their
`_est_price` is unaffected by this either way, since `assign_expected_prices`
applies the same flat override to them regardless of which curve was fit.
"""

import math
from typing import Dict

from sffl.value import _pool_of, _starter_counts

# Below this, an OLS fit of a two-parameter curve (a, b) has too few residual
# degrees of freedom to trust - it is barely more than interpolation, and one
# misjoined price can swing both parameters through the exponent. Production
# has 154 real prices available, so this costs nothing operationally.
MIN_OBSERVATIONS = 8


def fit_price_curve(pairs):
    """Least-squares fit of price = a * dollars**b, in log space.

    `pairs` is [(model_dollars, observed_price), ...]. Both sides are always
    >= 1 on real data, so no log of zero or a negative arises - but a bad
    join or a $0 in the roster CSV can still hand this a non-positive value,
    and `math.log` on that raises an opaque "math domain error" that reads
    as a math bug rather than the data problem it is. Check explicitly and
    name the offending pair, so a $0 price is reported as a data-integrity
    problem, not silently downgraded to a "curve not fitted" small-sample
    warning by the caller's except ValueError.
    """
    if len(pairs) < MIN_OBSERVATIONS:
        raise ValueError(
            "need at least %d observations to fit a price curve, got %d"
            % (MIN_OBSERVATIONS, len(pairs)))

    bad = [(m, a) for m, a in pairs if float(m) <= 0.0 or float(a) <= 0.0]
    if bad:
        raise ValueError(
            "model dollars and observed prices must both be positive; got "
            "non-positive pair(s) %s - check the source data for a $0 or "
            "negative value" % bad[:3])

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

    # dollars is always >= 1 and the curve is increasing (b > 0), so the
    # lowest raw value the curve ever produces, across its whole domain of
    # application, is at dollars == 1: a * 1**b == a. An intercept below $1
    # would clamp every player near the low end to an identical floored raw
    # value of exactly $1, silently destroying strict ordering among them.
    if a < 1.0:
        raise ValueError(
            "fitted intercept a=%.4f is below the $1 floor: the curve's "
            "lowest raw value (at dollars=1) would already clamp to the "
            "floor, collapsing distinct low-dollar players to an identical "
            "estimate. Check the observed prices for a bid near $1 that is "
            "pulling the intercept down." % a)
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

    Flat-priced pools (K, DST) never touch the curve - they are pinned to
    their configured flat price ($1) regardless of what k turns out to be,
    and they never contribute surplus. The curve, on the other hand, floors
    every NON-flat player's raw estimate at `a`, the fitted intercept, which
    `fit_price_curve` guarantees is strictly greater than $1. That means a
    flat player's raw value ($1) is never tied with, let alone above, a
    non-flat player's raw value (> $1) - so a plain "top total_spots() by
    raw value" selects only non-flat players once the non-flat pool is at
    least total_spots() deep, and silently drops every flat roster spot out
    of the surplus base even though the league fills flat_spots of them
    every year (one K and one DST per team).

    Reserve those flat_spots first - the sum of the per-pool starter counts
    for every pool in `lg.flat_priced_pools` - then distribute k over the
    top `total_spots() - flat_spots` NON-FLAT raw estimates: that smaller
    set is the actual surplus base once the flat spots the league always
    fills are accounted for.
    """
    missing = [p.name for p in pool if "_dollars" not in p.stats]
    if missing:
        raise ValueError(
            "%d player(s) have no '_dollars'; call value.assign_dollars first "
            "(e.g. %s)" % (len(missing), ", ".join(sorted(missing)[:3])))

    starters = _starter_counts(lg)
    flat_spots = sum(starters[name] for name in lg.flat_priced_pools)
    surplus_spots = lg.total_spots() - flat_spots

    raw = {}  # type: Dict[int, float]
    for p in pool:
        flat = lg.flat_priced_pools.get(_pool_of(p.pos))
        if flat is None:
            raw[id(p)] = expected_price(curve, p.stats["_dollars"])

    top = sorted(raw.values(), reverse=True)[:surplus_spots]
    surplus_raw = sum(v - 1.0 for v in top)
    if surplus_raw <= 0:
        raise ValueError(
            "the top %d non-flat raw estimates sum to no surplus above the "
            "$1 floor (surplus_raw=%.4f); the board cannot be renormalised "
            "to total_capital() because there is nothing above the floor to "
            "scale. Check the curve and the pool's _dollars values."
            % (surplus_spots, surplus_raw))
    k = lg.surplus() / surplus_raw

    for p in pool:
        flat = lg.flat_priced_pools.get(_pool_of(p.pos))
        if flat is not None:
            p.stats["_est_price"] = float(flat)
        else:
            p.stats["_est_price"] = 1.0 + k * (raw[id(p)] - 1.0)
    return k

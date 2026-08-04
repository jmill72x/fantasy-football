"""Choose the replacement-level policy by fitting against real auction prices.

The league paid 156 real prices in 2025. Rather than picking a policy by
preference, score both against what actually happened and report the error so a
poor fit is visible.

Name reconciliation happens at price-load time: `load_prices` maps each
hand-typed roster name through `identity/aliases.yaml` (via `sffl.identity.
Resolver`) before it becomes a lookup key, so `score_fit`/`choose_policy` only
ever compare already-canonical names and need no resolver of their own.
"""

import csv
from typing import Dict

from sffl.identity import Resolver, normalize_name
from sffl.value import assign_dollars, assign_vorp, replacement_levels

POLICIES = ("starter", "draftable")

DEFAULT_ALIASES = "identity/aliases.yaml"


def load_prices(path, alias_path=DEFAULT_ALIASES):
    """Map canonicalized player name -> price paid.

    The roster sheet is hand-typed and misspells names (e.g. "JAMAAR CHASE"
    for Ja'Marr Chase). Each name is normalized, then passed through the
    alias table so it lands on the same key the pool's canonical spelling
    normalizes to.
    """
    aliases = Resolver(alias_path).aliases
    out = {}  # type: Dict[str, float]
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            normalized = normalize_name(row["player_as_written"])
            if normalized:
                name = aliases.get(normalized, normalized)
                out[name] = float(row["price"])
    return out


def score_fit(lg, pool, prices, policy):
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


def choose_policy(lg, pool, prices):
    """Return the policy with the lower top-10 error, plus both reports.

    Top-10 error is the tiebreaker rather than overall error because the
    expensive players are where a mispriced board actually costs money.

    Side effect: this calls score_fit twice, and score_fit mutates the pool
    in place (assign_vorp/assign_dollars overwrite stats['_vorp'] and
    stats['_dollars']). The pool is left carrying the *second* policy's
    numbers regardless of which policy wins - do not read _vorp/_dollars off
    the pool after calling this and assume they belong to `best`. Re-run the
    valuation with the chosen policy if you need the pool's state to match it.

    Raises ValueError if neither policy matched a single observed price. Both
    reports would otherwise tie on (n=0, top10_mae=inf, mae=inf), and picking
    a "winner" from that tie is picking with no evidence at all - the wrong
    kind of silent failure for a pipeline whose whole point is not guessing.
    """
    reports = [score_fit(lg, pool, prices, p) for p in POLICIES]
    if all(r["n"] == 0 for r in reports):
        raise ValueError(
            "no pool player matched any observed price (pool has %d players, "
            "%d prices loaded); this policy choice has zero evidence behind it. "
            "Check whether %s needs a new entry for a misspelled or renamed "
            "player." % (len(pool), len(prices), DEFAULT_ALIASES))
    best = min(reports, key=lambda r: (r["top10_mae"], r["mae"]))
    return best["policy"], reports

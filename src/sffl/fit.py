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
import warnings
from typing import Dict

import yaml

from sffl.identity import NFL_TEAMS, Resolver, normalize_name
from sffl.value import POOLS, _pool_of, assign_dollars, assign_vorp, replacement_levels

POLICIES = ("starter", "draftable")

DEFAULT_ALIASES = "identity/aliases.yaml"
DEFAULT_TQB_STARTERS = "identity/tqb-2025-starters.yaml"


class SeasonMismatchError(ValueError):
    """Raised only by load_prices's own season guard - see its docstring.

    A `ValueError` subclass rather than a plain `ValueError` so a caller (the
    CLI) can convert exactly the guard's own failures into a clean
    single-line message without also swallowing an unrelated `ValueError` -
    an alias chain, a bad franchise code, a malformed price cell - raised
    from elsewhere in the same function, which deserves its traceback rather
    than being flattened to a single line that cannot locate the offending
    row.
    """


class UnverifiedPricesSeasonWarning(UserWarning):
    """The prices file carries no `season` column, so its season is UNVERIFIED.

    Not an error: the two prices files that predate the column
    (`data/league/auction-rosters-2025.csv`) must keep working. But the
    verification half of Decision 2 shipped without its announcement half,
    and a guard that cannot fire and says nothing is indistinguishable from
    a guard that passed. This is the "says so" - see `load_prices`.
    """


def unverified_season_message(path, season, tqb_starters_path):
    """The one wording for "this file's season could not be verified".

    Kept here, beside the guard that raises it, so the library warning and
    the CLI's printed NOTE cannot drift into saying two different things
    about the same run.
    """
    return (
        "%s carries no 'season' column, so THIS RUN CANNOT VERIFY that these "
        "prices are from %d. The season is being taken on trust from the Team "
        "QB starter map (%s), which is only a PROXY for it - the two are "
        "independent facts and only one of them was checkable here. Pairing "
        "one season's prices with another season's projections is exactly the "
        "error that fitted price = 2.443 * value^0.531 against a year-matched "
        "truth of 0.662, degraded Team QB joins from 21 to 15, and "
        "manufactured a phantom top-end bias, with every number looking "
        "plausible. Add a 'season' column to %s to make this verifiable."
        % (path, season, tqb_starters_path, path))


class PriceMap(dict):
    """dict[canonical name -> price] that also remembers how many rows the
    source CSV held, so a caller can report "n matched of N loaded" instead
    of a bare match count with no denominator. Behaves exactly like a plain
    dict everywhere else (iteration, `in`, `.get`, `len`, equality with a
    plain dict) - only `.total_rows` is new.
    """

    def __init__(self, *args, **kwargs):
        super(PriceMap, self).__init__(*args, **kwargs)
        self.total_rows = 0


def tqb_starters_season(path):
    """The season a Team QB starter map describes, or None if it says nothing.

    Exists so a caller that knows which season it is valuing can refuse a map
    from another one. Quarterbacks change franchises between Augusts - Kyler
    Murray was ARI in 2025 and MIN in 2026 - so the wrong map does not fail
    loudly, it silently mis-joins or drops every Team QB price.
    """
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    season = raw.get("season")
    return int(season) if season is not None else None


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


def _load_tqb_starters(path):
    """Map normalized quarterback name -> franchise code for one season.

    Raises ValueError on any right-hand side that is not a real NFL franchise
    code (per `sffl.identity.NFL_TEAMS`) - a typo like "PHIL" would otherwise
    join nothing and silently drop a TQB price from the fit with no signal.
    """
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    out = {}
    for qb, team in (raw.get("starters") or {}).items():
        code = str(team).strip().upper()
        if code not in NFL_TEAMS:
            raise ValueError(
                "%s maps %r to %r, which is not a real NFL franchise code; "
                "expected one of %s" % (path, qb, team, sorted(NFL_TEAMS)))
        out[normalize_name(qb)] = code
    return out


def load_prices(path, alias_path=DEFAULT_ALIASES,
                tqb_starters_path=DEFAULT_TQB_STARTERS, season=None,
                require_file_season=False):
    """Map canonical player key -> price paid.

    Three reconciliations, in order, because the roster sheet is hand typed:
      1. normalize spelling
      2. apply identity/aliases.yaml - fixes misspellings and the "PHILLY D" form
      3. apply the season's TQB starter map - the sheet names a Team QB unit by
         whoever started for that franchise, but the pool names it by franchise

    A franchise may appear twice when one roster carried a backup Team QB. The
    higher price wins: it is the one that reflects the unit's market value, and
    silently keeping whichever came last would depend on file order.

    `tqb_starters_path` defaults to the 2025 map and MUST be overridden with a
    season-matched map for any other season's prices file - see the
    `--tqb-starters` CLI flag. Applying the 2025 map to a later roster sheet
    would silently mis-join or silently drop every Team QB price.

    `season`, when given, asserts which season this call believes it is
    loading - see the guard below. When omitted, no season check runs at all;
    a caller that genuinely does not know the season (a poc script exploring
    an unknown file) is not forced to assert one.

    `require_file_season` turns "this file cannot state its own season" from a
    warning into a refusal. `sffl fit-market` sets it, and nothing else does -
    see the guard below for why the two callers differ.

    Returns a `PriceMap` (a `dict` subclass); `.total_rows` on the result is
    the number of priced rows read from `path`, independent of how many of
    them ended up matching a pool player.
    """
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
            raise SeasonMismatchError(
                "%s carries no 'season:' key, so it cannot be checked against "
                "the %d prices being loaded. A map with no season used to skip "
                "this check entirely - which is exactly how the wrong map goes "
                "unnoticed, since it does not fail loudly, it silently "
                "mis-joins or drops every Team QB price. Add 'season: <year>' "
                "to the map." % (tqb_starters_path, season))
        if map_season != season:
            raise SeasonMismatchError(
                "refusing to load %d prices with the %d Team QB starter map "
                "(%s). Quarterbacks change franchises between Augusts, so the "
                "wrong map silently mis-joins or drops every Team QB price."
                % (season, map_season, tqb_starters_path))
        file_season = prices_season(path)
        if file_season is None:
            # THE ANNOUNCEMENT HALF OF DECISION 2. Verification shipped
            # without it, so a column-less file simply skipped the check in
            # silence - and the whole point of the decision was that "the
            # silence is visible rather than assumed". A guard that cannot
            # fire must say that it could not fire, or the operator reads
            # its absence as a pass.
            #
            # REFUSED for a FIT, warned about everywhere else. A fit bakes
            # the pairing into a persisted artifact that later seasons trust
            # and never re-derive, and the only files `fit-market` can
            # legitimately be pointed at are ours, which can carry the
            # column. A `value`/`render` run reprices one board, in front of
            # an operator who is reading this warning, and must keep working
            # against the pre-column 2025 file.
            if require_file_season:
                raise SeasonMismatchError(
                    "refusing to FIT from %s: it carries no 'season' column, "
                    "so nothing here can verify that these prices are from "
                    "%d - the Team QB starter map (%s) is only a proxy for "
                    "it. A fit is persisted and trusted by later seasons "
                    "that will never re-derive it, so an unverifiable "
                    "pairing must not be baked into one. Add a 'season' "
                    "column to %s (the 2026 file has one), or fit from a "
                    "file that has it."
                    % (path, season, tqb_starters_path, path))
            warnings.warn(
                unverified_season_message(path, season, tqb_starters_path),
                UnverifiedPricesSeasonWarning, stacklevel=2)
        elif file_season != season:
            raise SeasonMismatchError(
                "%s declares season %d but %d was asserted. The prices file's "
                "own season column is direct evidence, unlike the TQB map "
                "which is only a proxy - this is the mismatch that used to "
                "pass silently and refit the artifact-era curve."
                % (path, file_season, season))

    aliases = Resolver(alias_path).aliases
    starters = _load_tqb_starters(tqb_starters_path)
    out = PriceMap()
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            name = normalize_name(row["player_as_written"])
            if not name:
                continue
            out.total_rows += 1
            name = aliases.get(name, name)
            if name in aliases:
                raise ValueError("alias chain in %s: %r -> %r (chains prevent non-transitive lookup; resolve to final spelling instead)" % (alias_path, row["player_as_written"], name))
            team = starters.get(name)
            if team is not None:
                name = normalize_name(team)
            price = float(row["price"])
            if name in out:
                out[name] = max(out[name], price)
            else:
                out[name] = price
    return out


def score_fit(lg, pool, prices, policy):
    """Value the pool under `policy` and compare to observed prices."""
    if policy not in POLICIES:
        raise ValueError("unknown replacement policy %r" % policy)

    levels = replacement_levels(lg, pool, policy)
    assign_vorp(lg, pool, levels)
    assign_dollars(lg, pool)

    pairs = []
    by_pool_pairs = dict((name, []) for name in POOLS)
    for p in pool:
        key = normalize_name(p.name)
        if key in prices:
            pairs.append((p.stats["_dollars"], prices[key]))
            by_pool_pairs[_pool_of(p.pos)].append(
                (p.stats["_dollars"], prices[key]))

    by_pool = {}
    for name, pool_pairs in by_pool_pairs.items():
        if not pool_pairs:
            by_pool[name] = {"n": 0, "mae": 0.0}
            continue
        errs = [abs(model - actual) for model, actual in pool_pairs]
        by_pool[name] = {"n": len(pool_pairs), "mae": sum(errs) / len(errs)}

    if not pairs:
        return {"policy": policy, "n": 0, "mae": float("inf"),
                "rmse": float("inf"), "top10_mae": float("inf"),
                "top10_bias": float("inf"), "by_pool": by_pool}

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
        # SIGNED, unlike top10_mae. Separates "wrong in both directions" from
        # "wrong in one direction" at the top of the board, which top10_mae
        # cannot distinguish and which choose_policy must - see its docstring.
        "top10_bias": sum(m - a for m, a in top) / len(top),
        "by_pool": by_pool,
    }


def top10_cost(report):
    """Rank policies by top-10 error with systematic error counted twice.

    WHY NOT top10_mae ALONE. It was, until the 2026 prices arrived and showed
    what it cannot see. Measured year-matched against them, `draftable` beat
    `starter` on top10_mae ($9.08 against $10.06) while being far worse in the
    only way that matters: its top-10 error was ENTIRELY systematic - mae
    $10.34 against bias -$10.34, meaning all sixteen round-one players were
    under-priced by about $10 apiece. `starter` had a larger spread around a
    bias of -$0.25.

    Those are not equally bad. Noise averages out across thirteen roster spots;
    a policy that under-prices every expensive player by $10 loses every one of
    them, and no amount of drafting skill recovers that. So bias is added to
    mae: it is already inside mae once, and this counts it again. Pure noise is
    charged once, pure bias twice.
    """
    return report["top10_mae"] + abs(report["top10_bias"])


def choose_policy(lg, pool, prices):
    """Return the policy with the lower bias-penalised top-10 error.

    Top-10 error decides rather than overall error because the expensive
    players are where a mispriced board actually costs money, and it is
    penalised for systematic bias - see `top10_cost`.

    Side effect: this calls score_fit twice, and score_fit mutates the pool
    in place (assign_vorp/assign_dollars overwrite stats['_vorp'] and
    stats['_dollars']). The pool is left carrying the *second* policy's
    numbers regardless of which policy wins - do not read _vorp/_dollars off
    the pool after calling this and assume they belong to `best`. Re-run the
    valuation with the chosen policy if you need the pool's state to match it.

    Raises ValueError if neither policy matched a single observed price. Both
    reports would otherwise tie on (n=0, top10_cost=inf, mae=inf), and picking
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
    best = min(reports, key=lambda r: (top10_cost(r), r["mae"]))
    return best["policy"], reports

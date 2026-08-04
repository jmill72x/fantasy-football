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
    pairs = [(d, 2.0 * d ** 0.5)
             for d in (1.0, 4.0, 9.0, 16.0, 25.0, 36.0, 49.0, 64.0)]
    a, b = fit_price_curve(pairs)
    assert a == pytest.approx(2.0, rel=1e-6)
    assert b == pytest.approx(0.5, rel=1e-6)


def test_fit_finds_compression_in_biased_data():
    # model overpays the top and underpays the bottom, like the real board
    pairs = [(1.0, 3.6), (2.0, 5.0), (3.5, 7.8), (8.8, 13.0), (14.7, 14.3),
             (22.9, 15.5), (40.1, 26.9), (50.0, 30.0)]
    a, b = fit_price_curve(pairs)
    assert 0.0 < b < 1.0, "expected compression, got exponent %r" % b


# Shared 8-observation curve for expected_price and the assign_expected_prices
# tests below - any valid 8-point curve works for these, so one is reused.
COMPRESSION_PAIRS = [(1.0, 3.6), (5.0, 9.0), (10.0, 12.0), (14.0, 14.0),
                     (18.0, 15.0), (25.0, 17.0), (32.0, 22.0), (40.0, 27.0)]


def test_expected_price_is_monotone_and_floored_at_one_dollar():
    curve = fit_price_curve(COMPRESSION_PAIRS)
    assert expected_price(curve, 1.0) >= 1.0
    assert expected_price(curve, 5.0) < expected_price(curve, 20.0)


def test_too_few_observations_raises():
    with pytest.raises(ValueError) as e:
        fit_price_curve([(1.0, 2.0), (3.0, 4.0)])
    assert "observation" in str(e.value).lower()


def test_a_curve_that_would_price_better_players_lower_raises():
    # deliberately inverted data - a real market never does this
    pairs = [(1.0, 40.0), (3.0, 35.0), (5.0, 30.0), (10.0, 20.0),
             (20.0, 10.0), (25.0, 7.0), (30.0, 5.0), (40.0, 2.0)]
    with pytest.raises(ValueError) as e:
        fit_price_curve(pairs)
    assert "monoton" in str(e.value).lower()


def test_identical_model_values_cannot_be_fitted():
    with pytest.raises(ValueError):
        fit_price_curve([(5.0, 2.0)] * 8)


def test_fit_below_minimum_observations_raises_even_with_valid_shape():
    # 7 clean, monotone points - one short of MIN_OBSERVATIONS - must still
    # raise on count, not attempt the fit.
    pairs = [(d, 2.0 * d ** 0.5) for d in (1.0, 4.0, 9.0, 16.0, 25.0, 36.0, 49.0)]
    with pytest.raises(ValueError) as e:
        fit_price_curve(pairs)
    assert "observation" in str(e.value).lower()


def test_intercept_below_one_dollar_raises():
    # Mostly flat near $1 with a late jump: the OLS line's value at
    # dollars=1 (the intercept, a) lands below $1 even though every
    # observed price is >= 1 and the curve is still increasing (b > 0).
    pairs = [(1.0, 1.0), (2.0, 1.0), (4.0, 1.0), (8.0, 1.0),
             (16.0, 1.0), (32.0, 1.0), (64.0, 3.0), (128.0, 9.0)]
    with pytest.raises(ValueError) as e:
        fit_price_curve(pairs)
    assert "floor" in str(e.value).lower()


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
    curve = fit_price_curve(COMPRESSION_PAIRS)
    assign_expected_prices(LG, pool, curve)
    spent = sum(sorted((p.stats["_est_price"] for p in pool),
                       reverse=True)[:LG.total_spots()])
    assert spent == pytest.approx(LG.total_capital(), abs=1.0)


def test_flat_priced_pools_keep_their_flat_price():
    pool = build_board()
    curve = fit_price_curve(COMPRESSION_PAIRS)
    assign_expected_prices(LG, pool, curve)
    for p in pool:
        if p.pos in ("K", "DST"):
            assert p.stats["_est_price"] == pytest.approx(1.0), p.name


def test_every_estimate_is_at_least_a_dollar():
    pool = build_board()
    curve = fit_price_curve(COMPRESSION_PAIRS)
    assign_expected_prices(LG, pool, curve)
    assert all(p.stats["_est_price"] >= 1.0 for p in pool)


def test_estimates_preserve_the_models_ordering():
    pool = build_board()
    curve = fit_price_curve(COMPRESSION_PAIRS)
    assign_expected_prices(LG, pool, curve)
    flex = [p for p in pool if p.pos in ("RB", "WR", "TE")]
    flex.sort(key=lambda p: -p.stats["_dollars"])
    ests = [p.stats["_est_price"] for p in flex]
    assert ests == sorted(ests, reverse=True)


def test_missing_dollars_raises_rather_than_defaulting():
    pool = build_board()
    del pool[0].stats["_dollars"]
    curve = fit_price_curve(COMPRESSION_PAIRS)
    with pytest.raises(ValueError) as e:
        assign_expected_prices(LG, pool, curve)
    assert "_dollars" in str(e.value)


class _AllFlatLeague(object):
    """Degenerate league stub where every pool is flat-priced.

    Exists only to force every top-`total_spots()` raw estimate to exactly
    $1 (so surplus_raw == 0) without depending on floating-point-exact
    equality out of an OLS fit. `assign_expected_prices` only needs
    `flat_priced_pools`, `total_capital()`, `total_spots()` and `surplus()`
    - see the "Interfaces you depend on" contract in the task brief.
    """
    flat_priced_pools = {"TQB": 1.0, "FLEX": 1.0, "K": 1.0, "DST": 1.0}

    def total_capital(self):
        return 30.0

    def total_spots(self):
        return 5

    def surplus(self):
        return 25.0


def test_no_surplus_to_distribute_raises():
    lg = _AllFlatLeague()
    pool = [player("p%d" % i, "RB", 10.0 + i) for i in range(5)]
    curve = fit_price_curve(COMPRESSION_PAIRS)  # unused: every pool is flat
    with pytest.raises(ValueError) as e:
        assign_expected_prices(lg, pool, curve)
    assert "surplus" in str(e.value).lower()

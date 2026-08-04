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

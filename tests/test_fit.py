import pytest

from sffl.fit import load_prices, score_fit, choose_policy
from sffl.league import load_league
from sffl.schema import PlayerProjection

LG = load_league("leagues/sffl/2026.yaml")
PRICES = "tests/fixtures/prices_sample.csv"


def player(name, pos, pts):
    return PlayerProjection(name=name, team="XXX", pos=pos, source="t",
                            source_year=2026, games=17,
                            stats={"_season_points": float(pts)}, raw_name=name)


def filler_players():
    """One TQB, one K and one DST so replacement_levels never sees an empty pool.

    Names are chosen to not appear in tests/fixtures/prices_sample.csv, so they
    are never matched to an observed price and leave the n/mae/top10_mae
    assertions in the price-matching tests untouched.
    """
    return [
        player("Filler Quarterback", "TQB", 50),
        player("Filler Kicker", "K", 50),
        player("Filler Defense", "DST", 50),
    ]


def test_load_prices_normalizes_hand_typed_names():
    prices = load_prices(PRICES)
    # the roster sheet misspells Ja'Marr Chase as "JAMAAR CHASE"
    assert any("chase" in k for k in prices)
    assert len(prices) == 5


def test_score_fit_reports_error_metrics():
    pool = [player("Ja'Marr Chase", "WR", 200), player("Chase Brown", "RB", 120)]
    pool += filler_players()
    rep = score_fit(LG, pool, load_prices(PRICES), "starter")
    assert rep["policy"] == "starter"
    assert rep["n"] >= 1
    assert rep["mae"] >= 0
    assert rep["rmse"] >= rep["mae"] * 0.0


def test_score_fit_rejects_an_unknown_policy():
    pool = [player("Ja'Marr Chase", "WR", 200)]
    pool += filler_players()
    with pytest.raises(ValueError):
        score_fit(LG, pool, load_prices(PRICES), "vibes")


def test_choose_policy_returns_one_of_the_two_and_both_reports():
    pool = [player("Ja'Marr Chase", "WR", 200), player("Chase Brown", "RB", 120),
            player("Bijan Robinson", "RB", 180), player("Nico Collins", "WR", 90)]
    pool += filler_players()
    best, reports = choose_policy(LG, pool, load_prices(PRICES))
    assert best in ("starter", "draftable")
    assert len(reports) == 2
    assert {r["policy"] for r in reports} == {"starter", "draftable"}


def test_players_with_no_observed_price_are_excluded_from_the_fit():
    pool = [player("Ja'Marr Chase", "WR", 200), player("Nobody At All", "WR", 150)]
    pool += filler_players()
    rep = score_fit(LG, pool, load_prices(PRICES), "starter")
    assert rep["n"] == 1


def test_score_fit_reports_zero_matches_without_raising():
    # None of these names appear in prices_sample.csv. score_fit must report the
    # zero-match fit honestly rather than raise, so a caller inspecting `n` can see it.
    pool = [player("Totally Unknown Player", "WR", 200)]
    pool += filler_players()
    rep = score_fit(LG, pool, load_prices(PRICES), "starter")
    assert rep["n"] == 0
    assert rep["mae"] == float("inf")
    assert rep["rmse"] == float("inf")
    assert rep["top10_mae"] == float("inf")


def test_choose_policy_raises_when_no_player_matches_any_price():
    # Both policies see zero matches here, so there is no evidence to pick a
    # winner on. choose_policy must raise rather than arbitrarily return
    # "starter" because Python's min() ties on (inf, inf).
    pool = [player("Totally Unknown Player", "WR", 200)]
    pool += filler_players()
    with pytest.raises(ValueError, match="identity/aliases.yaml"):
        choose_policy(LG, pool, load_prices(PRICES))

import pytest
import yaml

from sffl.silent import (BID_FLOOR, SilentBid, bids_for_rank, load_bid_history,
                         ranks_for_bid, tie_rate_at, winning_bumps_at)

FIXTURE = "tests/fixtures/silent_bids_sample.csv"
REAL = "data/league/silent-auction-bids.csv"
PROFILE = "leagues/sffl/2026.yaml"


def test_loads_every_row():
    h = load_bid_history(FIXTURE)
    assert len(h) == 9
    assert h[0].year == 2024
    assert h[0].bid == 41
    assert h[0].cap_cost == 42


def test_ranks_for_a_bid_span_the_observed_years():
    h = load_bid_history(FIXTURE)
    best, worst, median = ranks_for_bid(h, 26)
    assert best == 3          # 2025 rank 3
    assert worst == 5         # 2024 rank 5
    assert 3 <= median <= 5


def test_a_bid_below_the_floor_raises():
    h = load_bid_history(FIXTURE)
    with pytest.raises(ValueError) as e:
        ranks_for_bid(h, 20)
    assert "26" in str(e.value)


def test_a_bid_never_observed_reports_the_neighbouring_ranks():
    # $30 was never bid in the fixture; it sits between $26 and $39
    h = load_bid_history(FIXTURE)
    best, worst, median = ranks_for_bid(h, 30)
    assert best <= median <= worst


def test_bids_for_rank_reports_the_range_that_bought_it():
    h = load_bid_history(FIXTURE)
    lo, hi, median = bids_for_rank(h, 1)
    assert lo == 41
    assert hi == 43


def test_tie_rate_is_the_fraction_of_years_with_a_duplicate_bid():
    h = load_bid_history(FIXTURE)
    # $26 was bid twice in 2024 and twice in 2025 - tied in both years
    assert tie_rate_at(h, 26) == pytest.approx(1.0)
    # $43 appears once, in one year only
    assert tie_rate_at(h, 43) == pytest.approx(0.0)


def test_winning_bumps_come_from_cap_cost_not_the_bump_column():
    h = load_bid_history(FIXTURE)
    # Gamma 2024 recorded bump=2 but cap_cost == bid, so it was NOT charged
    assert 2 not in winning_bumps_at(h, 39)
    # Alpha 2024 paid 42 on a 41 bid -> a charged bump of 1
    assert winning_bumps_at(h, 41) == [1]


def test_the_real_history_loads_and_covers_five_years():
    h = load_bid_history(REAL)
    assert len(h) == 60
    assert sorted(set(b.year for b in h)) == [2021, 2022, 2023, 2024, 2025]
    assert all(b.bid >= 26 for b in h), "no observed bid is below the floor"


def test_every_real_year_has_twelve_bids():
    h = load_bid_history(REAL)
    counts = {}
    for b in h:
        counts[b.year] = counts.get(b.year, 0) + 1
    assert set(counts.values()) == {12}


def test_the_module_floor_matches_the_league_profile():
    # BID_FLOOR is the fallback for history analysis, which has no league in
    # scope. It must never drift from the value the league actually uses.
    with open(PROFILE) as fh:
        raw = yaml.safe_load(fh)
    assert raw["silent_auction"]["bid_floor"] == BID_FLOOR


def test_a_bid_above_everything_ever_observed_clamps():
    # Nobody has bid $60. Do not invent a rank for it - clamp to the best bid
    # that was actually observed rather than extrapolating off the top.
    h = load_bid_history(FIXTURE)
    assert ranks_for_bid(h, 60) == ranks_for_bid(h, 43)


def test_a_cap_cost_below_the_bid_is_rejected(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "year,rank,franchise,bid,bump,cap_cost,player,note\n"
        "2025,1,Alpha,40,0,39,Player One,\n")
    with pytest.raises(ValueError) as e:
        load_bid_history(str(bad))
    assert "cap_cost" in str(e.value)


def test_the_dataclass_carries_the_note():
    h = load_bid_history(FIXTURE)
    assert isinstance(h[0], SilentBid)
    assert h[0].note == "won tie vs Beta on bump"
    assert h[5].note == ""

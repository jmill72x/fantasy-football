import pytest
import yaml

from sffl.silent import (BID_FLOOR, SilentBid, bids_for_rank, escalated_at,
                         field_tie_rate_at, join_tie_rate_at, load_bid_history,
                         observations_at, ranks_for_bid, winning_bumps_at,
                         years_on_record)

HEADER = "year,rank,franchise,bid,bump,cap_cost,player,note\n"

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


def test_a_bid_never_observed_is_placed_against_every_year():
    # $30 was never bid in the fixture; it sits between $26 and $39. Both years
    # still get a vote: it clears three bids in 2024 and two in 2025.
    h = load_bid_history(FIXTURE)
    best, worst, median = ranks_for_bid(h, 30)
    assert best <= median <= worst
    assert (best, worst) == (3, 4)


def test_bids_for_rank_reports_the_range_that_bought_it():
    h = load_bid_history(FIXTURE)
    lo, hi, median = bids_for_rank(h, 1)
    assert lo == 41
    assert hi == 43


def test_tie_rate_is_the_fraction_of_years_with_a_duplicate_bid():
    h = load_bid_history(FIXTURE)
    # $26 was bid twice in 2024 and twice in 2025 - tied in both years
    assert field_tie_rate_at(h, 26) == pytest.approx(1.0)
    # $43 appears once, in one year only
    assert field_tie_rate_at(h, 43) == pytest.approx(0.0)


def test_the_join_rate_counts_years_someone_was_already_there():
    """The other tie question, and the one a bidder is actually asking.

    $43 was submitted once, in 2025 - the field never tied itself there, so
    field_tie_rate_at is 0.0. But bid $43 in a year like 2025 and you are in a
    tie, because somebody was already sitting on it. One of the fixture's two
    years, so 0.5. The two numbers are not interchangeable, and neither of
    them is "the tie rate".
    """
    h = load_bid_history(FIXTURE)
    assert join_tie_rate_at(h, 43) == pytest.approx(0.5)
    assert field_tie_rate_at(h, 43) == pytest.approx(0.0)
    # $26 was occupied in both years and tied in both, so the two agree there.
    assert join_tie_rate_at(h, 26) == pytest.approx(1.0)


def test_the_years_on_record_are_the_denominator_both_rates_divide_by():
    # Exported so a printed legend can name it instead of typing "5" and being
    # wrong the August 2026's twelve rows are appended.
    assert years_on_record(load_bid_history(REAL)) == 5
    assert years_on_record(load_bid_history(FIXTURE)) == 2
    # ...and it really is the denominator: one franchise at $43 in one of the
    # fixture's two years is 1/2.
    assert join_tie_rate_at(load_bid_history(FIXTURE), 43) == pytest.approx(0.5)


def test_the_join_rate_is_never_below_the_field_rate():
    # Two or more franchises at a bid implies at least one, always. A year
    # counted by field_tie_rate_at is always counted by join_tie_rate_at too.
    h = load_bid_history(REAL)
    for bid in sorted(set(b.bid for b in h)):
        assert join_tie_rate_at(h, bid) >= field_tie_rate_at(h, bid), "$%d" % bid


def test_both_tie_rates_on_the_real_history_at_the_levels_that_matter():
    """The gap Jeff ruled on, pinned bid by bid against the five-year file.

    Hand-counted from the rank->bid table: $30 held a bid in every one of the
    five years but only 2022 and 2023 saw two teams there. Reporting 40% alone
    would have said a $30 bid mostly walks in clean, when in fact somebody has
    been standing on $30 every single year on record.
    """
    h = load_bid_history(REAL)
    expected = {
        30: (1.0, 0.4),     # 2021,2022x2,2023x2,2024,2025
        33: (0.8, 0.2),     # 2022,2023,2024,2025x2 - only 2025 tied
        35: (0.8, 0.2),     # 2021x2,2022,2023,2024
        38: (0.8, 0.2),     # 2021,2022x2,2023,2025
        39: (0.8, 0.2),     # 2022,2023x4,2024,2025
        27: (0.4, 0.0),     # 2022,2025 - never twice in a year
        26: (1.0, 1.0),     # ranks 11-12 tie at the floor every year
    }
    for bid, (join, field) in sorted(expected.items()):
        assert join_tie_rate_at(h, bid) == pytest.approx(join), "$%d join" % bid
        assert field_tie_rate_at(h, bid) == pytest.approx(field), \
            "$%d field" % bid


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


def test_a_bid_above_everything_ever_observed_is_rank_one():
    # Nobody has bid $60. Rank 1 is not an extrapolation - it is what beating
    # every bid on record means. There is no rank 0 to invent.
    h = load_bid_history(FIXTURE)
    assert ranks_for_bid(h, 60) == (1, 1, 1.0)
    assert ranks_for_bid(h, 60) == ranks_for_bid(h, 43)


def test_a_cap_cost_below_the_bid_is_rejected(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        HEADER +
        "2025,1,Alpha,40,0,39,Player One,\n")
    with pytest.raises(ValueError) as e:
        load_bid_history(str(bad))
    assert "cap_cost" in str(e.value)


def test_a_duplicate_rank_within_a_year_is_rejected(tmp_path):
    bad = tmp_path / "dupe.csv"
    bad.write_text(
        HEADER +
        "2025,1,Alpha,40,0,40,,\n"
        "2025,1,Beta,38,0,38,,\n")
    with pytest.raises(ValueError) as e:
        load_bid_history(str(bad))
    assert "rank" in str(e.value)


def test_a_bid_that_rises_with_rank_is_rejected(tmp_path):
    # A transposed row in a hand-maintained file: rank 2 outbids rank 1.
    bad = tmp_path / "transposed.csv"
    bad.write_text(
        HEADER +
        "2025,1,Alpha,38,0,38,,\n"
        "2025,2,Beta,40,0,40,,\n")
    with pytest.raises(ValueError) as e:
        load_bid_history(str(bad))
    assert "lower bid" in str(e.value)


def test_ranks_are_monotone_in_the_bid():
    # A larger bid can never buy a worse rank. The nearest-neighbour bracket
    # this replaced claimed $36's best case was rank 6 and $35's was rank 5.
    h = load_bid_history(REAL)
    previous = None
    for bid in range(BID_FLOOR, 46):
        current = ranks_for_bid(h, bid)
        if previous is not None:
            assert current[0] <= previous[0], "best rank rose at $%d" % bid
            assert current[1] <= previous[1], "worst rank rose at $%d" % bid
            assert current[2] <= previous[2], "median rank rose at $%d" % bid
        previous = current


def test_every_year_votes_on_every_bid_not_just_the_years_that_bid_it():
    # $39 took rank 1 in 2023's four-way tie, but would only have been rank 5
    # in 2021. A lookup of observed ranks alone would never surface that.
    h = load_bid_history(REAL)
    best, worst, _ = ranks_for_bid(h, 39)
    assert best == 1
    assert worst == 5
    # $32 was submitted exactly once in five years; it is still placed against
    # all sixty bids rather than resting on that single observation.
    assert observations_at(h, 32) == 1
    assert ranks_for_bid(h, 32)[0] < ranks_for_bid(h, 32)[1]


def test_winning_bumps_exclude_ties_that_escalated_to_a_live_auction():
    h = load_bid_history(REAL)
    # 2023's four-way at $39, 2021's shared $4 bump at $35, and 2025's shared
    # $1 bump at $33 were all settled live. No bump won any of them.
    for bid in (39, 35, 33):
        assert winning_bumps_at(h, bid) == [], "$%d" % bid
        assert escalated_at(h, bid) != []
    # A real bump win is still reported: 2024 rank 8 outbumped EM 50s at $31.
    assert winning_bumps_at(h, 31) == [2]
    assert escalated_at(h, 31) == []


def test_the_floor_still_needs_a_bump_and_one_year_escalated():
    h = load_bid_history(REAL)
    assert field_tie_rate_at(h, BID_FLOOR) == pytest.approx(1.0)
    # Four of the five floor ties were settled by a $1-$2 bump.
    assert winning_bumps_at(h, BID_FLOOR) == [1, 2, 2, 2]
    # 2022's was not: both franchises bumped $0, so it escalated.
    assert escalated_at(h, BID_FLOOR) == [2022]


def test_the_structural_escalation_signal_agrees_with_every_note():
    """Pin the equivalence rather than trusting it once.

    Escalation is detected from a shared top bump inside a tie group. The
    `note` column is five years of hand-written prose and must never be the
    signal, but it is the only independent record of what happened, so the two
    must agree on every tie group in the file.
    """
    from sffl.silent import _escalated, _tie_groups

    h = load_bid_history(REAL)
    groups = _tie_groups(h)
    assert len(groups) == 15, "the real file holds fifteen tie groups"
    escalations = 0
    for key in sorted(groups):
        rows = groups[key]
        note_says = any("live" in b.note.lower() or "unresolved" in b.note.lower()
                        for b in rows)
        assert _escalated(rows) == note_says, "tie group %s" % (key,)
        escalations += note_says
    # Four escalated, eleven settled by a bump. Counted from the file, not
    # from the review note, which put the split at five/ten.
    assert escalations == 4
    assert sorted(k for k in groups if _escalated(groups[k])) == [
        (2021, 35), (2022, 26), (2023, 39), (2025, 33)]


def test_a_bid_nobody_ever_submitted_refuses_to_summarise_itself():
    # $36 sits mid-range with zero observations. "Tie rate 0%" would be a
    # fabrication; the caller must be made to notice.
    h = load_bid_history(REAL)
    assert observations_at(h, 36) == 0
    for fn in (join_tie_rate_at, field_tie_rate_at, winning_bumps_at,
               escalated_at):
        with pytest.raises(ValueError) as e:
            fn(h, 36)
        assert "never been submitted" in str(e.value)
    # A bid that WAS submitted and simply never tied still answers 0.0.
    assert observations_at(h, 44) == 1
    assert field_tie_rate_at(h, 44) == pytest.approx(0.0)
    assert winning_bumps_at(h, 44) == []
    # ranks_for_bid has no such gap - every year votes on every bid.
    assert ranks_for_bid(h, 36)[0] >= 1


def test_the_dataclass_carries_the_note():
    h = load_bid_history(FIXTURE)
    assert isinstance(h[0], SilentBid)
    assert h[0].note == "won tie vs Beta on bump"
    assert h[5].note == ""

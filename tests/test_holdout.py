"""The arithmetic behind `sffl score-auction` (runbook step 12.1).

Invented players and prices only. The real 2026 reproduction needs the
licensed extract and is recorded in NEXT.md instead.
"""

import pytest

from sffl.holdout import BANDS, band_of, errors, format_report, join, score
from sffl.schema import PlayerProjection


def _player(name, my, est=None):
    stats = {"_dollars": my}
    if est is not None:
        stats["_est_price"] = est
    return PlayerProjection(name=name, team="ARI", pos="WR", source="test",
                        source_year=2026, games=17, stats=stats)


def test_band_edges_are_the_2026_tables():
    assert [label for _, label in BANDS] == ["$26+", "$10-25", "$4-9", "$1-3"]
    assert band_of(26) == "$26+"
    assert band_of(25) == "$10-25"
    assert band_of(10) == "$10-25"
    assert band_of(9) == "$4-9"
    assert band_of(4) == "$4-9"
    assert band_of(3) == "$1-3"
    assert band_of(1) == "$1-3"
    # Never dropped: a bad sub-$1 price still lands somewhere visible.
    assert band_of(0.5) == "$1-3"


def test_errors_are_model_minus_paid():
    # Diffs -4 and +2: mae 3, rmse sqrt(10), bias -1.
    e = errors([(36.0, 40.0), (12.0, 10.0)])
    assert e["mae"] == pytest.approx(3.0)
    assert e["rmse"] == pytest.approx(10 ** 0.5)
    assert e["bias"] == pytest.approx(-1.0)
    assert errors([]) is None


def test_score_by_hand():
    rows = [
        # name, MY$, EST$, paid
        ("A", 40.0, 30.0, 36.0),   # $26+
        ("B", 30.0, 28.0, 30.0),   # $26+
        ("C", 12.0, 14.0, 15.0),   # $10-25
        ("D", 1.0, 1.0, 2.0),      # $1-3
    ]
    r = score(rows)
    assert r["n"] == 4
    # EST$ diffs: -6, -2, -1, -1
    assert r["est"]["mae"] == pytest.approx(2.5)
    assert r["est"]["bias"] == pytest.approx(-2.5)
    assert r["est"]["rmse"] == pytest.approx((42 / 4.0) ** 0.5)
    # MY$ diffs: +4, 0, -3, -1
    assert r["my"]["mae"] == pytest.approx(2.0)
    assert r["my"]["bias"] == pytest.approx(0.0)
    bands = dict((b["label"], b) for b in r["bands"])
    assert bands["$26+"]["n"] == 2
    assert bands["$26+"]["est"]["bias"] == pytest.approx(-4.0)
    assert bands["$26+"]["my"]["mae"] == pytest.approx(2.0)
    assert bands["$10-25"]["n"] == 1
    assert bands["$4-9"]["n"] == 0
    assert bands["$4-9"]["est"] is None
    assert bands["$1-3"]["my"]["bias"] == pytest.approx(-1.0)
    # Bands partition the rows: their n adds back to the total.
    assert sum(b["n"] for b in r["bands"]) == r["n"]


def test_an_empty_band_prints_dashes_not_zeros():
    lines = format_report(score([("A", 30.0, 28.0, 30.0)]))
    four = [l for l in lines if l.strip().startswith("$4-9")][0]
    assert "$0.00" not in four and "-" in four


def test_join_reports_what_did_not_match():
    pool = [_player("Market Fixture One", 40.0, 35.0),
            _player("Market Fixture Two", 20.0, 18.0)]
    prices = {"market fixture one": 42.0, "nobody at all": 5.0}
    rows, unmatched = join(pool, prices)
    assert rows == [("Market Fixture One", 40.0, 35.0, 42.0)]
    assert unmatched == ["nobody at all"]


def test_join_refuses_a_board_with_no_est():
    # Scoring EST$ on a board no model priced would measure nothing.
    with pytest.raises(ValueError, match="EST"):
        join([_player("Market Fixture One", 40.0)],
             {"market fixture one": 42.0})


def test_join_pairs_one_price_with_one_player():
    pool = [_player("Same Name", 30.0, 25.0), _player("Same Name", 2.0, 1.0)]
    rows, _ = join(pool, {"same name": 31.0})
    assert len(rows) == 1 and rows[0][1] == 30.0

"""The facts the workbook's second sheet states, and where they come from.

The point of `sffl.render.intel` is that the legend is measured from the run
that printed the board beside it. So these tests are mostly about provenance:
a figure must be derived when the run can derive it, and must be ABSENT - not
zero, not last month's value - when it cannot.
"""

import re

import pytest

from sffl.league import load_league
from sffl.render import intel
from sffl.render.rows import BoardRow
from sffl.schema import PlayerProjection
from sffl.silent import load_bid_history

LG = load_league("leagues/sffl/2026.yaml")


def row(rank, pos, dollars, est=None):
    return BoardRow(rank=rank, name="%s %d" % (pos, rank), team="GB", bye=11,
                    pos=pos, tier=1, avg_pts=10.0, my_dollars=float(dollars),
                    est_price=est)


def rows():
    return [row(1, "RB", 40.0, est=32.0), row(2, "WR", 30.0, est=25.0),
            row(3, "TQB", 20.0, est=18.0), row(4, "K", 1.0, est=1.0)]


def player(name, pos, dollars):
    p = PlayerProjection(name=name, team="GB", pos=pos, source="test",
                         source_year=2026, games=17.0)
    p.stats["_dollars"] = float(dollars)
    return p


def test_the_league_figures_need_nothing_but_the_league(tmp_path):
    f = intel.gather(LG, rows(), bids_path=str(tmp_path / "absent.csv"))
    assert f.total_capital == LG.total_capital() == 1320
    assert f.season == LG.season
    assert f.bid_floor == LG.silent_auction["bid_floor"]
    assert f.flat_price == 1.0 and set(f.flat_pools) == set(LG.flat_priced_pools)


def test_the_top_est_price_is_read_off_the_board_being_printed(tmp_path):
    # The "EST$ is a floor at the top" caveat quotes the highest EST$ on the
    # sheet. Typed once, it would be wrong the next time the extract changes -
    # which is the week before the auction.
    f = intel.gather(LG, rows(), bids_path=str(tmp_path / "absent.csv"))
    assert f.top_est_price == 32.0
    text = dict(intel._dollar_columns(f)[1])["Floor"]
    assert "$32" in text


def test_a_run_without_prices_quotes_no_market_numbers(tmp_path):
    f = intel.gather(LG, rows(), bids_path=str(tmp_path / "absent.csv"))
    assert f.curve is None and f.record_price is None
    assert f.mae_by_pool == {} and f.flat_obs is None

    body = " ".join(text for _heading, items in intel.sections(f)
                    for _term, text in items)
    # It must SAY it did not measure, rather than print a zero or a stale
    # figure. The two sentences that carry market numbers are the EST$ one
    # and the Team QB one.
    assert "fitted no price curve" in body
    assert "not quoted" in body
    assert "$8.98" not in body and "$0.00" not in body


def test_the_pool_error_is_measured_against_the_prices_that_joined():
    # $8.98 for Team QB and $6.28 for the skill pool are the production
    # figures; the mechanism is what is pinned here, on numbers a test can
    # own. MY$ minus price paid, per pool, over the joins.
    pool = [player("Alpha", "TQB", 30.0), player("Bravo", "TQB", 10.0),
            player("Charlie", "RB", 12.0), player("Delta", "WR", 5.0),
            player("Echo", "TE", 25.0)]
    prices = {"alpha": 20.0, "bravo": 20.0, "charlie": 10.0, "delta": 10.0}
    f = intel.gather(LG, rows(), pool=pool, prices=prices)

    assert f.mae_by_pool["TQB"] == (2, 10.0)       # |30-20|, |10-20|
    assert f.mae_by_pool["FLEX"] == (2, 3.5)       # |12-10|, |5-10|; Echo unjoined
    assert f.n_prices_joined == 4
    # The curve is fitted on the non-flat joins only - none of these are K/DST.
    assert f.n_curve_obs == 4
    assert f.record_price == 20.0


def test_flat_priced_pools_are_evidenced_by_what_was_paid_for_them():
    pool = [player("Kick One", "K", 1.0), player("Kick Two", "K", 1.0),
            player("Def One", "DST", 1.0), player("Alpha", "RB", 20.0)]
    prices = {"kick one": 1.0, "kick two": 3.0, "def one": 1.0,
              "alpha": 18.0}
    f = intel.gather(LG, rows(), pool=pool, prices=prices)

    assert f.flat_obs == {"n": 3, "max_price": 3.0, "n_at_flat": 2,
                          "kickers": 2, "kickers_at_flat": 1}
    text = dict(intel._the_room(f)[1])["K & DST"]
    assert "3 observed prices" in text and "none is above $3" in text
    assert "1 of the 2 kickers" in text


def test_the_silent_auction_figures_come_from_the_tracked_history():
    history = load_bid_history()
    f = intel.gather(LG, rows(), history=history)

    assert f.years == 5
    # Round one takes $412-$432 of the league's $1,320 - a third of it.
    assert (f.round_one_low, f.round_one_high) == (412, 432)
    assert f.record_bid == 45
    assert f.floor_ranks == (11, 12)
    assert [r for r, _lo, _hi in f.rank_bids] == list(intel.SAMPLE_RANKS)
    assert (1, 39, 45) in f.rank_bids

    text = dict(intel._the_silent_pick(f)[1])["The rank"]
    assert "rank 1 has cost $39-$45" in text
    assert "$26 floor in every year" in text


def test_a_missing_bid_history_degrades_instead_of_failing(tmp_path):
    # The board is the artifact that must exist on auction day. An unreadable
    # history costs one paragraph, not the render - and the paragraph says so.
    f = intel.gather(LG, rows(), bids_path=str(tmp_path / "nope.csv"))
    assert f.years is None and f.rank_bids == []
    text = dict(intel._the_silent_pick(f)[1])["The rank"]
    assert "no bid history was readable" in text
    assert "%" not in text


def test_no_bid_is_ever_named():
    # Jeff has not chosen a bid and it is his call; the sheet reports what the
    # record shows and stops. Nothing here may read as "bid $X".
    f = intel.gather(LG, rows(), history=load_bid_history())
    body = " ".join(text for _heading, items in intel.sections(f)
                    for _term, text in items)
    assert not re.search(r"\bbid \$\d", body), body
    for word in ("you should", "recommend", "must bid", "take the"):
        assert word not in body.lower()


def test_the_calibration_provenance_matches_the_curve_file():
    # CALIBRATION_PLAYERS / _PLAYER_WEEKS are typed into intel.py because the
    # curve file records them in a COMMENT, which yaml.safe_load discards. This
    # is what stops the two from drifting: if the curves are ever rebuilt from
    # a wider collection (TODO B - the target is ~120 players), this fails
    # until the sheet is told.
    with open("calibration/2025.yaml") as fh:
        header = fh.read(400)
    m = re.search(r"(\d+) distinct players, (\d+) player-weeks", header)
    assert m, "calibration/2025.yaml no longer records its own provenance: %r" % header
    assert intel.CALIBRATION_PLAYERS == int(m.group(1))
    assert intel.CALIBRATION_PLAYER_WEEKS == int(m.group(2))


def test_the_sheet_never_prints_a_bare_float():
    # Money is formatted once, in _money, so nothing on a printed page can
    # come out as "$41.0" or "8.983333333".
    f = intel.gather(LG, rows(), pool=[player("Alpha", "TQB", 30.0)],
                     prices={"alpha": 21.0}, curve=(2.248, 0.551),
                     history=load_bid_history())
    body = " ".join(text for _heading, items in intel.sections(f)
                    for _term, text in items)
    assert not re.search(r"\d\.\d{3,}", body), body
    assert not re.search(r"\$\d+\.0\b", body), body


def test_every_section_has_a_heading_and_at_least_one_item():
    f = intel.gather(LG, rows(), history=load_bid_history())
    got = [heading for heading, _items in intel.sections(f)]
    assert got == [
        "THE TWO DOLLAR COLUMNS",
        "THE OTHER COLUMNS",
        "WHAT THIS ROOM DOES - FROM ITS OWN PRICES",
        "WHERE THE MODEL IS WEAK",
        "ROUND ONE - THE SILENT AUCTION PICK",
    ]
    for heading, items in intel.sections(f):
        assert items, "%s carries no items" % heading
        for term, text in items:
            assert term and text.strip()


def test_gather_never_raises_on_a_pool_that_was_never_valued():
    # A record with no _dollars is skipped, not crashed on: this module is a
    # legend, and it must not be the thing that fails a render.
    p = PlayerProjection(name="Alpha", team="GB", pos="RB", source="test",
                         source_year=2026, games=17.0)
    f = intel.gather(LG, rows(), pool=[p], prices={"alpha": 10.0})
    assert f.mae_by_pool == {}


def test_an_empty_board_still_gathers(tmp_path):
    # render_xlsx raises on an empty board before this is reached, but the
    # module must not be the reason.
    f = intel.gather(LG, [], bids_path=str(tmp_path / "absent.csv"))
    assert f.top_est_price is None
    with pytest.raises(KeyError):
        f.mae_by_pool["TQB"]


def _silent_text(f):
    """The prose of the round-one section, as one searchable string."""
    for heading, items in intel.sections(f):
        if "SILENT" in heading:
            return " ".join("%s %s" % (k, v) for k, v in items)
    raise AssertionError("no silent-auction section")


def test_the_top_cluster_is_ranked_by_the_overall_block_not_by_raw_rows(tmp_path):
    # The page tells the drafter to read OVERALL, so the names it reasons over
    # must come from that same block - kickers and defenses are not in it, and
    # a flat-priced $1 K must never be quoted as the top of the board.
    f = intel.gather(LG, rows(), bids_path=str(tmp_path / "absent.csv"))
    assert [n for n, _ in f.top_cluster] == ["RB 1", "WR 2", "TQB 3"]
    assert all(not n.startswith("K ") for n, _ in f.top_cluster)


def test_a_tight_top_tells_the_drafter_the_next_name_is_an_equivalent(tmp_path):
    # $40 / $39 / $38: nothing worth defending at the top.
    tight = [row(1, "RB", 40.0), row(2, "WR", 39.0), row(3, "WR", 38.0)]
    text = _silent_text(intel.gather(LG, tight,
                                     bids_path=str(tmp_path / "absent.csv")))
    assert "not a cliff" in text
    assert "real drop-off" not in text
    # It must name the players and the gap, not speak in generalities.
    assert "RB 1" in text and "WR 2" in text and "$1" in text


def test_a_real_drop_off_at_the_top_is_reported_as_one(tmp_path):
    # $40 then $20: losing the top name costs far more than one rank.
    cliff = [row(1, "RB", 40.0), row(2, "WR", 20.0), row(3, "WR", 19.0)]
    text = _silent_text(intel.gather(LG, cliff,
                                     bids_path=str(tmp_path / "absent.csv")))
    assert "real drop-off" in text
    assert "not a cliff" not in text


def test_the_stale_board_warning_is_unconditional(tmp_path):
    # Whatever the shape of the top, the page must say the board predates the
    # night. It states that as a fact about the board, never as an
    # instruction - see test_no_bid_is_ever_named.
    for board in ([row(1, "RB", 40.0), row(2, "WR", 39.0)],
                  [row(1, "RB", 40.0), row(2, "WR", 20.0)]):
        text = _silent_text(intel.gather(LG, board,
                                         bids_path=str(tmp_path / "absent.csv")))
        assert "Snapshot" in text
        assert "not evidence a player is active" in text


def test_a_board_too_short_to_compare_says_nothing_rather_than_inventing(tmp_path):
    # One name cannot show a gap. Silence beats a fabricated reassurance.
    text = _silent_text(intel.gather(LG, [row(1, "RB", 40.0)],
                                     bids_path=str(tmp_path / "absent.csv")))
    assert "Snapshot" not in text

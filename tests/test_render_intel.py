"""The facts the workbook's second sheet states, and where they come from.

The point of `sffl.render.intel` is that the legend is measured from the run
that printed the board beside it. So these tests are mostly about provenance:
a figure must be derived when the run can derive it, and must be ABSENT - not
zero, not last month's value - when it cannot.
"""

import re

import pytest

from sffl.league import load_league
from sffl.market_model import MarketModel
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
    # Frozen five-year snapshot: the figures below are exact, and the live
    # file gains a season every August.
    history = load_bid_history("tests/fixtures/silent_bids_2021_2025.csv")
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


# --------------------------------------------------------------------------
# Team QB dispersion. Replaced two frozen tuples of franchise codes that named
# "rushing-QB" and "pocket-passer" teams; see intel.py's note for why that
# explanation did not survive the 2026 prices.
# --------------------------------------------------------------------------

def _tqb(my_dollars):
    return [player("TQB %d" % i, "TQB", d) for i, d in enumerate(my_dollars)]


def test_the_tqb_split_is_taken_at_the_median_the_data_chooses():
    # 1,1,1,20,30,40 -> median 10.5; three below, three above.
    pool = _tqb([1.0, 1.0, 1.0, 20.0, 30.0, 40.0])
    prices = {"tqb 0": 5.0, "tqb 1": 5.0, "tqb 2": 5.0,     # cheap ones cost MORE
              "tqb 3": 2.0, "tqb 4": 2.0, "tqb 5": 2.0}     # dear ones cost LESS
    d = intel._tqb_dispersion(pool, prices)
    assert d["n_low"] == 3 and d["n_low_under"] == 3
    assert d["n_high"] == 3 and d["n_high_over"] == 3


def test_dispersion_counts_only_the_misses_that_run_the_expected_way():
    pool = _tqb([1.0, 1.0, 1.0, 20.0, 30.0, 40.0])
    prices = {"tqb 0": 5.0, "tqb 1": 0.5, "tqb 2": 5.0,     # one cheap unit cost LESS
              "tqb 3": 2.0, "tqb 4": 99.0, "tqb 5": 2.0}    # one dear unit cost MORE
    d = intel._tqb_dispersion(pool, prices)
    assert d["n_low"] == 3 and d["n_low_under"] == 2
    assert d["n_high"] == 3 and d["n_high_over"] == 2


def test_too_few_priced_tqb_units_says_nothing_rather_than_splitting_noise():
    pool = _tqb([1.0, 40.0])
    assert intel._tqb_dispersion(pool, {"tqb 0": 5.0, "tqb 1": 2.0}) is None


def test_a_pool_that_lands_entirely_on_one_side_of_its_median_reports_nothing():
    # Every unit at the same MY$: nothing is above or below, so there is no
    # dispersion to describe and a split would be arithmetic on a tie.
    pool = _tqb([1.0, 1.0, 1.0, 1.0, 1.0])
    prices = {"tqb %d" % i: 5.0 for i in range(5)}
    assert intel._tqb_dispersion(pool, prices) is None


def test_the_team_qb_paragraph_quotes_derived_counts_and_names_no_franchise():
    f = intel.IntelFacts(total_capital=1320)
    f.mae_by_pool = {"TQB": (21, 7.55), "FLEX": (109, 4.55)}
    f.tqb_dispersion = {"median": 3.1, "n_low": 9, "n_low_under": 9,
                        "n_high": 10, "n_high_over": 8}
    text = dict(intel._model_weakness(f)[1])["Team QB"]
    assert "9 units it prices below $3.10" in text
    assert "of the 10 above, 8 went for less" in text
    # The old claim named six franchises and blamed quarterback style. Neither
    # may come back: both were wrong about the cause.
    for gone in ("BAL", "WAS", "PHI", "DAL", "CIN", "MIN",
                 "rushing", "pocket-passer"):
        assert gone not in text, gone


def test_the_team_qb_paragraph_degrades_instead_of_inventing_a_shape():
    f = intel.IntelFacts(total_capital=1320)
    f.mae_by_pool = {"TQB": (21, 7.55), "FLEX": (109, 4.55)}
    f.tqb_dispersion = None
    text = dict(intel._model_weakness(f)[1])["Team QB"]
    assert "too few Team QB units" in text
    assert "WIDER" not in text


# --------------------------------------------------------------------------
# Which market model priced EST$, and from which season (Task 6, Part 2).
#
# A fit-in-process curve and an applied persisted model produce the exact
# same (a, b) tuple - `gather` cannot tell them apart from the curve alone.
# It distinguishes them from whether `prices` is None (see `_value_pool`'s
# own docstring: --market leaves `prices` None, --prices does not) and, for
# an applied model's own season/observations/fit date, from the `market`
# argument - the loaded `MarketModel` itself. Absent that argument, those
# three facts are honestly None rather than assumed "this season".
# --------------------------------------------------------------------------

MODEL_SEASON = 2025
CROSS_MODEL = MarketModel(season=MODEL_SEASON, fitted_on="2025-08-15",
                          curve=(2.2, 0.6), policy="starter",
                          evidence={"observations": 130}, diagnostics={})
SAME_SEASON_MODEL = MarketModel(season=LG.season, fitted_on="2026-08-29",
                                curve=(2.0, 0.66), policy="starter",
                                evidence={"observations": 156}, diagnostics={})


def _model_text(f):
    return dict(intel._dollar_columns(f)[1])["Model"]


def test_a_curve_fit_in_process_names_this_seasons_own_observation_count():
    pool = [player("Alpha", "TQB", 30.0), player("Bravo", "RB", 12.0)]
    prices = {"alpha": 20.0, "bravo": 10.0}
    f = intel.gather(LG, rows(), pool=pool, prices=prices, curve=(2.0, 0.66))
    assert f.market_applied is False
    assert f.market_season == LG.season
    assert f.market_cross_season is False
    assert f.market_n_obs == f.n_curve_obs == 2

    text = _model_text(f)
    assert "fit fresh this run" in text
    assert "%d" % LG.season in text
    assert "2" in text  # the observation count
    assert "CROSS-SEASON" not in text

    est = dict(intel._dollar_columns(f)[1])["EST$"]
    assert "fitted no price curve" not in est


def test_an_applied_curve_with_no_model_object_names_nothing_it_cannot_know():
    # curve is set (assign_expected_prices ran) but `gather` was handed
    # neither `prices` (so this is not an in-process fit) nor `market` (so
    # there is no MarketModel to read a season off) - exactly a --market run
    # whose loaded model was never threaded through to `gather`.
    f = intel.gather(LG, rows(), curve=(2.0, 0.66))
    assert f.market_applied is True
    assert f.market_season is None
    assert f.market_n_obs is None
    assert f.market_cross_season is None

    text = _model_text(f)
    assert "did not record" in text
    assert "2025" not in text and "2026" not in text

    # The bug this replaces: EST$ IS populated on an applied run (curve is
    # not None), so the page must never say it fitted none.
    est = dict(intel._dollar_columns(f)[1])["EST$"]
    assert "fitted no price curve" not in est
    assert "APPLIED" not in est.upper() or "persisted" in est.lower()


def test_a_cross_season_applied_model_is_named_and_flagged(tmp_path):
    f = intel.gather(LG, rows(), curve=CROSS_MODEL.curve, market=CROSS_MODEL)
    assert f.market_applied is True
    assert f.market_season == MODEL_SEASON
    assert f.market_n_obs == 130
    assert f.market_fitted_on == "2025-08-15"
    assert f.market_cross_season is True

    text = _model_text(f)
    assert "2025" in text and "130" in text and "2025-08-15" in text
    assert "CROSS-SEASON" in text
    assert "%d" % LG.season in text  # names the board's own season too


def test_a_year_matched_applied_model_is_named_without_the_cross_season_flag():
    f = intel.gather(LG, rows(), curve=SAME_SEASON_MODEL.curve,
                     market=SAME_SEASON_MODEL)
    assert f.market_cross_season is False

    text = _model_text(f)
    assert "%d" % LG.season in text and "156" in text
    assert "CROSS-SEASON" not in text
    assert "year-matched" in text


def test_no_curve_means_no_market_model_to_name():
    f = intel.gather(LG, rows())
    assert f.market_applied is None
    text = _model_text(f)
    assert "no model priced this board" in text

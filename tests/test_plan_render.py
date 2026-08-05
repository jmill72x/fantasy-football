"""The silent-auction tradeoff table, as it reaches the printed page.

These tests read the generated PDF's bytes. `Sheet` writes uncompressed
content streams on purpose (see `sffl.render.pdf`), so every string the
management page draws is findable with a plain byte search.

WHAT IS BEING PROTECTED HERE IS A DISTINCTION, not a layout. Three states of
tie evidence exist and none of them may render as another:

    rate = 0.0   the bid was submitted and never tied     -> "0%"
    rate = None  the bid was never submitted at all       -> "no data" (BOTH
                 tie cells - one number beside a blank reads as a measured 0)
    bumps = [] with escalated years -> the tie went to a LIVE auction, where
                     real money was paid above the bid. Not "no bump risk".

Two tasks were spent keeping those apart in the data. A renderer that prints
$28 as "0%" throws all of it away at the last step.
"""

import pytest

from sffl.league import load_league
from sffl.plan import plan_bids
from sffl.render.pdf import fallback_bids, render_pdf
from sffl.render.rows import BoardRow
from sffl.silent import load_bid_history

LG = load_league("leagues/sffl/2026.yaml")
BIDS = "data/league/silent-auction-bids.csv"


def row(rank, name, pos, dollars, est):
    return BoardRow(rank=rank, name=name, team="GB", bye=11, pos=pos, tier=1,
                    avg_pts=10.0, my_dollars=float(dollars), est_price=float(est))


def board():
    rows, n = [], 1
    for pos, count in (("RB", 40), ("WR", 60), ("TE", 20),
                       ("TQB", 32), ("K", 32), ("DST", 32)):
        for i in range(count):
            rows.append(row(n, "%s %d" % (pos, i), pos, 60.0 - 0.1 * n,
                            40.0 - 0.07 * n))
            n += 1
    return rows


def outcomes():
    return plan_bids(LG, board(), load_bid_history(BIDS))


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def rendered(tmp_path):
    path = str(tmp_path / "b.pdf")
    render_pdf(LG, board(), path, outcomes=outcomes())
    return read(path)


def test_the_management_page_states_the_floor_and_its_penalty(tmp_path):
    data = rendered(tmp_path).lower()
    assert b"$26" in data
    assert b"forfeit" in data or b"discard" in data


def test_the_likely_pick_is_labelled_an_illustration(tmp_path):
    assert b"illustration" in rendered(tmp_path).lower()


def test_no_bid_below_the_floor_appears_on_the_page(tmp_path):
    out = outcomes()
    assert all(o.bid >= 26 for o in out)
    path = str(tmp_path / "b.pdf")
    render_pdf(LG, board(), path, outcomes=out)
    assert read(path).startswith(b"%PDF-")


def test_the_pdf_still_renders_without_outcomes(tmp_path):
    # rendering with no bid history must degrade, not crash
    path = str(tmp_path / "b.pdf")
    pages = render_pdf(LG, board(), path)
    assert pages > 0


def test_the_fallback_grid_never_offers_a_bid_that_forfeits_the_pick(tmp_path):
    # The block this task replaced offered $20 and $25. Both are below the
    # $26 floor, both would have been discarded, and both would have cost the
    # silent pick outright. The no-history path must not keep that bug alive
    # just because it has no evidence to draw instead.
    floor = LG.silent_auction["bid_floor"]
    assert min(fallback_bids(floor)) >= floor
    # ...and it must still state the rule, because that path still prints.
    path = str(tmp_path / "b.pdf")
    render_pdf(LG, board(), path)
    data = read(path).lower()
    assert b"forfeit" in data and b"$%d" % floor in data


def test_a_bid_nobody_has_ever_made_says_so_instead_of_zero_percent(tmp_path):
    # $28 sits between $27 and $29 and has never been submitted in five
    # years. Both tie rates are None there, not 0.0. Printing "0%" would claim
    # five years of evidence that a bid at $28 draws no tie.
    out = outcomes()
    unbid = [o for o in out if o.observations == 0]
    assert unbid, "expected at least one never-submitted candidate bid"
    assert all(o.join_tie_rate is None and o.field_tie_rate is None
               for o in unbid)
    assert b"no data" in rendered(tmp_path)


def test_an_observed_bid_that_never_tied_reads_as_a_measured_zero(tmp_path):
    # $27 was submitted twice and never tied: 0% is a real measurement and
    # must render as one, distinct from "no data".
    out = outcomes()
    measured = [o for o in out if o.observations and o.field_tie_rate == 0.0]
    assert measured, "expected at least one observed-but-never-tied bid"
    assert b"0%" in rendered(tmp_path)


def test_an_escalated_tie_is_never_shown_as_a_free_tie(tmp_path):
    # $35 and $39 both tied, both charged nothing THROUGH A BUMP, and both
    # went to a live auction where money was paid above the bid. An empty
    # winning_bumps there does not mean the tie was free.
    out = outcomes()
    escalated = [o for o in out
                 if o.escalated_years and not o.winning_bumps]
    assert escalated, "expected a bid whose only tie exposure was live"
    data = rendered(tmp_path).lower()
    assert b"live" in data


def test_the_page_names_a_rank_range_not_only_the_median_row(tmp_path):
    # $39 spans ranks 1-5. Naming only the median row silently discards a
    # four-rank spread, which is exactly where the illustration is weakest.
    out = outcomes()
    wide = [o for o in out if o.worst_rank - o.best_rank >= 3]
    assert wide, "expected a bid with a wide rank span"
    ranked = sorted([r for r in board() if r.pos in ("TQB", "RB", "WR", "TE")],
                    key=lambda r: -r.my_dollars)
    for o in wide:
        assert o.best_player == ranked[o.best_rank - 1].name
        assert o.worst_player == ranked[o.worst_rank - 1].name

    # Both ends on one line. Asserting the two names separately would pass on
    # a page that only drew the median row, since every board page already
    # carries every name.
    data = rendered(tmp_path)
    for o in wide:
        assert ("%s - %s" % (o.best_player, o.worst_player)).encode() in data


def test_shortening_a_pick_range_keeps_the_two_players_apart(tmp_path):
    # The first real render of this page merged the two names into one - the
    # fallback dropped the separator, turning a two-player range into a single
    # nonexistent player at four bids, several of them the wide spans the
    # range exists to show.
    from reportlab.pdfgen import canvas

    from sffl.render.pdf import _fit

    c = canvas.Canvas(str(tmp_path / "x.pdf"))
    text = "Dominic Marchetti - Cornelius Vance"
    short = _fit(c, text, "Helvetica", 5.5, 60)
    assert short != text, "expected this to be too wide to print in full"
    assert short == "Marchetti - Vance"

    # Drop the given name, do not keep the last word. A bare last word merges
    # players who share it, and turns a suffix into the whole name.
    assert _fit(c, "Aldous Marchetti - Bo St. Clair", "Helvetica", 5.5, 60) \
        == "Marchetti - St. Clair"
    assert _fit(c, "Aldous Marchetti - Cal Winters Jr.", "Helvetica", 5.5, 60) \
        == "Marchetti - Winters Jr."


def test_a_board_shallower_than_the_rank_names_nobody(tmp_path):
    # Same rule the median illustration already follows: no player rather
    # than a fabricated one.
    shallow = [row(1, "RB 0", "RB", 50.0, 30.0),
               row(2, "WR 0", "WR", 40.0, 25.0),
               row(3, "TE 0", "TE", 30.0, 20.0),
               row(4, "TQB 0", "TQB", 20.0, 15.0),
               row(5, "K 0", "K", 1.0, 1.0),
               row(6, "DST 0", "DST", 1.0, 1.0)]
    out = plan_bids(LG, shallow, load_bid_history(BIDS))
    floorbid = [o for o in out if o.bid == 26][0]   # ranks 11-12, board of 4
    assert floorbid.best_player is None
    assert floorbid.worst_player is None
    path = str(tmp_path / "b.pdf")
    render_pdf(LG, shallow, path, outcomes=out)
    assert read(path).startswith(b"%PDF-")


def test_a_table_too_tall_for_the_page_raises_instead_of_overflowing(tmp_path):
    # The first real render of this block set PLAN_ROW_H to 15.0, which was
    # 30pt too tall: the twelfth LEAGUE SPEND row landed below the page edge
    # and struck through the footer caveat. No byte search can see that, and
    # every previous defect in this renderer was found by opening the file.
    # So the geometry refuses rather than printing a page missing a franchise.
    from sffl.plan import default_candidates
    history = load_bid_history(BIDS)
    stretched = default_candidates(LG, history) * 3   # de-duplicated by plan_bids
    assert len(set(stretched)) == 20
    out = plan_bids(LG, board(), history, candidates=stretched)

    # ...and the real 20-row table clears it with room to spare.
    path = str(tmp_path / "b.pdf")
    render_pdf(LG, board(), path, outcomes=out)
    assert read(path).startswith(b"%PDF-")

    with pytest.raises(ValueError) as e:
        render_pdf(LG, board(), path,
                   outcomes=out + out[:1] * _OVERFLOW_EXTRA_ROWS)
    assert "LEAGUE SPEND" in str(e.value)


# Enough extra rows to push the stack past the footer. plan_bids de-duplicates
# its candidates, so this repeats an already-built outcome rather than asking
# for more bids than the history can answer.
_OVERFLOW_EXTRA_ROWS = 12


def test_the_page_carries_every_candidate_bid(tmp_path):
    data = rendered(tmp_path)
    for o in outcomes():
        assert b"$%d" % o.bid in data


def test_the_page_carries_both_tie_numbers_and_says_which_is_which(tmp_path):
    # Jeff's ruling on 2026-08-05: show both. $30 has held a bid in every one
    # of the five years (TIE1+ 100%) but only twice did two teams collide there
    # (TIE2+ 40%). One number under a bare "TIE" heading throws that away.
    out = outcomes()
    o30 = [o for o in out if o.bid == 30][0]
    assert (o30.join_tie_rate, o30.field_tie_rate) == (1.0, 0.4)
    data = rendered(tmp_path)
    assert b"TIE1+" in data and b"TIE2+" in data
    assert b"100%" in data
    # The legend must define both, unambiguously, on the page itself.
    assert b"ALREADY at this exact bid" in data
    assert b"2+ teams tied EACH OTHER" in data


def test_the_page_says_that_what_is_left_is_before_any_bump(tmp_path):
    # LEFT reads $71 at a $39 bid, but 2023's winner at $39 paid $42. The
    # bump is not netted off - it cannot be, since it is charged only on a
    # winning tie - so the page has to say the column is pre-bump.
    data = rendered(tmp_path)
    assert b"LEFT*" in data and b"DISCR*" in data
    assert b"PRE-BUMP" in data


def test_a_cell_too_wide_for_its_column_raises_instead_of_overprinting(tmp_path):
    # The horizontal twin of the PLAN_ROW_H guard. Before this, BUMP had 3.2pt
    # of clearance against "1,2,2,2" and TIE 2.7pt against "no data": one more
    # year of floor ties would have printed BUMP through LIVE, with every
    # string still findable by a byte search and nothing failing.
    from reportlab.pdfgen import canvas

    from sffl.render.pdf import PLAN_CELL_GAP, PLAN_COL, _cell

    c = canvas.Canvas(str(tmp_path / "x.pdf"))
    width = PLAN_COL["BUMP"][1]
    # Seven charged bumps at one level - two more years of floor ties than the
    # file holds today. It fits nothing and must not be drawn.
    too_wide = "1,2,2,2,2,2,2"
    assert c.stringWidth(too_wide, "Helvetica", 5.5) > width - PLAN_CELL_GAP
    with pytest.raises(ValueError) as e:
        _cell(c, 0.0, 0.0, too_wide, "Helvetica", 5.5, "BUMP")
    assert "BUMP" in str(e.value)
    assert too_wide in str(e.value)

    # ...and what the file holds today still draws.
    _cell(c, 0.0, 0.0, "1,2,2,2", "Helvetica", 5.5, "BUMP")


def test_every_column_has_room_for_the_widest_string_it_can_hold(tmp_path):
    """The guard is only useful if today's real table is inside it.

    A guard that raises on the production render is not a guard, it is an
    outage on 2026-08-26. So every cell the real 20-row table draws is measured
    here, plus the strings one more year of history could produce.
    """
    from reportlab.pdfgen import canvas

    from sffl.render.pdf import PLAN_CELL_GAP, PLAN_COL

    c = canvas.Canvas(str(tmp_path / "x.pdf"))

    def fits(column, text, font, size):
        room = PLAN_COL[column][1] - PLAN_CELL_GAP
        return c.stringWidth(text, font, size) <= room

    # Headers.
    for name in PLAN_COL:
        assert fits(name, name, "Helvetica-Bold", 5), name
    # Every cell of the real table.
    from sffl.plan import tie_cells
    for o in outcomes():
        join, field, bump, live = tie_cells(o)
        assert fits("BID", "$%d" % o.bid, "Helvetica-Bold", 7)
        span = ("%d" % o.best_rank if o.best_rank == o.worst_rank
                else "%d-%d" % (o.best_rank, o.worst_rank))
        assert fits("RANK", span, "Helvetica", 6)
        assert fits("TIE1+", join, "Helvetica", 5.5)
        assert fits("TIE2+", field, "Helvetica", 5.5)
        assert fits("BUMP", bump, "Helvetica", 5.5)
        assert fits("LIVE", live, "Helvetica", 5.5)
        assert fits("LEFT*", "$%d" % o.budget_left, "Helvetica", 6)
        assert fits("DISCR*", "$%d" % o.discretionary, "Helvetica", 6)
    # Headroom for 2026's file: a sixth year of floor ties, and a level that
    # escalated in three separate years.
    assert fits("BUMP", "1,2,2,2,2", "Helvetica", 5.5)
    assert fits("LIVE", "'21 '22 '23", "Helvetica", 5.5)
    assert fits("RANK", "11-12", "Helvetica", 6)
    assert fits("TIE1+", "no data", "Helvetica", 5.5)
    assert fits("TIE2+", "no data", "Helvetica", 5.5)


def test_the_columns_tile_the_block_exactly_with_no_overlap(tmp_path):
    """Widths are only a guard if the columns they describe are the real ones."""
    from sffl.render.pdf import COL_W, PLAN_COLS

    edge = 0.0
    for name, x, w, align in PLAN_COLS:
        assert x == pytest.approx(edge), "%s does not start where %s ends" % (
            name, "the previous column")
        assert w > 0, name
        assert align in ("left", "right")
        edge = x + w
    assert edge == pytest.approx(COL_W), "the columns must fill the block"

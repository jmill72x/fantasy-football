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
    here.

    THE COLUMNS ARE SIZED TO THIS YEAR'S FILE ON PURPOSE. They used to reserve
    room for strings 2027 might hold - "1,2,2,2,2", "'21 '22 '23" - and paid
    for it out of PICK RANGE, which then ellipsized three rows into ambiguity
    ("Robinson - McC..." is four real players). The reserve is gone and the
    guard replaces it: a bigger string next August fails loudly at render time,
    weeks before anyone bids. The bottom of this test pins that trade in both
    directions so nobody restores the reserve without seeing what it costs.
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
    # The widest strings this year's data can produce, whatever the board.
    assert fits("RANK", "11-12", "Helvetica", 6)
    assert fits("TIE1+", "no data", "Helvetica", 5.5)
    assert fits("TIE2+", "no data", "Helvetica", 5.5)
    assert fits("LIVE", "'21 '22", "Helvetica", 5.5), \
        "two escalations at one level is within reach of the 2026 file"

    # ...and NOT a point more. These are the 2027 strings whose reserve was
    # sold to PICK RANGE. If a change makes either of these fit again, PICK
    # RANGE has silently been narrowed and names have gone back to ellipsis.
    assert not fits("BUMP", "1,2,2,2,2", "Helvetica", 5.5)
    assert not fits("LIVE", "'21 '22 '23", "Helvetica", 5.5)


def test_no_pick_range_on_the_real_board_is_truncated_into_ambiguity(tmp_path):
    """Every illustration renders as full surnames - no ellipsis anywhere.

    "Robinson - McC..." is McCaffrey, McConkey, McLaurin or McBride, all real
    skill players, on a page read under a bid clock. The column is an
    illustration, not a prediction, but an ambiguous name is not an
    illustration of anything.
    """
    from reportlab.pdfgen import canvas

    from sffl.plan import pick_range
    from sffl.render.pdf import PLAN_CELL_GAP, PLAN_COL, _fit

    c = canvas.Canvas(str(tmp_path / "x.pdf"))
    room = PLAN_COL["PICK RANGE"][1] - PLAN_CELL_GAP
    for o in outcomes():
        drawn = _fit(c, pick_range(o), "Helvetica", 5.5, room)
        assert "…" not in drawn, \
            "$%d truncates to %r in %.1fpt" % (o.bid, drawn, room)
        # Both players still named, and still apart, wherever the span is wide.
        if o.best_player and o.worst_player and o.best_player != o.worst_player:
            assert " - " in drawn, "$%d lost the separator: %r" % (o.bid, drawn)

    # THIS BOARD'S NAMES ARE SYNTHETIC AND SHORT ("RB 7"), so the loop above
    # would pass at almost any width and catches nothing. What the column
    # actually has to hold is a real pair, and the widest the live 2026 board
    # produces is a hyphenated surname beside a long Mc- surname: 61.4pt at
    # Helvetica 5.5. These invented surnames are measured to 61.4pt for that
    # reason - the repo is public, so no real player name is committed here,
    # but the WIDTH is the real one, and it is what pins the column.
    pair = "Barnabas Brightwater - Ignatius Castellanos"
    surnames = "Brightwater - Castellanos"
    assert 61.0 <= c.stringWidth(surnames, "Helvetica", 5.5) <= 62.0, \
        "the stand-in must stay calibrated to the live board's widest pair"
    drawn = _fit(c, pair, "Helvetica", 5.5, room)
    assert drawn == surnames, \
        "%r rendered as %r in %.1fpt of PICK RANGE" % (pair, drawn, room)


def _drawn_fonts(pdf_bytes):
    """[(font, size, text)] for every string on the LAST page, in draw order.

    The content streams are uncompressed (see `sffl.render.pdf`), so the font
    actually in effect at each `Tj` can be read straight out of the file. A
    byte search for the VALUE cannot do this, and that is precisely how the BID
    column lost its font: `_cell` took `font`/`size` for `stringWidth` only,
    the `setFont` calls the old inline `drawString`s relied on were deleted
    with them, and every bid from row two down drew in Helvetica 5.5 - the pick
    range's font, left set by the row above - instead of Helvetica-Bold 7. All
    274 tests passed. The bid is the column Jeff scans to find his row, and it
    had become the lightest text in the table.
    """
    import re

    names = dict((m.group(2).decode(), m.group(1).decode()) for m in re.finditer(
        rb'/BaseFont\s*/([\w-]+)\s*/Encoding\s*/\w+\s*/Name\s*/(F\d+)', pdf_bytes))
    stream = [m.group(1) for m in re.finditer(
        rb'stream\r?\n(.*?)endstream', pdf_bytes, re.S)][-1].decode('latin-1')
    out, font, size = [], None, None
    for m in re.finditer(r'/(F\d+) ([\d.]+) Tf|\((.*?)\) Tj', stream):
        if m.group(1):
            font, size = names.get(m.group(1), m.group(1)), float(m.group(2))
        else:
            out.append((font, size, m.group(3)))
    return out


def test_the_bid_column_is_drawn_in_the_font_it_was_measured_in(tmp_path):
    # The BID cell is bold 7 - larger and heavier than RANK/LEFT/DISCR at 6 and
    # the tie cells at 5.5 - because it is what the eye lands on to find a row.
    # Pinned as DRAWN, not as bytes present somewhere on the page.
    drawn = _drawn_fonts(rendered(tmp_path))
    bids = set("$%d" % o.bid for o in outcomes())
    seen = [(f, s, t) for f, s, t in drawn if t in bids]
    assert len(seen) >= 20, "expected every candidate bid to be drawn"
    for font, size, text in seen:
        assert (font, size) == ("Helvetica-Bold", 7.0), \
            "%s drew in %s %s, not Helvetica-Bold 7" % (text, font, size)

    # ...and it really is the heaviest thing in its row: nothing else on the
    # page's table is bold at 7 or larger except the block's own headings.
    weights = set((f, s) for f, s, t in drawn if t in ("100%", "no data", "1,2,2,2"))
    assert weights and all(f == "Helvetica" and s == 5.5 for f, s in weights)


def test_every_cell_sets_its_own_font_and_inherits_nothing(tmp_path):
    """The bug generalises: nine `_cell` calls and two `_line` loops.

    Each was correct only because an unrelated `setFont` happened to precede
    its group. Assert the property instead - the font in effect at every draw
    is the font that draw asked for - by checking the whole table row by row.
    """
    drawn = _drawn_fonts(rendered(tmp_path))
    out = outcomes()
    expected = {}
    for o in out:
        expected["$%d" % o.bid] = ("Helvetica-Bold", 7.0)
        expected["$%d" % o.budget_left] = ("Helvetica", 6.0)
        expected["$%d" % o.discretionary] = ("Helvetica", 6.0)
    # LEFT/DISCR collide with no bid value on this board ($26-$45 vs $53-$84).
    assert not (set("$%d" % o.bid for o in out)
                & set("$%d" % o.budget_left for o in out))
    for font, size, text in drawn:
        if text in expected:
            assert (font, size) == expected[text], \
                "%r drew in %s %s, expected %s" % (text, font, size,
                                                   expected[text])

    # `_line` has the same hazard and the same fix: the notes follow the
    # block's bold-8 heading and the legend follows a 5.5pt table cell, so
    # dropping its setFont draws prose in whatever the neighbour left behind.
    prose = dict((t, (f, s)) for f, s, t in drawn)
    note = "bid order, which also sets nomination control all draft."
    legend = ("*LEFT and DISCR are PRE-BUMP: win a tie and the bump comes out "
              "of them too.")
    assert prose.get(note) == ("Helvetica", 5.8), \
        "note drew in %s" % (prose.get(note),)
    assert prose.get(legend) == ("Helvetica", 5.2), \
        "legend drew in %s" % (prose.get(legend),)


def test_the_legend_takes_its_denominator_from_the_file_not_a_typed_five(tmp_path):
    # "share of the 5 years" is right until 2026's twelve rows are appended,
    # at which point the page states a wrong denominator for numbers a bidder
    # is about to act on. It comes off the outcome, which took it from the file.
    out = outcomes()
    assert out[0].years == 5, "the tracked file holds 2021-2025"
    assert b"share of the 5 years" in rendered(tmp_path)

    # Six years of history moves the legend without anyone editing wording.
    from sffl.render.pdf import render_pdf
    import dataclasses
    six = [dataclasses.replace(o, years=6) for o in out]
    path = str(tmp_path / "six.pdf")
    render_pdf(LG, board(), path, outcomes=six)
    data = read(path)
    assert b"share of the 6 years" in data
    assert b"share of the 5 years" not in data


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

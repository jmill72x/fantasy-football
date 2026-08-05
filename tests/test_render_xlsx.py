import re

import openpyxl
import pytest

from sffl.league import load_league
from sffl.render.rows import BoardRow
from sffl.render.xlsx import render_xlsx

LG = load_league("leagues/sffl/2026.yaml")


def row(rank, name, pos, dollars, est=None):
    return BoardRow(rank=rank, name=name, team="GB", bye=11, pos=pos, tier=1,
                    avg_pts=10.0, my_dollars=float(dollars), est_price=est)


def board():
    rows, n = [], 1
    for pos, count in (("RB", 40), ("WR", 60), ("TE", 20),
                       ("TQB", 32), ("K", 32), ("DST", 32)):
        for i in range(count):
            rows.append(row(n, "%s %d" % (pos, i), pos, 60.0 - 0.2 * n,
                            est=40.0 - 0.15 * n))
            n += 1
    return rows


def test_writes_a_landscape_letter_sheet(tmp_path):
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    ws = openpyxl.load_workbook(path).active
    assert ws.page_setup.orientation == "landscape"
    assert ws.sheet_view.showGridLines is False


def test_header_row_carries_the_agreed_columns(tmp_path):
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    ws = openpyxl.load_workbook(path).active
    headers = [ws.cell(2, c).value for c in range(1, 9)]
    assert headers == ["Rank", "Name", "Team/Bye", "Pos", "Tier",
                       "AVG", "MY$", "EST$"]


def test_team_and_bye_are_one_cell(tmp_path):
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    ws = openpyxl.load_workbook(path).active
    assert ws.cell(3, 3).value == "GB/11"


def test_font_is_calibri_8(tmp_path):
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    ws = openpyxl.load_workbook(path).active
    assert ws.cell(3, 2).font.name == "Calibri"
    assert ws.cell(3, 2).font.sz == 8


def test_missing_est_price_is_blank_not_zero(tmp_path):
    rows = [row(i, "P%d" % i, "RB", 10.0, est=None) for i in range(1, 20)]
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, rows, path)
    ws = openpyxl.load_workbook(path).active
    assert ws.cell(3, 8).value in (None, "")


def test_an_empty_board_raises(tmp_path):
    with pytest.raises(ValueError):
        render_xlsx(LG, [], str(tmp_path / "board.xlsx"))


def big_board():
    """Big enough to overflow ROW_BUDGET (532 TQB/RB/WR/TE rows against a
    248-row Overall capacity), so the truncation path actually runs."""
    rows, n = [], 1
    for pos, count in (("RB", 200), ("WR", 200), ("TE", 100),
                       ("TQB", 32), ("K", 32), ("DST", 32)):
        for i in range(count):
            rows.append(row(n, "%s %d" % (pos, i), pos, 300.0 - 0.2 * n,
                            est=150.0 - 0.1 * n))
            n += 1
    return rows


def lean_board():
    """A board whose Overall pool is SMALLER than the Overall Board's own
    capacity (100 TQB/RB/WR/TE rows against a 124-row capacity) while
    Running Backs and Receivers still overflow group 3's allocation - so
    the continuation blocks must run, and must start immediately below a
    short Overall Board rather than at a fixed fraction of the budget."""
    rows, n = [], 1
    for pos, count in (("RB", 40), ("WR", 40), ("TE", 10),
                       ("TQB", 10), ("K", 32), ("DST", 32)):
        for i in range(count):
            rows.append(row(n, "%s %d" % (pos, i), pos, 300.0 - 0.2 * n,
                            est=150.0 - 0.1 * n))
            n += 1
    return rows


def _populated_rows(ws, col0):
    """Row numbers carrying content in a column group's first (Rank) column.
    Every row this module writes - title, header or data - populates it, so
    it is the one column that reports a group's real vertical extent."""
    return [r for r in range(1, ws.max_row + 1)
            if ws.cell(r, col0).value not in (None, "")]


def _assert_no_interior_gap(ws, col0, allow_empty=False):
    """A column must be solid from row 1 down to its last populated row. A
    column that is full at the bottom but holed in the middle is the same
    defect as one that stops short, wearing a disguise - blank printed rows
    while players are being cut.

    ONE exception, and it is bounded on all sides: a run of blank rows that
    ends exactly on the page break and is shorter than PAGE_ALIGN_SLACK.
    That is the fold, not a hole. It appears only when a section ran out of
    players a few rows above the break and the section below it would
    otherwise have opened there - printing its title and column header at
    the foot of one sheet with every player on the next, which is the shape
    Jeff rejected. See sffl.render.xlsx._continuation_start. Anything wider,
    or anywhere else in the column, is still the old defect.

    `allow_empty` permits a wholly unwritten column, which is only correct
    when the section that owns it has no members at all (an Overall pool of
    zero leaves groups 1 and 2 untouched). Every caller rendering a real
    board leaves it False - there, an empty column is itself the bug.
    """
    from sffl.render.xlsx import PAGE_ALIGN_SLACK, ROWS_PER_PAGE

    used = _populated_rows(ws, col0)
    if not used:
        assert allow_empty, "column %d is entirely empty" % col0
        return
    missing = sorted(set(range(1, used[-1] + 1)) - set(used))
    if missing:
        fold = list(range(missing[0], ROWS_PER_PAGE + 1))
        assert missing == fold and len(missing) < PAGE_ALIGN_SLACK, (
            "column %d has blank row(s) %s above its last populated row (%d) - "
            "a hole in the middle of a printed column" % (col0, missing, used[-1]))


def test_workbook_stays_within_the_two_page_row_budget(tmp_path):
    # The regression this guards against: a future change to margins, scale
    # or row height silently pushing the sheet past two printed pages again.
    # This recomputes the budget the same way render_xlsx does, rather than
    # hardcoding a row count, so it stays correct if that geometry changes.
    from sffl.render.xlsx import GROUP_GAP, ROW_BUDGET

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        used = 0
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, col0).value not in (None, ""):
                used = r
        assert used <= ROW_BUDGET, (
            "column %d used %d rows, exceeding the %d-row two-page budget"
            % (col0, used, ROW_BUDGET))


def test_render_xlsx_reports_what_it_truncated(tmp_path):
    rows = big_board()
    overall_total = sum(1 for r in rows if r.pos in ("TQB", "RB", "WR", "TE"))
    path = str(tmp_path / "board.xlsx")
    stats = render_xlsx(LG, rows, path)

    assert stats["total"] == len(rows)
    assert stats["overall"]["shown"] + stats["overall"]["cut"] == overall_total
    assert stats["overall"]["cut"] > 0, "this board was built to overflow the budget"

    # Every position with real members must be reported, and shown > 0 -
    # a section present with zero rows is the exact bug a first version of
    # this module had (see test_every_position_appears_on_the_printed_sheet).
    for title in ("TEAM QB", "RUNNING BACKS", "RECEIVERS (WR + TE)", "KICKERS", "TEAM DEFENSE"):
        assert title in stats["sections"], "%s missing from the truncation report" % title
        assert stats["sections"][title]["shown"] > 0, "%s got zero rows" % title


def test_every_position_appears_on_the_printed_sheet(tmp_path):
    # The regression this guards against: a first version of this module
    # filled group 3 greedily in POSITION_BLOCKS order and spent the whole
    # row budget on Team QB plus part of Running Backs, leaving Receivers -
    # the largest position group in this league - Kickers and Team Defense
    # off the sheet entirely (not even a title). This must fail against
    # that code.
    from sffl.render.xlsx import POSITION_BLOCKS

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    titles_present = set()
    for row_cells in ws.iter_rows():
        for cell in row_cells:
            if isinstance(cell.value, str):
                titles_present.add(cell.value)

    for title, _positions in POSITION_BLOCKS:
        assert title in titles_present, "%s is missing from the printed sheet" % title


def test_no_column_stops_short_of_the_budget_while_players_are_cut(tmp_path):
    # The regression this guards against: capping the Overall Board at half
    # of groups 1 and 2 freed 124 rows (close to half the printed sheet)
    # that a second version of this module left blank, while the same run
    # was cutting 105 Running Backs and 256 Receivers. A column may stop
    # short of the budget only once it has run out of players to show for
    # every section that uses it - never while there is still content that
    # would fit. big_board() has far more RB/Receivers than any budget can
    # hold, so every column here should reach ROW_BUDGET exactly.
    from sffl.render.xlsx import GROUP_GAP, ROW_BUDGET

    path = str(tmp_path / "board.xlsx")
    stats = render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    any_cut = stats["overall"]["cut"] > 0 or any(
        s["cut"] > 0 for s in stats["sections"].values())
    assert any_cut, "this board was built to overflow every budget - if " \
        "nothing was cut, the test proves nothing"

    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        used = _populated_rows(ws, col0)
        last = used[-1] if used else 0
        assert last == ROW_BUDGET, (
            "column %d stopped at row %d, short of the %d-row budget, "
            "while players are still being cut" % (col0, last, ROW_BUDGET))
        # Reaching the budget is not enough. A column can end at row 126 and
        # still waste a block of printed rows in the middle - which is
        # exactly what a fixed continuation start row does as soon as the
        # Overall Board is shorter than its capacity. See
        # test_a_short_overall_board_leaves_no_blank_gap_above_the_continuation.
        _assert_no_interior_gap(ws, col0)


def test_a_short_overall_board_leaves_no_blank_gap_above_the_continuation(tmp_path):
    # The regression this guards against: _write_continuation_block used to
    # start at a FIXED 3 + (ROW_BUDGET - HEADER_ROWS) // 2, independent of
    # how many rows the Overall Board actually wrote. That is only correct
    # while the Overall pool exceeds its capacity, as the production extract
    # does (453 against 124). A leaner extract, a different --policy or a
    # filtered pool can put it under - and then the continuation block still
    # starts at the fixed row, leaving a blank band in the middle of the
    # printed column while the position blocks below are still cutting
    # players. That is the same allocation failure class that shipped three
    # times in this module's history, just triggered by different input.
    from sffl.render.xlsx import GROUP_GAP, _overall_capacity

    rows = lean_board()
    overall_total = sum(1 for r in rows if r.pos in ("TQB", "RB", "WR", "TE"))
    assert overall_total < _overall_capacity(), (
        "this test only proves anything when the Overall pool is smaller "
        "than its capacity (%d vs %d)" % (overall_total, _overall_capacity()))

    path = str(tmp_path / "board.xlsx")
    stats = render_xlsx(LG, rows, path)
    ws = openpyxl.load_workbook(path).active

    assert stats["overall"]["cut"] == 0, "the Overall Board should fit whole here"
    # ... and yet the continuation blocks must still have run, or a passing
    # no-gap assertion below would be vacuous.
    col1, col2 = 1, 1 + GROUP_GAP
    titles = dict((col, [ws.cell(r, col).value for r in _populated_rows(ws, col)])
                  for col in (col1, col2))
    assert "RUNNING BACKS" in titles[col1], (
        "group 1's Running Backs continuation never ran - nothing to gap-check")
    assert "RECEIVERS (WR + TE)" in titles[col2], (
        "group 2's Receivers continuation never ran - nothing to gap-check")

    for col0 in (col1, col2, 1 + 2 * GROUP_GAP):
        _assert_no_interior_gap(ws, col0)


def _sections(ws, col0):
    """[(title, start_row, end_row)] for one column group.

    A section title is the only thing this module writes into a group's
    first column without also writing a Name beside it, so that is what
    identifies one.
    """
    used = _populated_rows(ws, col0)
    if not used:
        return []
    starts = [r for r in used
              if isinstance(ws.cell(r, col0).value, str)
              and ws.cell(r, col0).value != "Rank"
              and ws.cell(r, col0 + 1).value in (None, "")]
    out = []
    for i, start in enumerate(starts):
        end = starts[i + 1] - 1 if i + 1 < len(starts) else used[-1]
        out.append((ws.cell(start, col0).value, start, end))
    return out


def _assert_no_section_opens_on_the_fold(ws):
    """The defect Jeff reported, stated exactly: no block may open within
    PAGE_ALIGN_SLACK rows of a page break and then continue past it.

    That is what printed as "some RBs and WRs on the same page, and then
    the rest of the RBs on the next page" - group 3's Receivers block used
    to open at row 54, nine rows above the break, and run to 98, so page 1
    ended with a stub of receivers under the running backs and page 2
    carried the rest of them while group 1 was still listing running backs
    alongside. A long block that opens well clear of the break and runs
    over it is fine: that is one list continuing over the fold, not two
    sections interleaved.
    """
    from sffl.render.xlsx import GROUP_GAP, PAGE_ALIGN_SLACK, ROWS_PER_PAGE

    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        for title, start, end in _sections(ws, col0):
            break_row = (start - 1) // ROWS_PER_PAGE * ROWS_PER_PAGE + ROWS_PER_PAGE
            if end <= break_row:
                continue      # whole block sits on one page
            assert break_row - start >= PAGE_ALIGN_SLACK, (
                "column %d: %s opens at row %d, only %d row(s) above the page "
                "break at %d, and runs to %d - its title and column header "
                "print at the foot of one sheet with its players on the next"
                % (col0, title, start, break_row - start, break_row, end))


def _assert_no_section_straddles_the_fold_unless_it_is_last(ws):
    """The invariant that actually states Jeff's complaint.

    A section may run over the page break only if nothing follows it in its
    column - then it is one list continuing over the fold, which is fine and
    is what the continuation blocks do. A section that straddles the break
    WITH another section under it means the reader gets the tail of one
    position at the top of page 2 and a different position below it, while
    the facing column is still listing the first position: "you put some RBs
    and WRs on the same page, and then split the rest of the RBs on the next
    page, rather than using the real estate where you put the WRs for more
    RBs."

    Both defects reported against the first version fail this and pass the
    five-row check above, which is why both checks exist: the Overall Board
    ran 1-64, one row past the break with a continuation under it, and group
    3's Receivers ran 54-98 with Kickers and Team Defense under them.
    """
    from sffl.render.xlsx import GROUP_GAP, ROWS_PER_PAGE

    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        sections = _sections(ws, col0)
        for i, (title, start, end) in enumerate(sections):
            is_last = (i + 1 == len(sections))
            break_row = (start - 1) // ROWS_PER_PAGE * ROWS_PER_PAGE + ROWS_PER_PAGE
            if end <= break_row or is_last:
                continue
            assert False, (
                "column %d: %s runs %d-%d, across the page break at %d, with "
                "%s under it - two positions interleaved across the fold"
                % (col0, title, start, end, break_row, sections[i + 1][0]))


def test_no_section_opens_beside_the_page_break_and_continues_past_it(tmp_path):
    from sffl.render.xlsx import GROUP_GAP, ROWS_PER_PAGE

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    # Not vacuous: this board fills both pages of all three groups, so
    # there are blocks on either side of the break to get wrong.
    assert _populated_rows(ws, 1 + 2 * GROUP_GAP)[-1] > ROWS_PER_PAGE
    assert len(_sections(ws, 1 + 2 * GROUP_GAP)) >= 4
    _assert_no_section_opens_on_the_fold(ws)
    _assert_no_section_straddles_the_fold_unless_it_is_last(ws)


def test_group_3_position_blocks_are_each_whole_on_one_printed_page(tmp_path):
    # The 2022 template stacks its position blocks so every boundary lands
    # on its own page break (59/60). Ours must too: group 3 is a stack of
    # DIFFERENT positions, so a block spilling over the fold always puts two
    # of them on the same sheet for no reason. The first version opened
    # Receivers at row 54, nine rows above the break, and ran it to 98.
    from sffl.render.xlsx import GROUP_GAP, ROWS_PER_PAGE

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    col0 = 1 + 2 * GROUP_GAP
    sections = _sections(ws, col0)
    assert len(sections) == 5, "expected all five position blocks, got %s" % sections
    for title, start, end in sections:
        assert (start - 1) // ROWS_PER_PAGE == (end - 1) // ROWS_PER_PAGE, (
            "%s runs %d-%d and straddles the page break at %d"
            % (title, start, end, ROWS_PER_PAGE))


def test_no_section_opens_beside_the_page_break_for_any_pool_size(tmp_path):
    # The fold defect is a boundary bug like the gap one above: whether a
    # block lands on the break at all depends on how much content sits over
    # it, so a single fixture proves very little. Sweep the pool size.
    from sffl.render.xlsx import _overall_capacity

    cap = _overall_capacity()
    for total in (1, 2, 8, 30, cap // 2, cap - 3, cap - 1, cap, cap + 1,
                  cap * 2, cap * 4):
        rb_n = total // 2
        tqb_n = min(total // 8, 32)
        wr_n = total - rb_n - tqb_n
        rows, n = [], 1
        for pos, count in (("RB", rb_n), ("WR", wr_n), ("TE", total // 10),
                           ("TQB", tqb_n), ("K", 32), ("DST", 32)):
            for i in range(count):
                rows.append(row(n, "%s %d" % (pos, i), pos, 300.0 - 0.1 * n,
                                est=150.0))
                n += 1

        path = str(tmp_path / ("fold-%d.xlsx" % total))
        render_xlsx(LG, rows, path)
        ws = openpyxl.load_workbook(path).active
        try:
            _assert_no_section_opens_on_the_fold(ws)
            _assert_no_section_straddles_the_fold_unless_it_is_last(ws)
        except AssertionError as e:
            raise AssertionError("overall pool of %d: %s" % (total, e))


def test_a_continuation_pushed_off_the_fold_leaves_no_more_than_the_fold(tmp_path):
    # The one blank band this module may leave, bounded on purpose. An
    # Overall Board that stops a few rows above the break pushes the
    # continuation under it to the top of the next page; the rows in
    # between are blank. They must be fewer than PAGE_ALIGN_SLACK and must
    # end exactly ON the break - anything wider or anywhere else is the
    # blank-band defect this module shipped three times.
    from sffl.render.xlsx import (GROUP_GAP, PAGE_ALIGN_SLACK, ROWS_PER_PAGE,
                                  _overall_capacity)

    cap = _overall_capacity()
    saw_a_fold_gap = False
    for total in range(cap - 8, cap + 1):
        rows, n = [], 1
        # Overall pool of exactly `total`, plus enough RB/receivers below to
        # guarantee both continuations have something to write.
        for pos, count in (("RB", total // 2), ("WR", total - total // 2),
                           ("K", 32), ("DST", 32)):
            for i in range(count):
                rows.append(row(n, "%s %d" % (pos, i), pos, 300.0 - 0.1 * n,
                                est=150.0))
                n += 1
        path = str(tmp_path / ("fold-gap-%d.xlsx" % total))
        render_xlsx(LG, rows, path)
        ws = openpyxl.load_workbook(path).active

        for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
            used = _populated_rows(ws, col0)
            missing = sorted(set(range(1, used[-1] + 1)) - set(used))
            if missing:
                saw_a_fold_gap = True
                assert missing[-1] == ROWS_PER_PAGE, (
                    "pool %d, column %d: blank rows %s do not end on the page "
                    "break" % (total, col0, missing))
                assert len(missing) < PAGE_ALIGN_SLACK, (
                    "pool %d, column %d: %d blank rows, wider than the fold"
                    % (total, col0, len(missing)))
        _assert_no_section_opens_on_the_fold(ws)
        _assert_no_section_straddles_the_fold_unless_it_is_last(ws)

    assert saw_a_fold_gap, (
        "no pool size in this sweep pushed a continuation off the fold, so "
        "the bound above was never exercised")


def test_every_cell_in_the_used_rectangle_carries_the_ruled_border(tmp_path):
    # The biggest miss in the first version: the 2022 template switches
    # Excel's screen gridlines off AND draws an explicit thin border on all
    # four sides of every cell in its used rectangle (2,360 of them over
    # A1:T118). Only the gridline flag was carried across, so the printed
    # board had no rules on it at all.
    from sffl.render.xlsx import GROUP_GAP, N_COLS

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    last_col = 1 + 2 * GROUP_GAP + N_COLS - 1
    last_row = max(_populated_rows(ws, c)[-1]
                   for c in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP))
    assert last_row > 1 and last_col == 26

    missing = []
    for r in range(1, last_row + 1):
        for c in range(1, last_col + 1):
            b = ws.cell(r, c).border
            if not all(getattr(b, side) is not None
                       and getattr(b, side).style == "thin"
                       for side in ("left", "right", "top", "bottom")):
                missing.append((r, c))
    assert not missing, (
        "%d cell(s) in the used rectangle carry no thin border, e.g. %s"
        % (len(missing), missing[:5]))

    # Spacer columns too - the template rules them like everything else.
    for spacer in (1 + N_COLS, 1 + GROUP_GAP + N_COLS):
        assert ws.cell(5, spacer).border.left.style == "thin"


def test_a_bordered_blank_row_still_carries_the_measured_row_height(tmp_path):
    # Bordering a blank row makes Excel treat it as used, so it prints. Left
    # at Excel's 15pt default it would be half again as tall as the 9.95pt
    # the whole two-page geometry is computed from, and would push the foot
    # of page 2 onto a third sheet.
    from sffl.render.xlsx import GROUP_GAP, ROW_HEIGHT

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    last_row = max(_populated_rows(ws, c)[-1]
                   for c in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP))
    for r in range(1, last_row + 1):
        assert ws.row_dimensions[r].height == ROW_HEIGHT, (
            "row %d is %s pt, not the measured %s"
            % (r, ws.row_dimensions[r].height, ROW_HEIGHT))


def test_section_title_and_header_rows_carry_the_white_fill(tmp_path):
    # 134 solid fills in the template, all indexed colour 9 (white), on
    # exactly the section-title row and the column-header row of every
    # block, full group width.
    from sffl.render.xlsx import GROUP_GAP, N_COLS

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    checked = 0
    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        for title, start, _end in _sections(ws, col0):
            for r in (start, start + 1):
                for i in range(N_COLS):
                    fill = ws.cell(r, col0 + i).fill
                    assert fill.fill_type == "solid", (
                        "%s row %d col %d carries no fill"
                        % (title, r, col0 + i))
                    assert fill.fgColor.rgb == "FFFFFFFF", (
                        "%s row %d col %d is %s, not white"
                        % (title, r, col0 + i, fill.fgColor.rgb))
            checked += 1
    assert checked >= 7, "expected every block on the sheet to be checked"

    # ...and nowhere else. The template has no tier shading; an earlier note
    # claiming conditional formatting drove tier colour was wrong.
    for r in range(3, 20):
        assert ws.cell(r, 1).fill.fill_type != "solid", (
            "row %d is a data row and must carry no fill" % r)


def test_pos_column_carries_positional_rank_not_bare_position(tmp_path):
    # The template writes RB1, WR24, TE6 - the rank within the position,
    # which is both what you want to read across the table and what makes
    # the conditional colouring possible.
    from sffl.render.xlsx import GROUP_GAP

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    ws = openpyxl.load_workbook(path).active

    pos_col = 4
    labels = [ws.cell(r, pos_col).value for r in range(3, 60)]
    assert all(re.match(r"^(TQB|RB|WR|TE|K|DST)\d+$", str(v)) for v in labels), \
        "Pos column must read like RB1/WR24, got %s" % labels[:8]

    # Ranked by MY$ descending within the position, from 1, no gaps: the
    # board() fixture's dollars descend with rank, so the first RB written
    # anywhere is RB1.
    seen = {}
    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        for r in _populated_rows(ws, col0):
            v = ws.cell(r, col0 + 3).value
            m = re.match(r"^([A-Z]+)(\d+)$", str(v or ""))
            if m:
                seen.setdefault(m.group(1), set()).add(int(m.group(2)))
    for pos in ("RB", "WR", "TE", "TQB", "K", "DST"):
        assert pos in seen, "no %s ever labelled with a rank" % pos
        assert 1 in seen[pos], "%s never reaches rank 1" % pos


def test_wr_and_te_are_ranked_separately_in_the_pos_column_only(tmp_path):
    # WR and TE are ONE pool for valuation and stay one - same tier ladder,
    # same dollars, one RECEIVERS block. The template nonetheless ranks them
    # separately in this column (WR24, TE6), because "he is the WR31" tells
    # you nothing about the tight ends left on the board.
    from sffl.render.xlsx import GROUP_GAP, POSITION_BLOCKS

    rows = board()
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, rows, path)
    ws = openpyxl.load_workbook(path).active

    labels = []
    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        for r in _populated_rows(ws, col0):
            labels.append(str(ws.cell(r, col0 + 3).value))
    te = sorted(int(v[2:]) for v in set(labels) if re.match(r"^TE\d+$", v))
    wr = sorted(int(v[2:]) for v in set(labels) if re.match(r"^WR\d+$", v))
    assert te and te[0] == 1, "tight ends must be ranked from TE1, got %s" % te[:5]
    assert wr and wr[0] == 1, "receivers must be ranked from WR1, got %s" % wr[:5]

    # ...and they still share one block and one pool.
    titles = dict((t, p) for t, p in POSITION_BLOCKS)
    assert titles["RECEIVERS (WR + TE)"] == ("WR", "TE")


def test_position_colour_rules_are_attached_to_every_pos_column(tmp_path):
    # Position colour comes from conditional formatting keyed on the Pos
    # column's TEXT, exactly as the template does it - so the colour follows
    # the label with nothing to re-derive if the board is re-ranked.
    from openpyxl.utils import get_column_letter

    from sffl.render.xlsx import GROUP_GAP, POS_FILL_COLORS

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    found = {}
    for rng in ws.conditional_formatting:
        for rule in rng.rules:
            assert rule.operator == "between", rule.operator
            found.setdefault(str(rng.sqref).split(":")[0].rstrip("0123456789"),
                             []).append((tuple(rule.formula), rule))

    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        letter = get_column_letter(col0 + 3)
        assert letter in found, "no rules on group %d's Pos column (%s)" % (col0, letter)
        formulas = [f for f, _rule in found[letter]]
        for pos, rgb in POS_FILL_COLORS:
            want = ('"%s1"' % pos, '"%s99"' % pos)
            assert want in formulas, (
                "column %s has no rule for %s, only %s" % (letter, pos, formulas))
            rule = dict(found[letter])[want]
            assert rule.dxf is not None and rule.dxf.fill is not None, (
                "%s's rule on column %s carries no fill" % (pos, letter))


def test_no_column_is_ever_gapped_across_the_overall_capacity_boundary(tmp_path):
    # A sweep rather than a single fixture, because the fixed-start-row
    # defect is a boundary bug: it is invisible while the Overall pool
    # exceeds its capacity (the production case, 453 against 124) and
    # appears as soon as it lands under. Walk the pool size across that
    # boundary and check every column of every rendered sheet.
    #
    # This is committed and runs in the suite rather than living in a
    # throwaway script, so the claim stays checkable.
    from sffl.render.xlsx import GROUP_GAP, ROW_BUDGET, _overall_capacity

    cap = _overall_capacity()
    sizes = [0, 1, 2, 8, 30, cap // 2 - 1, cap // 2, cap // 2 + 1,
             cap - 2, cap - 1, cap, cap + 1, cap + 2, cap * 2, cap * 4]

    checked = 0
    for total in sizes:
        # Split the Overall pool across all four of its positions, so RB and
        # Receivers both have members to continue and TQB is realistic.
        rb_n = total // 2
        wr_n = total - rb_n - min(total // 8, 32)
        tqb_n = min(total // 8, 32)
        rows, n = [], 1
        for pos, count in (("RB", rb_n), ("WR", wr_n), ("TE", 0),
                           ("TQB", tqb_n), ("K", 32), ("DST", 32)):
            for i in range(count):
                rows.append(row(n, "%s %d" % (pos, i), pos, 300.0 - 0.1 * n,
                                est=150.0))
                n += 1

        path = str(tmp_path / ("board-%d.xlsx" % total))
        render_xlsx(LG, rows, path)
        ws = openpyxl.load_workbook(path).active
        for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
            used = _populated_rows(ws, col0)
            assert not used or used[-1] <= ROW_BUDGET, (
                "overall pool %d: column %d ran to row %d, past the %d-row "
                "budget" % (total, col0, used[-1], ROW_BUDGET))
            try:
                # An Overall pool of zero legitimately leaves groups 1 and 2
                # untouched - there is no section to gap.
                _assert_no_interior_gap(ws, col0, allow_empty=(total == 0))
            except AssertionError as e:
                raise AssertionError("overall pool of %d: %s" % (total, e))
        checked += 1

    assert checked == len(sizes)

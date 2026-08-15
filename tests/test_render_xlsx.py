import re
import xml.etree.ElementTree as ET
import zipfile

import openpyxl
import pytest
from openpyxl.utils import coordinate_to_tuple, get_column_letter

from sffl.league import load_league
from sffl.render.rows import BoardRow
from sffl.render.xlsx import render_xlsx

LG = load_league("leagues/sffl/2026.yaml")

SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def disk_styles(path):
    """{(row, col): (Border, PatternFill)} read from the saved FILE, not from
    openpyxl's in-memory view of it.

    Needed because the section titles are merged across their column group
    (see sffl.render.xlsx._write_title) and openpyxl's READER throws the
    style of every merged-away cell away: it replaces those cells with fresh,
    default-styled MergedCell objects on load. The styles are still in the
    .xlsx - each cell carries its `s=` index into xl/styles.xml, which is
    what Excel draws from - so the border and fill assertions below resolve
    that index themselves rather than believing openpyxl's reconstruction.
    Checking the bytes on disk is what the invariant was always about.
    """
    wb = openpyxl.load_workbook(path)
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    out = {}
    for c in root.iter(SHEET_NS + "c"):
        r, col = coordinate_to_tuple(c.get("r"))
        style = wb._cell_styles[int(c.get("s") or 0)]
        out[(r, col)] = (wb._borders[style.borderId], wb._fills[style.fillId])
    return out


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

    styles = disk_styles(path)
    missing = []
    for r in range(1, last_row + 1):
        for c in range(1, last_col + 1):
            entry = styles.get((r, c))
            b = entry[0] if entry else None
            if b is None or not all(getattr(b, side) is not None
                                    and getattr(b, side).style == "thin"
                                    for side in ("left", "right", "top", "bottom")):
                missing.append((r, c))
    assert not missing, (
        "%d cell(s) in the used rectangle carry no thin border, e.g. %s"
        % (len(missing), missing[:5]))

    # Spacer columns too - the template rules them like everything else.
    for spacer in (1 + N_COLS, 1 + GROUP_GAP + N_COLS):
        assert styles[(5, spacer)][0].left.style == "thin"


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

    styles = disk_styles(path)
    checked = 0
    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        for title, start, _end in _sections(ws, col0):
            for r in (start, start + 1):
                for i in range(N_COLS):
                    fill = styles[(r, col0 + i)][1]
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
        assert styles[(r, 1)][1].fill_type != "solid", (
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


# --------------------------------------------------------------------------
# Reading order across a position that occupies two blocks.
# --------------------------------------------------------------------------

def _blocks_by_title(ws):
    """{title: [(page, col0, start_row, [Rank values in order])]} over all
    three column groups, one entry per block written for that title.

    Rank is the board's own overall rank, and every block writes its members
    ordered by MY$ descending - which build_rows made the same ordering as
    Rank ascending. So a block's Rank list rising, and the list of one block
    sitting wholly below another's, is exactly "these players come first".
    """
    from sffl.render.xlsx import GROUP_GAP, ROWS_PER_PAGE

    out = {}
    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        for title, start, end in _sections(ws, col0):
            ranks = [ws.cell(r, col0).value for r in range(start + 2, end + 1)
                     if ws.cell(r, col0 + 1).value not in (None, "")]
            page = (start - 1) // ROWS_PER_PAGE
            out.setdefault(title, []).append((page, col0, start, ranks))
    return out


def _assert_reading_order(ws):
    """The defect Jeff reported, stated as an invariant.

    "You have the WR columns out of order, the first WRs are on the right of
    the 2nd column of WRs." Two statements, and the second is the sharp one:

      1. GLOBALLY, a position's blocks taken in reading order - all of page 1
         left to right, then all of page 2 left to right - must hand out its
         players in descending value, with no block repeating or skipping
         back. That is the whole list read the way the sheet is read.
      2. WITHIN ONE PAGE, of two blocks of the same position, the one in the
         left column must hold strictly earlier-ranked players. This is what
         actually failed: on page 2 group 3 opened at WR1 while group 2, to
         its left, opened at WR29.

    Check 2 is not implied by check 1 as a matter of arithmetic, but the
    reverse would let a fix that merely reversed the columns pass, so both
    are asserted.
    """
    for title, blocks in _blocks_by_title(ws).items():
        if title == "OVERALL":
            # Same rule, and it is checked here too - the Overall Board is
            # one list split across groups 1 and 2 exactly like a position.
            pass
        in_reading_order = sorted(blocks, key=lambda b: (b[0], b[1]))
        seen = []
        for _page, col0, _start, ranks in in_reading_order:
            assert ranks == sorted(ranks), (
                "%s: the block at column %d is not itself in board order"
                % (title, col0))
            seen.extend(ranks)
        assert seen == sorted(seen), (
            "%s: read page by page, left to right, its blocks give ranks out "
            "of order - %s" % (title, [(b[1], b[3][:1], b[3][-1:]) for b in in_reading_order]))
        assert len(set(seen)) == len(seen), (
            "%s: a player is listed in more than one of its blocks" % title)

        by_page = {}
        for page, col0, _start, ranks in blocks:
            by_page.setdefault(page, []).append((col0, ranks))
        for page, cols in by_page.items():
            cols.sort()
            for i in range(1, len(cols)):
                left_col, left = cols[i - 1]
                right_col, right = cols[i]
                if not left or not right:
                    continue
                assert max(left) < min(right), (
                    "%s on page %d: column %d holds ranks %d-%d and column "
                    "%d, to its RIGHT, holds %d-%d - the earlier players are "
                    "in the right-hand column"
                    % (title, page + 1, left_col, min(left), max(left),
                       right_col, min(right), max(right)))


def test_a_split_position_fills_its_blocks_in_reading_order(tmp_path):
    # Jeff, on the shipped file: "you have the WR columns out of order, the
    # first WRs are on the right of the 2nd column of WRs." Group 3's
    # RECEIVERS block opened at WR1 on page 2 while group 2 - the column to
    # its LEFT on the same page - opened at WR29.
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    blocks = _blocks_by_title(ws)
    # Not vacuous: both flex positions must really occupy two blocks here.
    for title in ("RUNNING BACKS", "RECEIVERS (WR + TE)"):
        assert len(blocks[title]) == 2, (
            "%s should be split across two blocks, got %s"
            % (title, [(b[1], b[2]) for b in blocks[title]]))
    _assert_reading_order(ws)


def test_receivers_lead_in_the_left_hand_column_of_page_two(tmp_path):
    # The same defect pinned to the exact geometry it appeared in, so this
    # test still fails if _reading_order_key is deleted and the generic
    # invariant above is somehow satisfied another way. Both RECEIVERS
    # blocks open on page 2; the left one (group 2) must lead.
    from sffl.render.xlsx import GROUP_GAP, ROWS_PER_PAGE

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    blocks = dict((b[1], b) for b in _blocks_by_title(ws)["RECEIVERS (WR + TE)"])
    col2, col3 = 1 + GROUP_GAP, 1 + 2 * GROUP_GAP
    assert set(blocks) == set([col2, col3])
    assert blocks[col2][0] == blocks[col3][0] == 1, (
        "this test only says anything while both receiver blocks open on "
        "page 2, got start rows %d and %d against a %d-row page"
        % (blocks[col2][2], blocks[col3][2], ROWS_PER_PAGE))
    assert max(blocks[col2][3]) < min(blocks[col3][3]), (
        "group 2 holds ranks %s and group 3 holds %s"
        % (blocks[col2][3][:2], blocks[col3][3][:2]))


def test_running_backs_keep_their_page_one_block_first(tmp_path):
    # The mirror-image mistake, and the reason _reading_order_key sorts on
    # the PAGE before the column. Running Backs occupies group 3 on page 1
    # and group 1 on page 2; a reader finishes page 1 before starting page 2,
    # so group 3's block leads even though group 1 is further left. Ordering
    # on the column alone would print RB1 overleaf from RB28.
    from sffl.render.xlsx import GROUP_GAP, ROWS_PER_PAGE

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    blocks = dict((b[1], b) for b in _blocks_by_title(ws)["RUNNING BACKS"])
    col1, col3 = 1, 1 + 2 * GROUP_GAP
    assert set(blocks) == set([col1, col3])
    assert blocks[col3][0] == 0 and blocks[col1][0] == 1, (
        "this test only says anything while group 3's block is on page 1 and "
        "group 1's on page 2 (start rows %d, %d; page is %d rows)"
        % (blocks[col3][2], blocks[col1][2], ROWS_PER_PAGE))
    assert max(blocks[col3][3]) < min(blocks[col1][3]), (
        "page 1's group 3 block holds ranks %s but page 2's group 1 block "
        "holds %s" % (blocks[col3][3][:2], blocks[col1][3][:2]))


def test_reading_order_holds_for_any_pool_size(tmp_path):
    # Which page a block opens on depends on how much sits above it, so one
    # fixture proves little - the RB case and the WR case differ only by
    # that. Sweep the pool size across the Overall Board's capacity.
    from sffl.render.xlsx import _overall_capacity

    cap = _overall_capacity()
    for total in (8, 30, cap // 2, cap - 3, cap - 1, cap, cap + 1, cap * 2,
                  cap * 4):
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

        path = str(tmp_path / ("order-%d.xlsx" % total))
        render_xlsx(LG, rows, path)
        ws = openpyxl.load_workbook(path).active
        try:
            _assert_reading_order(ws)
        except AssertionError as e:
            raise AssertionError("overall pool of %d: %s" % (total, e))


# --------------------------------------------------------------------------
# Section titles stay inside their own column group.
# --------------------------------------------------------------------------

def test_every_section_title_is_merged_across_exactly_its_own_group(tmp_path):
    # Jeff's second defect: titles are written into the group's first cell -
    # the Rank column, 2.8 width units - and Excel spills a too-long string
    # rightwards through every empty cell beside it. "RECEIVERS (WR + TE)"
    # is 19 characters. Merging is what bounds it structurally; nothing else
    # in this layout does, because the neighbouring group's first cell is not
    # guaranteed to be occupied on that row.
    from sffl.render.xlsx import GROUP_GAP, N_COLS

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active

    merged = dict(((m.min_row, m.min_col), m) for m in ws.merged_cells.ranges)
    checked = 0
    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        for title, start, _end in _sections(ws, col0):
            m = merged.get((start, col0))
            assert m is not None, (
                "%s at row %d column %d is not merged - it will spill into "
                "the next column group" % (title, start, col0))
            assert (m.max_col, m.min_row, m.max_row) == (col0 + N_COLS - 1,
                                                         start, start), (
                "%s at row %d spans %s, not exactly its group's %d columns"
                % (title, start, m.coord, N_COLS))
            assert ws.cell(start, col0).alignment.horizontal == "left", (
                "%s is not left-aligned inside its merge" % title)
            checked += 1
    assert checked >= 7, "expected every block on the sheet to be checked"

    # Nothing else on the sheet is merged - a stray merge over data cells
    # would silently swallow a player.
    assert len(ws.merged_cells.ranges) == checked


def test_no_title_is_wider_than_the_group_it_sits_in(tmp_path):
    # The width check behind the merge, so a future title cannot be added
    # that the merge would have to CLIP rather than merely contain. Bounded
    # above, deliberately: TITLE_MAX_CHAR_WIDTH_UNITS assumes every glyph is
    # a full 8pt em, which no Calibri character reaches, so passing here
    # needs no font installed and cannot happen by accident.
    from sffl.render.xlsx import (GROUP_GAP, GROUP_WIDTH, POSITION_BLOCKS,
                                  WIDTHS, _title_width_units)

    # GROUP_WIDTH must be the widths this module actually applies, not a
    # number typed beside them.
    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, big_board(), path)
    ws = openpyxl.load_workbook(path).active
    from openpyxl.utils import get_column_letter
    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        applied = sum(ws.column_dimensions[get_column_letter(c)].width
                      for c in range(col0, col0 + 8))
        assert abs(applied - GROUP_WIDTH) < 1e-9, (
            "group at column %d is %.2f units wide, GROUP_WIDTH says %.2f"
            % (col0, applied, GROUP_WIDTH))
    assert GROUP_WIDTH > WIDTHS["rank"]

    titles = ["OVERALL"] + [t for t, _p in POSITION_BLOCKS]
    # Every title the sheet actually wrote is one of these.
    written = set()
    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        written.update(t for t, _s, _e in _sections(ws, col0))
    assert written <= set(titles), "unexpected title(s): %s" % (written - set(titles))

    for title in titles:
        drawn = _title_width_units(title)
        assert drawn <= GROUP_WIDTH, (
            "%r needs up to %.1f width units, more than the %.1f its column "
            "group has - it would be clipped by the merge"
            % (title, drawn, GROUP_WIDTH))


# --------------------------------------------------------------------------
# Kicker / Team Defense depth.
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# The second worksheet: Key & Intel.
# --------------------------------------------------------------------------

def _intel_sheet(path):
    from sffl.render.xlsx import INTEL_SHEET_TITLE
    return openpyxl.load_workbook(path)[INTEL_SHEET_TITLE]


def _flat_text(ws):
    """Every string on the sheet as one line of text.

    The line breaks inside a cell are this module's own wrapping, not part of
    the sentence, so they are flattened before anything is matched against
    them - otherwise an assertion about a phrase would pass or fail on where
    the wrap happened to fall."""
    return re.sub(r"\s+", " ", " ".join(
        str(c.value) for row_cells in ws.iter_rows() for c in row_cells
        if c.value is not None))


def test_the_workbook_carries_a_second_intel_sheet(tmp_path):
    # The legend goes in the SAME file as the board - one thing to print, and
    # nothing that can be separated from what it explains - but on its own
    # sheet, because the board is full at 126 rows and every legend line
    # written into it would have cost a player.
    from sffl.render.xlsx import INTEL_SHEET_TITLE

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    wb = openpyxl.load_workbook(path)

    assert wb.sheetnames == ["Board", INTEL_SHEET_TITLE]
    # Board stays the sheet the file opens on, and every other test in this
    # module reads `.active` on that assumption.
    assert wb.active.title == "Board"


def test_the_intel_sheet_prints_on_exactly_one_page(tmp_path):
    # Arithmetic against the same page geometry the board's 126-row budget
    # comes from, not a guess: sum the row heights actually applied, undo the
    # print scale, and compare to the printable height of one landscape
    # letter sheet. Same for the columns against its width.
    from sffl.render.xlsx import (INTEL_LINE_PT, INTEL_ROW_BUDGET,
                                  MARGIN_BOTTOM_IN, MARGIN_TOP_IN,
                                  PAGE_HEIGHT_IN, SCALE_PCT, _column_px,
                                  _printable_width_px)

    path = str(tmp_path / "board.xlsx")
    stats = render_xlsx(LG, board(), path)
    ws = _intel_sheet(path)

    # A merged paragraph puts its text in the TOP-LEFT cell only, so the rows
    # under it read as empty - the sheet's real extent is the bottom of the
    # last merge, not the last cell carrying a value.
    last = max([r for r in range(1, ws.max_row + 1)
                if any(ws.cell(r, c).value not in (None, "")
                       for c in range(1, 6))]
               + [m.max_row for m in ws.merged_cells.ranges])
    assert stats["intel"]["rows"] == last
    assert last <= INTEL_ROW_BUDGET

    printed_pt = 0.0
    for r in range(1, last + 1):
        height = ws.row_dimensions[r].height
        assert height == INTEL_LINE_PT, (
            "row %d is %s pt, not the %s the one-page budget is computed from"
            % (r, height, INTEL_LINE_PT))
        printed_pt += height * (SCALE_PCT / 100.0)
    printable_pt = (PAGE_HEIGHT_IN - MARGIN_TOP_IN - MARGIN_BOTTOM_IN) * 72.0
    assert printed_pt <= printable_pt, (
        "the intel sheet prints %.1f pt tall against %.1f pt of page"
        % (printed_pt, printable_pt))

    widths = [ws.column_dimensions[get_column_letter(c)].width
              for c in range(1, 6)]
    assert sum(_column_px(w) for w in widths) <= _printable_width_px()


def test_the_intel_sheet_refuses_to_run_onto_a_second_page(tmp_path,
                                                           monkeypatch):
    # Wrong output must never be produced silently, and a legend whose last
    # paragraph is on a page nobody printed is wrong output. Shrink the budget
    # so the same content overflows it.
    from sffl.render import xlsx as xlsx_mod

    monkeypatch.setattr(xlsx_mod, "INTEL_ROW_BUDGET", 12)
    with pytest.raises(ValueError) as e:
        render_xlsx(LG, board(), str(tmp_path / "board.xlsx"))
    assert "one page" in str(e.value) or "second sheet" in str(e.value)


def test_the_board_sheet_is_untouched_by_the_intel_sheet(tmp_path,
                                                          monkeypatch):
    # THE INVARIANT: adding a second worksheet must not move a byte of the
    # first. openpyxl hands out style and shared-string indices in write
    # order, so this holds only while the intel sheet is written strictly
    # after the board is finished - which is exactly what a future edit could
    # break by, say, defining the legend's fonts earlier. Render the same
    # board with and without the second sheet and compare the board's own
    # worksheet XML byte for byte.
    from sffl.render import xlsx as xlsx_mod

    rows = big_board()
    with_intel = str(tmp_path / "with.xlsx")
    render_xlsx(LG, rows, with_intel)

    monkeypatch.setattr(xlsx_mod, "_write_intel_sheet", lambda wb, facts: 0)
    without = str(tmp_path / "without.xlsx")
    render_xlsx(LG, rows, without)

    def board_xml(path):
        with zipfile.ZipFile(path) as z:
            return z.read("xl/worksheets/sheet1.xml")

    assert openpyxl.load_workbook(without).sheetnames == ["Board"]
    assert board_xml(with_intel) == board_xml(without)


def test_the_intel_sheet_carries_every_section_of_the_briefing(tmp_path):
    from sffl.render import intel as intel_mod

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    ws = _intel_sheet(path)

    written = set()
    for r in range(1, ws.max_row + 1):
        for c in range(1, 6):
            v = ws.cell(r, c).value
            if isinstance(v, str):
                written.add(v)

    facts = intel_mod.gather(LG, board())
    assert intel_mod.title(facts) in written
    for heading, items in intel_mod.sections(facts):
        assert heading in written, "%s never reached the sheet" % heading
        for term, _text in items:
            assert term in written, "%s's term %r is missing" % (heading, term)


def test_no_prose_on_the_intel_sheet_can_overflow_its_cell(tmp_path):
    # The board shipped with exactly this defect once - a title written into a
    # 2.8-unit cell, spilling through its neighbours - and it was fixed by
    # merging. Prose is far longer than any title, so every paragraph here is
    # wrapped to a computed width, written with its line breaks already in it,
    # merged down as many rows as it has lines, and told to wrap on top of
    # that. All four, or a line goes missing on paper.
    from sffl.render.xlsx import (INTEL_BODY_PT, INTEL_TEXT_WIDTH,
                                  _chars_per_line)

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    ws = _intel_sheet(path)

    spans = {}
    for m in ws.merged_cells.ranges:
        spans[(m.min_row, m.min_col)] = (m.max_row - m.min_row + 1,
                                         m.max_col - m.min_col + 1)

    limit = _chars_per_line(INTEL_TEXT_WIDTH, INTEL_BODY_PT)
    checked = 0
    for text_col in (2, 5):
        for r in range(1, ws.max_row + 1):
            value = ws.cell(r, text_col).value
            if not isinstance(value, str) or not value:
                continue
            lines = value.split("\n")
            for line in lines:
                assert len(line) <= limit, (
                    "row %d column %d has a %d-character line against a %d "
                    "limit: %r" % (r, text_col, len(line), limit, line))
            rows_used = spans.get((r, text_col), (1, 1))[0]
            assert rows_used == len(lines), (
                "row %d column %d draws %d lines in %d row(s) - the rest is "
                "clipped" % (r, text_col, len(lines), rows_used))
            assert ws.cell(r, text_col).alignment.wrap_text
            assert ws.cell(r, text_col).alignment.vertical == "top"
            checked += 1
    assert checked >= 10, "only %d paragraphs checked" % checked


def test_the_intel_sheet_prints_like_the_board(tmp_path):
    from sffl.render.xlsx import (MARGIN_LEFT_IN, MARGIN_RIGHT_IN, SCALE_PCT)

    path = str(tmp_path / "board.xlsx")
    render_xlsx(LG, board(), path)
    wb = openpyxl.load_workbook(path)
    ws = _intel_sheet(path)

    assert ws.page_setup.orientation == "landscape"
    assert ws.page_setup.scale == SCALE_PCT
    assert ws.sheet_view.showGridLines is False
    for cell in ("A6", "B7"):
        assert ws[cell].font.name == "Calibri"

    # The width arithmetic above is only sound while these are the margins the
    # BOARD prints with too - they are the geometry both sheets share.
    board_ws = wb["Board"]
    assert board_ws.page_margins.left == MARGIN_LEFT_IN
    assert board_ws.page_margins.right == MARGIN_RIGHT_IN


def test_the_intel_sheet_states_the_run_it_was_rendered_from(tmp_path):
    # Passing facts gathered from a priced run must put THOSE numbers on the
    # page; passing none must leave the market sentences unquoted rather than
    # printing a stale figure.
    from sffl.render import intel as intel_mod
    from sffl.schema import PlayerProjection

    rows = board()
    pool = []
    for name, pos, dollars in (("Alpha", "TQB", 30.0), ("Bravo", "RB", 12.0)):
        p = PlayerProjection(name=name, team="GB", pos=pos, source="t",
                             source_year=2026, games=17.0)
        p.stats["_dollars"] = dollars
        pool.append(p)
    prices = {"alpha": 20.0, "bravo": 10.0}
    facts = intel_mod.gather(LG, rows, pool=pool, prices=prices,
                             curve=(2.248, 0.551))

    priced = str(tmp_path / "priced.xlsx")
    render_xlsx(LG, rows, priced, intel=facts)
    text = _flat_text(_intel_sheet(priced))
    assert "2.25 x value^0.55" in text
    # The pool errors are this run's own: |30-20| for the one Team QB join,
    # |12-10| for the one skill join. Nothing here is a remembered $8.98.
    assert "by $10 on average (n=1) against $2 for the skill pool (n=1)" in text

    bare = str(tmp_path / "bare.xlsx")
    render_xlsx(LG, rows, bare)
    text = _flat_text(_intel_sheet(bare))
    assert "fitted no price curve" in text
    assert "value^" not in text


def test_k_and_dst_depth_follows_the_one_constant(tmp_path, monkeypatch):
    # Jeff wants more than twelve of each. K_DST_DEPTH is the single dial;
    # this is what proves editing it is all anyone has to do.
    from sffl.render import xlsx as xlsx_mod

    for depth in (8, 12, 20, 26):
        monkeypatch.setattr(xlsx_mod, "K_DST_DEPTH", depth)
        path = str(tmp_path / ("depth-%d.xlsx" % depth))
        stats = render_xlsx(LG, big_board(), path)
        for title in ("KICKERS", "TEAM DEFENSE"):
            assert stats["sections"][title]["shown"] == depth, (
                "K_DST_DEPTH=%d gave %s %d rows"
                % (depth, title, stats["sections"][title]["shown"]))


def test_the_default_depth_is_twenty_not_the_team_count(tmp_path):
    # The regression: `lg.teams` (12) used to set this, on the argument that
    # a flat-$1 pool needs no more than one per roster spot. Jeff disagreed -
    # what matters at the table is seeing who is left.
    from sffl.render.xlsx import K_DST_DEPTH

    assert K_DST_DEPTH == 20 and K_DST_DEPTH != LG.teams
    path = str(tmp_path / "board.xlsx")
    stats = render_xlsx(LG, big_board(), path)
    assert stats["sections"]["KICKERS"]["shown"] == 20
    assert stats["sections"]["TEAM DEFENSE"]["shown"] == 20


def test_kicker_depth_is_bought_one_for_one_from_group_three_receivers(tmp_path,
                                                                       monkeypatch):
    # The exchange rate Jeff needs to dial this: the page is full, so every
    # row K or TEAM DEFENSE gains comes off group 3's RECEIVERS block and
    # nothing else. One step of K_DST_DEPTH moves two rows, because K and
    # DST move together. TEAM QB must never pay - all 32 are shown and that
    # is a complete position, not a top-N.
    from sffl.render import xlsx as xlsx_mod
    from sffl.render.xlsx import GROUP_GAP

    col3 = 1 + 2 * GROUP_GAP
    seen = {}
    for depth in (12, 16, 20, 24):
        monkeypatch.setattr(xlsx_mod, "K_DST_DEPTH", depth)
        path = str(tmp_path / ("rate-%d.xlsx" % depth))
        stats = render_xlsx(LG, big_board(), path)
        ws = openpyxl.load_workbook(path).active
        g3 = dict((t, e - (s + 1)) for t, s, e in _sections(ws, col3))
        seen[depth] = (stats["sections"]["RECEIVERS (WR + TE)"]["shown"],
                       g3["RECEIVERS (WR + TE)"], g3["TEAM QB"],
                       stats["sections"]["RUNNING BACKS"]["shown"])

    base_depth = 12
    base = seen[base_depth]
    for depth, (recv, g3_recv, tqb, rb) in sorted(seen.items()):
        step = depth - base_depth
        assert recv == base[0] - 2 * step, (
            "K_DST_DEPTH %d -> %d shown receivers; a 1:1 exchange from %d "
            "would give %d" % (depth, recv, base[0], base[0] - 2 * step))
        assert g3_recv == base[1] - 2 * step, (
            "the rows must come off GROUP 3's receiver block: %d at depth %d"
            % (g3_recv, depth))
        assert tqb == base[2] == 32, "TEAM QB paid for kicker depth"
        assert rb == base[3], "RUNNING BACKS paid for kicker depth"

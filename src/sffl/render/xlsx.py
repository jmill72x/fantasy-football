"""The printed cheatsheet: one landscape-letter worksheet Jeff prints and
carries to the auction, separate from the PDF he marks up on the iPad.

Format measured from Jeff's 2022 template
(`data/extracts/_templates/stripes-2022-rankings-template.xlsx`, gitignored -
licensed vendor data lives alongside it, but the workbook's own layout is not
licensed content): one sheet, landscape letter, 97% scale, gridlines off,
Calibri 8pt throughout with bold headers, three column groups separated by
narrow spacer columns. The 2022 sheet carried six columns per group (Rank,
Name, Team/Bye, Pos, Tier, AVG PTS); this league adds a second dollar column
(MY$ alongside EST$), so every group is eight columns wide.

Layout, matching the 2022 file: group 1 and group 2 together hold the
Overall Board (TQB/RB/WR/TE, ranked by MY$, continuing from the bottom of
group 1 into the top of group 2); group 3 stacks the position blocks (Team
QB, Running Backs, Receivers, Kickers, Team Defense) one under another, each
with its own title and header row.

THE TWO-PAGE ROW BUDGET. Inspecting the 2022 template itself (not just its
column widths) shows it was never a full player universe - its own OVERALL
block stops around rank 114, and every position block below it is a partial
top-N list. At this sheet's row height (9.95pt, also measured from that
template) and page geometry, 63 rows fit one printable landscape-letter
page, so two pages - back to back, the file's stated constraint - hold 126.
That is not a coincidence: it is why the 2022 file has 118 rows. A full
520-player board cannot fit in 126 rows no matter how the three columns are
packed (520 needs ~174 rows even divided perfectly three ways), and none of
the width-only reductions this module's history considered (narrower numeric
columns, dropping AVG from the position blocks, a lower scale) touch row
*count* - so this module truncates deliberately, computing the cutoff from
the page geometry below rather than hardcoding a player count. See
ROWS_PER_PAGE / ROW_BUDGET.

GROUP 3 ALLOCATION - every position gets a slot. A first pass filled group
3's five position blocks greedily in a fixed order (Team QB, then Running
Backs, then Receivers, Kickers, Team Defense) until ROW_BUDGET ran out.
Against the real 2026 pool that spent the whole budget on Team QB (32) and
part of Running Backs (90 of 122) and left Receivers - the single largest
position group in this league - Kickers and Team Defense with zero rows:
not even a title. A cheat sheet missing the receiver breakout entirely is
not usable, so this module now allocates ROW_BUDGET across the five blocks
deliberately (see _block_capacities): Team QB gets one row per real NFL
franchise (bounded and small - it always fits whole), Kickers and Team
Defense each get one row per drafting team (`lg.teams` - what actually
matters for a pool priced flat at $1), and whatever budget remains is split
between Running Backs and Receivers in proportion to their real relative
pool sizes in the run being rendered, not a fixed historical ratio. This
mirrors the 2022 template's own choice to give every position some room
rather than exhausting the page on whichever section happens to come first.

THE OVERALL BOARD does not consume the entirety of groups 1 + 2 either,
again matching the 2022 file: there, "OVERALL" took roughly half of each
column's usable rows (57 of ~116), with the remainder of those columns
carrying supplementary position content. A first pass left that freed half
blank - 124 rows, close to half the printed sheet, while the same run was
cutting 105 Running Backs and 256 Receivers. That is not an acceptable
trade: this module now snakes the two positions absorbing the most
truncation into that space exactly as 2022 does - Running Backs continuing
below group 1's Overall Board, Receivers (WR+TE) continuing below group 2's
- picking up where group 3's own allocation for that position left off
(see _write_continuation_block), never re-listing players already shown
elsewhere. Kickers, Team Defense and Team QB are not continued: their group
3 allocation already covers everyone that matters (one row per team, or the
whole bounded pool), so extra rows there would not reduce any real cut.

Each continuation starts at the first row its own column actually left
free, reported by _write_overall_columns - never at a fixed fraction of
ROW_BUDGET. The two agree only while the Overall pool exceeds its capacity,
as the production extract does (453 against 124); a leaner extract, a
different --policy or a filtered pool puts it under, and a fixed start row
would then print a band of blank rows in the middle of the column while the
blocks below were still cutting players. Same failure class as the two
above, different trigger.
"""

from openpyxl import Workbook
from openpyxl.styles import Font

from sffl.identity import NFL_TEAMS
from sffl.render.rows import overall_board

HEADERS = ["Rank", "Name", "Team/Bye", "Pos", "Tier", "AVG", "MY$", "EST$"]

# Column widths in Excel width units (~one default-font character each),
# measured from the 2022 template and rounded. `numeric` covers AVG, MY$ and
# EST$ - the three right-aligned number columns.
WIDTHS = {
    "rank": 2.8,
    "name": 11.6,
    "team_bye": 5.1,
    "pos": 3.8,
    "tier": 3.8,
    "numeric": 3.5,
}
SPACER_WIDTH = 0.9
N_COLS = len(HEADERS)          # 8 columns per group
GROUP_GAP = N_COLS + 1         # 8 data columns + 1 spacer column

FONT = Font(name="Calibri", size=8)
FONT_BOLD = Font(name="Calibri", size=8, bold=True)

# Measured from the 2022 template: every one of its 118 rows carries this
# explicit height rather than Excel's default (15pt), which is what actually
# fits 8pt Calibri text tightly. Setting it here rather than leaving it to
# each viewer's auto-fit is what makes the page-geometry arithmetic below
# (and in the task report) reproducible instead of platform-dependent.
ROW_HEIGHT = 9.95

# Page geometry - kept in sync with what render_xlsx() actually applies to
# the worksheet below (page_setup.scale, page_margins). Landscape letter is
# 11in x 8.5in; only the top/bottom margins affect printable height.
PAGE_HEIGHT_IN = 8.5
MARGIN_TOP_IN = 0.0
MARGIN_BOTTOM_IN = 0.0
SCALE_PCT = 97

# HEADER_ROWS a block "costs" before it can show a single data row: one
# title row, one column-header row.
HEADER_ROWS = 2


def _rows_per_page():
    """How many ROW_HEIGHT-tall rows fit in one printed page's height, at
    SCALE_PCT print scale. Excel's "scale" shrinks the printed output by
    that percentage, so more natural-size content fits per page as scale
    drops below 100 - printed_height = natural_height * scale/100, so a page
    holds natural_height <= printable_height / (scale/100)."""
    printable_pt = (PAGE_HEIGHT_IN - MARGIN_TOP_IN - MARGIN_BOTTOM_IN) * 72.0
    return int(printable_pt // (ROW_HEIGHT * (SCALE_PCT / 100.0)))


ROWS_PER_PAGE = _rows_per_page()
# The hard cap this module exists to respect: "must print on two letter
# sheets, back to back" is a two-page-tall budget, derived from geometry
# rather than picked - see the module docstring.
ROW_BUDGET = ROWS_PER_PAGE * 2

# (title, member positions) - same five blocks as the PDF's position pages,
# WR and TE merged into one pool since they are one position in this league.
POSITION_BLOCKS = [
    ("TEAM QB", ("TQB",)),
    ("RUNNING BACKS", ("RB",)),
    ("RECEIVERS (WR + TE)", ("WR", "TE")),
    ("KICKERS", ("K",)),
    ("TEAM DEFENSE", ("DST",)),
]


def _set_widths(ws, col0):
    """Apply the measured widths to one 8-column group starting at col0
    (1-indexed), and a spacer immediately after it."""
    order = ["rank", "name", "team_bye", "pos", "tier",
             "numeric", "numeric", "numeric"]
    for i, key in enumerate(order):
        letter = ws.cell(1, col0 + i).column_letter
        ws.column_dimensions[letter].width = WIDTHS[key]
    spacer_letter = ws.cell(1, col0 + N_COLS).column_letter
    ws.column_dimensions[spacer_letter].width = SPACER_WIDTH


def _write_header(ws, row, col0):
    ws.row_dimensions[row].height = ROW_HEIGHT
    for i, h in enumerate(HEADERS):
        ws.cell(row, col0 + i, h).font = FONT_BOLD


def _write_title(ws, row, col0, title):
    ws.row_dimensions[row].height = ROW_HEIGHT
    ws.cell(row, col0, title).font = FONT_BOLD


def _write_data_row(ws, row, col0, r):
    ws.row_dimensions[row].height = ROW_HEIGHT
    ws.cell(row, col0 + 0, r.rank).font = FONT
    ws.cell(row, col0 + 1, r.name).font = FONT
    ws.cell(row, col0 + 2, "%s/%s" % (r.team, r.bye if r.bye else "-")).font = FONT
    ws.cell(row, col0 + 3, r.pos).font = FONT
    ws.cell(row, col0 + 4, r.tier).font = FONT
    ws.cell(row, col0 + 5, round(r.avg_pts, 1)).font = FONT
    ws.cell(row, col0 + 6, round(r.my_dollars, 0)).font = FONT
    # A missing EST$ (no market curve fitted, or a flat-priced pool with no
    # observation) renders as an empty cell, never 0 - a zero reads as a
    # measurement of "the market will pay nothing," which is not what an
    # absent estimate means.
    est = round(r.est_price, 0) if r.est_price is not None else ""
    ws.cell(row, col0 + 7, est).font = FONT


def _overall_capacity():
    """Max Overall Board rows across group 1 + group 2 combined.

    Each column has ROW_BUDGET - HEADER_ROWS usable data rows; the Overall
    Board gets half of that per column, matching the 2022 template's own
    proportion (its OVERALL block took 57 of ~116 usable rows per column,
    not the full column) rather than filling every column edge to edge."""
    per_col_data = ROW_BUDGET - HEADER_ROWS
    return 2 * (per_col_data // 2)


def _write_overall_columns(ws, overall):
    """Write the Overall Board title + header + as much data as
    ROW_BUDGET allows into group 1, spilling into group 2.

    Returns (shown, cut, next_rows):
      shown, cut - the two slices of `overall` this call wrote and dropped,
                   so the caller can report the cutoff;
      next_rows  - {col0: first free row} for each of the two columns, so a
                   continuation block starts immediately below whatever was
                   ACTUALLY written rather than at a fixed fraction of the
                   budget. Those two numbers coincide only when the Overall
                   pool fills its capacity (the production case); when it is
                   smaller, or odd-sized, the columns end at different rows
                   and a fixed start row would leave one or both of them
                   holed. See _write_continuation_block.
    """
    col1, col2 = 1, 1 + GROUP_GAP
    for col0 in (col1, col2):
        _write_title(ws, 1, col0, "OVERALL")
        _write_header(ws, 2, col0)

    capacity = _overall_capacity()
    shown, cut = overall[:capacity], overall[capacity:]

    half = -(-len(shown) // 2)   # ceil division: group 1 gets the larger half
    left, right = shown[:half], shown[half:]
    next_rows = {}
    for col0, chunk in ((col1, left), (col2, right)):
        row = 3
        for r in chunk:
            _write_data_row(ws, row, col0, r)
            row += 1
        next_rows[col0] = row
    return shown, cut, next_rows


def _block_capacities(lg, rows):
    """Data-row capacity for each of the five position blocks in group 3
    (not counting each block's own HEADER_ROWS - the caller pays that
    separately), derived from ROW_BUDGET so every position is guaranteed a
    non-empty slot rather than however much a greedy fill leaves over. See
    the module docstring's GROUP 3 ALLOCATION note.

    Two-phase allocation, entirely in data rows:
      1. Guaranteed minimums for the three positions whose real pool size is
         small and bounded: Team QB (one per real NFL franchise - capped at
         len(NFL_TEAMS), the same authority `sffl.cli.cmd_render` already
         uses for what counts as a franchise - so it always fits whole),
         Kickers and Team Defense (one per drafting team - `lg.teams` - the
         number that actually matters for a pool priced flat at $1).
      2. Whatever budget remains ("stretch") is split between Running Backs
         and Receivers (WR+TE - one pool, never a separate ladder) in
         proportion to their real relative pool sizes in this run, not a
         fixed historical ratio, so the split tracks the data being
         rendered rather than a snapshot of the 2022 file.
    """
    header_overhead = len(POSITION_BLOCKS) * HEADER_ROWS
    data_budget = ROW_BUDGET - header_overhead

    min_tqb = len(NFL_TEAMS)
    min_k = lg.teams
    min_dst = lg.teams
    stretch = max(0, data_budget - (min_tqb + min_k + min_dst))

    rb_n = sum(1 for r in rows if r.pos == "RB")
    recv_n = sum(1 for r in rows if r.pos in ("WR", "TE"))
    pool_n = rb_n + recv_n
    rb_cap = int(round(stretch * rb_n / pool_n)) if pool_n else 0
    recv_cap = stretch - rb_cap

    return {
        "TEAM QB": min_tqb,
        "RUNNING BACKS": rb_cap,
        "RECEIVERS (WR + TE)": recv_cap,
        "KICKERS": min_k,
        "TEAM DEFENSE": min_dst,
    }


def _write_position_blocks(lg, ws, rows):
    """Stack position blocks in group 3, exactly as the 2022 file stacks
    QUARTERBACKS / RUNNING BACKS / WIDE RECEIVERS / TIGHT ENDS / KICKERS /
    TEAM DEFENSE - collapsed to five blocks here since WR and TE share one
    pool in this league.

    Each block gets its own fixed capacity from _block_capacities - not
    whatever a previous block left over - so every position with any real
    members gets a non-empty title, header and at least its guaranteed
    share of rows.

    Returns (shown, cut): dicts of block title -> list of BoardRow, both
    always present together for a title with any real members (cut may be
    an empty list). `cut` is the list of members this block's capacity
    couldn't fit - kept as the actual rows, not just a count, so the caller
    can continue showing them elsewhere (see _write_continuation_block)
    instead of just reporting how many were dropped.
    """
    col0 = 1 + 2 * GROUP_GAP
    row = 1
    capacities = _block_capacities(lg, rows)
    shown = {}
    cut = {}
    for title, positions in POSITION_BLOCKS:
        members = sorted([r for r in rows if r.pos in positions],
                          key=lambda r: -r.my_dollars)
        if not members:
            continue

        _write_title(ws, row, col0, title)
        row += 1
        _write_header(ws, row, col0)
        row += 1

        cap = capacities[title]
        block_shown, block_cut = members[:cap], members[cap:]
        for r in block_shown:
            _write_data_row(ws, row, col0, r)
            row += 1

        shown[title] = block_shown
        cut[title] = block_cut

    return shown, cut


def _continuation_capacity(start_row):
    """Data rows available for a continuation position block that begins at
    `start_row` in group 1 or group 2: everything from its first data row
    down to ROW_BUDGET, after paying its own HEADER_ROWS (title + header).

    Derived from where the block actually starts, not from a fixed fraction
    of the budget, so it stays exact whatever the Overall Board above it
    consumed."""
    first_data_row = start_row + HEADER_ROWS
    return max(0, ROW_BUDGET - first_data_row + 1)


def _write_continuation_block(ws, col0, title, members, start_row):
    """Write a continuation position block below the Overall Board in group
    1 or group 2, picking up exactly where group 3's own allocation for
    this position left off - `members` is that position's own cut list, so
    this never re-lists a player already shown elsewhere on the sheet.

    `start_row` is the first free row in this column, reported by
    _write_overall_columns from what it actually wrote. It must NOT be a
    fixed fraction of ROW_BUDGET: that is only equal to the real first free
    row while the Overall pool exceeds its capacity (453 against 124 in the
    production extract). A leaner extract, a different --policy or a
    filtered pool puts it under, and a fixed start row then leaves a band of
    blank printed rows in the middle of the column while the position blocks
    below are still cutting players - the same allocation failure this
    module's history shipped three times. See
    test_a_short_overall_board_leaves_no_blank_gap_above_the_continuation.

    Writes nothing (and returns two empty lists) if there is nothing left
    to continue - a position group 3 already covered in full has no cut
    members to place here.

    Returns (shown, cut): the slice of `members` this call wrote, and
    whatever was still left over after this block's own capacity.
    """
    if not members:
        return [], []

    capacity = _continuation_capacity(start_row)
    if capacity <= 0:
        # No room even for a title: the Overall Board filled this column to
        # the budget. Write nothing rather than a headed but empty block.
        return [], list(members)

    _write_title(ws, start_row, col0, title)
    _write_header(ws, start_row + 1, col0)

    shown, cut = members[:capacity], members[capacity:]
    row = start_row + HEADER_ROWS
    for r in shown:
        _write_data_row(ws, row, col0, r)
        row += 1
    return shown, cut


def render_xlsx(lg, rows, path):
    """Render the printed cheatsheet to `path`.

    Raises ValueError on an empty `rows` rather than writing a blank sheet -
    the same "raise clearly" rule `render_pdf` follows.

    Returns a stats dict describing any truncation this call applied to fit
    the two-page ROW_BUDGET. Reported per section - a single global
    shown/cut number hides exactly the failure mode this module exists to
    avoid: it can look "mostly fine" while an entire position is silently
    missing (see the module docstring's GROUP 3 ALLOCATION note).
        total    - len(rows), everyone this call was asked to render
        overall  - {"shown": n, "cut": n} for the Overall Board (group 1+2)
        sections - {block title: {"shown": n, "cut": n}} for each of the
                   five position blocks in group 3 that had at least one
                   real member; a position absent from `rows` entirely does
                   not get an entry (there is nothing to report), but every
                   position that DID have members is guaranteed "shown" > 0
                   by _block_capacities - if this call fails to write a
                   position's title at all, that is the bug this stats dict
                   is here to catch, not a valid outcome.
    A full board never needs this - see the caller (`sffl.cli.cmd_render`)
    for how it's reported.
    """
    if not rows:
        raise ValueError("render_xlsx: rows is empty; nothing to render")

    wb = Workbook()
    ws = wb.active
    ws.title = "Board"

    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_LETTER
    ws.page_setup.scale = SCALE_PCT
    ws.sheet_view.showGridLines = False
    ws.page_margins.left = 0.75
    ws.page_margins.right = 0.0
    ws.page_margins.top = MARGIN_TOP_IN
    ws.page_margins.bottom = MARGIN_BOTTOM_IN
    ws.page_margins.header = 0.0
    ws.page_margins.footer = 0.0

    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        _set_widths(ws, col0)

    # One shared filter with render_pdf's Overall Board - see
    # sffl.render.rows.overall_board. Spelling it out separately in each
    # renderer let a future edit to one silently disagree with the other
    # about what the Overall Board even contains.
    col1, col2 = 1, 1 + GROUP_GAP
    overall = overall_board(rows)
    overall_shown, overall_cut = [], []
    # With no Overall Board written at all, both columns are free from row 1
    # and a continuation may start there - never at a fixed offset into
    # rows that nothing occupies.
    next_rows = {col1: 1, col2: 1}
    if overall:
        overall_shown, overall_cut, next_rows = _write_overall_columns(ws, overall)

    block_shown, block_cut = _write_position_blocks(lg, ws, rows)

    # Running Backs and Receivers are what absorb almost all of group 3's
    # truncation (Team QB is always complete; Kickers and Team Defense's
    # guaranteed one-per-team allocation already covers what matters for a
    # flat-$1 pool), so they're the two that continue into the space freed
    # by capping the Overall Board at half of groups 1 and 2 - Running Backs
    # below group 1's Overall, Receivers below group 2's, matching where the
    # 2022 template put them.
    rb_extra_shown, rb_extra_cut = _write_continuation_block(
        ws, col1, "RUNNING BACKS", block_cut.get("RUNNING BACKS", []),
        next_rows[col1])
    recv_extra_shown, recv_extra_cut = _write_continuation_block(
        ws, col2, "RECEIVERS (WR + TE)", block_cut.get("RECEIVERS (WR + TE)", []),
        next_rows[col2])

    wb.save(path)

    extra_shown = {"RUNNING BACKS": rb_extra_shown, "RECEIVERS (WR + TE)": recv_extra_shown}
    extra_cut = {"RUNNING BACKS": rb_extra_cut, "RECEIVERS (WR + TE)": recv_extra_cut}

    sections = {}
    for title, _positions in POSITION_BLOCKS:
        if title not in block_shown:
            continue
        shown_n = len(block_shown[title]) + len(extra_shown.get(title, []))
        cut_n = len(extra_cut.get(title, block_cut[title]))
        sections[title] = {"shown": shown_n, "cut": cut_n}

    return {
        "total": len(rows),
        "overall": {"shown": len(overall_shown), "cut": len(overall_cut)},
        "sections": sections,
    }

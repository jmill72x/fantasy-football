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
"""

from openpyxl import Workbook
from openpyxl.styles import Font

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
    """Max Overall Board rows across group 1 + group 2 combined: each
    column gets the full ROW_BUDGET, minus its own title + header rows."""
    return 2 * (ROW_BUDGET - HEADER_ROWS)


def _write_overall_columns(ws, overall):
    """Write the Overall Board title + header + as much data as
    ROW_BUDGET allows into group 1, spilling into group 2. Returns
    (shown, cut) - the two slices of `overall` this call wrote and dropped,
    so the caller can report the cutoff."""
    col1, col2 = 1, 1 + GROUP_GAP
    for col0 in (col1, col2):
        _write_title(ws, 1, col0, "OVERALL")
        _write_header(ws, 2, col0)

    capacity = _overall_capacity()
    shown, cut = overall[:capacity], overall[capacity:]

    half = -(-len(shown) // 2)   # ceil division: group 1 gets the larger half
    left, right = shown[:half], shown[half:]
    for col0, chunk in ((col1, left), (col2, right)):
        row = 3
        for r in chunk:
            _write_data_row(ws, row, col0, r)
            row += 1
    return shown, cut


def _write_position_blocks(ws, rows):
    """Stack position blocks in group 3, exactly as the 2022 file stacks
    QUARTERBACKS / RUNNING BACKS / WIDE RECEIVERS / TIGHT ENDS / KICKERS /
    TEAM DEFENSE - collapsed to five blocks here since WR and TE share one
    pool in this league.

    Fills blocks in POSITION_BLOCKS order against a single ROW_BUDGET shared
    by the whole column (group 3 is one column, unlike the Overall Board's
    two): each block gets its title + header rows plus as many of its
    highest-$ members as remain, then the next block continues in whatever
    budget is left. A block that arrives after the budget is already spent
    is skipped entirely (not even its title/header), since printing an empty
    section's headers with nothing under them isn't a page a reader can use.

    Returns (shown, cut): dicts of block title -> list of BoardRow shown /
    count cut, for the caller to report.
    """
    col0 = 1 + 2 * GROUP_GAP
    row = 1
    remaining = ROW_BUDGET
    shown = {}
    cut = {}
    for title, positions in POSITION_BLOCKS:
        members = sorted([r for r in rows if r.pos in positions],
                          key=lambda r: -r.my_dollars)
        if not members:
            continue
        if remaining < HEADER_ROWS:
            cut[title] = len(members)
            continue

        _write_title(ws, row, col0, title)
        row += 1
        _write_header(ws, row, col0)
        row += 1
        remaining -= HEADER_ROWS

        block_shown, block_cut = members[:remaining], members[remaining:]
        for r in block_shown:
            _write_data_row(ws, row, col0, r)
            row += 1
        remaining -= len(block_shown)

        shown[title] = block_shown
        if block_cut:
            cut[title] = len(block_cut)

    return shown, cut


def render_xlsx(lg, rows, path):
    """Render the printed cheatsheet to `path`.

    Raises ValueError on an empty `rows` rather than writing a blank sheet -
    the same "raise clearly" rule `render_pdf` follows.

    Returns a stats dict describing any truncation this call applied to fit
    the two-page ROW_BUDGET:
        total       - len(rows), everyone this call was asked to render
        made        - distinct players actually written anywhere on the
                       sheet (the Overall Board and the position blocks are
                       independently truncated - see _write_position_blocks -
                       so a player cut from one can still appear via the
                       other; this is the true union, not just Overall's)
        cut         - total - made
        last_dollar - the lowest MY$ among everyone who made the sheet, i.e.
                       "the sheet covers everyone worth more than $X" - or
                       None if nothing was written (only possible if every
                       position pool is empty, since `rows` is non-empty)
        overall_shown / overall_cut - the Overall Board's own split, for
                       detail beyond the headline made/cut/last_dollar
        block_shown / block_cut - per-position-block counts in group 3, for
                       whichever blocks got a partial or zero allocation
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

    # Overall Board: TQB/RB/WR/TE only, same filter as render_pdf's Overall
    # Board - K/DST are flat-priced $1 fillers with their own block below,
    # not part of the ranked overall list.
    overall = sorted([r for r in rows if r.pos in ("TQB", "RB", "WR", "TE")],
                      key=lambda r: -r.my_dollars)
    overall_shown, overall_cut = [], []
    if overall:
        overall_shown, overall_cut = _write_overall_columns(ws, overall)

    block_shown, block_cut = _write_position_blocks(ws, rows)

    wb.save(path)

    # The Overall Board and each position block are truncated independently
    # against their own share of ROW_BUDGET (see _write_position_blocks), so
    # a player cut from the Overall Board's 248-row cap can still appear via
    # their position's own block, or vice versa - the two views don't cut at
    # the same rank. "made the sheet" has to be the union of everyone
    # written anywhere, not just the Overall Board's count, or this would
    # understate real coverage.
    shown_union = {}
    for r in overall_shown:
        shown_union[(r.name, r.team, r.pos)] = r
    for members in block_shown.values():
        for r in members:
            shown_union[(r.name, r.team, r.pos)] = r

    return {
        "total": len(rows),
        "made": len(shown_union),
        "cut": len(rows) - len(shown_union),
        "last_dollar": (min(r.my_dollars for r in shown_union.values())
                         if shown_union else None),
        "overall_shown": len(overall_shown),
        "overall_cut": len(overall_cut),
        "block_shown": dict((t, len(m)) for t, m in block_shown.items()),
        "block_cut": block_cut,
    }

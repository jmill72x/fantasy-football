"""The printed cheatsheet: one landscape-letter worksheet Jeff prints and
carries to the auction, separate from the PDF he marks up on the iPad.

Format measured from Jeff's 2022 template
(`data/extracts/_templates/stripes-2022-rankings-template.xlsx`, gitignored -
licensed vendor data lives alongside it, but the workbook's own layout is not
licensed content): one sheet, landscape letter, 97% scale, gridlines off,
Calibri 8pt throughout with bold headers, three column groups separated by
narrow spacer columns. The 2022 sheet carried six columns per group (Rank,
Name, Team/Bye, Pos, Tier, AVG PTS); this league adds a second dollar column
(MY$ alongside EST$), so every group is eight columns wide - see
`docs/superpowers/sdd/2026-08-04-renderers/task-3-report.md` for the
column-width arithmetic behind that choice.

Layout, matching the 2022 file: group 1 and group 2 together hold the
Overall Board (TQB/RB/WR/TE, ranked by MY$, continuing from the bottom of
group 1 into the top of group 2); group 3 stacks the five position blocks
(Team QB, Running Backs, Receivers, Kickers, Team Defense) one under another,
each with its own title and header row.
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
# each viewer's auto-fit is what makes the page-count arithmetic in the task
# report reproducible instead of platform-dependent.
ROW_HEIGHT = 9.95

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


def _write_overall_columns(ws, overall):
    """Write the Overall Board title + header + data into group 1, spilling
    into group 2 once group 1's rows run out. Returns nothing - both groups
    are fully populated by this call, matching the 2022 file's two-column
    Overall spread."""
    col1, col2 = 1, 1 + GROUP_GAP
    for col0 in (col1, col2):
        _write_title(ws, 1, col0, "OVERALL")
        _write_header(ws, 2, col0)

    half = -(-len(overall) // 2)   # ceil division: group 1 gets the larger half
    left, right = overall[:half], overall[half:]
    for col0, chunk in ((col1, left), (col2, right)):
        row = 3
        for r in chunk:
            _write_data_row(ws, row, col0, r)
            row += 1


def _write_position_blocks(ws, rows):
    """Stack the five position blocks in group 3, exactly as the 2022 file
    stacks QUARTERBACKS / RUNNING BACKS / WIDE RECEIVERS / TIGHT ENDS /
    KICKERS / TEAM DEFENSE - collapsed to five blocks here since WR and TE
    share one pool in this league."""
    col0 = 1 + 2 * GROUP_GAP
    row = 1
    for title, positions in POSITION_BLOCKS:
        members = sorted([r for r in rows if r.pos in positions],
                          key=lambda r: -r.my_dollars)
        if not members:
            continue
        _write_title(ws, row, col0, title)
        row += 1
        _write_header(ws, row, col0)
        row += 1
        for i, r in enumerate(members, 1):
            _write_data_row(ws, row, col0, r)
            row += 1


def render_xlsx(lg, rows, path):
    """Render the printed cheatsheet to `path`.

    Raises ValueError on an empty `rows` rather than writing a blank sheet -
    the same "raise clearly" rule `render_pdf` follows.
    """
    if not rows:
        raise ValueError("render_xlsx: rows is empty; nothing to render")

    wb = Workbook()
    ws = wb.active
    ws.title = "Board"

    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_LETTER
    ws.page_setup.scale = 97
    ws.sheet_view.showGridLines = False
    ws.page_margins.left = 0.75
    ws.page_margins.right = 0.0
    ws.page_margins.top = 0.0
    ws.page_margins.bottom = 0.0
    ws.page_margins.header = 0.0
    ws.page_margins.footer = 0.0

    for col0 in (1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP):
        _set_widths(ws, col0)

    # Overall Board: TQB/RB/WR/TE only, same filter as render_pdf's Overall
    # Board - K/DST are flat-priced $1 fillers with their own block below,
    # not part of the ranked overall list.
    overall = sorted([r for r in rows if r.pos in ("TQB", "RB", "WR", "TE")],
                      key=lambda r: -r.my_dollars)
    if overall:
        _write_overall_columns(ws, overall)

    _write_position_blocks(ws, rows)

    wb.save(path)

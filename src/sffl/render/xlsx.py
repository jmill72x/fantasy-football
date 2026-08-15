"""The printed cheatsheet: a landscape-letter workbook Jeff prints and carries
to the auction, separate from the PDF he marks up on the iPad.

TWO WORKSHEETS. "Board" is the board - 126 rows over two printed pages, every
row a player, and the whole of what follows is about it. "Key & Intel" is a
third printed page in the same file: what the columns mean, what this room has
historically paid, and where the model is weak, for a drafter who is not the
person who built the board. It is a separate SHEET rather than a block of the
board because the board is full - 126 rows is a page-geometry budget, so every
line of legend written into it would have cost a player. See the SECOND
WORKSHEET section further down.

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
deliberately (see _allocate_page): Team QB gets one row per real NFL
franchise (bounded and small - it always fits whole), Kickers and Team
Defense each get K_DST_DEPTH rows (the one dial for how deep those two
flat-priced $1 pools print), and whatever budget remains is split
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
truncation into that space exactly as 2022 does - Running Backs sharing
group 1's column with its Overall Board, Receivers (WR+TE) sharing group
2's - so each of those two positions occupies TWO blocks on the sheet, one
in group 3 and one under an Overall Board, and no player is ever listed in
both. Kickers, Team Defense and Team QB get one block each: their group 3
allocation already covers everyone that matters (K_DST_DEPTH rows, or the
whole bounded pool), so extra rows there would not reduce any real cut.

The second block starts at the first row its own column actually left
free, reported by _write_overall_columns - never at a fixed fraction of
ROW_BUDGET. The two agree only while the Overall pool exceeds its capacity,
as the production extract does (453 against 122); a leaner extract, a
different --policy or a filtered pool puts it under, and a fixed start row
would then print a band of blank rows in the middle of the column while the
blocks below were still cutting players. Same failure class as the two
above, different trigger.

READING ORDER ACROSS A SPLIT POSITION. A position that occupies two blocks
has to decide which block gets its best players. The first version answered
"group 3 always", because group 3's block was written first and the other
one was merely its continuation - and on page 2 that printed group 3, the
RIGHTMOST column, opening at WR1 while group 2 to its LEFT opened at WR29.
Jeff, correctly: "you have the WR columns out of order, the first WRs are
on the right of the 2nd column of WRs."

The sheet is read the way any two-page printout is read: all of page 1 left
to right (group 1, group 2, group 3), then all of page 2 left to right. So
a block's place in that order is (the page it opens on, its column group) -
_reading_order_key - and a split position hands its players out strictly in
that order, filling each block to the size the layout already gave it. Two
consequences, both intended:

  - RUNNING BACKS does not move. Its group 3 block opens on page 1 and its
    group 1 block on page 2, so (page 0, group 3) still sorts before (page
    1, group 1): RB1-27 in group 3 on page 1, RB28+ in group 1 overleaf.
    The page outranks the column because the reader finishes page 1 before
    starting page 2 - sorting on the column alone would have "fixed" this
    one into being wrong.
  - RECEIVERS flips. Both its blocks open on page 2, so the column decides:
    group 2 takes WR1 onward and group 3 picks up where group 2 stops.

The same rule already governed the Overall Board's own split across groups
1 and 2 (both on page 1, so the left column takes the higher ranks); it is
now stated once, in one function, instead of being implied by the order two
different writers happened to run in.

SECTION TITLES ARE MERGED ACROSS THEIR GROUP. A title is written into the
group's first cell, which is the Rank column - 2.8 width units, narrower
than any of the five titles. Excel spills a too-long string rightwards
through whatever cells are empty, and on a title row all eight of the
group's cells are empty (they carry a fill, and a fill does not stop a
spill), as is the spacer beyond them. The only thing that bounds the spill
is content in the NEXT group's first cell on that same row, and that
content is not guaranteed: a group whose column ends higher than its
neighbour's leaves the whole row open to the right. _write_title therefore
merges the title across exactly its own eight columns, which clips it
structurally rather than relying on what happens to sit beside it. The 2022
template does not merge - it does not have to, with six narrower columns
and titles as short as "WR" to place.

SECTION BOUNDARIES LAND ON THE PAGE BREAK. The first version of this module
sized every block from the row BUDGET (126) and never from the page it
would print on, so blocks landed wherever the arithmetic left them: the
Overall Board ran to row 64, one row onto page 2, and group 3's Receivers
block opened at row 54 - nine rows above the break - and ran to 98. Printed,
that reads as running backs, then a stub of receivers, then more receivers
overleaf, with the rest of the running backs on the facing page: two
positions interleaved across the fold for no reason. The 2022 template does
not do this; its own boundaries land at 59/60, exactly its page break.

So the unit of layout here is the PAGE (ROWS_PER_PAGE rows), not the
budget. Group 3's blocks are partitioned into whole pages by
_plan_position_blocks - no block ever straddles the break - and groups 1
and 2 cap the Overall Board at one page, putting each continuation block on
the next one (_continuation_start). A continuation whose Overall Board came
up short still starts immediately below it and may run across the break -
one long list continuing over the fold is fine, it is two DIFFERENT
sections interleaved that is not - unless it would start within
PAGE_ALIGN_SLACK rows of the break, which would print a title and a column
header at the very bottom of page 1 with the data overleaf. That case
alone leaves up to PAGE_ALIGN_SLACK blank rows at the foot of page 1.

BORDERS, FILLS AND POSITION COLOUR. The template switches Excel's own
gridlines off (`showGridLines: False`) and draws an explicit thin border on
all four sides of every cell in its used rectangle - 2,360 cells over
A1:T118, data, headers and the narrow spacer columns alike. That grid, not
the screen gridlines, is what makes it read as a ruled table on paper; an
earlier reading of this file recorded only the gridline flag and this
module shipped with no borders at all. _apply_grid draws it.

Its section-title and column-header rows additionally carry a solid white
fill across the full width of their group (rows 1, 2, 27, 28, 60, 61, ...),
and position colour comes from conditional formatting on the Pos column
keyed on that column's TEXT - `cellIs between "RB1" and "RB99"`, and the
same for WR, TE and QB. There is no tier shading anywhere in the template.
That is why the template's Pos column reads `RB1`, `WR24`, `TE6` rather
than a bare position, and why this module now writes positional rank there
too (_pos_labels). WR and TE remain ONE pool for valuation - this label is
the only place they are counted separately, exactly as the template does.
"""

import textwrap

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from sffl.identity import NFL_TEAMS
from sffl.render import intel as intel_mod
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

# The ruled grid. Measured from the 2022 template: every cell of its used
# rectangle (A1:T118 - data cells, title and header cells, and the narrow
# spacer columns between the groups) carries a thin border on all four
# sides. See the module docstring's BORDERS note for why the gridline flag
# alone was not enough.
_THIN = Side(style="thin")
GRID_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

# Solid white, indexed colour 9 in the template - the fill it puts on every
# section-title row and column-header row, across the full width of that
# block's group.
HEADER_FILL = PatternFill(fill_type="solid", start_color="FFFFFFFF",
                          end_color="FFFFFFFF")

# Conditional formatting on the Pos column, keyed on its text, one rule per
# position prefix - the template's own mechanism (`cellIs between "RB1" and
# "RB99"`). The template's colours are theme references that do not
# round-trip, so these are solid RGB fills chosen to stay distinguishable
# after a greyscale print as well: their relative luminances are roughly
# 242 / 210 / 189 / 170 out of 255, spread rather than clustered, and every
# one is light enough to read black 8pt text over.
#
# K and DST are deliberately uncoloured, as in the template: they are
# flat-priced $1 fillers with their own block, and colouring them would
# spend the reader's attention on the one part of the board where no
# decision is made.
POS_FILL_COLORS = [
    ("WR", "FFFFF2CC"),    # amber   - lightest
    ("TQB", "FFBDD7EE"),   # blue
    ("RB", "FFA9D08E"),    # green
    ("TE", "FFB1A0C7"),    # violet  - darkest
]

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
# "Must print on two letter sheets, back to back" - a two-page budget,
# derived from geometry rather than picked. See the module docstring.
N_PAGES = 2
ROW_BUDGET = ROWS_PER_PAGE * N_PAGES

# How close to the foot of a page a section may open and still continue
# overleaf. A block starting inside this band prints its title and its
# column header at the bottom of one sheet with the data on the next, which
# is the shape Jeff objected to; such a block is pushed to the top of the
# following page instead. See _continuation_start.
PAGE_ALIGN_SLACK = 5

# (title, member positions) - same five blocks as the PDF's position pages,
# WR and TE merged into one pool since they are one position in this league.
POSITION_BLOCKS = [
    ("TEAM QB", ("TQB",)),
    ("RUNNING BACKS", ("RB",)),
    ("RECEIVERS (WR + TE)", ("WR", "TE")),
    ("KICKERS", ("K",)),
    ("TEAM DEFENSE", ("DST",)),
]

# The two blocks whose real pool has no natural ceiling, so they are the
# ones that absorb whatever room a page has left over. Team QB is bounded by
# the number of NFL franchises; Kickers and Team Defense by K_DST_DEPTH.
FLEX_BLOCKS = ("RUNNING BACKS", "RECEIVERS (WR + TE)")

# How deep the Kickers and Team Defense blocks run - THE ONE NUMBER TO EDIT
# to trade kicker/defense depth against receiver depth.
#
# It used to be `lg.teams` (12): one row per drafting team, the argument
# being that a pool priced flat at $1 needs no more than one per roster
# spot. Jeff wants more than that - the pool holds 35 K and 32 DST, and the
# useful thing on auction day is seeing who is left, not just twelve names.
#
# The page is full, so this is a straight exchange and the rate is 1:1.
# Group 3's page 2 carries RECEIVERS, KICKERS and TEAM DEFENSE; the two
# bounded blocks are served to their `want` before the flex block gets
# anything (see _allocate_page), so every row added here is a row taken off
# group 3's RECEIVERS block - and since both K and DST move together, one
# step of K_DST_DEPTH costs TWO receiver rows. Receivers is the right place
# to borrow from: it is the deepest of the split positions, so a row cut
# from group 3 comes off the very bottom of a 78-deep list rather than off
# a position that is only shown once. TEAM QB is never touched - all 32 are
# shown and that is a complete position, not a top-N.
#
# Measured against the real 2026 pool, one step of this constant moves
# exactly two rows: K 12/DST 12 shows 94 receivers, 20/20 shows 78, 26/26
# shows 66. Group 3's own receiver block is the whole of what moves (33 ->
# 17 -> 5); group 2's receiver block is 61 rows either way, because it is
# sized by what its column has left below the Overall Board and nothing
# here touches that.
#
# CEILING = 28, and it is hard. Group 3's page 2 carries RECEIVERS, KICKERS
# and TEAM DEFENSE: ROWS_PER_PAGE - 3 * HEADER_ROWS = 57 data rows, of which
# _allocate_page reserves one for each block before serving the bounded ones,
# so K and DST can take 1 + 54/2 = 28 each and RECEIVERS is down to its
# guaranteed single row - already past useful. Set it higher and K (served
# first) keeps growing while TEAM DEFENSE starts LOSING rows to it: 29 gives
# K 29 and DST 27. Showing all 35 kickers is therefore not reachable at all
# without cutting defenses; the per-section truncation report render_xlsx
# returns says so out loud, but do not set this above 28 expecting depth.
K_DST_DEPTH = 20

# Which column group carries each split position's SECOND block, in the
# space its Overall Board leaves below itself: Running Backs under group 1,
# Receivers under group 2, exactly where the 2022 template puts them. Which
# of a position's two blocks gets its best players is NOT decided here - see
# _reading_order_key.
CONTINUED_IN = (
    (1, "RUNNING BACKS"),
    (1 + GROUP_GAP, "RECEIVERS (WR + TE)"),
)

# Total width of one column group, in the same Excel width units as WIDTHS -
# the ceiling a section title has to stay inside. See _title_width_units.
GROUP_WIDTH = (WIDTHS["rank"] + WIDTHS["name"] + WIDTHS["team_bye"]
               + WIDTHS["pos"] + WIDTHS["tier"] + 3 * WIDTHS["numeric"])

# An Excel column-width unit is the width of the '0' glyph in the workbook's
# Normal-style font, which openpyxl leaves at Calibri 11 - 7 pixels at
# 96dpi. A title is drawn in Calibri 8 BOLD, whose widest glyph is under one
# em: 8pt = 10.667px at 96dpi, so no character can exceed 10.667 / 7 width
# units. That is a deliberate over-estimate (real bold Calibri averages
# nearer half of it) chosen so the check below needs no font file to be
# installed and cannot pass by accident on a machine that happens to have a
# narrow substitute for Calibri.
TITLE_MAX_CHAR_WIDTH_UNITS = (8.0 * 96.0 / 72.0) / 7.0


def _title_width_units(title):
    """A hard upper bound on a section title's drawn width, in Excel column
    width units, so it can be compared against GROUP_WIDTH.

    Upper bound, not an estimate: nothing here should depend on which fonts
    a particular machine has installed, and a bound that is too generous can
    only ever make the check stricter."""
    return len(title) * TITLE_MAX_CHAR_WIDTH_UNITS


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
        cell = ws.cell(row, col0 + i, h)
        cell.font = FONT_BOLD
        cell.fill = HEADER_FILL


def _write_title(ws, row, col0, title):
    """Write a section title across the full width of one column group.

    MERGED, not just written into the group's first cell. That first cell is
    the Rank column at 2.8 width units and every title this module writes is
    longer than that, so Excel spills the text rightwards through the empty
    cells beside it - and "empty" includes the seven filled-but-valueless
    cells of the group and the spacer past them. What stops the spill is
    content in the next group's Rank cell on the same row, which is not
    something this layout guarantees. Merging bounds the title to its own
    group structurally instead. See the module docstring's SECTION TITLES
    note.

    Merging FIRST and styling afterwards is deliberate: openpyxl replaces
    the merged-away cells with fresh, unstyled MergedCell objects, so a fill
    or a border applied before the merge is discarded. Applied after, both
    are kept and written out (the grid in _apply_grid runs later still, for
    the same reason).
    """
    ws.row_dimensions[row].height = ROW_HEIGHT
    if N_COLS > 1:
        ws.merge_cells(start_row=row, start_column=col0,
                       end_row=row, end_column=col0 + N_COLS - 1)
    cell = ws.cell(row, col0)
    cell.value = title
    cell.font = FONT_BOLD
    # Left, explicitly: a merged cell is where Excel's default centring
    # would otherwise become visible, and these titles head a left-aligned
    # column of ranks.
    cell.alignment = Alignment(horizontal="left")
    # The template fills the whole width of the group on a title row, not
    # just the cell carrying the words.
    for i in range(N_COLS):
        ws.cell(row, col0 + i).fill = HEADER_FILL


def _pos_labels(rows):
    """id(BoardRow) -> "RB1" / "WR24" / "TQB5": position plus rank WITHIN
    that position, ordered by MY$ descending.

    The template's Pos column reads this way, and two things follow from it.
    It answers the question actually asked across the table - not "he is a
    receiver" but "he is the WR1" - and it is what the position colouring
    keys on, since the template's conditional rules compare this column's
    text against "RB1".."RB99" (see POS_FILL_COLORS).

    WR and TE are ONE pool everywhere else in this pipeline and stay one
    here: nothing about the ladder, the tiers or the dollars changes. This
    label alone counts them separately, because the template does - a TE
    printed as WR31 tells you nothing about the tight ends left on the
    board.

    Keyed by id() rather than by name: the same BoardRow objects are written
    in several places on the sheet (group 3's block and its continuation in
    group 1 or 2), and two real players can share a name.
    """
    by_pos = {}
    for r in rows:
        by_pos.setdefault(r.pos, []).append(r)
    labels = {}
    for pos, members in by_pos.items():
        # Ties on MY$ fall back to the board's own rank, which build_rows
        # already resolved deterministically, so this never depends on the
        # order the vendor CSV happened to arrive in.
        for i, r in enumerate(sorted(members, key=lambda m: (-m.my_dollars, m.rank)), 1):
            labels[id(r)] = "%s%d" % (pos, i)
    return labels


def _write_data_row(ws, row, col0, r, pos_labels):
    ws.row_dimensions[row].height = ROW_HEIGHT
    ws.cell(row, col0 + 0, r.rank).font = FONT
    ws.cell(row, col0 + 1, r.name).font = FONT
    ws.cell(row, col0 + 2, "%s/%s" % (r.team, r.bye if r.bye else "-")).font = FONT
    ws.cell(row, col0 + 3, pos_labels.get(id(r), r.pos)).font = FONT
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

    Exactly one printed PAGE per column - title, column header and
    ROWS_PER_PAGE - HEADER_ROWS data rows, ending on the page break - not
    half of the two-page budget. The two differ by one row (61 against 62
    per column), and that one row is the whole of Jeff's first complaint:
    sized against the budget, the Overall Board ran to row 64 and bled a
    single line of itself onto page 2. Sized against the page, it ends at
    ROWS_PER_PAGE and the continuation below it opens the next page.

    This still matches the 2022 template's proportion - its OVERALL block
    took 57 of ~116 usable rows per column and stopped at its own page
    break, rather than filling the column edge to edge."""
    return 2 * (ROWS_PER_PAGE - HEADER_ROWS)


def _write_overall_columns(ws, overall, pos_labels):
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
                   holed. See _plan_split_positions.
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
            _write_data_row(ws, row, col0, r, pos_labels)
            row += 1
        next_rows[col0] = row
    return shown, cut, next_rows


def _block_members(rows):
    """The group 3 blocks that have any real members, in POSITION_BLOCKS
    order, as (title, members, want, flex).

    `want` is how many data rows the block would use if the sheet were
    unlimited:
      Team QB       - one per real NFL franchise (len(NFL_TEAMS), the same
                      authority `sffl.cli.cmd_render` uses for what counts
                      as a franchise), so it always fits whole;
      Kickers, DST  - K_DST_DEPTH, the single dial for how deep those two
                      flat-priced $1 pools are printed;
      the other two - everyone, i.e. no natural ceiling, which is what makes
                      them the FLEX_BLOCKS that absorb a page's leftover
                      room.
    """
    out = []
    for title, positions in POSITION_BLOCKS:
        members = sorted([r for r in rows if r.pos in positions],
                         key=lambda r: (-r.my_dollars, r.rank))
        if not members:
            continue
        if title == "TEAM QB":
            want = min(len(members), len(NFL_TEAMS))
        elif title in ("KICKERS", "TEAM DEFENSE"):
            want = min(len(members), K_DST_DEPTH)
        else:
            want = len(members)
        out.append((title, members, want, title in FLEX_BLOCKS))
    return out


def _allocate_page(page_blocks, page_rows):
    """Hand out one printed page's rows among the blocks assigned to it.

    Returns (alloc, leftover) - {title: data rows} and the rows nothing on
    this page could use - or None if the page cannot give every block on it
    a title, a header and at least one data row, which is the one outcome
    this module treats as not a layout at all (see
    test_every_position_appears_on_the_printed_sheet).

    Bounded blocks are served to their `want` first, then the flex blocks
    share whatever is left. A block never spills onto the next page: the
    page is the unit, which is what keeps two different positions from
    interleaving across the fold.
    """
    if not page_blocks:
        return {}, page_rows

    avail = page_rows - HEADER_ROWS * len(page_blocks)
    if avail < len(page_blocks):
        return None

    alloc = dict((b[0], 1) for b in page_blocks)
    avail -= len(page_blocks)

    for title, _members, want, flex in page_blocks:
        if flex:
            continue
        take = min(want - alloc[title], avail)
        alloc[title] += take
        avail -= take

    flex_blocks = [b for b in page_blocks if b[3]]
    while avail > 0 and flex_blocks:
        hungry = [b for b in flex_blocks if alloc[b[0]] < b[2]]
        if not hungry:
            break
        share = max(1, avail // len(hungry))
        for title, _members, want, _flex in hungry:
            if avail <= 0:
                break
            take = min(share, want - alloc[title], avail)
            alloc[title] += take
            avail -= take

    return alloc, avail


def _page_partitions(n_blocks, n_pages):
    """Every way to cut an ordered list of n_blocks into n_pages contiguous,
    possibly empty runs - as lists of (start, stop) index pairs.

    Exhaustive rather than greedy, and cheap enough to be: five blocks over
    two pages is six candidates. Greedy packing is what produced the layout
    Jeff rejected - it filled page 1 with Team QB and part of the Running
    Backs and then opened Receivers nine rows above the fold, because at
    that moment there was still room and nothing was looking ahead to what
    the choice cost page 2.
    """
    if n_pages == 1:
        return [[(0, n_blocks)]]
    out = []
    for cut in range(n_blocks + 1):
        for rest in _page_partitions(n_blocks - cut, n_pages - 1):
            tail = [(cut + s, cut + e) for s, e in rest]
            out.append([(0, cut)] + tail)
    return out


def _plan_position_blocks(rows):
    """Choose where each of group 3's position blocks starts and how many
    data rows it gets, one whole printed page at a time.

    Returns a list of (title, members, start_row, n_data) in sheet order.

    Every candidate partition of the blocks across the N_PAGES pages is
    scored on, in order:
      1. validity  - a partition that cannot give some position a single
                     row is not a layout; those are dropped outright, and
                     if none survives this raises rather than quietly
                     printing a sheet with a position missing.
      2. gap       - blank rows left ABOVE the last thing on the sheet. Those
                     are printed white space while players are being cut,
                     the defect three earlier versions of this module
                     shipped.
      3. rows shown - maximised, so the layout never stops at the foot of
                     page 1 with page 2 empty and players still cut.

    Against the real 2026 pool this picks Team QB + Running Backs on page 1
    and Receivers + Kickers + Team Defense on page 2 - the same split the
    2022 template makes, and with no gap on either page.
    """
    blocks = _block_members(rows)
    if not blocks:
        return []

    best = None
    for partition in _page_partitions(len(blocks), N_PAGES):
        pages = [blocks[s:e] for s, e in partition]
        placements = []
        leftovers = []
        ok = True
        for p, page_blocks in enumerate(pages):
            result = _allocate_page(page_blocks, ROWS_PER_PAGE)
            if result is None:
                ok = False
                break
            alloc, leftover = result
            row = p * ROWS_PER_PAGE + 1
            for title, members, _want, _flex in page_blocks:
                n = alloc[title]
                placements.append((title, members, row, n))
                row += HEADER_ROWS + n
            leftovers.append(leftover)
        if not ok:
            continue

        last_page = max(p for p, pb in enumerate(pages) if pb)
        # Space left at the foot of the LAST page carrying content is the
        # sheet simply ending; space left on any page before it is a hole.
        gap = sum(lv for p, lv in enumerate(leftovers) if p < last_page)
        shown = sum(n for _t, _m, _r, n in placements)
        key = (gap, -shown)
        if best is None or key < best[0]:
            best = (key, placements)

    if best is None:
        raise ValueError(
            "cannot lay out group 3: %d position block(s) do not fit in %d "
            "printed pages of %d rows even at one row each"
            % (len(blocks), N_PAGES, ROWS_PER_PAGE))
    return best[1]


def _continuation_capacity(start_row):
    """Data rows available for a continuation position block that begins at
    `start_row` in group 1 or group 2: everything from its first data row
    down to ROW_BUDGET, after paying its own HEADER_ROWS (title + header).

    Derived from where the block actually starts, not from a fixed fraction
    of the budget, so it stays exact whatever the Overall Board above it
    consumed."""
    first_data_row = start_row + HEADER_ROWS
    return max(0, ROW_BUDGET - first_data_row + 1)


def _continuation_start(start_row, n_members):
    """Where a continuation block actually opens, given the first row its
    column left free.

    Normally that is exactly `start_row`: a single long list running over
    the fold is not the problem Jeff reported - two DIFFERENT sections
    interleaved across it is. The one case this adjusts is a block opening
    in the last PAGE_ALIGN_SLACK rows of page 1 and continuing past the
    break, which prints a section title and a column header at the very
    foot of one sheet with every one of its players on the next. That is
    pushed to the top of page 2 instead, leaving at most
    PAGE_ALIGN_SLACK - 1 blank rows on the fold - the only blank rows this
    module ever leaves above content, and only when the section above ran
    out of players to fill them with.

    A block that would fit whole above the break is left where it is: there
    is nothing to straddle.
    """
    if start_row > ROWS_PER_PAGE:
        return start_row
    if ROWS_PER_PAGE - start_row >= PAGE_ALIGN_SLACK:
        return start_row
    rows_before_break = ROWS_PER_PAGE - (start_row + HEADER_ROWS) + 1
    if n_members <= max(0, rows_before_break):
        return start_row
    return ROWS_PER_PAGE + 1


def _reading_order_key(col0, start_row):
    """Where a block sits in the order a human reads the printed sheet.

    Two landscape sheets, three column groups on each. A reader takes all of
    page 1 left to right - group 1, group 2, group 3 - and only then starts
    page 2, again left to right. So a block's place in that order is (the
    page it opens on, its column group), page first.

    Page BEFORE column is the whole subtlety, and getting it backwards would
    have swapped a defect for its mirror image. Running Backs occupies group
    3 on page 1 and group 1 on page 2; ordering on the column alone would
    have declared group 1 "first" and printed RB1 overleaf from RB28. It is
    Receivers, whose two blocks BOTH open on page 2, where the column
    decides - and that is the pair Jeff found backwards. See the module
    docstring's READING ORDER note.

    A block that opens on page 1 and runs over the fold is keyed on the page
    it opens on: that is where the reader meets its title and its first row,
    which is what the ordering is about.
    """
    page = (start_row - 1) // ROWS_PER_PAGE
    return (page, col0)


def _plan_split_positions(rows, next_rows):
    """Every position block on the sheet, in the order it will be READ, as
    (col0, title, start_row, members) with each block's slice of that
    position already cut.

    Group 3 stacks all five blocks (_plan_position_blocks). Two of those
    positions - the FLEX_BLOCKS, which absorb nearly all the truncation -
    additionally get a second block in the space group 1 and group 2 have
    left below their Overall Board, at whichever row those columns actually
    reached (`next_rows`, see _write_overall_columns for why that must not
    be a fixed fraction of ROW_BUDGET).

    Two decisions live here and they are independent:

      SIZE. Each block's row count is exactly what the layout already gave
      it - group 3's from _plan_position_blocks, the second block's from
      whatever its column has left. This function does not change any block's
      size, so no page can grow a hole because of it. In particular group
      3's block is always filled to its planned n_data: it has other blocks
      stacked under it, so a block short of its allocation is blank printed
      rows in the middle of a column.

      WHICH PLAYERS. The blocks are then sorted by _reading_order_key and
      served the position's members in that order - so the block a reader
      reaches first holds the higher-valued players, whichever group it
      happens to be in. That is the fix for Jeff's WR ordering complaint;
      before it, group 3 was always served first because it was written
      first.
    """
    col3 = 1 + 2 * GROUP_GAP
    placements = _plan_position_blocks(rows)

    members_by_title = {}
    slots = {}          # title -> [(col0, start_row, n_data)]
    order = []          # titles, in POSITION_BLOCKS order, for determinism
    for title, members, start_row, n_data in placements:
        members_by_title[title] = members
        slots[title] = [(col3, start_row, n_data)]
        order.append(title)

    for col0, title in CONTINUED_IN:
        members = members_by_title.get(title)
        if not members:
            continue
        placed = sum(n for _c, _r, n in slots[title])
        remaining = len(members) - placed
        if remaining <= 0:
            # Group 3 already showed this position whole; a second block
            # would be a title over nothing.
            continue
        start_row = _continuation_start(next_rows[col0], remaining)
        n_data = min(_continuation_capacity(start_row), remaining)
        if n_data <= 0:
            # No room even for a title - the Overall Board filled this
            # column to the budget. Write nothing rather than a headed but
            # empty block.
            continue
        slots[title].append((col0, start_row, n_data))

    plan = []
    for title in order:
        members = members_by_title[title]
        taken = 0
        for col0, start_row, n_data in sorted(
                slots[title],
                key=lambda s: _reading_order_key(s[0], s[1])):
            plan.append((col0, title, start_row, members[taken:taken + n_data]))
            taken += n_data
    return plan, members_by_title


def _write_block(ws, col0, title, start_row, members, pos_labels):
    """Title row, column-header row, then one data row per member."""
    _write_title(ws, start_row, col0, title)
    _write_header(ws, start_row + 1, col0)
    row = start_row + HEADER_ROWS
    for r in members:
        _write_data_row(ws, row, col0, r, pos_labels)
        row += 1


def _group_col0s():
    """First column (1-indexed) of each of the three column groups."""
    return [1, 1 + GROUP_GAP, 1 + 2 * GROUP_GAP]


def _last_used_row(ws):
    """The lowest row carrying content in any of the three groups' first
    (Rank) column - every row this module writes, title, header or data,
    populates it, so it reports the sheet's real vertical extent."""
    last = 0
    for col0 in _group_col0s():
        for r in range(1, ws.max_row + 1):
            if ws.cell(r, col0).value not in (None, ""):
                last = max(last, r)
    return last


def _apply_grid(ws, last_row):
    """Draw the ruled table: a thin border on all four sides of every cell
    in the used rectangle, spacer columns included, exactly as the 2022
    template does over its own A1:T118.

    This is NOT the same thing as Excel's screen gridlines, which both this
    sheet and the template switch off. The template turns those off AND
    draws this; reading only `showGridLines: False` off it is how this
    module came to ship a printed board with no rules on it at all.

    Every row inside the rectangle also gets ROW_HEIGHT here, not just the
    rows carrying text: a bordered blank row left at Excel's 15pt default
    would be half again as tall as the 9.95pt this sheet's whole two-page
    geometry is computed from, and would push the foot of page 2 onto a
    third sheet.
    """
    last_col = _group_col0s()[-1] + N_COLS - 1
    for r in range(1, last_row + 1):
        ws.row_dimensions[r].height = ROW_HEIGHT
        for c in range(1, last_col + 1):
            ws.cell(r, c).border = GRID_BORDER


def _apply_pos_colours(ws, last_row):
    """Attach the template's position colouring: one `cellIs between` rule
    per position over each group's Pos column, keyed on that column's text
    (see _pos_labels and POS_FILL_COLORS).

    Conditional formatting rather than a static fill, matching the template,
    so the colour follows the label - reorder or re-rank the board and the
    colours stay correct with nothing to re-derive.
    """
    if last_row < 1:
        return
    for col0 in _group_col0s():
        letter = get_column_letter(col0 + 3)          # the Pos column
        ref = "%s1:%s%d" % (letter, letter, last_row)
        for pos, rgb in POS_FILL_COLORS:
            ws.conditional_formatting.add(ref, CellIsRule(
                operator="between",
                formula=['"%s1"' % pos, '"%s99"' % pos],
                fill=PatternFill(start_color=rgb, end_color=rgb,
                                 fill_type="solid"),
                font=Font(color="FF000000")))


# --------------------------------------------------------------------------
# THE SECOND WORKSHEET - "Key & Intel".
#
# The board is full: 126 rows, two printed pages, every one of them a player.
# A legend cut into it costs player rows one for one, so the legend goes on
# its own sheet in the SAME workbook - one file to print, nothing that can be
# separated from the board it explains.
#
# Its content is prose, which is a different layout problem from the board's
# and gets its own geometry rather than reusing ROW_HEIGHT. Two decisions
# carry it:
#
#   A UNIFORM LINE GRID. Every row on the sheet is INTEL_LINE_PT tall and a
#   paragraph occupies as many rows as it has lines, merged vertically. That
#   is what lets two independent columns of prose share one set of rows
#   without either going ragged: both pack against the same grid, and the
#   one-page check is a row count exactly as it is on the board.
#
#   THE LINE BREAKS ARE COMPUTED HERE, NOT LEFT TO EXCEL. Text is wrapped to
#   an explicit character count and written with real newlines in it. Excel is
#   still told to wrap (a viewer with a wider substitute font must not spill
#   text out of the cell), but with the breaks already in place it has nothing
#   left to do, so the number of lines a paragraph draws is a number this
#   module KNOWS rather than one it hopes for - and the row height it sets is
#   therefore right. _chars_per_line is deliberately an under-estimate of what
#   fits, so the error can only ever be a short line, never a clipped one.
#
# The board had exactly the opposite bug (a title written into a 2.8-unit cell
# and left to spill through its neighbours) and it was fixed by merging; the
# same rule applies here, everything is merged or wrapped, nothing is left to
# overflow.
# --------------------------------------------------------------------------

INTEL_SHEET_TITLE = "Key & Intel"

# Five columns: term, text, gutter, term, text. Two columns of prose, because
# a single column across a landscape sheet is a 10-inch measure and unreadable
# at any size that also fits the page.
#
# The five together must clear _printable_width_px() with room to spare, not
# merely fit it: the pixel arithmetic below is the standard conversion and is
# close but not identical to what a given Excel build does with the last
# fraction of a column. The widths here leave ~25px (a quarter inch) of that
# slack, so a rounding disagreement cannot push the right-hand column onto a
# second sheet of paper. _write_intel_sheet raises if it ever stops fitting.
INTEL_TERM_WIDTH = 10.0
INTEL_TEXT_WIDTH = 57.5
INTEL_GUTTER_WIDTH = 3.0

INTEL_TITLE_PT = 14
INTEL_SUB_PT = 9
INTEL_HEAD_PT = 11
INTEL_BODY_PT = 10

# One line of the grid. 10pt Calibri needs ~13.4pt of leading to look like
# prose rather than a stack; 14 gives the 11pt section headings room too, so
# one constant serves every row on the sheet and the page arithmetic stays a
# row count.
INTEL_LINE_PT = 14.0

# An Excel column-width unit is the width of '0' in the workbook's Normal font
# (Calibri 11, which openpyxl leaves alone) - 7 pixels at 96dpi. A column of
# width w draws 7w pixels of text plus about 5 pixels of cell padding.
PX_PER_WIDTH_UNIT = 7.0
CELL_PADDING_PX = 5

# Landscape letter, and the margins render_xlsx applies below. Only these
# affect how much of a line fits across the printed page.
PAGE_WIDTH_IN = 11.0
MARGIN_LEFT_IN = 0.75
MARGIN_RIGHT_IN = 0.0

INTEL_FONT_TITLE = Font(name="Calibri", size=INTEL_TITLE_PT, bold=True)
INTEL_FONT_SUB = Font(name="Calibri", size=INTEL_SUB_PT, italic=True)
INTEL_FONT_HEAD = Font(name="Calibri", size=INTEL_HEAD_PT, bold=True)
INTEL_FONT_TERM = Font(name="Calibri", size=INTEL_BODY_PT, bold=True)
INTEL_FONT_BODY = Font(name="Calibri", size=INTEL_BODY_PT)

# Top-aligned everywhere: a paragraph merged down four rows must start at the
# first of them, beside its term, not float in the middle of them.
INTEL_ALIGN_TEXT = Alignment(horizontal="left", vertical="top", wrap_text=True)
INTEL_ALIGN_TERM = Alignment(horizontal="left", vertical="top")
# The rule under a section heading - the board's own thin line, used where it
# suits. A full ruled grid over prose would read as a table, which this is not.
INTEL_RULE = Border(bottom=_THIN)


def _intel_rows_per_page():
    """Rows of INTEL_LINE_PT that fit one printed page, at SCALE_PCT.

    Same derivation as _rows_per_page, against the same page geometry - only
    the row height differs. See that function for why scale divides.
    """
    printable_pt = (PAGE_HEIGHT_IN - MARGIN_TOP_IN - MARGIN_BOTTOM_IN) * 72.0
    return int(printable_pt // (INTEL_LINE_PT * (SCALE_PCT / 100.0)))


# ONE printed page, not two: the board's overflow costs players, this sheet's
# would cost a third sheet of paper carrying four lines of text.
INTEL_ROW_BUDGET = _intel_rows_per_page()


def _printable_width_px():
    """Width available on one landscape-letter page, in natural pixels.

    Natural, i.e. before the print scale shrinks it - the same convention as
    _rows_per_page, so a column layout is compared against the space it will
    actually occupy at SCALE_PCT.
    """
    inches = PAGE_WIDTH_IN - MARGIN_LEFT_IN - MARGIN_RIGHT_IN
    return inches * 96.0 / (SCALE_PCT / 100.0)


def _column_px(width_units):
    """Pixels one column of `width_units` occupies, padding included."""
    return int(round(width_units * PX_PER_WIDTH_UNIT)) + CELL_PADDING_PX


def _chars_per_line(width_units, font_pt, bold=False):
    """How many characters this module will allow on one line of that column.

    A DELIBERATE UNDER-ESTIMATE. It prices every character at the width of a
    DIGIT in the given size (Calibri's digits are wider than its lowercase
    average), and adds 5% for bold. Wrapping short can only leave a line
    ending early; wrapping long would put more lines in the cell than the row
    height allows, and Excel would clip them - text missing from a printed
    page, which is the failure this sheet cannot have. It also means the
    result depends on no font being installed anywhere.
    """
    usable = width_units * PX_PER_WIDTH_UNIT - 2.0
    char_px = PX_PER_WIDTH_UNIT * (float(font_pt) / 11.0)
    if bold:
        char_px *= 1.05
    return max(1, int(usable / char_px))


def _wrap(text, width_chars):
    """Word-wrap to a list of lines, never empty."""
    lines = textwrap.wrap(text, width_chars, break_long_words=False,
                          break_on_hyphens=False)
    return lines or [""]


def _check_fits(text, width_units, font_pt, bold, where):
    """Refuse to write a single-line string wider than its cell.

    Section headings and the term beside each paragraph are written on one
    line by design - they are not wrapped, so nothing would break them and a
    too-long one would be silently clipped by its merge. Raise instead: a
    legend with half a heading on it is worse than a render that stops.
    """
    limit = _chars_per_line(width_units, font_pt, bold=bold)
    if len(text) > limit:
        raise ValueError(
            "%s %r is %d characters; only %d fit the %.1f-unit space it is "
            "written into at %dpt. Shorten it, or widen the column."
            % (where, text, len(text), limit, width_units, font_pt))


def _write_intel_heading(ws, row, term_col, heading):
    """A section heading, merged across the term and text columns and ruled
    underneath - the board's white-filled header row, restated for prose."""
    _check_fits(heading, INTEL_TERM_WIDTH + INTEL_TEXT_WIDTH, INTEL_HEAD_PT,
                True, "section heading")
    ws.merge_cells(start_row=row, start_column=term_col,
                   end_row=row, end_column=term_col + 1)
    cell = ws.cell(row, term_col, heading)
    cell.font = INTEL_FONT_HEAD
    cell.alignment = INTEL_ALIGN_TERM
    for col in (term_col, term_col + 1):
        ws.cell(row, col).fill = HEADER_FILL
        ws.cell(row, col).border = INTEL_RULE


def _write_intel_item(ws, row, term_col, term, lines):
    """One term and its paragraph, occupying len(lines) rows of the grid.

    Both cells are merged down those rows so the paragraph is one block of
    text with one border and one alignment, and so nothing can spill sideways
    into the other column of prose.
    """
    _check_fits(term, INTEL_TERM_WIDTH, INTEL_BODY_PT, True, "term")
    n = len(lines)
    if n > 1:
        for col in (term_col, term_col + 1):
            ws.merge_cells(start_row=row, start_column=col,
                           end_row=row + n - 1, end_column=col)
    cell = ws.cell(row, term_col, term)
    cell.font = INTEL_FONT_TERM
    cell.alignment = INTEL_ALIGN_TERM
    cell = ws.cell(row, term_col + 1, "\n".join(lines))
    cell.font = INTEL_FONT_BODY
    cell.alignment = INTEL_ALIGN_TEXT


def _write_intel_column(ws, term_col, sections, start_row):
    """Write one column of sections. Returns the last row it used."""
    chars = _chars_per_line(INTEL_TEXT_WIDTH, INTEL_BODY_PT)
    row = start_row
    for i, (heading, items) in enumerate(sections):
        if i:
            row += 1          # one blank line of the grid between sections
        _write_intel_heading(ws, row, term_col, heading)
        row += 1
        for term, text in items:
            lines = _wrap(text, chars)
            _write_intel_item(ws, row, term_col, term, lines)
            row += len(lines)
    return row - 1


def _write_intel_sheet(wb, facts):
    """Add the Key & Intel worksheet to `wb`, and return the rows it used.

    Called after the Board is finished and never before: openpyxl assigns
    style and shared-string indices in the order cells are written, so every
    font, fill and string this sheet introduces appends AFTER the board's and
    leaves the board's own worksheet XML byte for byte what it was.

    Raises ValueError if the laid-out sheet would not print on one page, or if
    the columns would not fit the printed width. Both are arithmetic on the
    same geometry the board uses - neither is a guess, and neither may be
    discovered by a person at the printer on auction morning.
    """
    widths = [INTEL_TERM_WIDTH, INTEL_TEXT_WIDTH, INTEL_GUTTER_WIDTH,
              INTEL_TERM_WIDTH, INTEL_TEXT_WIDTH]
    used_px = sum(_column_px(w) for w in widths)
    if used_px > _printable_width_px():
        raise ValueError(
            "the Key & Intel columns need %d px and one landscape-letter page "
            "gives %d at %d%% scale; the sheet would print on two pages side "
            "by side" % (used_px, int(_printable_width_px()), SCALE_PCT))

    ws = wb.create_sheet(INTEL_SHEET_TITLE)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_LETTER
    ws.page_setup.scale = SCALE_PCT
    ws.sheet_view.showGridLines = False
    ws.page_margins.left = MARGIN_LEFT_IN
    ws.page_margins.right = MARGIN_RIGHT_IN
    ws.page_margins.top = MARGIN_TOP_IN
    ws.page_margins.bottom = MARGIN_BOTTOM_IN
    ws.page_margins.header = 0.0
    ws.page_margins.footer = 0.0

    for i, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    last_col = len(widths)
    # The title gets two rows of the grid: 14pt text does not sit in a 14pt
    # row, and merging it down two is cheaper than a second row height.
    ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=last_col)
    cell = ws.cell(1, 1, intel_mod.title(facts))
    cell.font = INTEL_FONT_TITLE
    cell.alignment = Alignment(horizontal="left", vertical="center")

    full_width = sum(widths)
    sub_lines = _wrap(intel_mod.subtitle(facts),
                      _chars_per_line(full_width, INTEL_SUB_PT))
    ws.merge_cells(start_row=3, start_column=1,
                   end_row=2 + len(sub_lines), end_column=last_col)
    cell = ws.cell(3, 1, "\n".join(sub_lines))
    cell.font = INTEL_FONT_SUB
    cell.alignment = INTEL_ALIGN_TEXT
    for col in range(1, last_col + 1):
        ws.cell(2 + len(sub_lines), col).border = INTEL_RULE

    start_row = 2 + len(sub_lines) + 2      # one blank row under the rule
    last = max(
        _write_intel_column(ws, 1, intel_mod.left_sections(facts), start_row),
        _write_intel_column(ws, 4, intel_mod.right_sections(facts), start_row))

    if last > INTEL_ROW_BUDGET:
        raise ValueError(
            "the Key & Intel sheet needs %d rows of %.2fpt and one "
            "landscape-letter page holds %d at %d%% scale; it would run onto "
            "a second sheet. Shorten the text or raise the budget "
            "deliberately." % (last, INTEL_LINE_PT, INTEL_ROW_BUDGET,
                               SCALE_PCT))

    for r in range(1, last + 1):
        ws.row_dimensions[r].height = INTEL_LINE_PT
    return last


def render_xlsx(lg, rows, path, intel=None):
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
                   by _allocate_page - if this call fails to write a
                   position's title at all, that is the bug this stats dict
        intel    - {"rows": n, "budget": n} for the second worksheet; see
                   INTEL_ROW_BUDGET. `intel` (the argument) is the
                   `sffl.render.intel.IntelFacts` that sheet states, built by
                   the caller from the run that priced this board. Passing
                   None gathers what can be derived from `lg` and `rows`
                   alone, which is a legend without the market and fit
                   figures - never a legend quoting stale ones.
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

    for col0 in _group_col0s():
        _set_widths(ws, col0)

    # Position + rank within position ("RB1", "WR24"), computed once over
    # the whole board so a player carries the same label wherever he is
    # written - group 3's block and its continuation in group 1 or 2.
    pos_labels = _pos_labels(rows)

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
        overall_shown, overall_cut, next_rows = _write_overall_columns(
            ws, overall, pos_labels)

    # Every position block on the sheet - group 3's stack plus the second
    # block Running Backs and Receivers each get below an Overall Board -
    # planned together, so the two blocks a split position owns can be
    # served its players in the order they will be READ rather than in the
    # order they happen to be written. See _plan_split_positions.
    plan, members_by_title = _plan_split_positions(rows, next_rows)
    for col0, title, start_row, members in plan:
        _write_block(ws, col0, title, start_row, members, pos_labels)

    # Last, over whatever the writes above actually produced: the ruled grid
    # and the Pos-column colouring both need the sheet's real extent.
    last_row = _last_used_row(ws)
    _apply_grid(ws, last_row)
    _apply_pos_colours(ws, last_row)

    # The legend, on its own sheet in the same workbook, and written LAST.
    # Nothing above this line may depend on it, and it may not perturb the
    # board: openpyxl hands out style and shared-string indices in write
    # order, so a sheet added after a finished board leaves the board's
    # worksheet XML byte-identical (test_the_board_sheet_is_untouched_by_the
    # _intel_sheet pins that).
    facts = intel if intel is not None else intel_mod.gather(lg, rows)
    intel_rows = _write_intel_sheet(wb, facts)

    wb.save(path)

    written = {}
    for _col0, title, _start_row, members in plan:
        written[title] = written.get(title, 0) + len(members)

    sections = {}
    for title, _positions in POSITION_BLOCKS:
        if title not in members_by_title:
            continue
        shown_n = written.get(title, 0)
        sections[title] = {"shown": shown_n,
                           "cut": len(members_by_title[title]) - shown_n}

    return {
        "total": len(rows),
        "overall": {"shown": len(overall_shown), "cut": len(overall_cut)},
        "sections": sections,
        "intel": {"rows": intel_rows, "budget": INTEL_ROW_BUDGET},
    }

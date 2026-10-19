# Test fixtures

This repo is public, so no fixture holds licensed vendor data or real CBS league pages.

**CBS pages** (`cbs_weekly_*.txt`, `cbs_team_page.txt`) were captured from the live league
site in August 2026 and replaced on 2026-10-19 with constructed copies:

- **Kept exactly:** the layout (column count and order, tabs, spaces, trailing spaces after
  some team codes, the `id=` prefix and id lengths, `•`, `N/R`, `---`, `W (m/dd)` waiver
  tokens, placeholder owner names, the row with no id), and the public facts: NFL player
  and team names, team codes, opponents, bye weeks, game times.
- **Constructed:** every CBS id and every CBS number (projected stats, FPTS, OVP, ROST,
  START, EXPERT, rank, 2025 and 3-year points, O/U). Each constructed row scores exactly
  what the real row it replaced scored under `leagues/sffl/2026.yaml`, so lineup, waiver,
  tie and tolerance tests exercise the same behaviour. FPTS sits inside the TQB and DST
  tolerance windows measured on the real capture, and K's FPTS follows CBS's flat
  convention (field goals plus extra points).
- **The real pages** are kept in the private data repo (`jmill72x/fantasy-football-data`,
  `2026/cbs/snapshot-2026-10-19/test-fixtures/`). `poc/measure_weekly_calibration.py`
  reads the real RB-WR-TE page from there by default.

`cbs_ros_*.txt` were constructed from the start.

**Draft Sharks samples** (`draftsharks_*.csv`) keep the export's real 47-column header with
invented numbers (cleaned 2026-08-18). `footballguys_sample.csv` is not verbatim either.

**Not cleaned (Jeff's call):** `weekly_sample.csv` and the golden lines in
`tests/test_scoring.py` are real 2025 CBS game logs. They are the evidence behind the
scoring engine's validation, and swapping in invented lines would make that check circular.

Never add a real capture or vendor export here. Put it in the private data repo and, if a
test needs its shape, construct rows the way these were.

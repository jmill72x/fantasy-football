# Preseason runbook: 2027 and every season after

Every step to get from "new season" to a printed auction board, then to a working in-season
alert. Written 2026-10-19 so that nothing depends on memory, old commits or a chat
transcript. **Swap 2027 for the season you're preparing, and the year before it for 2026.**

This file holds no licensed numbers, so it can stay in the public repo. Licensed and league
data lives in the private archive below.

## Where the data lives

The repo is public, so the vendor extracts (`data/extracts/`), the CBS weekly data
(`data/weekly/`) and the CBS captures (`data/captures/`) are gitignored and live only on
the Mac mini. They're kept privately in three more places:

| Copy | Where | State |
|---|---|---|
| **Private data repo (the main copy)** | `jmill72x/fantasy-football-data` (private GitHub repo), cloned at `~/Projects/fantasy-football-data`; by season, source and week | Created and loaded from the 2026 archive 2026-10-19, with a `MANIFEST.sha256` and a `git bundle --all` of this repo. Its README says how to add each week |
| Local archive | `~/Archive/fantasy-football-data/<season>/` on the mini (dir 700, files 600) | 2026 archived 2026-10-19 |
| **Pi copy (the fallback)** | piNAS, Documents share: `Documents/fantasy-football-data/<season>/` (on the Pi: `<data disk>/Documents/fantasy-football-data/`, where the data disk is the `/srv/dev-disk-by-uuid-…` mount holding Documents) | 2026 copied and checksum-verified 2026-10-19 |

**If anything happens to the private repo or the mini, there's a local copy on the Pi.**
Each season folder has a `README.txt` and a `MANIFEST-<date>.sha256`; check a copy with
`shasum -a 256 -c MANIFEST-<date>.sha256` (on the Pi, `sha256sum -c`). The iCloud folder
`Fantasy Football/extracts-archive/` holds the 08-03 vendor extracts too, but not the
08-23 Draft Sharks file or any CBS data, so don't rely on it alone.

What the 2026 archive holds, and why 2027 needs it:

- `extracts/Draft Sharks/2026/rankings-2026-08-23.csv`: the file `market/2026.yaml` was
  fitted on. Its sha256 equals `projections_file_sha256` in that YAML. Without it the
  2026 market model can't be refit or re-checked.
- `weekly/2025/`: the CBS game logs behind `calibration/2025.yaml`. CBS drops per-week
  data when it rolls the season over, so they can't be collected again.
- `captures-2026-10-19/`, `real-fixtures-2026-10-19/` and `superpowers-2026-10-19/`: the
  in-season CBS pages as of that day, the real CBS pages the tests use today, and the
  working records NEXT.md cites.

To restore onto a fresh checkout, copy `extracts/` to `data/extracts/` and `weekly/` to
`data/weekly/`. The CBS login (`data/browser-profile/`) is never archived: it's a live
credential, so recreate it with `./.venv/bin/python ops/cbs_login.py`.

## Calendar

| When | What |
|---|---|
| May (NFL schedule release) | Byes file and the alert's week-1 date (steps 3 and 13) |
| Early to mid August | League rules check, Draft Sharks export, first board (steps 2 to 8) |
| The weekend before the auction | Fresh Draft Sharks export, final board, print, sealed bid (steps 4, 7 to 10). 2026: refresh 08-21 to 08-23, bid due 08-24, auction 08-26 |
| The days after the auction | Prices, bids, TQB map, out-of-sample check, refit (steps 11 and 12) |
| Before week 1 | In-season switch-over (step 13) |
| Every week in season | Collect and archive (below) |
| After the last week, before CBS rolls over | Season results, then the curves decision (step 6) |

## Season-bound values

None of these warns when it's stale. Each one is a 2026 value in code or a script.

| Value | Where | 2026 value | What to do for 2027 |
|---|---|---|---|
| League profile | `DEFAULT_LEAGUE`, `src/sffl/cli.py:32` | `leagues/sffl/2026.yaml` | Step 2: write `leagues/sffl/2027.yaml` and point the default at it |
| Bye weeks | `DEFAULT_BYES`, `src/sffl/render/rows.py:21` | `leagues/nfl-byes-2026.yaml` | Step 3: write `leagues/nfl-byes-2027.yaml`; pass `--byes` or move the default |
| TQB starter map | `DEFAULT_TQB_STARTERS`, `src/sffl/fit.py:25` | `identity/tqb-2025-starters.yaml` | Read only with `--prices`. Step 11 writes the 2027 map after the auction |
| Market model | the `--market` flag | `market/2026.yaml` | Use it as is before the 2027 auction (step 7); fit `market/2027.yaml` after it (step 12) |
| Calibration curves | `--curves` everywhere; `ops/run_alert.sh` line 84 | `calibration/2025.yaml` | Step 6 |
| Alert week-1 date | `ops/run_alert.sh` line 57 | `datetime.date(2026, 9, 9)` | Step 13 |
| CBS parse season | `season=2026` default in `cbs_weekly.parse` | 2026 | CLI callers pass the league profile's season, so step 2 covers it |

## Steps, in order

### 1. Environment

```bash
cd ~/Projects/fantasy-football
./.venv/bin/pip install -r requirements.txt     # the venv is Python 3.9.6; see CLAUDE.md
./.venv/bin/pytest -q
```

The suite count is in NEXT.md's machine-checked block. Three tests skip when
`data/weekly/` is missing; restore it from the archive first.

### 2. League rules

Check the league's settings on CBS for any change since last season.

- **No change:** copy `leagues/sffl/2026.yaml` to `leagues/sffl/2027.yaml`, set
  `season: 2027`, and point `DEFAULT_LEAGUE` (`src/sffl/cli.py:32`) at it. The alert job
  passes no `--league`, so the default is what it uses.
- **A change:** do the same, change the bands, and validate each changed band against real
  CBS weekly points before trusting it (design spec, "a 2027 rule change is a new file").
  Never validate against pre-2025 data: the rules changed between 2024 and 2025. Don't
  touch `src/sffl/scoring.py` without new ground truth.
- Still open from 2026: the lost-fumble term (NEXT.md's checklist). Draft Sharks doesn't
  publish offensive fumbles, so it needs a Footballguys join.

### 3. Bye weeks

Write `leagues/nfl-byes-2027.yaml` the way the 2026 file's header describes: two
independent sources that agree on all 32 teams, keys quoted (unquoted `NO` parses as
false), and the per-week counts summing to 32. Pass `--byes leagues/nfl-byes-2027.yaml`
on every render and plan, or move `DEFAULT_BYES`. A 2027 render without it silently prints
2026 byes.

### 4. Draft Sharks export

1. Renew the subscription and re-sync the league.
2. Set the draft type to **AUCTION**, and re-check it after every re-sync: a sync imports
   as Snake.
3. Go to RANKINGS, then Redraft (`/rankings`), then the **Projections** tab, and export
   the **NON-PPR** row with the icon at the far right. **Not** RANKINGS, then Auction: that
   export has 13 columns and no stat lines.
4. Save it as `data/extracts/Draft Sharks/2027/rankings-<yyyy-mm-dd>.csv`.
5. Check it has **47 columns** and about 550 rows, and that the header matches the 2026
   one (`sources/draftsharks.yaml` reads by column index, so an added or moved column
   shifts every stat after it; `expect_columns: 47` makes ingest refuse a different
   width). Eyeball one known player's line.
6. **Archive it the same day**: copy it into `~/Archive/fantasy-football-data/2027/extracts/`
   and the Pi copy, and add it to the manifest (see "Collect and archive" for the
   commands). The 2026 board file was never archived until 2026-10-19; that's the gap this
   step closes.

Footballguys is optional: the board doesn't use it (the consensus path was measured and
declined). Archive it anyway if you pull it.

### 5. Ingest check

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli ingest --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2027/<file>" --year 2027
```

Unmatched players are reported loudly. Add any fixes to `identity/aliases.yaml`.

### 6. The curves decision

`calibration/2025.yaml` was built from 2025 CBS game logs. For 2027, decide whether to:

- **keep the 2025 curves** (nothing to do), or
- **rebuild with 2026 added.** That needs the 2026 game logs and CBS points, collected
  before CBS rolls the season over (see "Collect and archive"). `poc/build_calibration.py`
  is hardwired to `data/weekly/2025`, so it needs a change to read 2026, and the adoption
  needs the same pre-registered measurement the 2025 curves went through (NEXT.md, "THE
  FOLLOW-UP RAN"). Only another season adds power here: 2025 is exhausted.

If the curves change, pass the new file to every `--curves`, including
`ops/run_alert.sh` line 84, and refit the market model on the new curves (step 12).

### 7. Price the board before the auction

There's no 2027 price file yet, so apply last year's model of how the room pays. Don't
fit on 2026 prices against 2027 projections: the season guard refuses it, and it's the
mistake that produced the phantom +$13.2 bias.

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli render \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2027/<file>" --year 2027 \
  --market market/2026.yaml --curves calibration/2025.yaml \
  --byes leagues/nfl-byes-2027.yaml --league leagues/sffl/2027.yaml \
  --xlsx output/sffl-2027.xlsx --pdf output/sffl-2027.pdf
```

It prints a `CROSS-SEASON apply` note; that's expected. Swap `render` for `value` and the
two output flags for `--out board.csv` to get the CSV only. Checked 2026-10-19 with the
2026 extract standing in for a 2027 file: it runs and prints that note.

How to read it (NEXT.md, the 2026 holdout result): **MY$ for round-one targets, EST$ for
the $4 to $25 range, MY$ again at $1 to $3.** EST$ is a floor at the very top.

### 8. Silent-auction table

The same flags with `plan` instead of `render` (and without `--xlsx`/`--pdf`) prints the
sealed-bid tradeoff table from `data/league/silent-auction-bids.csv`.

### 9. Print and hand off

- Open the Excel and confirm it really prints on two sheets plus `Key & Intel`. This has
  never been verified by a print (`soffice` isn't installed).
- Re-check the news on the top of the board before printing.
- Copy `output/sffl-2027.xlsx` and `.pdf` to iCloud `Fantasy Football/` for printing and
  for a surrogate, if one drafts.

### 10. Sealed bid

Submit by the league's deadline. NEXT.md's 2026 sealed-bid entries hold the reasoning
(the bid buys pick order; a $0 bump is fine).

### 11. After the auction: league data (tracked in the repo)

- Write `data/league/auction-rosters-2027.csv` with the header
  `franchise,pick_order,player_as_written,price,season`, 156 rows, `season` = 2027.
  **Write each player exactly as the roster sheet shows it**; the raw spellings are what
  drive the aliases. `fit-market` checks the `season` column.
- Append 2027 to `data/league/silent-auction-bids.csv`.
- Add aliases for anything that doesn't join.
- Write `identity/tqb-2027-starters.yaml` with `season: 2027`, mapping each quarterback
  name on the sheet to its franchise, resolved against the 2027 extract (see the 2026
  file's header).

### 12. After the auction: test, then refit

1. **First, score the 2027 prices against `market/2026.yaml`** before any refit. It's the
   one clean out-of-sample test of last year's model.
2. Run the pre-registered RB/FLEX replacement test (NEXT.md, "The RB positional gap"). It
   needs 2026 season results (step 6 and "Collect and archive").
3. Then fit the 2027 model:

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli fit-market \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2027/<the board's file>" --year 2027 \
  --curves calibration/2025.yaml --league leagues/sffl/2027.yaml \
  --prices data/league/auction-rosters-2027.csv \
  --tqb-starters identity/tqb-2027-starters.yaml --out market/2027.yaml
```

Update NEXT.md's machine-checked block in the same commit if the shipped market model or
curves change (`tests/test_docs_match_artifacts.py` checks it).

### 13. Before week 1: in-season switch-over

- Change the week-1 date in `ops/run_alert.sh` line 57 to the Wednesday of 2027's
  week-1 week (2026 used Wednesday 2026-09-09). The week number is computed from it; see
  `docs/operations/in-season-alerting.md`, "The week number".
- Change `--curves` on line 84 if step 6 changed the curves.
- Refresh the CBS login if it has expired: `./.venv/bin/python ops/cbs_login.py`.
- Rehearse with `ops/run_alert.sh tuesday --dry-run`. If CBS changed its pages, the
  `expect_tokens` guards refuse them loudly.
- The launchd jobs and their schedules are Vision's; ask through Jarvis if they need to be
  reloaded.

## Collect and archive, every week in season

Next season's model changes compare projections with what actually happened, so every
week's CBS projections and every week's actual results must be kept, before CBS rolls the
season over and drops them.

**State on 2026-10-19:** this isn't automated yet (board item, P1). The alert jobs save
the current week's CBS pages to `data/captures/`, but each run overwrites the last, and
nothing collects actual results. Weeks before the 2026-10-19 snapshot are not archived.

Until it's automated, after the Tuesday run each week:

```bash
cd ~/Projects/fantasy-football
WK=wk07                                     # the NFL week the pages are for
D=~/Archive/fantasy-football-data/2026/cbs-weekly/$WK
(umask 077 && mkdir -p "$D" && cp -p data/captures/*.txt "$D"/ \
  && cd "$D" && shasum -a 256 *.txt > MANIFEST.sha256)
PI=$(ssh jeff@pinas 'ls -d /srv/dev-disk-by-uuid-*/Documents' | head -1)/fantasy-football-data/2026
ssh jeff@pinas "mkdir -p -m 700 '$PI/cbs-weekly' && test ! -e '$PI/cbs-weekly/$WK'" \
  && scp -p -r "$D" "jeff@pinas:$PI/cbs-weekly/" \
  && ssh jeff@pinas "cd '$PI/cbs-weekly/$WK' && sha256sum -c MANIFEST.sha256"
```

The copy refuses to overwrite a week already on the Pi. Actual results (CBS points and
the game logs, in the format of `data/weekly/2025/`) need their own collection; the
design spec's "Method, proven" section describes how the 2025 set was gathered.

Then add the same week to the private data repo, under `<season>/cbs/weekly/<wk>/`, with
the commands in that repo's README ("Adding a week"). It never overwrites a week either.

## End of season

- Collect the full season's results before CBS rolls over.
- Archive, verify both copies, and add the season to the private data repo
  (`jmill72x/fantasy-football-data`).
- Decide on the curves (step 6) and the RB/FLEX test (step 12) while the data is fresh.
- The alert jobs keep running after week 18 (the week is clamped at 18); ask Vision,
  through Jarvis, to unload them for the off-season if wanted.

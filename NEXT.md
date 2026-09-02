# NEXT — pick up here

Handoff notes for a fresh session. Read this first, then the spec and the relevant plan.

## CURRENT ARTIFACT FACTS — machine-checked, do not hand-drift

<!-- BEGIN MACHINE-CHECKED FACTS -->
<!-- Every line in this block is asserted against the committed artifact by
     tests/test_docs_match_artifacts.py. If you change an artifact, change this
     block in the same commit - the test fails otherwise. If prose elsewhere in
     this file disagrees with this block, THIS BLOCK IS RIGHT and the prose is
     stale: the rest of the file records history and is full of superseded
     numbers left deliberately in place. -->

- market_curve_a: `2.028495994199789`
- market_curve_b: `0.6511171620237226`
- market_mae: `4.4154`
- market_top10_mae: `9.1609`
- market_top10_bias: `4.1025`
- isotonic_stats: `pass_cmp`, `rec_ct`, `rec_yds`, `rush_yds`
- interpolated_stats: `def_pa`, `def_ya`, `pass_yds`
- isotonic_dataset: `127` players / `2339` player-weeks
- interpolated_dataset: `46` players / `777` player-weeks
- weekly_groups: `RB-WR-TE`, `TQB`, `DST`, `K`, `RB-WR-TE-ROS`, `TQB-ROS`, `DST-ROS`, `K-ROS`
- full_suite: `868` passed

<!-- END MACHINE-CHECKED FACTS -->

`top10_bias` is **+4.1025**, positive. It is not −0.25: that number was fabricated, sat in
two docstrings and a test for weeks, and cost this project real time before anyone
measured it. Never quote a diagnostic from memory.

## Where things stand

Auction cheatsheet pipeline for the STRIPES Fantasy Football League (CBS). Four plans;
**all four plans are merged and done.** Valuation is validated against real prices; both
artifacts render. **TODO B is done and answered NO** (see below). What remains is the
08-21→08-23 data refresh, which needs Jeff at the Mac.

**A fifth, later addition beyond the four auction plans: the read-only in-season core**
(`sffl week` — weekly waivers and start/sit). It had three pre-merge fix waves, all on
2026-08-28: a review wave (C1/I1-I5/I8), a verification-pass wave (F1/F3/F4/F5/F8), and a
second C1 wave (the monotone-envelope fix). **MERGED to `main` 2026-08-29 as commit
`09e1b0d` ("Merge in-season core: sffl week --waivers and --start-sit"); the
`in-season-core` branch is gone.** (This paragraph and the status table below both said
"lives on branch `in-season-core` and is still UNMERGED" until 2026-08-30 — that was
already false when written; verify with `git merge-base --is-ancestor 09e1b0d main`.)
See the status table below and "What works today."

**A sixth: in-season automation** — capture, StatsDeck injury extraction, and the
scheduled Friday/Sunday ntfy alerts. **Also MERGED to `main` 2026-08-29, as commit
`93314a1`.** Its runbook is `docs/operations/in-season-alerting.md`.

**A seventh, still later addition: full position coverage (TQB/K/DST) — MERGED to
`main` 2026-08-30 as `26031e8`; the `position-coverage` branch is gone.** (This
paragraph read "lives on branch `position-coverage`, UNMERGED, as of 2026-08-30"
until 2026-08-31, when it was already false — the same drift the in-season-core
paragraph above records. Verify with `git merge-base --is-ancestor 26031e8 main`.) `sffl alert`/`sffl week` now capture
and score all eight lineup slots, not five - see `docs/superpowers/specs/
2026-08-30-full-position-coverage.md` and the plan alongside it.

**DUPLICATE-ENTITY DATA-INTEGRITY FIX — DONE 2026-08-30 — every stated weekly player
count above and below this note was WRONG until today.** Four gitignored weekly-data
files carried the SAME real entity under two different `player_id`s, with byte-identical
week-by-week stats under both: `data/weekly/2025/RB.csv` (TreVeyon Henderson, Kyle
Monangai - two separate pairs), `_held_back/TQB.full.csv` (Eagles), `_held_back/
WR.full.csv` (Jaxon Smith-Njigba), `_held_back/DST.full.csv` (Vikings, ids 1916/1918).
**The corrected real per-file player counts are TQB 31 (not 32), DST 21 (not 22), WR 28
(not 29), RB 34 (not 36), TE 12 (unaffected).** The build-set total is **46 players / 777
player-weeks** (was quoted as 48/811) and the full dataset (build set + held-back) is
**127 players / 2,339 player-weeks** (was quoted as 132/2424) - see `calibration/
2025.provenance.yaml`'s corrected `player_count` fields and `data/weekly/2025/
_held_back/README.md`'s CORRECTION section.
**Why it mattered:** `calibrate_eval.player_folds` splits fit/holdout by `player_id`
specifically so a player's own weeks can never land on both sides of a cross-validation -
but the duplicate ids were genuinely distinct, so the splitter separated them into
different folds while the held-out id's identical twin sat in the fit set, letting
interpolation "predict" it almost exactly. This flattered the BASELINE in the isotonic-
adoption comparison below (leaked measurements favor whichever candidate looks most like
raw interpolation).
**The fix:** `sffl.weekly.load_weekly` now collapses byte-identical-history duplicate
ids at load - the one chokepoint every caller (`poc/build_calibration.py`, `poc/
compare_calibration_methods.py`, `poc/measure_dst_ranking.py`, `calibrate_eval`'s own
tests) already goes through, so this cannot be silently bypassed by a future script. Every
collapse fires a `DuplicateEntityWarning` naming the file/ids/player AND prints to stderr -
never a silent drop. Tested in `tests/test_weekly.py` (collapse fires; two real players who
merely SHARE A NAME with different stat histories are proven to survive uncollapsed).
**`calibration/2025.yaml` is UNCHANGED and NOT to be regenerated as part of this fix** -
`build_curves`/`build_curves_isotonic` merge anchors by rounded mean, so a duplicate
pair's identical rows were already landing on one anchor; every adopted stat's anchor list
was verified byte-identical with and without the duplicates.
**RESOLVED 2026-08-30: `calibration/2025.yaml`'s header comment is NOT stale.** It was
briefly stale (reading "132 distinct players... 48 distinct players..."), and this note
used to say so and to instruct a future reader to leave it alone — but the file was
legitimately regenerated for an unrelated reason a few hours later, by the `pass_yds`
revert (commit `e82d2e2`), and its header now correctly reads **127 distinct players /
2339 player-weeks** (isotonic) and **46 distinct players / 777 player-weeks**
(interpolated). Verified by re-running `poc/build_calibration.py`, which reproduces both
generated files byte-for-byte (`git status` clean afterwards).
**The cross-validated isotonic-adoption comparison was re-run on de-duplicated data**
(`poc/compare_calibration_methods.py`, full dataset, `predict_weekly` - the harness's
default and what `score_week` actually calls): isotonic still beats the baseline
(`build_curves`) for `pass_cmp` (0.1253 vs 0.1333), `rec_ct` (0.0864 vs 0.1205), `rec_yds`
(0.0588 vs 0.0700), and `rush_yds` (0.0718 vs 0.0926). **`pass_yds` FLIPS: isotonic now
LOSES to the baseline (0.1572 vs 0.1520)** - under the leaked data it had appeared to win
(0.1524 vs 0.1659). Under `predict_raw` (the auction-board predictor), all five still
hold post-dedup, `pass_yds` included (0.1420 vs 0.1713). **ACTED ON 2026-08-30 (commit
`e82d2e2`):** `pass_yds`'s isotonic adoption was no longer justified by an honest
cross-validation under the predictor that actually matters for `sffl week`'s weekly path
(`predict_weekly`), so it was **reverted** to `build_curves`/interpolation — the shipped
curve is NOT unaffected by this: `calibration/2025.yaml`, `market/2026.yaml`, and the
adopted-stat list all changed (see the isotonic-adoption checklist item below for the
current numbers). The adopted isotonic bundle is now four stats: `pass_cmp`, `rec_ct`,
`rec_yds`, `rush_yds`. Full report:
`.superpowers/sdd/2026-08-30-full-position-coverage/dedup-report.md` (the original
measurement) and `.superpowers/sdd/2026-08-30-full-position-coverage/pass-yds-revert-
report.md` (the revert).

**TASK 3b (2026-08-30) CLOSED THE CBS ↔ CBS IDENTITY GAP WITH REAL CBS PLAYER IDs -
the composite key below is now only the FALLBACK, not the primary mechanism.**
`sffl.capture.capture` no longer saves `page.inner_text("body")` verbatim: it pairs each
`<tr>` it can with its own `playerpage/<id>` link (`tr a[href*='playerpage/']`) and
prefixes that row's saved text with `id=<id>\t` (see `capture._prefix_ids`/
`_capture_page_text`). `cbs_weekly.parse` and `cbs_roster.parse_lineup_rows` strip and
carry that id onto `PlayerProjection.player_id`/`RosterRow.player_id`; `identity.
resolve_key(player_id, name, team, pos)` is the join every CBS ↔ CBS lookup in
`_merge_projection_groups` and `_cmd_alert` now uses - a real id when BOTH sides have
one, `player_key`'s (name, team, pos) composite as the documented fallback otherwise.
**A genuine surprise verified live 2026-08-30, correcting an assumption in this task's own
brief: TQB and DST rows get an id too, not just individual players** - CBS gives each
team's TQB unit and DST unit its own synthetic `playerpage/<id>` (Chargers' TQB unit is
`1974`, its DST unit a DIFFERENT `1924` - never a shared team id that would re-collide the
two). On a real live capture, 100/100 RB-WR-TE rows, 98/98 K, 32/32 TQB, and 32/32 DST all
carried one; only page furniture and pre-existing hand-saved fixtures fall back to the
composite. The Chargers TQB+DST case was re-verified live end to end: both slots resolve
independently via id, no residual collision, no degradation.

**THE MERGE/LOOKUP IDENTITY KEY IS STILL A HEURISTIC WHEREVER AN ID IS ABSENT** - record
this so it is not re-discovered the hard way. Merging TQB/K/DST meant a projection row and
a roster row can legitimately share a display name (CBS's TQB and DST pages both use the
NFL TEAM NICKNAME as a row's "player name"), and separately, two different real NFL
players can share a name at the same position on different teams (two players both named
Mike Williams, both WRs, in the same season, is real). `player_key`'s (name, team, pos)
triple resolves both of those without an id, but **is still NOT provably unique** for two
same-named players at the same position on the SAME team (a churn artifact, a data error) -
`resolve_key`'s id-first preference actually closes that residual case wherever both rows
carry an id (two different ids can never collide), but a row with NO id still falls all the
way back to the composite. `_merge_projection_groups` and `_cmd_alert` detect a residual
collision on this key (an id shared by two rows counts too) and report it loudly (a
WARNING, the pushed alert body, and a non-zero exit) rather than silently keeping one row
and dropping the other.

**THE REMAINING HEURISTIC IS CBS ↔ STATSDECK INJURY MATCHING, NOT CBS ↔ CBS.**
StatsDeck's injury feed uses nflverse ids (`00-0036900` for Ja'Marr Chase) - a different
namespace CBS's `playerpage/<id>` has no relationship to - so `sffl.injuries.for_roster`
stays name-based (`identity.normalize_name`), by design; see that module's own docstring
for why this is judged an acceptable, narrower residual (wrong news beside a player, never
a silently dropped lineup slot). Unifying that would need a cross-source id mapping (e.g.
via nflverse's own CBS-id crosswalk, if one exists) - not attempted here, and not cheap:
correctly out of scope, same reasoning as Task 3b's own brief.

**Jeff is not attending the auction.** A surrogate drafts for him on 08-26. **Jeff owns the
BID; the surrogate owns the SELECTION.** The Excel + `Key & Intel` sheet is the deliverable;
the PDF/iPad path is no longer the primary artifact and no annotation app needs buying.

| | Status |
|---|---|
| **Plan 1 — scoring foundation & ingest** | ✅ merged, 64 tests |
| **Plan 2 — value engine (VORP → dollars)** | ✅ merged, plus valuation corrections, lineup floors and market calibration — 165 tests |
| **Plan 3 — Excel + PDF renderers** | ✅ merged — 203 tests. `sffl render` writes both |
| **Plan 4 — silent auction planner** | ✅ merged — 279 tests. `sffl plan`; the table is on PDF p17 |
| **In-season core — weekly waivers & start/sit (read-only)** | ✅ **merged 2026-08-29 (`09e1b0d`)** — 409 tests at merge, three pre-merge fix waves. `sffl week --waivers` / `--start-sit`. **Deferred:** the write path (waiver submit, lineup set), `--trade`, the state file, and — not previously recorded — `(add, drop)` pairing: `--waivers` ranks additions only and does not yet choose which rostered player to drop. **ALL OF THIS IS NOW DONE — see the row below** |
| **Write path + trades** | ✅ **DONE 2026-09-01/02.** `sffl trade` (rest-of-season valuation, targets by owner, give/get evaluation, drafted proposals — never contacts a manager); `sffl lineup` (live-verified round trip on the real team, atomic commit); `sffl claim` (waiver add+drop, dry-run verified). All three: DRY RUN by default, `--confirm` to act, and `--confirm` REFUSED when stdin is not a TTY so a scheduled job can never submit. The Friday digest carries the top 3 trade targets. **`(add, drop)` pairing done 2026-08-31.** THE ONE UNPROVEN PATH: `sffl claim` has never pressed Submit — every layer beneath it is verified, but the final POST is unexercised because it ends in a real drop and Jeff declined to spend one. Add/drop IS open (CBS: "5 waiver offers remaining", "processed on 9/16") |
| **In-season automation — capture, injury fetch, scheduled alerts** | ✅ **merged 2026-08-29 (`93314a1`)** — `sffl alert`, `ops/run_alert.sh`, two launchd LaunchAgents. Runbook: `docs/operations/in-season-alerting.md`. (ntfy/launchd delivery was listed as "deferred" on the row above until 2026-08-30; it is not — it shipped here) |
| **Full position coverage — TQB/K/DST** | ✅ MERGED (`26031e8`) — 868 tests. All eight lineup slots captured and scored |

Verify state in one command:

```bash
cd ~/Projects/fantasy-football && ./.venv/bin/pytest -q && git log --oneline -3
```

**What works today — this is the production command.** It reads an extract, scores it
against league rules, values the pool, fits both the replacement policy and the market
price curve against 154 real 2025 prices, and writes a priced board:

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli value \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026 \
  --policy fit --prices data/league/auction-rosters-2025.csv \
  --curves calibration/2025.yaml --out board.csv
```

543 players, TQB=32. Every row carries **MY$** (worth against replacement) and **EST$**
(what the room will pay). Swap `value` for `render` and add `--pdf`/`--xlsx` to write the
artifacts — that is the command to run on 08-21.

**What works today, in-season (read-only).** `sffl week` ranks waiver targets and flags
start/sit changes from a saved CBS weekly-projections page — this module does no network
I/O, so the page is fetched by a browser tool and saved first, same discipline as every
other extract in this project:

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli week \
  --projections tests/fixtures/cbs_weekly_rbwrte.txt --group RB-WR-TE --week 1 \
  --roster roster.txt --curves calibration/2025.yaml --waivers
```

`--roster` (and, for `--start-sit`, `--current`) is a text file of one player name per
line, saved the same way. The `--projections` path above is the tracked test fixture —
8 real CBS rows, captured 2026-08-28 — since no full saved page is committed yet; a real
week points this at a saved page under `data/weekly/` (gitignored). Swap `--waivers` for
`--start-sit --current current.txt` to check whether the lineup currently set on CBS is
already optimal.
**CORRECTED 2026-08-30 — this paragraph used to say "only the `RB-WR-TE` group is defined
in `sources/cbs-weekly.yaml` so far — TQB/K/DST would each need their own entry there."
That is done.** `sources/cbs-weekly.yaml` now defines **eight** groups — the four weekly
ones `RB-WR-TE`, `TQB`, `DST`, `K`, plus a REST-OF-SEASON twin of each
(`*-ROS`, added 2026-09-01 for `sffl trade`). The ROS pages carry one extra
column (FPTS/G before FPTS) and `parse` slices the stat block off the RIGHT,
so reusing a weekly map reads every field one place out — the weekly
`expect_tokens` caught exactly that on the first real run. Original text
follows: `RB-WR-TE`, `TQB`,
`DST`, `K` — each with its own measured column map and its own `expect_tokens`
(17/17/16/21 respectively). `sffl week` takes `--projections-tqb`, `--projections-k` and
`--projections-dst` alongside `--projections`, and `sffl alert` builds all four page URLs
from `--week`. The `expect_tokens` warning still stands for any group added in future: it
is opt-in (`groups[group].get("expect_tokens")` in `cbs_weekly.py`), not required by the
schema, so a group added without it silently loses the whole-width layout guard — the
exact Critical already fixed once, where a shifted column made a 0.9-reception back read
as 7.9. **Ranks adds only:**
it does not yet choose which rostered player to drop to make room, so the spec's
`(add, drop)` pairing is half-built (see the plan's Self-Review).

## GOAL — the dry run is DONE. What is left is the refresh.

The dry run's purpose was to make the week of 08-23 a pure data swap with no code changes
and no surprises. **That is achieved**: both artifacts generate end to end from archived
extracts, at the best fit measured (mae $5.66, top10_mae $11.22).

Done now means: Jeff re-pulls both extracts Fri 08-21 → Sun 08-23, re-runs one command,
prints the Excel, and sends it to the surrogate with his sealed bid decided.

### Current position

Update this block at the end of every session so the next one can resume blind.

- [x] Plan 1 — scoring foundation & ingest (merged, 64 tests)
- [x] TODO A — execute plan 2, the value engine (all 8 tasks)
- [x] Valuation corrections — K/DST flat at $1, TQB + DST markets joined to the fit
- [x] Lineup floors — 1 RB and 1 WR/TE enforced at flex replacement
- [x] Market calibration — EST$ (what the room pays) beside MY$ (what he's worth), 165 tests
- [x] **Plan 3 — renderers MERGED** (203 tests). PDF 17 pages, Excel 2 pages
- [x] **Full dry run — DONE.** Both artifacts generate end to end from archived extracts.
      The 08-21 refresh is now a pure data swap with no code changes, which was the point.
- [x] Plan 4 — silent auction planner MERGED. 5 years of real bids on the management page
- [x] **Excel format fixes — Jeff's review 2026-08-05, all three FIXED 2026-08-06.**
      Every one was found by opening the generated file, not by a test; all three are now
      asserted so they cannot regress.
      1. **Cell borders and fills were missing entirely.** The spec had recorded "gridlines
         off" from `showGridLines: False` — that is the SCREEN setting, true of the template
         too. The template switches Excel's gridlines off and draws **explicit cell
         borders**, which is what makes it read as a ruled table. **Keep this trap in mind
         for any future template work: `showGridLines` tells you nothing about how a sheet
         looks printed.** Now draws 2,388 thin-bordered cells.
      2. Section boundaries now align to the page break after row 63.
      3. Positions no longer interleave across the break, and blocks fill **left to right**
         — WR1 was landing to the right of WR29.
      Widths, fonts and the three column groups are unchanged.
- [x] **K and DST depth raised** — the list had been trimmed to 12 each.
- [~] **iPad/PDF annotation — DROPPED, do not spend money here.** Jeff has work travel the
      night of the auction and is not attending, so nothing gets marked up on an iPad. The
      PDF still generates and is still useful as a printed reference for the surrogate; only
      the annotation-app purchase is off. Research is kept in git history if it ever returns
      (conclusion was iAnnotate 4 at $9.99 one-time, chosen because it navigates the PDF's
      own embedded outline — GoodNotes loses imported outlines, PDF Expert is $79.99/yr, and
      Notability has an undisclosed free-tier edit cap).
- [x] **TODO B — DONE 2026-08-18, and the answer is NO.** Scraped 1,428 more weekly rows
      (84 players: WR/TE/DST/TQB) via Chrome, hitting the ~120-player target. **The wider
      curves measured WORSE and are not shipped.** Full reasoning below under *TODO B —
      ANSWERED*. Shipping 48 players / 811 player-weeks (18 seed + 30 stratified RB) -
      **corrected 2026-08-30 to 46/777**, RB.csv carried a duplicate-entity pair; see
      the dedup note near the top of this file.
- [x] **DATA REFRESH — DONE 2026-08-23.** Fresh Draft Sharks extract pulled and installed
      at `data/extracts/Draft Sharks/2026/rankings-2026-08-23.csv` (552 players, page stamped
      Aug 23 7:15pm). Both artifacts regenerated. 324 tests pass.
      **THE EXPORT PATH, since it took a while to find again:**
      draftsharks.com -> **RANKINGS -> Redraft** (`/rankings`) -> the **Projections** tab
      (beside Rankings/Analysis) -> export icon at the far right of the NON-PPR row.
      Downloads as `rankings.csv`. **47 columns, ~550 rows** - that is the shape to check.
      **DO NOT use RANKINGS -> Auction (`/auction-values`).** Its export is only 13 columns
      and 250 rows: vendor totals and vendor auction values, NO per-stat lines, so the
      scoring engine has nothing to score. It also prices Nacua at $103 against a $110
      per-team budget - the ~$200-cap THEIR$ problem, present even with the league synced.
      **The real integrity check is the 47-column header, not the AUCTION/Snake setting.**
      The profile reads `by_index: true`, so a renamed column is harmless but an added,
      removed or reordered one silently shifts every stat after it. The 08-23 header was
      verified byte-identical to the 08-03 one before any number was trusted.
      Fit on fresh data: mae $5.68, top10_mae $11.41 (was $5.66 / $11.22) - unchanged in
      substance. 153 of 156 prices join. 17 unrostered dropped.
      **What moved:** top three unchanged (Nacua, Chase, St. Brown). Rashee Rice -$7.3
      (#8 -> #13) is the largest move on the board; Kenneth Walker III +$5.5 (#45 -> #33);
      Josh Jacobs -$3.9; CIN TQB -$3.7; Gibbs +$2.7 to #4.
      **Draft Sharks has NOT downgraded Nacua** - still #1, so the injury/suspension news
      is not in their projection. The Nacua-Chase gap TIGHTENED to $1.05 (was $1.30).
      **Footballguys was NOT re-pulled** - it feeds only the declined consensus path, so it
      does not affect the board. Not a gap.
- [x] **SEALED BID — SETTLED 2026-08-24: $42, BUMP $0.** Submitted deadline was Mon 08-24.
      **$42 is the cleanest number on the board.** Buys rank 1-2 in all 5 years on record,
      20% TIE1+, **0% TIE2+**. It strictly dominates $43 and $44 (identical rank range and
      tie profile, $2 cheaper). $41 drops to rank 1-3 with 40%/20% tie exposure; $39 is
      80%/20% and went live in '23. $45 buys rank 1 outright but pays $3 for the Nacua-Chase
      difference, which is $1.10.
      **Why NOT the bottom-4 zone Jeff first leaned toward.** The flexibility worry does not
      survive the league's own data: the four franchises that spent MOST on their top player
      in 2025 paid $43/$41/$40/$39 and filled their remaining 12 spots with **$67-71**. A $42
      bid leaves $68 - the normal shape of an aggressive roster here, not a squeeze. Median
      price paid across all 156 spots was **$3**; 49% went at $1-2.
      Also: the top of the board is genuinely scarce ($56.5/$55.4/$48.2/$47.4, then a step to
      $42.3 and a long flat run), and **a rank 1-2 pick makes the surrogate's job trivial** -
      take the best name, and the top two are $1.05 apart so he cannot really get it wrong.
      At rank 10-11 he would face the hardest choice on the board on live news Jeff cannot
      brief him on. Bidding high REMOVES the decision Jeff is least able to help with.
- [x] **BUMP $0 — Jeff was right, and the first recommendation here ($3) was WRONG.**
      Recorded because the reasoning generalises and the raw tie history is misleading.
      A $0 bump has never won a tie (0-for-7), which looks damning until you price the
      outcomes. **Losing a tie is nearly free: the loser pays only their original bid and
      still takes the next rank.** And a bump tie escalating to a live auction is NOT
      unbounded - every live resolution on record settled at a small increment with the
      loser paying +$0:
        2025 $33  both bumped 1 -> winner $34 (+1), loser $33 (+0), kept rank 8
        2023 $39  four-way      -> $42/$41/$40/$39, an orderly +3/+2/+1/+0 ladder by rank
        2021 $35  both bumped 4 -> winner $39 (+4), loser $35 (+0)
      So from $42/$0 the branches are: take #2 at $42, or take #1 at $43. Bumping $3 blind
      costs $45 for that same #1. **The sealed bump is a BLIND commitment; the live auction
      is an OPEN one where you keep control** - paying a premium to avoid the branch where
      you have MORE information is backwards. With the prize only $1.10, nothing is worth
      insuring.
      **If it goes live, it is the SURROGATE'S call, unconstrained — ruled by Jeff
      2026-08-24.** A scripted dollar limit was drafted here and Jeff declined it: the
      tiebreak is a real-time read in a room he will not be in, and the whole cap
      difference between winning and losing it is $1-2. Do not re-add a limit.
      Noted once for the record: a live tiebreak spends CAP, so by the "Jeff owns the BID,
      the surrogate owns the SELECTION" split it technically sits on Jeff's side of the
      line. At $1-2 that is a distinction without a difference, and over-constraining an
      experienced leaguemate costs more than it saves.
- [x] **Room intel — CLOSED 2026-08-18, nothing to add and nothing missing.** Jeff has no
      owner-by-owner tells worth writing down, and **the surrogate has played in this league
      before, so he already knows these owners.** Do not re-open this or prompt him for it.
      It costs the sheet nothing: `Key & Intel`'s room section is titled *"WHAT THIS ROOM
      DOES — FROM ITS OWN PRICES"* and is derived entirely from the tracked price and bid
      history (K/DST at $1, top-end compression, the record bid, the ~third of all capital
      spent in round one). No item on that page was ever sourced from owner gossip.
      **This is the right division of labour** — the surrogate brings the people-read; the
      sheet brings what he cannot have: Jeff's valuations, the MY$/EST$ gap, where the model
      is weak, and the Snapshot caveat that the board predates auction night.
- [~] **Nacua — RULED 2026-08-18: leave him where he is** until there is a real update on
      the injury or the suspension. Jeff's call, and it is cheap to be wrong about:
      **Nacua $55.9 and Chase $54.6 are $1.30 apart**, ~2%, well inside the model's own
      error. If Nacua drops out entirely, Chase slides up and the top of the board barely
      changes shape. **The bid buys pick ORDER, not a specific player**, so the Nacua risk
      does not move the bid.
      The exposure is the SELECTION, and it is a calendar problem: the board freezes
      Sun 08-23, Jeff travels 08-25, the auction is 08-26 — so news can break in a window
      where nobody can regenerate anything. Handled in the sheet, not by picking for the
      surrogate: `Key & Intel` now carries a **Snapshot** item stating the board predates
      the night and measuring how tight the top is. Still worth re-checking the news on
      08-23 before printing.
- [x] **Licensed values cleaned out of the tracked fixtures — DONE 2026-08-18.** Also out of
      the copy quoted in the plan doc. Names kept deliberately; see FOLLOW-UP below. One
      related question is left open there: the CBS golden file in `tests/test_scoring.py`.
- [ ] **Add a lost-fumble term to `leagues/sffl/2026.yaml`** — found 2026-08-18, see below.
      Deferred past the auction deliberately, now with a MEASURED size (2026-08-19):
      Footballguys projects ~3.2 lost fumbles for a lead RB (Bijan 3.9, Gibbs 2.9, Cook 3.2)
      against 0.7-1.3 for a WR (Nacua 1.2, Chase 1.3). At the observed ~-1/fumble that is
      about **-$2.4 on a top RB and -$1.0 on a top WR**, so the missing term quietly favours
      **RBs over receivers by ~$1.50**. Systematic, but too small to reorder the top.
      **BLOCKER when it is picked up: Draft Sharks — the production source — does not publish
      offensive fumbles at all** (only defensive `Fum Rec`/`Forced Fumble`). Footballguys has
      `fum-lost`. So adding the term needs an FBG join, not just a YAML line.
- [x] **Isotonic calibration curves ADOPTED for 4 stats — DONE 2026-08-30 (revised).** The
      fitted/regularised-curve follow-up TODO B called for actually ran. It cleared its
      gate for FIVE stats on 2026-08-30 — and later the same day one of the five,
      `pass_yds`, was withdrawn, leaving FOUR. Read the sequence, not either number
      alone: **five adopted, then four from commit `e82d2e2` onward; four is what
      ships.** Measured on the full dataset (build set + held-back, 132/2424 -
      **corrected 2026-08-30 to 127/2339**, four files carried duplicate entities;
      see the dedup note near the top of this file). `pass_yds`'s cross-validated win
      over the baseline did NOT survive de-duplication under the weekly predictor
      (`predict_weekly`: 0.1572 vs baseline 0.1520, a loss) and was **reverted**
      (commit `e82d2e2`) - the shipped curve is back to interpolated, byte-identical to
      the pre-adoption version. **The adopted set is four stats: `pass_cmp`, `rec_ct`,
      `rec_yds`, `rush_yds`.** Re-measured with `pass_yds` removed: `top10_cost` 15.1681 →
      13.2633, `mae` 4.3392 → 4.4154, `top10_bias` stays positive at +4.1025.
      `def_pa`/`def_ya` deliberately NOT adopted (DST is flat-priced, structurally
      inert on the board). `market/2026.yaml` refit accordingly: `a=2.028495994199789,
      b=0.6511171620237226, mae=4.4154, top10_bias=4.1025`.
      **Resolved:** whether `def_pa`/`def_ya` should move to isotonic for the weekly
      (`sffl week`) path WAS measured (commit `9b2fcdc`, pre-registered gate,
      `docs/superpowers/specs/2026-08-30-def-curve-weekly-gate.md`) - **underpowered at
      n=21, keep the baseline.** No combination of `build_curves_isotonic`/
      `build_curves_pooled` cleared the pre-registered +0.15 Spearman margin on both
      k=5 and leave-one-out; this is underpowered evidence, not a claim the candidates
      are worse. Pooled residual estimation is eliminated, do not revisit. See the full
      section further down and
      `.superpowers/sdd/2026-08-30-regularised-calibration-curves/`.
      **RE-RUN 2026-08-31 AT n=32 - THE FULL LEAGUE. Same verdict, and 2025 is now
      exhausted.** The missing 11 defenses were reconstructed
      (`data/weekly/2025/_reconstructed/DST.boxscore32.csv`) and the identical
      pre-registered gate re-run against all 32, threshold untouched at 0.15:
      nothing cleared. The largest margin any candidate achieved on any fold count
      was **+0.0048**, roughly an order of magnitude short of the bar and well inside
      the noise floor - so this is NOT a near miss that more data would resolve in the
      candidates' favour. Do not spend another session collecting 2025 DST data; n=32
      is every defense in the league. Only another SEASON adds power here.

Work top to bottom. Each unchecked box is the next thing to do.

### Renderers — MERGED 2026-08-04

`sffl render` writes both artifacts. Production command is in "What works today" above,
plus `--pdf output/x.pdf --xlsx output/x.xlsx`.

**PDF — 17 pages**, the iPad layout ported verbatim from `poc/render_poc.py`. Row is
`# | PLAYER | TM/BYE | MY$ | EST$ | PAID`. Six bookmarks. Footer carries the EST$-is-a-floor
caveat.

**Excel — 3 printed pages in 2 SHEETS.** `Board` is the board (2 pages, 126 rows, unchanged);
`Key & Intel` is a third page in the same workbook — what the columns mean, what this room
pays, where the model is weak, and how round one works, for the **surrogate drafting on
2026-08-26 while Jeff travels**. Jeff owns the BID; the surrogate owns the SELECTION, and the
sheet is intel for a peer, not an instruction list. Every figure on it is derived from the run
that printed the board (`src/sffl/render/intel.py`); a figure the run cannot produce prints as
"not measured", never as a stale constant. Its one-page fit is arithmetic on the same geometry
as the board's (41 of 45 rows used on the production extract) and `render_xlsx` raises rather
than spilling onto a fourth page.
**CORRECTED 2026-08-30 — the sentence that stood here was wrong twice over.** It said
"only three numbers are hardcoded — the 48 players/811 player-weeks behind the calibration
curves ... and the direction of the TQB residuals (BAL/WAS/PHI under, DAL/CIN/MIN over)."
Neither half holds. The TQB-residual direction constants (`TQB_UNDERPRICED`/
`TQB_OVERPRICED`) were **REMOVED on 2026-08-27** — `intel.py` carries a comment explaining
that the pattern was real but the causal story invented, and `_tqb_dispersion` now derives
it. And the calibration counts are **four** constants, not one pair, since the isotonic
adoption split them into two regimes: `CALIBRATION_PLAYERS_ISOTONIC = 127` /
`CALIBRATION_PLAYER_WEEKS_ISOTONIC = 2339` and `CALIBRATION_PLAYERS_INTERPOLATED = 46` /
`CALIBRATION_PLAYER_WEEKS_INTERPOLATED = 777`. Those four are the only hardcoded numbers
on the page, they match `calibration/2025.yaml`'s header comment (which is current, not
stale), and `tests/test_render_intel.py::test_the_calibration_provenance_matches_the_curve_file`
fails if they drift from it.

**Excel — 2 pages**, the 2022 template's shape. **126 rows is the budget**: 63 rows/page at
the template's 9.95pt row height, landscape letter, 97% scale. Jeff's 2022 file is 118 rows —
it was ALWAYS a curated cheat sheet, never the full pool. 520 players need ~174 rows even
packed perfectly, so no column-width change can fit them; it is a row-count problem.

Per-section on the 2026 data: Overall 124/453, TQB 32/32, RB 77/122, Receivers 103/299,
K 12/35, DST 12/32. **23 of 543 players dropped** as unrostered (`UNS` ×22 unsigned free
agents, `RK` ×1) — no NFL team means no bye; all below replacement so no dollar value moves.
The count is printed, never silent.

**Two things needing Jeff's eyes, not more code:**
1. **Is 124 rows the right depth for the overall board?** The cross-position "who's next best
   regardless of position" view stops ~32 short of the 156 drafted. That view is what matters
   for late-auction bid timing. Only visible on a printed page.
2. **Does it actually print on two sheets?** `soffice` is not installed, so 126 rows = 2 pages
   is arithmetic, not verification.

The workbook took three fix rounds, every defect caught by opening the generated file rather
than by a passing test. All three are now asserted: no position missing, no column short of
budget, no interior gaps. A committed capacity-boundary sweep pins it.

**Carry into plan 3 — the caveats that must survive onto the printed page:**
EST$ is a *floor* at the very top, not a point estimate. Spread is unmeasured, so render
it blank and never `$0`. Both are explained below; the person bidding reads the board,
not the source.

## Timeline — hard deadline

| Date | What |
|---|---|
| 2026-08-03 | Plan 1 merged. Extracts archived to iCloud as insurance. |
| 2026-08-04 | Plan 2 merged. K/DST at $1, 154 of 156 prices joining, lineup floors, MY$/EST$ two-column board. |
| 2026-08-06 | Plans 3 and 4 merged. Excel format fixes from Jeff's review. |
| 2026-08-18 | ✅ **Full dry run complete.** TODO B answered NO — wider curves measured worse. Board at mae $5.66 / top10 $11.22. |
| **Fri 2026-08-21 → Sun 2026-08-23** | **THE REFRESH — needs Jeff at the Mac.** Re-pull fresh extracts from Draft Sharks and Footballguys. Confirm Draft Sharks still reads **AUCTION**, not Snake — every sync imports as Snake and a reverted setting yields a plausible file with a worthless value column. Re-run `sffl render`, print the Excel. |
| **Sun 2026-08-23** | **Board must be baked and printed.** Re-check the Nacua news before printing. |
| **Mon 2026-08-24** | **Jeff's sealed bid due.** The last deliverable he owes. |
| 2026-08-25 | Jeff travels, early. Nothing can be regenerated from here. |
| **2026-08-26** | **AUCTION.** Jeff is absent; the surrogate drafts from the printed Excel + `Key & Intel`. Jeff's sealed bid must be submitted by him beforehand. |

Nothing in the pipeline blocks the refresh — it is a data swap by design. The remaining
risk is entirely on the 08-21 re-pull, and specifically on the AUCTION/Snake setting.

## Facts a fresh session must NOT re-derive

- **The scoring engine is validated and must not be modified.** 44 of 45 bands proven
  against ~250 real CBS weekly observations. Details in the spec.
- **Never mix seasons.** 2024 CBS points use different scoring rules. Only 2025 may
  calibrate 2026.
- **Touchdowns are not symmetric across positions.** Goal-line rushing scores 3 where a
  short receiving TD scores 5; 36-74 yard rushing scores 8 where receiving scores 6.
- **WR and TE are ONE position.** Never split them for valuation.
- **The repo is public.** `data/extracts/` and `data/weekly/` are gitignored because they
  hold licensed vendor and CBS data. Never commit from either.
- **Python 3.9.6 only.** No `match`, no `int | None`. Use the venv at `.venv/`.
- **A zero is not a no-op for `def_pa` and `def_ya`.** Both band the value `0` at their
  MAXIMUM (6 points). Any code that loops over `lg.bands` for every player pays a phantom
  shutout to every receiver and kicker. `score_game` gates its defense block on
  `pos == "DST"` for exactly this reason, and the same trap was caught twice more during
  plan 2 — once in `build_curves`, once in `score_season_calibrated`. Both are now gated
  by `calibrate.STAT_POSITIONS`. Do not "simplify" those gates away.
- **`band_points` floors, `expected_points` clamps.** Below the first band, `band_points`
  returns 0; `expected_points` returns the curve's lowest anchor. Swapping one for the
  other without a position gate paid every non-passer 72 phantom season points. Producer
  and consumer must agree on `STAT_POSITIONS`.
- **Replacement level is `starter`, fitted, not chosen.** See the table above.

## TODO A — DONE. Plan 2 results (2026-08-04)

*(TODO B below is a data-collection chore that produces no code. The numbered plans are
the implementation roadmap above.)*

The value engine is built and works on real data. What you can run today:

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli value \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2026/rankings (1).csv" --year 2026 \
  --policy fit --prices data/league/auction-rosters-2025.csv \
  --curves calibration/2025.yaml --out board.csv
```

**The replacement-level open question is now answered empirically — and on a much wider
base of evidence than the first pass gave it.** Fitted against **154 of 156** real 2025
prices (production path, i.e. run WITH `--curves` as above):

| policy | mae | rmse | top10_mae |
|---|---|---|---|
| **starter** (chosen) | $5.73 | $9.46 | **$11.24** |
| draftable | $5.44 | $8.12 | $16.32 |

Per pool, starter policy:

| pool | n | mae |
|---|---|---|
| DST | 12 | $0.58 (flat $1 — see below) |
| K | 12 | $0.25 (flat $1 — see below) |
| FLEX | 109 | $6.28 |
| TQB | 21 | $8.98 |

**154 of 156 joins, up from 108 — and the 108 was never a whole-board number.** The roster
sheet writes defenses as `PHILLY D` and Team QB units by their 2025 starting quarterback's
name, so before this branch neither the DST nor the TQB market matched anything in the
pool at all. The old $11.68 top10_mae was computed on RB/WR/TE/K only; nothing said so at
the time. The only two prices that still don't join — Joe Mixon and Ricky Pearsall — are
genuinely absent from the 2026 Draft Sharks extract, not a resolution failure.

`draftable` wins slightly on overall error but is far worse at the top of the board, and
the top is where a mispriced board costs real money — so `choose_policy` tiebreaks on
`top10_mae` and picks **starter**. Do not re-litigate this without new price data.

Replacement levels under starter: DST 63.9, FLEX 63.8, K 141.1, TQB 239.9 pts, at
**$0.7273 per VORP point** (up from $0.6465 — flat-pricing K/DST returns their VORP share
to the pools people actually bid on).

New modules: `weekly.py`, `calibrate.py`, `consensus.py`, `value.py`, `fit.py`, plus
`score_season_calibrated` in `pool.py` and the `value` CLI command.
`calibration/2025.yaml` is committed derived data (aggregate curve points only, no
player data) generated by `poc/build_calibration.py`.

### Things plan 3 must know

- **TWO numbers render, not one.** `_dollars` (MY$) is worth against replacement;
  `_est_price` (EST$) is what the room will pay. Both go on the board — the gap between
  them is the edge. Also on each record: `_season_points`, `_vorp`. `_est_price` is
  absent when the run had no `--prices`, so plan 3 must render it blank, never $0.
- **`_spread_<stat>` and `_n_sources` are NOT populated yet.** Only `consensus.merge`
  writes them and nothing calls it — see the wiring gap below. The CLI now writes an
  **empty string**, not `0.0`, for those columns so a zero can never be mistaken for a
  measurement. Plan 3 must handle empty.
- **Kickers and defenses are now priced flat at $1, closing the earlier open question.**
  21 real 2025 prices back this: K n=9 ranged $1–$3 (seven of nine at exactly $1); DST
  n=12 ranged $1–$3. Their projected point spreads are real but not actionable, and the
  league already prices them as fungible $1 fillers, so the model now matches the market
  instead of paying one of them ~$20. Configured via `flat_priced_pools` in
  `leagues/sffl/2026.yaml`; validated at load time in `src/sffl/league.py`. No K or DST
  appears in the top 25 by dollar value anymore. On today's archived extract the top 25
  is 6 RB, 3 TE, 3 TQB, 13 WR — re-measure against whatever extract is live when this is
  read, since the position mix will shift as projections refresh.
- **Flat-pricing K/DST also silences the documented DST sack-zeroing limitation**
  (`src/sffl/pool.py:23-35` — season-averaging zeroes every defense's sack points) **for
  pricing purposes.** DST dollars no longer depend on DST points at all, which is fine for
  the auction but means the per-pool fit table can never again surface that failure. If
  the DST model itself is ever revisited, don't look to the fit table for evidence either
  way.

### Known gaps carried forward

1. **`consensus.py` is written, tested, and wired to nothing.** The `value` command reads
   one extract. Merging Draft Sharks + Footballguys into a consensus with the spread
   preserved is the single biggest remaining edge and is not yet reachable from the CLI.
2. **The calibration curves rest on 48 players** (811 player-weeks) - **corrected
   2026-08-30 to 46 players / 777 player-weeks for the three interpolated stats
   (`def_pa`, `def_ya`, `pass_yds`); the four isotonic stats rest on the full
   127 players / 2339 player-weeks. See the dedup note near the top of this file.
   `calibration/2025.yaml`'s own header comment is CURRENT and records both regimes.**
   **This is settled —
   widening it was tried and measured worse; see TODO B — ANSWERED.** `expected_points`
   still clamps silently outside the observed range. The remaining improvement is a
   *fitted* curve, not more points.
3. Sacks are still uncorrected (see Open questions).

### Plan 3 — decisions Jeff settled on 2026-08-04

1. **Columns.** Derive `Tier` and `AVG PTS` from data already modelled. `AVG PTS` is
   `_season_points / games`. `Tier` comes from natural breaks in `_dollars` within each
   position group — the gaps between clusters are the useful thing at the table ("if I
   miss him, the next one is $8 cheaper"). The 2022 sheet ran tiers 1-6; match that depth
   unless the breaks say otherwise.
2. **Bye weeks — SOLVED.** Neither vendor has them: verified against the Draft Sharks
   header and all 61 Footballguys columns. Now in `leagues/nfl-byes-2026.yaml`, keyed by
   canonical team code, two independent sources agreeing on all 32. **Jeff should
   spot-check it before the auction** — it is the only file here sourced from outside the
   pipeline. Note the file quotes its keys deliberately: unquoted `NO` parses as boolean
   false under YAML 1.1 and silently dropped New Orleans on the first pass.
3. **THEIR$ — DROP IT.** Decided. It was FantasyPros' `VALUES` column, read at
   `poc/render_poc.py:123` from `~/Library/Mobile Documents/com~apple~CloudDocs/Fantasy
   Football/cheatsheet (3).csv`, rendered at `:207`/`:237`, and populated for K/DST only
   (Draft Sharks rows set `"their": None` at `:75` because that vendor's auction column is
   broken). Jeff's reason for dropping it is the important part and generalises: **those
   numbers are not customised to this league** — they assume a ~$200 cap, so FantasyPros
   prices Ja'Marr Chase at $62 when $43 is the highest price this league has ever paid.
   An uncalibrated vendor number is not defendable at the table. Do not reintroduce it
   from another vendor without calibrating to this league's capital first.
4. **RB / WR-TE floors — DONE**, merged. Both are hard lineup requirements and are now
   enforced in `replacement_levels`. **No dollar values changed:** the natural top 60 flex
   is 19 RB and 41 WR/TE against floors of 12 and 12, so the floors do not bind on this
   extract. It is a guard for a future one.

   Worth recording so nobody re-derives it: forcing a floor can only **raise** the flex
   replacement level, never lower it. A floored-in player displaces a higher-ranked one,
   so the best *excluded* player improves. An early draft of the brief asserted the
   opposite and was provably wrong.

### RESOLVED — MY$ / EST$, the two-column board (2026-08-04)

Jeff chose option C below. `_dollars` (MY$) keeps its meaning: worth against
replacement. `_est_price` (EST$) is what the room will actually charge, fitted from
this league's own prices in `src/sffl/market.py`, and it occupies the column THEIR$
vacated. **The gap between the two columns is the edge.**

Fitted curve: `price = 2.248 * value^0.551`, from **130** observations — K and DST are
excluded from the fit because their `_dollars` is $1 by policy, not by model, so they
were 24 points at `x = log(1) = 0` anchoring the intercept. Excluding them measured
better or equal in **all six** bands.

| model band | MY$ bias | EST$ bias |
|---|---|---|
| $30+ | +$13.2 | **+$0.2** |
| $20-30 | +$7.4 | +$4.3 |
| $10-20 | +$0.5 | +$1.1 |
| $5-10 | -$4.2 | -$1.6 |
| $2-5 | -$4.3 | -$1.2 |
| $1-2 | -$2.6 | -$1.1 |

**EST$ is a floor at the very top, not a point estimate.** The fit is concave, so it
compresses range; the $30+ band average is excellent while the single most expensive
player still runs above the estimate. Top EST$ is $32.27 against a $43 record high.
Budget above EST$ for your number-one target. This caveat is in `market.py`'s docstring
and on the printed board header — **plan 3 must carry it onto the PDF**, because the
person bidding reads the board, not the module.

Correcting the tail is **cheap and deferred, not unaffordable**: weighting the four
existing closed-form sums (~4 lines) measured Pareto-better at both ends
(`b` 0.551 → 0.653; MAE on paid ≥ $25 $13.42 → $12.34 AND on paid ≤ $3 $3.96 → $3.50).
Not adopted three weeks out on in-sample single-year evidence. Revisit with 2026 prices.

### FOLLOW-UP — licensed values in two tracked fixtures

**DONE 2026-08-18.** `tests/fixtures/draftsharks_sample.csv` and
`draftsharks_value_sample.csv` carried verbatim Draft Sharks projections, committed since
`55d5d49` in a PUBLIC repo. Both now hold invented round numbers matching the
already-cleaned `draftsharks_market_fit_sample.csv`, as does the copy of the fixture
quoted in `docs/superpowers/plans/2026-08-03-scoring-and-ingest.md`.

**Player NAMES were kept deliberately** — they are public fact, not vendor output, and
`test_cli_value` needs Ja'Marr Chase to join a real price from the tracked roster file.
Only the figures were licensed, and only the figures are gone.

DST sacks are 35 over 17 games (2.06/gm), still under the 3-sack threshold, so
`test_known_limitation_season_path_zeroes_all_dst_sacks` keeps exercising the limitation
it documents. Verified the production board is byte-identical before and after
(md5 `d7b6dfe0`), because fixtures touch no production path.

**Still outstanding, and a different question:** `tests/test_scoring.py:88` carries a
golden file of real CBS weekly stat lines (Eagles DST 2025 wks 13-17). That is the ground
truth validating the scoring engine, not vendor output, and `data/weekly/` is gitignored
for the same class of data. Decide whether the golden file belongs in the repo — do NOT
"clean" it casually: the engine's validation rests on it.

### Original finding — the model's top end is hotter than this league has ever paid

Found 2026-08-04 while checking Jeff's remark that "$47 or $48 would be a record high."
He is right, and it is measurable. Highest price ever paid in this league: **$43**
(Ja'Marr Chase, 2025). The model's top three are $54.2, $53.7, $47.0.

Bias against the 154 matched 2025 prices, by model dollar band:

| model band | n | model avg | actually paid | bias |
|---|---|---|---|---|
| $30+ | 13 | $40.1 | $26.9 | **+$13.2** |
| $20-30 | 10 | $22.9 | $15.5 | +$7.4 |
| $10-20 | 19 | $14.7 | $14.3 | +$0.5 |
| $5-10 | 7 | $8.8 | $13.0 | -$4.2 |
| $2-5 | 13 | $3.5 | $7.8 | -$4.3 |
| $1-2 | 92 | $1.0 | $3.6 | -$2.6 |

Monotonic and systematic. The board still totals exactly $1,320 — the total is right, the
**distribution is too steep**. This is the whole of the $11.24 top10_mae. Cause is
structural, not a bug: linear VORP-to-dollars assumes points are fungible currency, but a
real auction is budget-constrained (nobody spends $54 and still fills 13 spots) and needs
to fill every roster spot, so the top compresses and the $1 tail is bid up.

**Design question to settle before plan 3 renders anything**, because it decides what the
column means:

- **A — MY$ = what it will cost.** Calibrate to observed prices. Best for budgeting.
- **B — MY$ = what he is worth to me.** Leave it. The board then says "Nacua is worth $54,
  he will go for $43, bid." Best for finding edges. This is what it does today.
- **C — both.** Keep MY$ as value, add EST$ calibrated to this league.

Recommendation is **C, using the column THEIR$ just vacated** — swap an uncalibrated
vendor guess for a league-calibrated price prediction fitted on 154 real prices. Same page
width, far better column. Fit a monotone transform from model dollars to observed price
and renormalise so the board still sums to `total_capital()`.

This is a value-engine change, so like the lineup floors it lands **before** the renderers.

### Still blocking plan 3

**Excel target is now known.** Jeff supplied the 2022 workbook, preserved (gitignored) at
`data/extracts/_templates/stripes-2022-rankings-template.xlsx`. Requirement: **prints on
2 letter sheets, back to back.** Measured format:

| | |
|---|---|
| One sheet, landscape letter, 97% scale, gridlines off | |
| Three 6-column groups: `A-F`, `H-M`, `O-T`, separated by 0.9-wide spacers `G`, `N` | |
| Calibri 8pt throughout, bold headers, conditional formatting drives tier shading | |
| Widths: rank 2.8, name 11.6, Team/Bye 5.1, pos 3.8, tier 3.8, pts 3.5 | |
| 118 rows. OVERALL spans groups 1+2 (ranks 1-116, rows 1-59); position blocks stack below and fill group 3 | |
| 2022 columns were `Rank, Name, Team/Bye, Pos, Tier, AVG PTS` — the QB block alone had a `$` column | |

- **Confirm the THEIR$ recommendation** above (drop it, widen PAID). One-line answer.
- **`reportlab` and `openpyxl` are not installed in `.venv/`**, and there is no
  `requirements.txt`. `poc/render_poc.py` cannot run today. Installing them is the first
  task of plan 3; pin a `requirements.txt` at the same time, since the repo has no
  dependency manifest and the 08-23 refresh must not surprise anyone.
- **`poc/render_poc.py` still carries its own `load_ds`, `load_fp_kdst` and `value_pool`.**
  Plan 3 replaces all three with the real engine — `build_pool`, `score_season_calibrated`,
  `replacement_levels`, `assign_vorp`, `assign_dollars` — and keeps only the `Sheet` class,
  which is the settled, iPad-reviewed layout. The poc's own valuation is now obsolete and
  must not be carried forward: it predates flat-priced K/DST, the TQB/DST price joins, and
  the calibration curves.

## SILENT AUCTION — mechanic and data (confirmed with Jeff 2026-08-04)

**`data/league/silent-auction-bids.csv` is tracked and holds 5 complete years, 60 rows.**
Columns: `year, rank, franchise, bid, bump, cap_cost, player, note`.

**Mechanic:** sealed bid, floor **$26**. Bids ranked; you pay your own bid; you pick a
player in bid order, highest first. That order also governs nomination for the rest of the
draft. Ties are broken by a sealed **bump**, charged only if it wins the tie (matches
`bump_charged_only_on_winning_tie` in the league YAML).

**A sub-$26 bid is DISCARDED and the team forfeits its silent pick.** Hard constraint with
teeth — the planner must never suggest less.

**Jeff does not know whether finishing first buys a real advantage beyond the silent round.**
Do not assume it does. Present the order consequence factually and let him weigh it.

**Jeff wants the tradeoff shown, not a recommendation.** A table of candidate bids with what
each likely wins and what it leaves.

**TWO tie numbers, ruled 2026-08-05 — do not collapse them back into one.** `TIE2+`
(`field_tie_rate_at`) is the share of years two or more franchises tied EACH OTHER at a bid;
`TIE1+` (`join_tie_rate_at`) is the share of years at least ONE was already there, which is
what a bidder joining that number is exposed to. The second is never smaller and is much
larger where it matters: $30 is 40% against **100%**, and $33/$35/$38/$39 are all 20%
against **80%**. Both print on the management page and in `sffl plan`, and both go
`no data` — never `0%` — at $28, $29 and $36, which nobody has ever bid.

Empirical rank -> bid, all five years:

| rank | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| 1 | 44 | 45 | 39 | 41 | 43 |
| 2 | 41 | 42 | 39 | 41 | 40 |
| 3 | 40 | 39 | 39 | 40 | 40 |
| 4 | 40 | 38 | 39 | 39 | 39 |
| 5 | 38 | 38 | 38 | 35 | 38 |
| 6 | 37 | 35 | 35 | 34 | 37 |
| 7 | 35 | 33 | 33 | 33 | 33 |
| 8 | 35 | 30 | 31 | 31 | 33 |
| 9 | 32 | 30 | 30 | 31 | 30 |
| 10 | 30 | 27 | 30 | 30 | 27 |
| 11 | 26 | 26 | 26 | 26 | 26 |
| 12 | 26 | 26 | 26 | 26 | 26 |

Total spent is stable at **$412-432** of the league's $1,320 — roughly a third of all capital
goes in round one. Ranks 11-12 tie at the floor every single year, so the bump decides them.

### THIS CHANGES HOW TO READ EST$ AT THE TOP

**The top 12 prices in `auction-rosters-2025.csv` ARE the silent auction results.** Verified
by matching `cap_cost` exactly: Bijan $41, Henry $39, Barkley $38, Lamb $37, McCaffrey $34,
Jeanty $33, Jefferson $30, St. Brown $27, Nabers $27, Collins $26.

So the market curve `price = 2.248 * value^0.551` was fitted on data whose top end is
**sealed-bid prices, not open-auction prices** — formed by a $26 floor, competition for pick
order rather than for the player, and first-price sealed bidding that induces shading.

Consequences:
1. **EST$ at the top is more trustworthy than the earlier "it under-predicts the $43 record"
   note suggested** — the top players genuinely ARE bought in the silent auction, so EST$
   approximates what you must bid there.
2. **The tail compression is substantially the MECHANISM, not just curve concavity.** The
   twelve best players span only $26-$43 because the floor compresses from below and sealed
   bidding from above.
3. **Plan 4 should quote the empirical rank->bid table above, not infer from the curve.**

## TODO B — ANSWERED 2026-08-18. More weekly data does NOT improve the curves.

**Do not redo this. Do not "finish widening the collection."** It was finished, measured,
and rejected on the evidence.

The collection was widened to the spec's ~120-player target: 1,428 rows scraped from CBS
for 84 more players (WR/TE/DST/TQB) on top of the 30 RBs, giving 2,239 player-weeks across
120 players. **Corrected 2026-08-30 — these four figures were never re-derived after the
duplicate-entity fix, and none of them survives it.** Measured through `load_weekly`
today, the held-back files hold **92 distinct players / 1,562 rows** (the "1,428" was
84 × 17 assumed, not counted), and the full dataset — build set plus held-back, deduped —
is **127 players / 2,339 player-weeks**, not 120/2,239. The 2,239 figure was the old
build-set 811 plus the assumed 1,428. The verdict below is unaffected: it turns on the
held-out comparison, not on these counts. The curves got far denser — `rush_yds` 13 → 77 points, `rec_yds` 9 → 61,
`def_pa` 3 → 19, `pass_yds` 4 → 31.

**They also got worse.** Held out on players *no* candidate curve had been built from, the
18-player curve beat the widened curve on **6 of 7 banded stats** (mean abs error):

| stat | n | naive band | 18-player | widened |
|---|---|---|---|---|
| rush_yds | 289 | 0.181 | **0.074** | 0.085 |
| rec_yds | 205 | 0.137 | **0.053** | 0.072 |
| rec_ct | 205 | 0.264 | **0.075** | 0.101 |
| pass_yds | 84 | 0.443 | **0.150** | 0.173 |
| pass_cmp | 84 | 0.361 | 0.144 | **0.107** |
| def_pa | 53 | 0.716 | **0.120** | 0.143 |
| def_ya | 53 | 0.495 | **0.106** | 0.155 |

The price fit agreed: top10_mae **$11.22** (48-player) < $11.24 (18) < $11.32 (120), and
TQB mae degraded $8.98 → $9.95.

**Why, and this is the part worth keeping:** each curve point is *one player's whole noisy
season*, not one observation. Adding points lets the piecewise-linear interpolation chase
individual players' variance instead of the underlying mean-to-points relationship. More
data would help a *fitted* curve; it hurts a *interpolated* one. Smoothing and
usage-filtering (floors of 0/2/4 fpg) were both tried and neither recovered it.

**Shipped: 48 players, 811 player-weeks** — the 18 seed plus 30 stratified RBs. Best on
BOTH accuracy (0.683 vs 0.693 held out) and price fit. `calibration/2025.yaml`'s header
comment records this and a test pins it. **Corrected 2026-08-30: the real count is 46
players / 777 player-weeks — RB.csv carried a duplicate-entity pair (TreVeyon
Henderson, Kyle Monangai); see the dedup note near the top of this file. The shipped
curve itself is unaffected; only the header comment (left unregenerated) and this
count are stale.**

The 84 extra players' rows are kept at `data/weekly/2025/_held_back/` (gitignored) with a
README repeating this reasoning. They are real and expensive to re-collect. **The right way
to use them is a fitted/regularised curve rather than raw interpolation — a genuine
follow-up, and a good one, but not an auction-week change.**

## THE FOLLOW-UP RAN — isotonic curves ADOPTED for 5 stats, later revised to 4 (2026-08-30)

**REVISED 2026-08-30 (commit `e82d2e2`): `pass_yds` was REMOVED from the isotonic bundle
after re-measurement on de-duplicated data showed it losing to the baseline under
`predict_weekly` (0.1572 vs 0.1520). The section below is left as the historical record of
the ORIGINAL five-stat adoption; wherever it describes what is currently shipped (the stat
list, the `market/2026.yaml` coefficients, the "shipped curve is unaffected" claim, the test
count), read the correction in the isotonic-adoption checklist item above instead — this
section's numbers for those are stale.**

**DONE.** The follow-up TODO B predicted ("a fitted/regularised curve rather than raw
interpolation") was built, measured through three pre-registered gates, and adopted. Full
history: `docs/superpowers/specs/2026-08-30-curve-adoption-third-measurement.md` (the gate
that cleared) and `.superpowers/sdd/2026-08-30-regularised-calibration-curves/` (all five
task reports). Do not re-run this experiment; read the record instead.

**What changed.** `calibrate.build_curves_isotonic` (monotone/PAVA fit, already in
`src/sffl/calibrate.py` and untouched by this adoption) replaces `build_curves`
(interpolation) for exactly five stats **— as adopted on 2026-08-30; `pass_yds` was
withdrawn later that same day (commit `e82d2e2`), so the shipped count is FOUR. The list
immediately below is the ORIGINAL five, kept as the record of what was adopted; it is not
what ships** — built on the FULL dataset — the original 48-player
build set plus this held-back data folded in (132 distinct players, 2,424 player-weeks -
**corrected 2026-08-30 to 127/2339**, three held-back files carried a duplicate entity
each; see the dedup note near the top of this file):

    pass_cmp, pass_yds, rec_ct, rec_yds, rush_yds

**`def_pa` and `def_ya` are explicitly NOT adopted** and remain `build_curves` on the
build-set-only 48/811 (**corrected 2026-08-30 to 46/777**). Two independent, binding
reasons — do not revisit this "for
consistency" without a new gate:
1. DST sits in `flat_priced_pools`, so its curve never reaches `_dollars` — structurally
   inert on the auction board.
2. The weekly (in-season, `sffl week`) path where a DST curve DOES matter was never covered
   by any pre-registered gate in this experiment. **RESOLVED 2026-08-30 (commit `9b2fcdc`):**
   a pre-registered gate (`docs/superpowers/specs/2026-08-30-def-curve-weekly-gate.md`) was
   run — **underpowered at n=21, keep the baseline.** No candidate cleared the pre-registered
   +0.15 Spearman margin on both k=5 and leave-one-out; this is underpowered evidence, not a
   finding that the candidates are worse.

**Pooled residual estimation (`build_curves_pooled`) was tried and eliminated** — it failed
the bundle gate outright (`top10_cost` change of -0.05, i.e. no improvement) and does not
return as a candidate.

**Measured effect on the real 2026 board**, policy held at `starter` throughout:

| | shipped (interpolated) | isotonic bundle (adopted) | Δ |
|---|---:|---:|---:|
| `top10_cost` | 15.1681 | 12.5436 | **-2.6244 (-17%)** |
| `mae` | 4.3392 | 4.4758 | +0.1366 (within the ≤0.25 guard) |
| `top10_bias` | +5.1042 | +3.7312 | shrinks toward zero, same sign — no flip |

Leave-one-out over the top-10 priced players, corrected framing (an earlier draft of this
result claimed "10 of 10 replicates improve" — that overstated it): three of the ten
replicates (dropping Jonathan Taylor, dropping BUF, or the resulting promotion of Saquon
Barkley into the top ten) reproduce a `top10_cost` figure IDENTICAL to the no-drop case for
BOTH curve sets — a real identity of the metric (both players and their replacement sit on
the same side of the pricing bias), not evidence of ten independent perturbations. **The
honest count is 7 of 7 genuine perturbations improved, by +2.04 to +2.50, against a full
effect of +2.62** — the gain does not concentrate in one or two players.

**Files changed to adopt this:**
- `poc/build_calibration.py` — now the single source of truth, per-stat: `build_curves_isotonic`
  on build-set + held-back for the five stats above, `build_curves` on the build set only for
  `def_pa`/`def_ya`. Re-running it reproduces the committed files byte-for-byte (re-verified
  2026-08-30). **Superseded 2026-08-30 by commit `e82d2e2`: it is now isotonic for FOUR
  stats and `build_curves` for THREE — `pass_yds` moved to the interpolated side.**
- `calibration/2025.yaml` — regenerated. `def_pa`/`def_ya` are byte-identical to the prior
  shipped file (verified); the other five changed as measured above. **Superseded
  2026-08-30 (`e82d2e2`): `pass_yds` was regenerated back to its pre-adoption interpolated
  curve, so three stats — `def_pa`, `def_ya`, `pass_yds` — are byte-identical to the
  pre-adoption file and four changed.**
- `calibration/2025.provenance.yaml` — NEW, sibling file. `calibrate.load_curves` crashes on
  any key whose value is not a list of (mean, expected) pairs, so provenance cannot live
  inside `calibration/2025.yaml` itself. Records per-stat method, dataset, player count,
  anchor count. `tests/test_calibrate.py::test_every_curve_stat_has_provenance_and_vice_versa`
  keeps the two files from drifting apart.
- `market/2026.yaml` — refit with `sffl fit-market --force` against the same evidence
  (same extract, same prices, same league profile) recorded in its own `evidence` block,
  since the curves it depends on changed. **HISTORICAL — NOT WHAT IS COMMITTED. These are
  the five-stat bundle's coefficients, superseded the same day; the committed values are
  quoted at the end of this bullet.** New curve at the time:
  `a=2.0482551357513357, b=0.6459690793595126` (was `a=2.0115481304265863,
  b=0.6620227660597623`). New `diagnostics`: `mae=4.4758, top10_mae=8.8124,
  top10_bias=3.7312` (was `mae=4.3392, top10_mae=10.0638, top10_bias=5.1042`).
  **SUPERSEDED 2026-08-30 (commit `e82d2e2`, `pass_yds` reverted): the COMMITTED
  `market/2026.yaml` today is the four-stat refit, `a=2.028495994199789,
  b=0.6511171620237226`, `mae=4.4154, top10_bias=4.1025` — the numbers just above are
  historical, not what is currently shipped.**
- `tests/test_market_model.py::test_the_committed_2026_artifact_is_pinned` — updated to the
  new coefficients (a deliberate refit, not drift — see the test's own comment).
- `tests/test_calibrate_eval.py::test_the_harness_reproduces_the_shipped_curves` — updated:
  it used to assume one dataset/one method for every stat, which the shipped file no longer
  follows: it now rebuilds each stat with whichever method/dataset actually produced it.
- `src/sffl/render/intel.py` — the "Curves" disclosure item on the printed `Key & Intel`
  sheet said "widening it further was tried and measured WORSE" for every stat, which is now
  false for five of seven. Rewritten to describe the two-regime split; constants renamed
  `CALIBRATION_PLAYERS_ISOTONIC`/`_INTERPOLATED` (was one pair, `CALIBRATION_PLAYERS`/
  `CALIBRATION_PLAYER_WEEKS`). `tests/test_render_intel.py`'s provenance-drift test updated
  to match (two regimes, two regex matches, not one).
- `data/weekly/2025/_held_back/README.md` — amended (not rewritten): the original finding is
  marked TRUE FOR INTERPOLATION and superseded for these five stats by the isotonic result
  above, with a pointer back to the full experiment record. **Superseded 2026-08-30
  (`e82d2e2`): four stats, not five — that README carries its own dated
  `REVISION 2026-08-30` block recording the `pass_yds` withdrawal.**

**Full test suite: 654 passed** (was 653 — one added, `test_every_curve_stat_has_
provenance_and_vice_versa`). **Stale as of 2026-08-30: the current full suite (after the
`pass_yds` revert, the duplicate-entity fix, and full position coverage, and the all-13 roster board) is **868 passed**,
measured by `./.venv/bin/pytest -q` on `position-coverage` on 2026-08-30. (This line read
"770 passed" until the docs audit later that day: 770 predated the final review round's
three tests, which took it to 773, and the audit itself added the eight in
`tests/test_docs_match_artifacts.py`. The count is now asserted mechanically against the
run — see the machine-checked block at the top of this file.) See the isotonic-adoption
checklist item above and the top of this file.**

### Also found while checking the new data — a real scoring gap

An integrity check over all 2,239 rows (the pre-dedup count as it stood on 2026-08-18; the
deduped figure is 2,339 — see the correction in TODO B above) found exactly
**2 over-scoring rows** (Cooper Kupp
wk7, Chris Olave wk4), both off by exactly **−1**. Cause: **the league penalises a lost
fumble ~−1, and `leagues/sffl/2026.yaml` has no offensive fumble term at all.**

Real, but low urgency: fumbles touch no banded stat, so no curve and no price moves. It is
a small negative on a handful of players. Fix it with the 2026 rules pass, not this week.
**Note this is a league-YAML gap, NOT a `scoring.py` bug** — the engine stays untouched.

## Open questions

1. `rush_yds 250+` is the one unproven band — no 2025 game reached it (season high 244).
   Unprovable for now, not wrong.
2. Sacks are not corrected by the calibration curves; they use a threshold rule rather
   than a band table, so a defense averaging 2.5 sacks per game still scores zero across
   a season. Pinned by a characterization test. Needs a threshold-aware curve.
3. Which subscription to buy. Draft Sharks and Footballguys both export per-stat
   projections and are already ingested. See `docs/research/2026-service-evaluation.md`.
4. **TQB is the worst-fitting pool** — mae $8.98, 1.4x FLEX's $6.28 — and the second most
   expensive pool on the board after FLEX. **Do not treat that mae as a model-quality
   score until its two components are separated; a reviewer already did the separation
   once, so don't re-derive it:**
   - The residuals are **structured, not random noise.** Rushing-QB franchises are
     under-priced (BAL −$28, WAS −$27, PHI −$18); pocket-passer franchises are
     over-priced (DAL +$21, CIN +$17, MIN +$16). WAS is the sharpest case: it averages
     45.8 rush yd/gm, under the scoring bands' 50-yard floor, so season-averaging
     (`score_season`'s known bias — see `src/sffl/pool.py:14-33`) scores that production
     as zero every week it doesn't clear 50 on its own.
   - The remainder is **irreducible by construction**, not a modeling gap to close: the
     fit asks a 2026 point projection to explain a 2025 price for an entity — a Team QB
     unit — whose actual quarterback turns over wholesale between those two years far
     more often than any skill player's roster spot does.
   - Until someone separates "how much of $8.98 is the rushing-QB averaging bias" from
     "how much is un-fixable year-over-year turnover," TQB's mae is not comparable to
     FLEX's on the same terms.
5. **The fixture cannot witness an in-season page.** `tests/fixtures/cbs_weekly_rbwrte.txt`
   was captured 12 days before kickoff, in a week with no byes, no injury designations,
   and no rows owned by other managers. Verified on the real parser: a manager's 2-letter
   team abbreviation, or one with lowercase/digits, fails the `avail` regex and the whole
   page is REFUSED; an injury tag between position and bullet ("Nick Chubb RB Q • CLE")
   also refuses the page; a tag after the name silently renames the player ("Nick Chubb
   Q"); a bye row parses only if it still totals 17 tokens. Failing loudly is the right
   behavior — but the first bye week is exactly when this tool is most needed, and
   nothing today warns that the regex may need widening on first live use.
6. **`--week` is required but inert.** `cbs_weekly.parse(path, group, week, ...)` accepts
   `week` and never reads it in the function body; nothing stores it on the returned
   `PlayerProjection`, echoes it, or validates it against the page, and nothing reads the
   page's "REPORT UPDATED AS OF" stamp that the spec names as the staleness signal.
   Saving week 3's page and running `sffl week --week 4 ...` exits 0 with no warning.
   **FIXED 2026-08-31.** `parse` now records `week` and the opponent on every
   `PlayerProjection`, `cbs_weekly.read_report_stamp` reads the page's own
   "REPORT UPDATED AS OF" line, and `sffl alert` runs two independent checks:
   cross-page opponent agreement (a mixed-week pair disagrees on ~every shared
   team — measured 32/32, against a 2/32 noise floor from a real CBS TQB-page
   OPP defect, hence the ratio threshold `WEEK_MISMATCH_RATIO`) and page
   freshness against `STALE_PROJECTIONS_HOURS`. Both warn at the TOP of the
   digest and make the exit code non-zero; neither refuses to send, because an
   unattended job that produces nothing before kickoff is worse than one that
   flags its own inputs.

7. **`--waivers` names the drop. DONE 2026-08-31.** `lineup.best_add_drop`
   picks the cheapest release and the waiver board prints a DROP column.
   **Measured, and NOT what was assumed:** the drop is FREE at this league's
   geometry — 8 lineup slots against a 13-man roster always leave spare
   non-starters, so `net == delta` exactly (3000 randomised rosters: 3000
   equal, 0 different, pinned by
   `test_the_drop_is_free_at_this_league_s_roster_size`). An earlier draft of
   that function claimed `delta` overstated the gain; it does not. The value
   is naming the release, not correcting the number.

## OUTSIDE RANKINGS — the standing rule (reaffirmed 2026-08-19)

**Do not adopt an outside ranking or projection as a validating source unless it is
calibrated to THIS league's scoring.** This is the THEIR$ ruling generalised, and it keeps
coming up because outside sources are easy to find and feel like confirmation.

Worked example, the CBS/SportsLine "2026 busts" article Jeff raised on 08-19
(`cbssports.com/.../fantasy-football-rankings-2026-busts-by-model-that-projected-terry-
mclaurins-tough-season/`). Why it was DECLINED as validation:

1. **It is PPR.** This league bands receptions (7-8 catches = a flat 3 points) and does not
   pay per catch, and its TDs are not symmetric across positions. A PPR ranking cannot
   confirm or refute a banded-scoring valuation.
2. **It quotes ADP** — snake pick order — not auction dollars against a $1,320 cap.
   Different currency, and this league's round one is a sealed bid on top of that.
3. **No point totals and no dollar values are published**, so there is nothing to compare
   numerically even if the scoring matched.
4. **n=3 named players.**
5. **Its track record is a hand-picked list of hits with no denominator** (McLaurin 2025,
   A.J. Brown 2020, Jonathan Taylor 2021). This board quotes mae against 154 real prices.

**Directional agreement is not validation.** It happened to agree on 3 of 4 here — Nabers
outside the top 15 (board: WR20), Smith over Nabers (board: WR19 over WR20), Collins over
Nabers (board: WR10) — and disagreed on James Cook (their RB10, board RB4). Agreeing on a
few names using an incompatible yardstick tells you nothing about the model.

**What outside coverage IS good for: news, not numbers.** Injury, suspension and
depth-chart items are exactly what the board cannot know — that is the `Snapshot` item on
`Key & Intel`. Read it for events; never for values.

## NEXT UP — the 2026 prices are the first OUT-OF-SAMPLE test

Jeff is collecting the real 2026 auction prices (2026-08-27). **This is the most valuable
data this project can receive**, and it is worth being clear why: every number the model
currently reports was fitted on 2025 prices and measured against those same 2025 prices.
It is all in-sample. 2026 prices are a genuine holdout — the first honest answer to
whether any of this works.

**Capture format** — same as `data/league/auction-rosters-2025.csv`:
`franchise,pick_order,player_as_written,price`, 156 rows (12 franchises x 13 spots).

**Write `player_as_written` EXACTLY as the roster sheet shows it. Do not clean it up.**
The 2025 sheet wrote `PHILLY D`, `JAMAAR CHASE` (a typo), and Team QB units under their
starting quarterback's name. Those raw forms are what drove `identity/aliases.yaml` and
`identity/tqb-2025-starters.yaml` and took price joins from 108 to 154. Hand-normalising
them silently destroys the evidence about what still needs an alias.

Also extend `data/league/silent-auction-bids.csv` (`year,rank,franchise,bid,bump,cap_cost,
player,note`) with 2026 - six years of bid history instead of five.

### What the comparison actually tests, in priority order

1. **Is EST$ any good out of sample?** The headline question. `price = a * value^b` was
   fitted on 130 non-flat 2025 observations. Scoring 2026 prices against the CURRENT curve
   — before refitting — is the only clean measurement this project will ever get. Do that
   FIRST and record it, because once the curve is refitted on both years the holdout is
   gone forever.
2. **Was the +$13.9 top-end bias structural or a 2025 artifact?** The reasoning said it is
   structural: linear VORP-to-dollars assumes fungible currency while a real auction is
   budget-constrained and must fill every spot. If 2026 shows the same monotone pattern,
   that is confirmed on independent data. If it does not, the explanation was a
   just-so story fitted to one year.
3. **The deferred tail reweighting** (NEXT.md line ~433). Weighting the four closed-form
   sums measured Pareto-better on 2025 (`b` 0.551 -> 0.653, better at BOTH ends) and was
   not adopted on in-sample single-year evidence. 2026 is the evidence it was waiting for.
4. **starter vs draftable replacement policy.** The current rule says do not re-litigate
   without new price data. This is new price data. Re-run `choose_policy` on both years.
5. **TQB**, the worst-fitting pool at mae $8.70. Its residuals were structured (rushing-QB
   franchises under-priced, pocket-passers over). A second year says whether that shape
   repeats or was noise.

**Doubles the price base: 154 joined observations -> ~310.** Every fit in the project gets
better, and `MIN_OBSERVATIONS = 8` stops being anywhere near binding.

### Jeff's own 2026 roster, for reference when the prices land

Won the silent auction outright at **$42, bump $0** (rank 1; winning top bids over five
years were $44/$45/$39/$41/$43, median $43). Surrogate took **Ja'Marr Chase** over Nacua -
both carried unpriced injury risk the board could not see (Nacua injury/suspension talk
Draft Sharks had NOT priced; Chase hyperextended a knee in practice 08-25, two days after
the board was built).

QB LAC + SF · RB Skattebo, Stevenson, Henderson, Dowdle · WR/TE Chase, McConkey, Bowers,
Jameson Williams, Sutton · K McPherson · D Patriots.

$118 of board value against a $110 cap. Chase ($55.4) and Bowers ($24.9) are 68% of it.
**The RB room is entirely at or below replacement** (best is Skattebo at 65 projected
points against a 64.5 FLEX replacement), which the 1-RB lineup floor forces into the
starting lineup every week. Worth checking in-season whether that cost what the model
implies - it is a live test of the flex/replacement machinery.

## 2026 PRICES — THE HOLDOUT RESULT (measured 2026-08-27). READ THIS.

The 2026 auction happened and the real prices are in
`data/league/auction-rosters-2026.csv` (156 rows, 12 franchises x 13). **Scored against
the curve fitted on 2025 BEFORE any refit** - this is the one clean out-of-sample
measurement this project will ever get, and it is now spent.

**156 of 156 prices join the board**, up from 154 of 156 in 2025, after 29 new aliases and
a season-matched `identity/tqb-2026-starters.yaml`.

| | mae | rmse | bias |
|---|---|---|---|
| **EST$** | **$3.94** | **$5.65** | +$0.03 |
| MY$ | $4.34 | $7.01 | +$0.06 |

| band | n | EST$ mae | EST$ bias | MY$ mae | MY$ bias |
|---|---|---|---|---|---|
| $26+ (round one) | 16 | $8.74 | **-$8.74** | $9.78 | **-$0.25** |
| $10-25 | 28 | $5.50 | -$0.90 | $8.23 | +$0.18 |
| $4-9 | 40 | $3.62 | +$0.62 | $4.49 | -$1.31 |
| $1-3 | 72 | $2.45 | +$2.01 | **$1.53** | +$0.84 |

### FINDING 1 — the "+$13.2 top-end bias" was an ARTIFACT. Do not act on it again.

That figure (recorded at length further down this file, with a whole causal story about
budget-constrained auctions and linear VORP-to-dollars over-separating the top) came from
comparing **2026 projections against 2025 prices** - mismatched years, the same player
priced off a different season's expectations. Measured properly, 2026 against 2026,
**MY$ bias in the $26+ band is -$0.25.** There is no top-end bias to correct.

**The deferred tail reweighting was explicitly waiting on 2026 prices. The answer is NO -
do not adopt it.** It was tuned to remove a bias that does not exist.

Keep this as a method lesson: the explanation was coherent, quantitative, monotone across
six bands, and wrong. A story that good is exactly the kind that survives unchallenged
until someone measures it out of sample.

### FINDING 2 — EST$ is OVER-corrected at the top, and the printed caveat was right.

EST$ was fitted to remove that artifactual bias, so at the top it now under-predicts by a
systematic **-$8.74 on all 16 round-one prices**. The board's printed caveat - "EST$ is a
floor at the very top, not a point estimate" - is confirmed out of sample and now has a
number on it.

**Practical rule for 2027: use MY$ for round-one targets, EST$ for the $4-25 range, and
MY$ again at $1-3.** EST$ earns its keep in the middle, which is most of the board.

### What is now available that was not before

- Price base doubles: 154 -> 310 joined observations. `MIN_OBSERVATIONS = 8` is no longer
  anywhere near binding, and both the market curve and `choose_policy` can be refit on two
  independent years.
- **Re-run `choose_policy` on both years.** The old rule said do not re-litigate starter vs
  draftable without new price data. There is now new price data.
- TQB's structured residuals (rushing-QB franchises under-priced, pocket-passers over) can
  be tested for whether the shape repeats or was one year of noise.

### 2026 round one, for the bid history

All twelve bids DISTINCT - no ties, the first tie-free year in six. Bump was moot.
$42 / $39 / $38 / $36 / $35 / $33 / $32 / $31 / $30 / $28 / $27 / $26, total **$397**
(below the $412-432 of the prior five years). Jeff won outright at $42 by $3.
Still to do: append 2026 to `data/league/silent-auction-bids.csv` for a sixth year.

## REFIT ON THE 2026 PRICES (2026-08-27). What changed and why.

**The production command now takes the season's OWN price file and TQB map:**

```bash
PYTHONPATH=src ./.venv/bin/python -m sffl.cli value \
  --source sources/draftsharks.yaml \
  --file "data/extracts/Draft Sharks/2026/rankings-2026-08-23.csv" --year 2026 \
  --policy fit --prices data/league/auction-rosters-2026.csv \
  --tqb-starters identity/tqb-2026-starters.yaml \
  --curves calibration/2025.yaml --out board.csv
```

**There is no 2025 projection file anywhere in `data/extracts/` - only 2026.** So the 154
"2025 observations" the model shipped on were never year-matched and never could be. The
fit is now 156 of 156 year-matched observations, and the old price file is history, not
training data. Do not "combine both years" to double the sample: without 2025 projections
there is no 2025 value to pair a 2025 price with, and pairing it with a 2026 value is
exactly what manufactured the phantom bias.

| | old (mismatched) | new (year-matched) |
|---|---|---|
| joins | 153 of 156 | **156 of 156** |
| starter mae / top10 | $5.68 / $11.41 | **$4.34 / $10.06** |
| market curve | 2.273 x value^0.556 | **2.012 x value^0.662** |
| FLEX mae | $6.27 | $4.55 |
| TQB mae | $8.70 | $7.55 |

The curve's concavity fell (b 0.556 -> 0.662) because it was largely fitted to the
artifact. EST$ at the top improved: band bias -$8.74 -> **-$6.55**, overall mae $3.94 ->
$3.85. **It did NOT go away** - a power curve with b < 1 still compresses the top, so the
printed "EST$ is a floor at the very top" caveat still holds, just smaller.

### `choose_policy` had a real defect, now fixed (`fit.top10_cost`)

On the year-matched data `draftable` beat `starter` on the old tiebreak (top10_mae $9.08
against $10.06) - and shipping it would have been a serious mistake:

```
STARTER    $26+  MY$ mae $ 9.78   bias $ -0.25     <- noise around zero
DRAFTABLE  $26+  MY$ mae $10.34   bias $-10.34     <- mae EQUALS |bias|
```

For draftable, mae equals |bias| exactly: **all sixteen round-one players under-priced, by
about $10 each, in the same direction.** `top10_mae` cannot see the difference between that
and honest noise. Noise averages out over thirteen roster spots; a policy that under-prices
every expensive player by $10 loses all of them and no drafting skill recovers it.

`top10_cost = top10_mae + |top10_bias|` - pure noise charged once, pure bias twice. Picks
`starter` on the 2026 data. Four tests pin the rule, including the exact numbers above.

### Tests no longer break every August

Twenty tests asserted exact tie rates and rank ranges against the LIVE
`silent-auction-bids.csv`, so appending 2026 broke them all at once - not a regression,
just the data doing its job. Behaviour is now pinned against a frozen five-year snapshot
at `tests/fixtures/silent_bids_2021_2025.csv`, and the live file has three growth-proof
structural tests instead (row count is years x 12, every bid clears the floor, 2026 is
present and tie-free). **Do not re-point those assertions at the live file.**

### Still open

- **TQB residuals**: is the rushing-QB/pocket-passer shape (`intel.TQB_UNDERPRICED` /
  `TQB_OVERPRICED`, still hardcoded from the 2025 analysis) real, or was it one year of
  noise? Now testable year-matched, and the constants should be re-derived or dropped.
- **`market.py`'s tail-reweighting note is answered: do not adopt it.** It was tuned to
  remove the artifact.
- The `choose_policy` change is a value-engine change and has NOT had an independent
  review - it was written, tested and merged in one session.

## THE YEAR'S LESSONS, BAKED IN (2026-08-27)

Three guards and one derived figure, so the mistakes found this season cannot recur
silently. Each replaces something that failed WITHOUT an error message - the whole class
of bug this project keeps hitting is "plausible wrong board", never a crash.

**1. Cross-season fits are refused** (`fit.tqb_starters_season`, checked in `cli`).
Both starter maps now carry `season:`, and valuing year N projections against year M's map
exits with an explanation. This is the guard the whole refit paid for: pairing 2025 prices
with 2026 projections manufactured a $13.2 phantom bias, an EST$ curve fitted to remove it,
and a deferred code change waiting on evidence that never existed - with nothing in the
output looking wrong.

**2. Policy choice is bias-aware** (`fit.top10_cost`). `top10_mae` alone could not tell a
policy wrong in both directions from one wrong in a single direction, and picked the
latter. Bias is now charged twice, noise once.

**3. Index-mapped extracts are width-checked** (`ingest.profiles._check_width`,
`expect_columns: 47` in `sources/draftsharks.yaml`). A `by_index` profile reads stats by
POSITION, and `_cell` returns "" for an out-of-range index - so a vendor adding or removing
a column shifts every stat after it and the run still completes.
**Width, not a header hash, ON PURPOSE:** Draft Sharks renamed "3D Proj" to "DS Proj"
mid-preseason with the layout unchanged, and a hash would have refused a good file. The
honest cost: a pure REORDER at unchanged width is still undetectable, so a refreshed
extract still wants one known player's stat line eyeballed.

**4. The Team QB shape is derived, not frozen** (`intel._tqb_dispersion`). The hardcoded
`TQB_UNDERPRICED`/`TQB_OVERPRICED` tuples named six franchises and blamed quarterback
style. All six DO land in the claimed direction against the 2026 prices - and the cause was
invented. corr(MY$, residual) across all 21 units is 0.773 (r^2 0.598); the six named teams
are just the extremes of the MY$ scale, all three "rushing" ones sitting at the $1
replacement floor, and **nine of the nine units at that floor are under-priced, not the
three named**. What the model really does is OVER-DISPERSE Team QB dollars. The sheet now
says so, split at the pool's own median, and degrades to "too few units to say" rather than
inventing a shape.

**The method lesson, hit twice in one week:** a coherent causal story fitted to a pattern
that a duller explanation covers better. Both times the story was quantitative, monotone,
and survived until someone measured it out of sample. When a finding explains itself too
well, check whether a boring variable already accounts for it.

## SURROGATE FEEDBACK, AND THE POSITIONAL BIAS IT SURFACED (2026-08-27)

Christopher drafted the board on 08-26 and reported back. **His observation was right and
his explanation was wrong**, and chasing the difference found the most actionable defect
of the season.

**What he said:** "a lot of times, auction prices didn't fall within the range of predicted
spend... In a silo, those ranges make sense, but when you get a couple of guys who have
missed out on early targets and have a higher max than most everyone else, the pricing
guide pretty much goes out the window." He also stuck closely to the rankings, and outside
Chase went into double digits only twice.

**His diagnosis - late-draft budget divergence - is not what the data shows.** The guide is
at its BEST late and worst early:

| pick | n | EST$ mae | errors > $5 |
|---|---|---|---|
| 1 | 10 | $6.84 | 50% |
| 2-3 | 14 | $7.23 | 57% |
| 4-6 | 22 | $4.38 | 36% |
| 7-9 | 22 | $2.51 | 14% |
| 10-13 | 30 | $2.12 | 7% |

**The real cause is POSITIONAL.** Every one of the eight largest overpays was a running
back, and the whole-auction split is unambiguous:

| pos | n | mae | bias |
|---|---|---|---|
| **RB** | 34 | $5.03 | **-$3.92** (room pays MORE than the model says) |
| WR | 46 | $3.73 | +$1.56 |
| TE | 7 | $4.74 | +$4.65 (model overprices) |

On picks 1-3: **RB bias -$8.29, TE +$8.26.** Across the auction the room put **+$133 into
RB** against the model's valuation and **-$104 into WR/TE** - about 10% of league capital
allocated differently by position than the board advised.

**Likely mechanism:** RB and WR/TE share one FLEX pool and therefore one replacement level.
If RB falls off more steeply than WR/TE, a shared replacement understates RB scarcity. The
lineup floors added in plan 2 were a guard for exactly this and were measured as NOT
binding on this extract - so they did not catch it.

**The consequence is on Jeff's own roster.** He finished with Skattebo, Stevenson,
Henderson and Dowdle - all four at or below FLEX replacement - while spending his only
double-digit non-Chase money on McConkey and Bowers, both from the pool the model
overprices. The surrogate followed the board faithfully; the board's positional skew is
what he inherited.

### DO NOT change the valuation on this yet

One season, year-matched. It is consistent across every pick range and large, which is more
than the phantom top-end bias ever had - but that finding is exactly why this one waits for
2027 prices. **Test it first, with the pooled-replacement hypothesis stated in advance:**
split FLEX replacement by position and re-measure, rather than fitting a positional fudge
factor to a single year.

**Also worth recording about the bid.** Jeff won at $42; second was $39, so $40 would have
taken it and he paid ~$2-3 more than the minimum. That was still correct ex ante: $40
carried 60% TIE1+ / 40% TIE2+ against $42's 20%/0%, and he bought certainty in what turned
out to be the first tie-free year in six. Hindsight is not evidence the decision was wrong.

## Weekly calibration — measured (2026-08-28, Task 7 of the in-season-core plan)

The design spec's case for `score_week` rests on +4.88 across eight **hand-picked**
low-projection lines (band edges bite hardest there). `poc/measure_weekly_calibration.py`
measures the same comparison — `scoring.score_game` (CBS's banded point estimate) against
`pool.score_week` (the calibrated expectation, `calibration/2025.yaml`, 48 players / 811
player-weeks — **corrected 2026-08-30 to 46/777**, see the dedup note near the top of
this file) — on real data instead of a chosen sample.

**The input is 8 fixture rows from one saved CBS week-1 projections page
(`tests/fixtures/cbs_weekly_rbwrte.txt`), not a real full page.** It is the only real
weekly projection data captured before the season starts, so this is a measurement on
what exists today, not on "a whole position group" as the brief's phrasing suggested.

```
n=8   CBS total 20.70   calibrated 28.67   diff +7.97
players moved by >= 0.5 pts: 7 of 8
```

Every one of the 7 movers moved **up**. That direction is expected, not a bias finding:
this fixture is all low-volume TE/WR/RB lines sitting below several band floors, exactly
where `E[band(X)] > band(E[X])` — the same selection effect the spec's own +4.88 number
came from, just not hand-picked this time.

**Pairwise order — all 28 pairs of 8 players checked. Zero reorder.** 27 of the 28 pairs
have a definite CBS order, and the calibrated scorer agrees with CBS on every one of
them. The 28th pair, Elic Ayomanor vs. Kyle Pitts, is an exact CBS tie (2.50 = 2.50, no
order to begin with); calibration separates it, Pitts (3.56) over Ayomanor (3.37).

**Conclusion — a null result, reported plainly.** On the only real data available,
calibration does not change a single real ranking decision in this sample; it only
resolves one exact tie. That is a correction to what this section used to say: an
earlier measurement (before the C1 monotone-envelope fix, `c1702e3`) reported a
different pair of totals (28.16, diff +7.46) and named "1 pair reorders outright" — CBS
ranking Braelon Allen above Woody Marks, calibration flipping them to Marks over Allen —
as the concrete evidence that calibration moves a real decision. **That flip no longer
exists.** Allen now scores 2.74 to Marks's 2.72, agreeing with CBS, and it should not
have been reported as a stable finding in the first place. **Why it changed:** the C1
fix raised calibrated values in the noisy low-mean region of the curves by replacing raw
interpolation with a monotone envelope (see `_monotone_envelope` in `src/sffl/pool.py`);
doing so removed the exact non-monotone inversion that used to put Marks above Allen.
Nobody re-ran this measurement after that fix until now, which is why the section stayed
wrong.

This 8-row sample is itself low-projection and TE/WR/RB-only, so it still cannot speak
to whether calibration changes orderings among higher-projection players, whose
CBS-banded estimates sit further from band floors — that needs more saved CBS pages
than exist right now, which is a data-collection gap, same shape as TODO B above.
Extending the fixture to another position group is a separate, smaller gap: adding one
to `sources/cbs-weekly.yaml` is not the one-entry, no-Python-change addition it might
look like — the new entry must also set `expect_tokens`, which is opt-in
(`.get("expect_tokens")` in `cbs_weekly.py`). Skip it and the whole-width layout guard is
silently disabled for that group, which is exactly the Critical already fixed once on
this branch (a shifted column made a 0.9-reception back read as 7.9).

**Re-run this measurement after any change to `score_week` or the calibration curves.**
It has now gone stale silently once already — do not assume the numbers above still hold:

```
PYTHONPATH=src ./.venv/bin/python poc/measure_weekly_calibration.py
```

## AUCTION-PATH AUDIT (2026-08-28) — findings that must survive the branch cleanup

An independent audit of the MERGED auction pipeline, run because the 2026 auction is
over but the code runs again in 2027 and may be pointed at a second league. Everything
below was MEASURED against the real production board, not argued.

### CRITICAL — the 2027 pre-auction run cannot be done legitimately today

`cli.py`'s cross-season guard checks only `tqb_starters_season(--tqb-starters) != --year`.
**The prices CSV carries no season metadata at all**, so the TQB map is only a PROXY for
the prices' season. Three verified holes:

1. **Mismatched prices with a matched map passes silently.** `--year 2026 --prices
   auction-rosters-2025.csv --tqb-starters tqb-2026-starters.yaml` runs to completion and
   refits the artifact-era curve: **b = 0.531** against the year-matched truth of 0.662,
   TQB joins silently degrade 21 -> 15. This is byte-for-byte the configuration that
   manufactured the phantom +$13.2 bias.
2. **A starter map with no `season:` key skips the guard entirely** (`_map_season is None`).
3. **The guard exists only in `cli._value_pool`.** Direct `fit.load_prices` callers get
   `DEFAULT_TQB_STARTERS` (the 2025 map) forever with no check.

**The structural problem:** before auction night 2027 there is no 2027 price file, so
`--policy fit` must use 2026 prices. Pass the 2026 map (correct for those prices) and the
guard REFUSES. Pass a 2027 map and you get hole #1 — a silent cross-season fit. A
year-matched EST$ is therefore only computable AFTER the auction it was meant to inform.

**The fix, and it is architectural, not a patch: SEPARATE FITTING FROM APPLYING.** Fit the
curve now, on year-matched 2026 prices and 2026 projections, and PERSIST the coefficients
(e.g. `market/2026.yaml`). In 2027, APPLY that saved curve to 2027 projections. That is
what you actually want — last year's model of how this room behaves — and it makes the
guard honest: refuse a cross-season FIT, permit a cross-season APPLY, and print which
curve is in use and from which year. It also removes the prices file from the pre-auction
run entirely, which closes all three holes at once.

### The `expected_points` clamp does NOT affect the 2026 board — but the margin is thin

Measured across all 1,477 curve consultations on the real board: **no FLEX player is out
of span on any stat** (max rush_yds mean is Bijan at 85.1 against a 93.8 anchor; max
rec_yds Nacua 99.0 vs 107.2). Only LAR TQB is materially understated, by ~$2-3. Under the
defensible counterfactual, **zero dollars move on any player**.

**The 2027 latency:** the clamp becomes material when a projected mean crosses the next
scoring-band boundary above an anchor. Realistic trigger is a **100+ rush-yd/game RB
projection** (a 1,700-yard season, which vendors do project) — clamp 3.18/gm against a
true ~4.2/gm, i.e. **~17 season points ~ $13 understated on the #1 RB, silently.** Today's
margin is 15 yd/game and nothing warns when it erodes. TQB is already sitting on the
anchor (LAR 104%, CIN 101%). **Add a warning when any projection comes within ~10% of a
curve's top anchor.** (The in-season path solved the same problem differently — see
`_monotone_envelope` in `pool.py` — but `score_season_calibrated` still clamps.)

### `fit.top10_cost` is sound — but its tests pin a fabricated number

The metric and the reasoning hold: draftable's top-10 error is entirely one-directional
(mae $10.34 = |bias| $10.34), starter's is noise, and starter wins for any bias weight
above 0.25, so the choice is not knife-edge. The top-10 set is chosen BY PRICE, so
policies cannot reshuffle their own scoring population.

**But `tests/test_fit.py` (~lines 244-251, 276-285) pins "the real 2026 numbers" with
starter `top10_bias = -0.25`. The real value is +5.10.** The -0.25 belongs to the $26+
band from a different table. The decision the tests pin is right either way, but a green
test asserting starter's top-10 is unbiased when it over-prices by $5.10 is this
codebase's signature failure in miniature. **Fix the numbers or drop them.**

**Latent gaming hole:** `top10_cost` has no term for spread or ordering fidelity. A future
third policy that compresses the top AND recenters it (bias ~0, mae ~ spread) would beat
starter while destroying discrimination among the best players. Harmless while POLICIES is
(starter, draftable); a trap the day a "calibrated" policy is added.

### SECOND LEAGUE — what silently produces a plausible wrong board

Ordered most-silent first. A crash is fine; these do not crash.

1. **The calibration curves ARE this league's scoring table.** `score_season_calibrated`
   replaces the banded portion of scoring ENTIRELY with curve values. **Demonstrated:
   doubling one band table and zeroing another in a copied league YAML changes the
   no-curves score by 51 points and the with-curves score by 0.000 — identical to 13
   decimals.** A second league running with `--curves` gets STRIPES scoring regardless of
   its own YAML, and nothing warns: no league name, no band hash, no season in the curve
   file, and `load_curves` validates nothing. **A second league needs its own weekly
   ground truth and its own `poc/build_calibration.py` run.**
2. **Team QB is hardwired, not configured.** `build_pool` unconditionally drops individual
   QBs and fabricates franchise units. A normal-QB league gets a board of 32 team units
   and every other position reshaped around them.
3. **Lineup structure and floors live in CODE, not the YAML.** `value._starter_counts`
   hardcodes 1 TQB + flex + 1 K + 1 DST; `_select_flex_starters` hardcodes the 1 RB /
   1 WR-TE floor; WR/TE-as-one-position is baked into the FLEX tuple. `starters: 8` in the
   YAML is loaded and used for nothing on the auction path.
4. **Season-bound defaults.** `DEFAULT_BYES` is the 2026 bye file — a 2027 render silently
   prints 2026 byes. `DEFAULT_LEAGUE` is the 2026 profile. `lg.season` is never compared
   to `--year`.
5. **`DEFAULT_BIDS` is an absolute path into THIS repo's bid history** — a second league
   with a `silent_auction:` key renders STRIPES' five-year bid table on its page.
6. **Price joining is keyed to this league's artifacts** — `identity/aliases.yaml` holds
   this room's typos; join keys are name-only, so same-named players collide.

What DOES fail loudly and should stay that way: `flat_priced_pools` validation,
`fit_price_curve`'s refusals, `build_curves`' STAT_POSITIONS check, profile stat-key
validation, `_check_width`. `league.py` validates TYPES, not SEMANTICS.

### The RB positional gap — hypothesis strengthened, plus an unrecorded confounder

The pooled-replacement mechanism is real and measured: moving flex demand from 19 RB /
41 WRTE to 24/36 drops RB replacement 64.6 -> 54.0 while WRTE moves only +2.0 — RB
drop-off at the margin is ~5x steeper. The residual shape matches a level effect, not a
slope (RB residual vs MY$ slope is -0.09, flat). **A 24 RB / 36 WRTE split reproduces
about 80% of the observed gap with the right shape.** The room's RB capital share was
42.9% in 2025 and 39.6% in 2026 against the model's 24.9% — two independent years.

**UNRECORDED CONFOUNDER: the calibration curves themselves redistribute points by
position.** Calibration adds **+33% to top-12 TEs**, +33% to mid WRs, -3% to top WRs, +21%
to mid RBs. The rec-stat curves were built from a 48-player set of 30 RBs plus an 18-player
seed with few TEs, so the low-catch region driving the TE boost is WR-shaped. That is the
likely source of the recorded TE +$4.65 overprice. **Any split-replacement test must
separate "replacement is pooled" from "WR/TE mid-tier points are calibration-inflated" —
both push dollars the same way.**

**The distinguishing test does NOT need 2027 prices.** Prices only reveal the room's
beliefs again. The 2026 SEASON, scored under this league's own rules, settles which side
was wrong: if the mid-tier RBs bought at +$10 over model fail to clear flex replacement's
weekly output, the room burned money and the board's fade was an edge worth keeping; if
they beat it comfortably, the shared replacement (or the calibration) understates RBs and
the split ships for 2027. **The in-season core can measure this weekly.** Stating it now,
before results exist, is the pre-registration this file has been asking for.

### One more, and it is the same trap as the artifact

`cli.py`'s printed "bias against observed prices, by model dollar band" table conditions on
MODEL DOLLARS — the same selection geometry that produced the phantom bias — and on fully
year-matched 2026 data it still prints **+$12.7 at $30+**, two screens below a fit whose
top-10-by-price bias is +$5.10. No caveat is printed. **A future session could re-fit
something to remove that number and repeat the 2026 mistake with year-matching intact.**
Either print the caveat or drop the table.

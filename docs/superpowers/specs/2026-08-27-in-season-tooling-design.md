# In-Season Tooling — Design

**Date:** 2026-08-27
**Status:** approved in brainstorming; data sources VERIFIED 2026-08-28, not yet planned

## Goal

Answer three in-season questions in this league's actual scoring — **who to start, who to
claim off waivers, and whether a trade helps** — and let Jeff execute waiver moves from his
phone. One command, no dashboard, no web service.

## Why this is worth building

**NOT because we score better than CBS. We do not.** Measured 2026-08-28 against six real
week-1 projections off the league site, `score_game` agrees with CBS's own projected FPTS to
within $0.01 on every one. CBS applies this league's banded scoring to its weekly
projections correctly. Any design premised on out-scoring them is wrong.

The edge is two things, both measured:

**1. CBS bands a POINT ESTIMATE; the right answer is an EXPECTATION.** `E[band(X)]` is not
`band(E[X])`, and the gap is large exactly where in-season decisions are made — at the
margins between similar players. On eight real week-1 stat lines:

| stat | projection | CBS's band | calibrated | diff |
|---|---|---|---|---|
| rec_ct | 4.4 | **0.00** | 1.17 | +1.17 |
| rec_ct | 4.1 | **0.00** | 1.02 | +1.02 |
| rec_ct | 5.2 | 2.00 | 1.57 | **-0.43** |
| rush_yds | 36.8 | **0.00** | 0.83 | +0.83 |
| rush_yds | 41.0 | **0.00** | 0.85 | +0.85 |
| rec_yds | 46.5 | **0.00** | 0.77 | +0.77 |
| **total (8 lines)** | | **3.00** | **7.88** | **+4.88** |

A player projected just UNDER a band edge scores zero for that stat in CBS's numbers and has
a real non-zero expectation in ours; one just OVER is overstated. Systematic and
directional, not noise. `calibration/2025.yaml` maps per-game mean -> expected points, and a
weekly projection IS a per-game mean, so the curves apply directly. **This is their real
home — a better fit than the season totals they were built for.**

**2. The optimizer.** CBS gives per-player points and nothing else. It has no notion of the
best legal lineup under this league's slots and floors, and no notion of which free agent
most improves *Jeff's worst starting slot*. That question is unanswerable from a ranked list
and is the whole of the waiver query.

`src/sffl/scoring.py::score_game(lg, stats, pos)` remains the foundation, validated against
~250 real CBS weekly observations.

## Scope

**In:** weekly projection ingest, live roster + free-agent scrape, a lineup optimizer, three
queries built on it, waiver-queue submission, and a one-line push when something changed.

**Out:** injury/news monitoring beyond what the scrape reveals; any web page or dashboard;
season-long standings or playoff modeling; anything that writes to CBS other than the
waiver queue and the starting lineup.

## Global constraints

Inherited from `CLAUDE.md` and non-negotiable:

- **Python 3.9.6 only.** No `match`, no PEP 604 (`int | None`).
- **Use the venv:** `./.venv/bin/pytest`, `./.venv/bin/python`. `sffl` is not pip-installed,
  so ad-hoc scripts need `PYTHONPATH=src`.
- **`src/sffl/scoring.py` MUST NOT be modified.** It is validated ground truth.
- **The repo is public.** Anything holding licensed vendor projections or CBS stat lines is
  gitignored. Extend `.gitignore` before adding a new data path.
- **Never mix seasons.** A projection from one season and a price or actual from another is
  what produced this project's largest measurement error. The `tqb_starters_season` guard
  exists for exactly this; anything new that pairs data across a season boundary must fail
  loudly rather than proceed.
- **`by_index` source profiles declare `expect_columns`.** `_cell` returns `""` for an
  out-of-range index, so a vendor adding a column shifts every stat silently.

## The lineup — the fact everything else derives from

Eight starters from a thirteen-man roster:

| slot | eligible |
|---|---|
| TQB | TQB |
| RB | RB |
| WR/TE | WR, TE |
| FLEX x3 | RB, WR, TE |
| K | K |
| DST | DST |

This matches `leagues/sffl/2026.yaml`'s `starters: 8` and
`flex_slots: 5  # RB/WR/TE, floor of 1 RB and 1 WR/TE`. **Five of the eight starting slots
draw from one RB/WR/TE pool** with only one RB and one WR/TE forced — which is why the
auction model treats the two as near-interchangeable, and is the structural reason the
2026 positional bias (room paid +$133 into RB) did not surface in it.

The explicit slot list is NOT currently in the league YAML — only the aggregate. **Task 1
adds it**, because an optimizer needs slots, not counts.

## The calibration curves apply weekly, unchanged

Worth stating because it is not obvious and it saves building anything new.

`calibration/2025.yaml` maps **per-game mean -> expected points** for each banded stat. It
exists because `band(mean) != E[band(weekly)]` — averaging a season and banding the average
loses the distribution.

**A weekly projection is a per-game mean.** So `calibrate.expected_points(curve, projection)`
is exactly the right transform for a single week, and arguably a better fit than the season
use it was built for. The pattern to reuse is `pool.score_season_calibrated` — full score,
subtract the naive banded terms, add the calibrated ones — evaluated at `games=1`.

The same `STAT_POSITIONS` gating applies. **A zero is not a no-op for `def_pa`/`def_ya`**:
both band 0 at their MAXIMUM, so any loop over bands that is not position-gated pays every
receiver a shutout. That trap has been hit three times in this codebase. Do not hit it a
fourth.

## Data source — ONE, and it is verified

**`https://stripesfantasyfootballleague.football.cbssports.com/stats/stats-main`**, verified
2026-08-28 while logged in.

`Players -> PROJECTIONS -> TIMEFRAME: WEEK n (PROJ)` gives everything this design needs, in
one table:

- **Per-stat weekly projections**: rushing ATT/YDS/AVG/TD, receiving TAR/REC/YDS/AVG/TD,
  **FUMBLES LOST**, plus OPP (the matchup is already baked in), BYE, ROST%, START%.
- **Weeks 1-18**, selectable. Live now, twelve days before kickoff.
- **`FREE AGENTS` / `ALL PLAYERS` / `FANTASY TEAM` filters** — the free-agent pool waivers
  needs, from the same table.
- **This league's own positions**: `TQB`, `RB-WR-TE`, K, DST. No aggregation to build.
- Readable as plain text via `get_page_text`; 17 pages with an `All` option, and an export
  control on the page.
- `PENDING ADD/DROPS` at the page foot is the waiver queue.
- Stamped `REPORT UPDATED AS OF ...`, so staleness is detectable.

**Draft Sharks is NOT a dependency.** Its weekly tool is likely paywalled in-season; it is
also unnecessary, since the league site is free, included, and richer.

**Fractional projections (0.4 attempts, 5.2 receptions) confirm these are per-game
expectations**, which is precisely the input `calibrate.expected_points` wants.

CBS's `FL` column unblocks the recorded lost-fumble gap: the league penalises a lost fumble
(~-1) and `leagues/sffl/2026.yaml` has no term. Note CBS displays fumbles lost but does NOT
appear to score them (Braelon Allen's FPTS reconciles exactly without the penalty), so this
is a real divergence from what the league actually pays.

**Remaining unverified: the WRITE path only** — submitting to `PENDING ADD/DROPS` and
setting a lineup. Reading is proven. Task 1 shrinks to verifying the write.

## Architecture

Four new modules, one new command. Everything else is reused.

| file | responsibility |
|---|---|
| `src/sffl/weekly_proj.py` | Load weekly per-stat projections for a given week from a source profile. Returns `PlayerProjection` objects, same schema the auction path uses. |
| `src/sffl/roster.py` | Scrape live roster, free agents, and the waiver queue from the CBS league site. Read-only. |
| `src/sffl/lineup.py` | The optimizer and the marginal-value primitive. No I/O. |
| `src/sffl/waiver.py` | Submit `(add, drop)` pairs to the CBS queue and verify the result. The only module that writes anything. |
| `src/sffl/cli.py` | New `week` command. |

`lineup.py` holds no I/O on purpose: it is the piece with real logic and it must be testable
against hand-built rosters with no network and no fixtures.

## The optimizer

```
best_lineup(lg, players) -> (slots, total_points)
```

Small enough to solve exactly, and it must be solved exactly rather than greedily:

1. TQB, K, DST each take the highest-scoring eligible player. Independent of everything else.
2. The five flex-eligible slots take the best legal set from RB/WR/TE subject to **>=1 RB and
   >=1 WR/TE**.

Step 2 is the only interesting part. Take the top 5 by projected points; if a floor is
violated, the fix is a single swap — the best player of the missing position replaces the
worst player of the over-represented one. **The plan must include a test that brute-forces
every legal combination on a small roster and asserts the fast path agrees**, because a
greedy repair that is subtly wrong produces a plausible lineup and silently costs points.

Marginal value is then one line, and it is what all three queries use:

```
delta(player) = best_lineup(roster + [player]).total - best_lineup(roster).total
```

**This is deliberately marginal against Jeff's roster, not against a league replacement
level.** A generic tool ranks the best available player. This ranks the player who most
improves *his worst starting slot* — which, with four backs at or below replacement and one
RB slot forced every week, is a different answer.

## The three queries — and why waivers is the GENERAL case

All three are `sffl week`. **Waivers is not a separate question from start/sit; it is the
same question over a wider candidate pool.**

The only reason to claim a player is that he would crack the starting lineup. So
"does this free agent improve my optimal lineup" IS the start/sit computation, asked on
Tuesday about players Jeff does not own yet. Start/sit is then the degenerate case with the
candidate pool restricted to the current roster — which makes it nearly free once waivers
exists, and is why it is built second.

- **`--waivers`** (the general case) — compute `delta` for every free agent; rank
  `(add, drop)` pairs. The drop is chosen as the player whose removal costs least, not simply
  the lowest-projected.
  **The output MUST name the starting slot the added player would fill.** A claim that
  improves the optimal lineup is a different recommendation from one that only deepens the
  bench, and presenting them identically hides the distinction that justifies the claim. A
  bench stash is sometimes right — it just needs saying so.
- **`--start-sit`** (the restricted case) — same optimizer, candidate pool = owned players;
  report only where the optimum differs from the lineup currently set on CBS. Silence means
  the lineup is already right.
- **`--trade "GIVE1,GIVE2 for GET1,GET2"`** — `delta` for a hypothetical swap. Names resolve
  through `sffl.identity` like every other name in this project.

Default with no flag: run all three and report only what changed since the last run.

**"Since the last run" needs state**, and the spec must say where it lives:
`data/weekly-state/<season>-week<N>.json`, holding the previous run's optimal lineup, the
ranked waiver pairs, and a timestamp. **Gitignored** — it contains roster composition and
vendor-derived projections, and `.gitignore` must be extended before the path is first
written. A missing state file means "first run this week": report everything, push nothing,
since a first run has no change to report and should not fire an alert.

## Execution — the waiver queue

CBS processes waivers on a schedule, so a submission is a **queued pair, not a live drop**.
That is the difference that makes execution acceptable: nothing is irreversible at the moment
of submission, and the queue can be reviewed and edited before it processes.

Rules:

1. **Print the COMPLETE resulting queue**, not just what was added. A queue Jeff has not seen
   in full is one he cannot approve.
2. **Verify after submitting** by re-reading the queue from CBS. A click that did not land
   must be an error, never silence.
3. **Never drop a player who is in the current optimal starting lineup** without saying so
   explicitly in the output.

Lineup changes are written the same way, with the same read-back verification.

## Delivery

- **ntfy** sends one line when something changed: *"inactives are out — 2 lineup changes
  worth making."* It is the only piece that must fire unprompted, and it must work when
  nothing else is alive. The existing `linkedin-post-agent` pattern is the reference:
  topic in Keychain, never in the repo; thin body; the detail lives behind the link.
  fantasy-football gets its OWN topic — no coupling between the repos.
- **Dispatch** is the conversation and the execution. Jeff messages it from his phone, it
  spawns a Code session on the mini with the repo and his logged-in browser, and pushes back
  when done or when it needs approval. **Nothing to build for this.**

Scheduling is launchd, matching `linkedin-post-agent/launchd/`. Sessions did not survive the
Desktop app auto-updating on 2026-08-26; launchd jobs and the standalone review server did.
That is measured on this machine, not assumed.

Three runs, in the order the week actually needs them: **Tuesday** (waivers, before CBS
processes — the decision with the most lead time and the one that changes what is even
available to start), **Saturday** (start/sit over whatever the roster now holds),
**Sunday morning** (late scratches). Each run always leaves a trace even when it pushes
nothing, so silence is checkable rather than ambiguous.

## Failure modes that must be handled

| failure | required behaviour |
|---|---|
| Scrape returns an empty roster | Raise. An empty roster optimizes to an empty lineup and would recommend claiming everyone. |
| Weekly projections missing for a rostered player | Name the player and exclude him from optimization. Never score him as 0 — that silently benches him. |
| Projection source column layout shifted | Raise via `expect_columns`. |
| A scheduled run dies | The next run reports the gap. A missed Sunday must not look like a quiet Sunday. |
| CBS write did not take effect | Raise after read-back. Never report success on an unverified write. |

## Testing

- `lineup.py` is pure and gets the most tests: floors enforced, brute-force agreement,
  ties broken deterministically, empty and short rosters, a roster with no eligible RB.
- Scrapers get fixture-based tests against saved HTML/CSV, plus one live smoke test marked
  so it can be skipped offline.
- `waiver.py` is tested against a fake queue; **no test may submit to the real league.**
- Golden-file tests pin the weekly output so a scoring change shows up as a visible diff.
- Follow the existing convention: behaviour pins against **frozen fixtures**, live data gets
  only structural tests that survive growth. See `tests/fixtures/silent_bids_2021_2025.csv`
  and the note above it.

## Sequencing

1. **Spike — prove the WRITE path only.** Reading is verified. Confirm a pair can be queued
   into `PENDING ADD/DROPS` and read back. Output is an answer, not code we keep.
2. Explicit lineup slots in the league YAML.
3. `lineup.py` and the optimizer, fully tested, no I/O.
4. `weekly_proj.py`.
5. `roster.py`.
6. `sffl week --waivers` end to end — **the general case, built first.** It runs Tuesday and
   Wednesday, ahead of CBS processing, and a claim made then is what changes Sunday's lineup.
7. `--start-sit` — the same optimizer with the candidate pool restricted to owned players.
   Small once step 6 exists.
8. `waiver.py` submission with read-back verification.
9. ntfy + launchd.
10. `--trade`.

Steps 3-6 are buildable against fixtures before the season starts. Steps 1, 5, 7 and 8
cannot be finished until the CBS league site and weekly projections are live.

## Open questions

**1, 2 and 3 are RESOLVED** (2026-08-28): the league URL works, weekly projections carry full
stat lines, and Draft Sharks is not needed.

1. **Can the waiver queue and lineup be written programmatically**, and does the page confirm
   the write on read-back? The only unproven part of the design.
2. **Should the lost-fumble term be added now that CBS publishes `FL`?** CBS shows the stat
   but does not appear to score it, while the league does. It is a scoring change and belongs
   on its own branch with its own evidence, not folded into this.
3. **Does the calibration edge hold at the top of the roster, or only at the margins?** The
   +4.88 measured above is on eight low-projection lines, where band edges bite hardest. The
   plan should measure it across a full week before claiming a general improvement.

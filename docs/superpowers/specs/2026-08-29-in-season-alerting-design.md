# In-Season Parser Hardening, Injury Extraction, and Sunday Alerting — Design

**Date:** 2026-08-29
**Status:** approved 2026-08-29; schedule decided (see Schedule below)

## Goal

Three things, in dependency order:

1. **Harden the CBS weekly parser** so the first real in-season page does not refuse or mis-read.
2. **Extract injury designations** from that page and use them, so the optimizer stops starting a player who is Out.
3. **A Sunday-morning alert** that packages the injury and news status of every player on Jeff's roster into one push.

Kickoff is 2026-09-09. (1) has a hard deadline; (3) is only useful once the season starts.

## Why now

The in-season core shipped, but three independent verification passes found that its parser
has only ever seen a **pre-season** page — captured 2026-08-28, in a week with no byes, no
injury designations, and no rows owned by other managers. It structurally cannot have been
tested against the shape it will meet in week 1.

## Part 1 — Parser hardening

**The failure modes are known and measured**, not speculative. Each was demonstrated against
the real regex in `src/sffl/cbs_weekly.py`:

| input | today | why |
|---|---|---|
| 2-letter manager abbreviation in `avail` | **whole page refused** | `avail` group requires `FA`, `W (...)`, or `[A-Z]{3,}` |
| abbreviation with lowercase or digits | **whole page refused** | same |
| `Nick Chubb RB Q • CLE` (tag before bullet) | **whole page refused** | no group accepts it |
| `Nick Chubb Q ...` (tag after name) | **silently renamed** to "Nick Chubb Q" | greedy name group absorbs it |
| bye-week row | unknown | never observed; parses only if it keeps 17 tokens |

**Design:**

- Widen the `avail` group to accept 1–3 character team codes, mixed case, and digits.
- Add an OPTIONAL injury-designation group, accepted in both observed positions (after the
  name and after the position), matching the standard set: `Q`, `D`, `O`, `IR`, `PUP`, `SUSP`,
  `NA`.
- **Keep the near-miss counter loud.** We cannot test against a real in-season page, so the
  honest posture is: widen what is demonstrably too narrow, extract what is demonstrably
  present, and make anything else fail with a diagnostic naming the offending line. A refused
  page is recoverable in a minute; a silently mis-read one is not.
- Do NOT relax `expect_tokens`. The width guard is what catches a column shift, and a bye row
  that genuinely has a different width should refuse loudly.

## Part 2 — Injury extraction and use

- `PlayerProjection` gains `status` (raw designation, `""` when absent) beside the existing
  `avail`.
- **`O`, `IR`, `PUP`, `SUSP` are excluded from the optimal lineup.** Starting a player who
  will not play scores zero, so today's optimizer will happily field one. This is a
  correctness fix, not a nicety.
- **`Q` and `D` are flagged, never excluded.** A questionable player usually plays, and
  silently benching him would be a worse error than starting him.
- Excluded players are NAMED in the output with their designation — never dropped silently,
  matching the existing treatment of players with no projection.

## Part 3 — Sunday alerting

**The dependency that made this look hard is gone.** `cbs_weekly.parse` reads a saved file, so
a scheduled job has no page to read — but the alert does not need one. StatsDeck's
`get_injuries` is **nflverse data, not league data**, and works with no CBS connection.
Verified 2026-08-29 against Ja'Marr Chase: it returned two dated intel rows including the
hyperextended knee, source-labeled and corroboration-tiered.

**Also verified:** a headless `claude -p` session on the mini has full StatsDeck MCP access,
so launchd can drive it.

```
launchd (see Schedule below)
  -> claude -p on the mini
       -> read the roster file
       -> StatsDeck get_injuries: one unscoped call (75 intel rows), filtered to
          the roster; per-player calls only for anyone the unscoped call missed
       -> package into ONE message
       -> ntfy -> phone
```

This mirrors `linkedin-post-agent` exactly — launchd spawning `claude`, ntfy for delivery —
which is proven on this machine and survived the Desktop app auto-update that killed every
app-hosted session on 2026-08-26.

**Rules the alert must follow, taken from `get_injuries`' own contract:**

- **The official report is the record; intel supplements it and never overrides it.** When
  they disagree, show both with their dates and pick neither. The alert quotes; it does not
  adjudicate.
- **`tier` is corroboration strength, not severity.** "Corroborated" means well-sourced, not
  serious. Never render it as a severity signal.
- **Feed statuses include non-injury designations** — holdouts, rest days. The
  `reported_date` is load-bearing and travels with every line.
- **StatsDeck is connected to a DIFFERENT league** (Yahoo, half-PPR). Use only its
  league-agnostic NFL data. Never quote its points for a STRIPES player — scoring comes from
  this project's own banded engine.

**Delivery:** its own ntfy topic, distinct from `linkedin-post-agent`'s, stored in Keychain
and never in the repo. `PushNotification` is not used: it requires Remote Control to be
connected, and a headless launchd job cannot rely on that.

**Digest, not change-detection.** The alert sends every Sunday with the full roster status,
whether or not anything changed. A silent week is then indistinguishable from a dead job only
by its absence — so the message always sends, even when the news is "no designations on your
roster."

### The roster staleness problem, and the decision

`data/league/auction-rosters-2026.csv` is the DRAFT roster. It goes stale the first time Jeff
adds a player. StatsDeck cannot fix this — it reads Yahoo/ESPN/Sleeper, not CBS.

**Decision: a small hand-maintained roster file, with its age printed in every alert.**
Realistically 1-2 edits a week. The alternative — headless CBS capture — is a fragile scrape
of a page whose week selector is not even a URL, and its failure mode is silent.

The alert states "roster as of \<date\>" every time, and says so loudly when the file is more
than 10 days old. Visible staleness beats invisible staleness.

## Out of scope

- **Lineup recommendations in the Sunday alert.** Those need a saved CBS projections page,
  which a headless job does not have. The alert carries news only. Start/sit stays on demand.
- **Waiver submission and lineup writing.** Still deferred; this remains read-only.
- **`--trade`.** Blocked on rest-of-season projections — CBS has no ROS view, though weeks
  1-17 can be summed. Revisit once we know whether CBS's `Season` timeframe self-updates to
  remaining games in-season.
- **Automated CBS page capture.** Deliberately not attempted before we have seen a real
  in-season page.

## Testing

- Parser: fixture-based, with hand-constructed lines for every failure mode in the Part 1
  table. Do NOT add constructed lines to `tests/fixtures/cbs_weekly_rbwrte.txt`, which is
  labelled as real captured data.
- Injury exclusion: a roster where an `O` player would otherwise start, asserting he does not
  and that he is named in the output.
- Alerting: the message-composition function must be pure and unit-tested against fixture
  `get_injuries` payloads. **No test may call StatsDeck or send an ntfy message.**
- The launchd job itself is verified by a manual dry run, not by a test.

## Schedule — decided 2026-08-29

**TWO jobs, not one.**

| job | when | why |
|---|---|---|
| **Friday practice report** | Fri 4:45pm ET | Practice participation (DNP / limited / full) is the best available predictor of Sunday availability, and it arrives with two days left to make a waiver claim or line up a replacement. This is the ACTIONABLE one. |
| **Sunday inactives** | Sun 11:30am ET | Ninety minutes before the 1pm window, when official inactives land. This is the CONFIRMATION one — it catches the surprise scratch, on a short fuse. |

Both are digests: they send every time, even when there is nothing to report, so an absent
message means a dead job rather than a quiet week.

The two carry different content and should say which they are. Friday leads with practice
participation and reads as "here is what to plan around." Sunday leads with official
inactives and reads as "here is what changed since Friday." A Sunday alert that simply
repeats Friday's news trains its reader to ignore it.

## Open questions

1. Whether CBS's `Season` projection becomes rest-of-season in-season — decides whether
   `--trade` is cheap or a 13-page pull. Check in week 1.

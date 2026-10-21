# Replace StatsDeck with direct sources, then remove it

**Scoping plan, 2026-10-20, by John Madden. Jeff said go the same evening**, and his
decisions are in section 11. Done so far: step 0 (StatsDeck's write tools are denied) and
the CBS probe in step 1 (finding 5). Nothing else is built, and no job, plist or schedule
has changed. The evidence comes from the alert's own files and logs, a few public requests,
and one read-only look at the league site (Appendix A).

Sections: 1 the ask, 2 what StatsDeck does, 3 what the measurements show, 4 sources job by
job, 5 what Jeff chose, 6 build order, 7 the replay test, 8 what Ultron vets, 9 keeping the
alerts working, 10 removal, 11 decisions.

## 1. The ask

Jeff, 10-20: "I have a yahoo login we can use now since the 1 league is a yahoo league, and
truthfully we can source cbs too. And we should be able to source from nfl.com also. Or espn
without a login."

Why StatsDeck has to go:

- **Write tools.** It exposes `connect_league`, `disconnect_league`, `set_scoring` and
  `save_espn_credentials`, and any Claude Code session on the mini could call them (Ultron,
  10-20). Since 10-20 those four are denied by exact name in Claude Code's user settings,
  and `get_injuries` still works.
- **Persona.** Its "You are StatsDeck..." server instructions load into every main
  session. They were in this scoping session's own context on 10-20.
- **A whole headless session for one copy.** `ops/fetch_injuries.sh` starts `claude -p`
  three times a week only to copy `get_injuries` into a file. A refused or denied tool is
  the documented failure mode ("INJURY DATA UNAVAILABLE" in
  `docs/operations/in-season-alerting.md`). It's also why an agent's dry run needs a
  `CLAUDE_BIN` stub.

**The alerts must keep working all season.** Nothing switches until the new fetcher has
passed its check, Ultron has vetted it and Jeff OKs it (sections 7 to 9).

## 2. What StatsDeck does today

Jarvis's count of StatsDeck calls in Claude Code transcripts over the 60 days to 10-20:

| Job | Calls |
|---|---|
| **Alert injuries** (unattended) | `get_injuries` on every Tue/Fri/Sun run, through `ops/fetch_injuries.sh`. The alerts' only injury source |
| **Stats** (on demand) | `get_team_defense` 17, `get_player_stats` 4, `get_schedule` and `get_snap_counts` 2-3 each |
| **Yahoo Pick 6s** (on demand) | `get_my_roster` 6, then `get_available_players`, `start_sit` and `get_scoring` 2-3 each |
| Preseason only | `draft_help`, `connect_league` |

## 3. What the measurements show (10-20)

1. **StatsDeck's official report is nflverse's daily injury file, with renamed fields.** For
   the final week-6 report, both have 376 rows with the same game statuses (195 none, 94
   Questionable, 82 Out, 5 Doubtful) and the same practice statuses (183 full, 105 limited,
   87 did not practice, 1 blank). StatsDeck renames `report_status` to `game_status` (blank
   becomes "Not listed") and `report_primary_injury` to `injury`, and adds `age` and
   `eligibility`.
2. **So Friday's digest shows Thursday's report.** nflverse publishes the file once a day
   (its published schedule says 07:00 UTC; today's copy is stamped 08:41 ET). I compared the
   file the 10-16 16:45 run fetched with the final week-6 report. Of its 354 players, 163
   got a game designation in a later report that Friday's digest didn't have (82
   Questionable, 76 Out, 5 Doubtful). 102 practice statuses changed, and 22 more players
   were added. The Friday report the run is named for was not in it.
3. **Sunday's digest has never carried inactives.** The 10-18 11:30 file is the final
   week-6 report, with the same counts as Monday's copy and as nflverse's file today. No
   source can carry the 1 pm inactives at 11:30 either: teams announce inactives 90
   minutes before kickoff, so 11:30 ET is the moment they come out for the 1:00 games.
4. **Intel is capped at 100 rows.** All three saved files hold exactly 100 intel rows, so
   the window is about ten days now (10-10 to 10-19 in Monday's file), not the four weeks the
   runbook says. The rows come from two outlets: `sleeper_feed` (43 to 62 of the 100) and
   `web_digest` (38 to 57). `previous_status` and `status_since` are StatsDeck's own
   change tracking.
5. **CBS has the designations; the captured text drops them.** The four weekly pages of
   10-19 have 1,876 rows, all with a CBS id, and the captured text of none carries a
   designation, because CBS draws them as icons. The read-only probe of 10-20 found them in
   the page's markup at rest, with no click or hover needed:
   - Each player cell has a `span.playerIconsWrapper` holding, per icon, a `span[title]`
     around an `a.playerLink` whose `aria-label` repeats the title, around the icon's own
     `span`. Injury links also carry `subtab="Injury Report"`.
   - The icon class gives the kind: `icon-red_cross` (Questionable, Doubtful, Out, Retired,
     Did Not Report), `icon-player-status-ir` (Injured Reserve, NFI-R),
     `icon-player-status-pup` and `icon-suspended`. `icon-news-note-recent` is a news
     headline, and `-hot` and `-cold` are CBS's player trend.
   - An injury label reads `Injury Report: <body part>: Questionable for Week 7 at
     <opponent>`. IR and PUP labels add `Expected Return - Week N`; a suspension reads
     `Suspension: Suspended for <N> games`.
   - On the week-7 RB/WR/TE page, 197 of 1,714 rows carry one. A label counts only for the
     week it names: 9 bye players' labels named week 8, and 7 labels still named week 5 or
     6.
   - **News:** the icon carries only a headline. The body is on the player's own page,
     dated and credited "by RotoWire", and the league pages load it only into a pop-up on
     a click. So the capture can get designations and headlines, never the RotoWire text.
     Jeff chose ESPN for the news text anyway (section 5).
   - **A side effect for STRIPES:** the lineup gate that never starts an O, IR, PUP or SUSP
     player (`cbs_weekly.OUT_STATUSES`) has never had a designation to act on. None of the
     18 logged digests has an "EXCLUDED from the lineup" block. In week 1 two rostered
     players who were officially Out sat at 0.00 only because CBS had zeroed their
     projections. Step 1 fixes this.
6. **A CBS id crosswalk exists.** The ffverse/DynastyProcess `db_playerids.csv` (the file
   `nflreadr::load_ff_playerids()` reads) carries `cbs_id` beside the gsis (nflverse), ESPN,
   Sleeper and Yahoo ids. It maps 10 of 10 individual players on Jeff's roster, 124 of 125
   week-6 skill-position report rows, 400 of 403 ESPN skill-position injury rows and 249 of
   288 Sleeper injured skill players. It has a CBS id for 318 of 328 2026 rookies, but a
   Yahoo id for none of them. It is refreshed weekly (Fridays, about 05:00 UTC). The repo is
   GPL-3.0, so we read it at run time and never commit it.
7. **Matching today is by name only** (`injuries.for_roster`), though every StatsDeck row
   carries an nflverse id. So a TQB unit ("49ers TQB") never gets its quarterbacks'
   injury lines.

## 4. Sources, job by job

### 4.1 Alert injuries (unattended, Tue/Fri/Sun)

What `src/sffl/injuries.py` reads: a name, team, `status` (or `report_status` /
`game_status`), `practice`, `reported_date`, a detail text, and for change rows
`previous_status` and `status_since`. Appendix B maps each source's fields.

| Source | Fri 16:45 | Sun 11:30 | Fields | Match to CBS | Reliability | Terms | Effort |
|---|---|---|---|---|---|---|---|
| **nflverse injuries** (`injuries_<season>.csv`, GitHub release) | Thursday's report (measured, finding 2) | Friday's final; no inactives | status, practice, body part; no per-row date (the release's `timestamp.json` gives the as-of time); no change fields | gsis id, then the crosswalk | High: a daily job, a stable URL, 205 KB | CC-BY 4.0, documented through nflreadr | S |
| **Sleeper** (`api.sleeper.app/v1/players/nfl`) | Same day (its newest news timestamp on 10-20 was 15:30 ET); whether Friday's designations are all in by 16:45 is not measured | Same day; inactives not measured | status, body part (one word), a news timestamp; no practice, no prose | Sleeper id, then the crosswalk (249/288); otherwise name and team | Good: documented, no login. The call is 14.7 MB, and its status can lag or disagree with the official report | "Free to use for non-commercial purposes"; this call at most once a day; under 1,000 calls a minute | S |
| **CBS** (the existing league capture) | Same day: CBS's own label (on Tuesday it already showed week-7 labels) | Same day; whether CBS marks inactives by 11:30 is not measured | designation, body part, the week it applies to, expected return (IR, PUP), a news headline; no practice, no news body (finding 5) | Native CBS ids | Same as today's capture | Unchanged: the capture already runs on Jeff's login | S: read in the capture's existing `page.evaluate` call |
| **ESPN** (`site.api.espn.com/.../nfl/injuries`, no login) | Same day (rows dated to the minute; newest on 10-20 at 15:18 ET) | Same day; inactives not measured | status, date, short and long comment (prose), return date; no practice | ESPN id, then the crosswalk (400/403) | Medium: undocumented and can change without notice; 8.7 MB | Disney terms, section 2.B(x): no "copy or extract ... using a robot, spider, script, or other automated means" | S |
| **nfl.com injury report** (`/injuries/league/<season>/reg<N>`) | Friday's report as each team posts it (timing not measured) | Friday's final. Inactives are on the game pages, not this one | game status, practice status, body part; no date | Name and team (player slugs, no ids) | Medium: an HTML table that can change | NFL terms, 1.3: "Systematic retrieval of data or other content ... is prohibited absent our express prior written consent" | M |
| **Yahoo API** | Same-day status (expected, not sampled) | Not measured | status and injury note (to confirm); no practice | Yahoo id, then the crosswalk (no 2026 rookies) | Good | Documented, OAuth | M |

Yahoo is not proposed for the CBS alert: it would make the STRIPES digest depend on the
Yahoo token, and the crosswalk has no Yahoo ids for this year's rookies.

### 4.2 Yahoo Pick 6s (on demand, read-only advice)

| | **Fantasy Sports API** (OAuth 2.0, Read access) | **Logged-in browser profile** (like CBS's) |
|---|---|---|
| What Jeff does | Creates the app with Read access to Fantasy Sports, consents once, and stores the refresh token at the machine | Logs in once in a Playwright window, then again whenever Yahoo expires the session |
| What sits on the mini | A refresh token that can only read fantasy data, revocable in Yahoo's connected apps | A full Yahoo session (Mail and everything else) in a profile folder |
| Can it write? | No. The API's writes (roster PUT, transaction POST/PUT/DELETE) need Read/Write, and the app won't have it | Yes: anything Jeff can click |
| Stability | Documented URIs (below) | Page scraping, Yahoo's bot checks and CAPTCHAs, which only Jeff may solve (rule 6) |
| Effort | M: a stdlib OAuth refresh and a handful of GETs | M to build, then ongoing upkeep |
| Risks | Yahoo's developer page (10-20) says access goes through an application and review, while its API docs still describe self-service app creation. The token may rotate, and the client must store the new one | Session expiry; blocked automation |

**Jeff chose the API (10-20).** It has the least privilege by a wide margin, and no
password, cookie or CAPTCHA ever reaches an agent. Details from Yahoo's docs:

- Base `https://fantasysports.yahooapis.com/fantasy/v2`: `/league/{key}/standings`,
  `/league/{key}/scoreboard;week={N}`, `/team/{key}/roster;week={N}`,
  `/league/{key}/players;status=A` (or `FA`, `W`, with `position`, `sort`, `count` and
  `start`), `/league/{key}/settings` (the scoring).
- OAuth: authorize at `https://api.login.yahoo.com/oauth2/request_auth`, exchange at
  `.../oauth2/get_token`. The redirect may be `oob` (Yahoo shows a code to paste), so no
  web server is needed. Access tokens last an hour; the refresh token lasts long, but Yahoo
  may issue a new one, which replaces the old.
- Terms: Yahoo's API Access and Use Agreement, and the attribution line "Fantasy data
  provided by Yahoo Fantasy" on anything built from it.
- To confirm on the first real call: the JSON output (`format=json`) and the names of the
  player injury fields (`status`, `injury_note`).

**Start/sit.** Yahoo's API doesn't document projections, which StatsDeck's `start_sit`
used. The option is to re-score the CBS projections we already capture for every NFL player
under Pick 6s' half-PPR rules, as a second league profile on the existing engine, checked
against Yahoo's own weekly points from the API. **Jeff, 10-20: that comes later, only if he
misses projections.** Until then, Pick 6s advice is league data and injuries.

`draft_help` (preseason) isn't replaced here. Next August that's Yahoo's own draft tools or
a separate plan.

### 4.3 Stats (on demand)

| Need | Source | Why |
|---|---|---|
| Anything STRIPES-scored, DST included | **CBS**: projections captured every run, actual results by `sffl collect` | CBS scores the league. StatsDeck's DST numbers matched CBS for points allowed on only 4 of 11 defenses (2026-08-31) |
| NFL player stats by week, kickers included | **nflverse** `stats_player_week_<season>.csv` (nightly after game days) | Documented, CC-BY 4.0; the kicking columns are to confirm |
| Team defense | **nflverse** `stats_team_week_<season>.csv` | Same |
| Snap counts | **nflverse** `snap_counts_<season>.csv` (from PFR, four times a day) | Same |
| NFL schedule | **nflverse** `games.csv` (every few minutes in season) | Same |
| Yahoo-scored numbers | **Yahoo API** | Its own scoring |

Every one of those nflverse files was updated on 10-20, between 07:01 and 15:36 ET.
Effort S: one helper that downloads a named file into a gitignored cache and records its
update time. It's used only when someone asks, never by a job.

## 5. What Jeff chose (2026-10-20)

| Job | Source | Notes |
|---|---|---|
| Alert injuries, the record | **nflverse injuries** | The same data StatsDeck serves today (finding 1), documented and openly licensed |
| Alert injuries, same day | **Sleeper**, plus **CBS's own designation** from the capture | The probe showed CBS's label is readable at rest (finding 5). It's the league's own view, with exact ids, and it brings the lineup gate back to life |
| Alert news text | **ESPN's public injury feed** | Jeff: "Let's go with espn since it's 3 times a week and non-commercial". It runs only on the alert's runs, sends an honest User-Agent, and stops if ESPN blocks it. If ESPN breaks, the NFL team sites' RSS feeds are the backup. FantasyPros is out |
| Yahoo Pick 6s | **Yahoo Fantasy Sports API**, Read access | Projections later, only if Jeff misses them |
| Stats | **CBS** for STRIPES, **nflverse** for the NFL, **Yahoo API** for Yahoo | Each league's numbers come from the site that scores it |

**Keep the file contract.** The new fetcher writes the same
`data/captures/injuries-<kind>.json` that `injuries.load` reads: nflverse rows in `report`,
and Sleeper and ESPN rows in `intel`, with the outlet as each row's `source`. It adds a
`cbs_id` and an as-of time to each row, so `alert.py` hardly changes, and the failure
behaviour (delete before fetching, check the shape, show "INJURY DATA UNAVAILABLE") carries
over unchanged. CBS's designations come from the capture itself, by CBS id, and the alert
shows them beside the others. No source gives `previous_status` or `status_since`. The
fetcher derives them from its own previous snapshot and labels them for what they are
("first seen by this pipeline at <time>"). On Sunday that is exactly "what changed since
Friday".

**What this fixes besides StatsDeck:** each official row gets an honest as-of date
(Friday's digest would say "report as of Thursday" instead of "official undated"), CBS-id
matching replaces name matching, TQB units get their quarterbacks' lines, and the lineup
gate finally sees CBS's designations.

**What it doesn't fix by itself:** Friday's practice line stays a day behind (nfl.com
wasn't chosen), and no source has the 1 pm inactives at 11:30 (finding 3, decision 7).

## 6. Build order

Each step is its own staged change, committed only on Jeff's "C&P".

| Step | What | Effort |
|---|---|---|
| 0 | **Done 10-20:** StatsDeck's four write tools are denied by exact name; `get_injuries` still works | — |
| 1 | **CBS designations.** The probe is done (finding 5). The code: `_ID_EXTRACT_JS` also returns each row's icon labels, in the same `page.evaluate` call. They go to a sidecar file per page (`<page>.icons.json`, keyed by CBS id), so the captured text and its parsers don't change. Labels map to the parser's tags: Questionable Q, Doubtful D, Out O, Injured Reserve and NFI-R IR, Physically Unable to Perform PUP, Suspension SUSP; Retired and Did Not Report count as out. A label applies only to the week it names, and it feeds `OUT_STATUSES`. No new pages, no clicks | Half a day |
| 2 | **Injury fetcher**, a `sffl` subcommand: nflverse, the crosswalk (cached for a week), Sleeper and ESPN, written to the contract above. ESPN is called once per run with an honest User-Agent and no retry loop. A block (403 or 429) turns ESPN off until someone looks, and the digest says so. Standard library only (`urllib`, `csv`, `json`), with no new packages. Tests use constructed fixtures and no network | 1 day |
| 3 | **Matching by CBS id first** in `for_roster` (then name and team), quarterback lines for TQB units, our own change fields, and the stale docstrings (`injuries.py` still calls the official mapping "provisional", and says the feed has no position field) | Half a day |
| 4 | **The replay test** (section 7; Jeff confirmed it 10-20), then **Ultron's vet** of steps 1 to 3 (section 8) | Half a day |
| 5 | **Switch, on Jeff's OK only:** `run_alert.sh` runs the new fetcher instead of `fetch_injuries.sh`, which stays in the tree for a week as a one-line rollback. Never after week 12 (section 9) | 1 hour |
| 6 | **Yahoo**, once Jeff has created the app and consented: a read-only client (GET only, enforced in code), the refresh token in the Keychain, and `sffl yahoo` roster, matchup, free-agent, standings and scoring commands. Projections only if Jeff misses them | 1.5 days |
| 7 | **Stats helper** (nflverse cache), whenever it's first needed | Half a day |
| 8 | **Removal** (section 10), once the switch has run a clean week and Yahoo is live | Half a day |

That's about five days of work, with no trial in between.

## 7. The replay test (confirmed by Jeff, 10-20)

Jeff, 10-20: "No trial. What do we need a 2 week trial for?" In its place Jarvis
proposed this check, and Jeff confirmed it that evening: "yes to the no-trial plan."

- **Replay.** Run the new fetcher once and compare its output with the three saved
  StatsDeck files (`data/captures/injuries-{friday,sunday,tuesday}.json`).
  - The official rows must match the Sunday and Tuesday files exactly (376 rows, the same
    statuses and practice values), since both come from nflverse.
  - Against the Friday file, the only differences allowed are the known
    Thursday-to-Friday changes (163 designations, 22 added players, 102 practice
    statuses). That's the day-behind gap in finding 2, not a fetcher bug.
  - Render the digest's injury block for Jeff's roster from both files and compare it line
    by line. Every difference must be explainable: an as-of date, a match gained by CBS
    id, a TQB quarterback line, or a different news outlet.
- **Then** Ultron vets, Jeff OKs the switch, and `fetch_injuries.sh` stays for a week as a
  one-line rollback.
- **What it can't show:** how fresh Sleeper, ESPN and CBS are at Friday 16:45 and Sunday
  11:30, because the saved files are past snapshots. The first live Friday and Sunday after
  the switch show that, with the rollback one line away.

## 8. What Ultron vets first

1. **The injury fetcher** (new network code run unattended). Hosts: `github.com` and its
   download hosts (nflverse's release files, the crosswalk), `api.sleeper.app` and
   `site.api.espn.com`. No credentials. Timeouts and size caps. ESPN only once per run, with
   an honest User-Agent, and off after a block. It parses CSV and JSON only (never
   nflverse's `.rds`, `.qs` or pickle formats), writes only to `data/captures/` and a
   gitignored cache, and adds no packages.
2. **The CBS capture change:** one more read from the same pages, in the same `evaluate`
   call, on the same session, with no new pages and no clicks.
3. **The Yahoo client:** the app has Read access only, the code refuses anything but GET,
   and the refresh token lives in the Keychain, rotation included, never in a log.
4. **The NFL team sites' RSS feeds**, only if ESPN breaks and they replace it.
5. **After removal:** no session lists a StatsDeck tool or its instructions, and Yahoo's
   connected apps no longer list StatsDeck.

## 9. Keeping the alerts working all season

- StatsDeck stays the digest's source until Jeff OKs the switch. Its write tools are denied
  since 10-20.
- After the switch, a failed fetch reads exactly as today ("INJURY DATA UNAVAILABLE"), and
  the digest still sends.
- **Rollback** is one line in `run_alert.sh` for as long as `fetch_injuries.sh` exists.
- The jobs, their plists and their schedules don't change; they're Vision's. A change to
  the 11:30 Sunday run (decision 7) is a request to Vision through Jarvis, with Jeff's OK.
- **Freeze:** STRIPES's playoffs are weeks 15 to 17. The league's rules page (read 10-20)
  says the playoffs start in week 15 and last 3 weeks; the regular season is weeks 1 to 14,
  and the commissioner sets the playoff matchups by hand. No switch inside the playoffs or
  the two weeks before them, so the switch lands by Tue 12-01 (the end of week 12) or waits
  for next season.
- **Time budget:** the new fetch must finish within about two minutes (60-second timeouts,
  one retry, about 25 MB a run with ESPN's 8.7 MB).
- **A bonus once switched:** `run_alert.sh --dry-run` no longer starts a Claude session.

## 10. Removal, at the end

**Jeff, in his own accounts:**

1. claude.ai, under Settings → Connectors: remove StatsDeck.
2. His Yahoo account's connected apps: revoke StatsDeck.
3. If StatsDeck keeps an account with his league data or saved credentials, delete it
   there.

**This repo, in one staged change:** delete `ops/fetch_injuries.sh` and
`tests/fixtures/statsdeck_injuries.json`. Rewrite the StatsDeck parts of `injuries.py`,
`alert.py`, `cli.py`, `cbs_roster.py`'s comment, `run_alert.sh`'s `CLAUDE_BIN` block, and
the tests that name StatsDeck. Rewrite the runbook's "INJURY DATA UNAVAILABLE" and "older
item(s) hidden" sections, NEXT.md (its CBS ↔ StatsDeck matching paragraph and the dry-run
stub notes), and the specs' StatsDeck lines where they describe the present.

**Outside this repo:** the agent definition and Jarvis's own files that mention StatsDeck
are Jarvis's to update (he has the list). Once the tools are gone, the deny rules can go
too.

## 11. Decisions

**Decided by Jeff on 2026-10-20 (19:53 ET, relayed by Jarvis):**

1. **Alert sources:** nflverse for the record, Sleeper for same-day statuses, CBS's own
   designation (the probe shows it can be read), and ESPN's public injury feed for the news
   text: "Let's go with espn since it's 3 times a week and non-commercial". The NFL team
   sites' RSS feeds are the backup if ESPN breaks, and FantasyPros is out. ESPN stays on the
   alert's runs only, with an honest User-Agent, and stops if ESPN blocks it.
2. **No two-week trial:** "No trial. What do we need a 2 week trial for?"
3. **Yahoo:** the Fantasy Sports API with Read access. Projections come later, only if he
   misses them.
4. **StatsDeck's write tools:** denied by exact name (done 10-20).
5. **The replay test** in place of the trial (section 7): "yes to the no-trial plan."
6. **Sunday timing:** "Yes, change the sun run to 11:45." The 11:30 run couldn't carry the
   1 pm inactives, which come out at 11:30. Done 10-20 by Jarvis: the plist (repo and
   LaunchAgents), the runbook and the alert's comments. 11:45 still leaves 75 minutes before
   the 1 pm lock. How fast CBS, Sleeper and ESPN show inactives is not measured yet.

**Still open:**

7. **When to switch:** after the replay test, Ultron's vet and Jeff's OK, and by Tue 12-01
   at the latest (the playoff freeze in section 9).

## Appendix A: what was sampled

**Public endpoints:** eleven requests between 15:53 and 16:06 ET on 2026-10-20, at least two
seconds apart, with no login and no cookies.

| Endpoint | Size | Confirmed |
|---|---|---|
| `api.github.com` nflverse release `injuries`, and the `timestamp.json` file | 114 KB, 43 B | The 2026 files were updated 10-20 at 08:41 ET |
| nflverse `injuries_2026.csv` | 205 KB | Columns `gsis_id`, `report_status`, `practice_status`, `report_primary_injury`; weeks 1 to 6; week 6 identical to StatsDeck's report |
| `api.github.com` nflverse releases list | 6.4 MB | The update times of the stats, snap-count, schedule and roster files |
| DynastyProcess `db_playerids.csv`, plus its commit history and license | 2.6 MB | `cbs_id` and coverage (finding 6); weekly updates; GPL-3.0 |
| `site.api.espn.com` NFL injuries | 8.7 MB | 800 rows across 32 teams; per-row dates and comments; ESPN ids |
| `www.nfl.com` `robots.txt` and `/injuries/league/2026/reg6` | 343 B, 383 KB | `/injuries/` isn't disallowed; 376 rows, the same as nflverse's week 6; no timestamps |
| `api.sleeper.app/v1/players/nfl` | 14.7 MB | Its injury fields and ids; practice participation on only 1 player |

**The CBS probe:** six read-only page loads between 19:57 and 20:01 ET on 2026-10-20, with
the capture's own session and settle time: the roster page (`/teams`), the week-7 RB/WR/TE
projections page (the capture's own URL), `/schedule/team`, `/rules`,
`/standings/playoff-race`, and one rostered player's page. There were no clicks, hovers or
form input, and every URL was checked against an allowlist first. The pages' background
requests carried no injury data (26 requests: consent, analytics and a social widget).

Everything is saved under `.superpowers/sdd/2026-10-20-replace-statsdeck/`, which is
gitignored and outside the repo's tracked files.

**Docs read:** Yahoo's developer page and API docs at `sports.yahoo.com/developer`, and its
OAuth 2.0 authorization-code guide; Sleeper's API docs; nflverse's data schedule; the
Disney (ESPN) and NFL terms of use. **Read locally:** the three StatsDeck files in
`data/captures/`, the 10-19 CBS captures, and `logs/alert-*.log`. **Not sampled:** Yahoo
(it needs Jeff's consent).

## Appendix B: field mapping

| `injuries.py` field | nflverse | Sleeper | ESPN | CBS (capture sidecar) | nfl.com |
|---|---|---|---|---|---|
| name | `full_name` | `full_name` | `athlete.displayName` | row name | Player |
| team | `team` | `team` | `athlete.team` | row team | table team |
| status | `report_status` (already a fallback name) | `injury_status` | `status` | the icon label's designation | Game Status |
| practice | `practice_status` | none | none | none | Practice Status |
| detail | `report_primary_injury`, `report_secondary_injury` | `injury_body_part` | `shortComment`, `longComment` | the label's body part and expected return; the news headline | Injuries |
| reported_date | the release's `timestamp.json` (as-of) | `news_updated` | `date` | capture time | fetch time |
| status_since, previous_status | ours, from the last snapshot | ours | ours | ours | ours |
| id for matching | `gsis_id` | Sleeper `player_id` | ESPN id in `athlete.links` | CBS id (native) | none (name and team) |

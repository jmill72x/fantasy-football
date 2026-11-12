# In-season alerting: what it does, and what to do when it doesn't

Three unattended jobs run `sffl alert` against the live CBS league site and push a digest
to Jeff's phone over ntfy. This doc is the runbook: what runs when, how to set it up the
first time, and what each failure mode means and how to fix it.

## What runs when

| Job | Fires | Carries |
|---|---|---|
| `com.sffl.alert.tuesday` | Tuesday 16:45 local | **The claim run.** Drop/add opens Tuesday in this league and CBS processes waivers ~2am Wednesday, so this is the only digest whose claim advice can still be acted on. Carries the bye look-ahead and the trade targets. It projects the COMING week: `run_alert.sh`'s week on a Tuesday is the week just played, so `sffl alert` adds one for a Tuesday run (since 2026-10-20; before that, Tuesday scored the week already played). |
| `com.sffl.alert.friday` | Friday 16:45 local | Practice participation (DNP / limited / full), which only exists after Wednesday-to-Friday practices - so Tuesday cannot carry it. Also carries waiver targets (added 2026-10-02), each tagged with its own CBS clear date - after Wednesday's run players clear on different days. |
| `com.sffl.alert.sunday` | Sunday 11:45 local | Official inactives, 75 minutes before the 1pm kickoff window. Teams announce inactives 90 minutes before kickoff (11:30 for 1pm games), so the run moved from 11:30 to 11:45 on 2026-10-20 to give them time to land (Jeff: "Yes, change the sun run to 11:45."). |

**Why Tuesday was added (2026-09-16).** The planning content used to ride on the
Friday run, where it was incoherent: the bye look-ahead told Jeff "a claim has to
be in by Tuesday night" in a message that fired on FRIDAY, after that deadline had
passed. Friday keeps the hole warning ("you will be a man short") because that
stays useful once the window shuts; the shopping list moved to Tuesday.

All three are `launchd` **LaunchAgent**s (`ops/com.sffl.alert.<kind>.plist`), each
running `ops/run_alert.sh <tuesday|friday|sunday>`.

`StartCalendarInterval`'s `Hour`/`Minute` are the **machine's local time**. This Mac's
local time is already Eastern, which is the league's timezone, so 16:45/11:45 fire at
4:45pm/11:45am ET exactly as intended and this needs **no timezone handling anywhere in
the code**. If a future reader is tempted to add TZ conversion because "launchd surely
means UTC" - it doesn't; leave it alone.

These jobs are LaunchAgents, not LaunchDaemons, **on purpose**: a LaunchAgent runs inside
the user's logged-in GUI session, which is what gives it access to the unlocked login
Keychain (see "delivery failed" below). A LaunchDaemon runs outside any user session and
would lose that access entirely. Do not "promote" these to daemons later - it would
silently break every delivery.

## First-time setup

1. Install Playwright (already required by `sffl alert`'s capture step):
   ```
   ./.venv/bin/pip install playwright
   ./.venv/bin/python -m playwright install chromium
   ```
2. Log in to CBS once, by hand, so the automation has a session to reuse:
   ```
   ./.venv/bin/python ops/cbs_login.py
   ```
   This opens a real, visible browser window - it needs a GUI session and **cannot be
   completed over SSH** (there's no window server to show you the page), and is awkward
   over VNC too. Do it at the machine, logged in to the desktop.
3. Put the ntfy topic in the login Keychain. **Generate an all-lowercase topic** -
   ```
   LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c 24; echo
   ```
   Uppercase is legal per ntfy's own spec, but **the ntfy iOS app fails on a mixed-case
   topic**: it displays the subscription as `?/?`, receives nothing, and gives no error,
   while the server stores the messages perfectly well (confirmed by polling ntfy.sh
   directly for a 24-character mixed-case topic that never reached the phone; an
   all-lowercase probe topic to the same phone delivered instantly). Do not tighten
   `notify._TOPIC_RE` to lowercase-only in response to this - it would reject topics the
   server accepts and other clients handle. This is a client bug, worked around here.

   **Do this at the machine (Terminal.app), not over SSH** - `security` needs the window
   server to be able to unlock/write the keychain, and an SSH session (e.g. Termius) does
   not have one:
   ```
   security add-generic-password -a sffl-alert-ntfy-topic -s sffl -w <your-topic> -U
   ```
   The `-U` flag is required to **update** an entry that already exists - without it,
   `security` refuses and reports "the specified item already exists in the keychain"
   instead of silently overwriting the old topic. Both mistakes below have already
   happened once on this machine, in this order:
   - Ran the command over SSH -> `SecKeychainItemModifyContent: User interaction is not
     allowed.` Fix: run it at the machine instead.
   - Ran it again at the machine but without `-U` on an entry that already existed ->
     "already exists" error. Fix: add `-U`.
4. Copy the plists into place and load them (a human's decision, not something an agent
   should do automatically - see the note at the end of this section):
   ```
   cp ops/com.sffl.alert.*.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.sffl.alert.tuesday.plist
   launchctl load ~/Library/LaunchAgents/com.sffl.alert.friday.plist
   launchctl load ~/Library/LaunchAgents/com.sffl.alert.sunday.plist
   launchctl list | grep com.sffl
   ```

Before loading, rehearse the exact scheduled command without editing anything:
```
ops/run_alert.sh friday --dry-run
```
(or `DRY_RUN=1 ops/run_alert.sh friday`). This runs the real capture and scoring
pipeline and prints the full digest to stdout, but passes `--dry-run` through to `sffl
alert` so nothing is pushed to the phone. Confirm the roster names are Jeff's, the
digest reads sensibly for the current week, and no Yahoo point values appear anywhere
in the text. Two age lines are printed for exactly this check: the roster age (captured
by this run, so `0 days`) and the injury-data age (`fetched N minutes ago`) - if the
second reads in the hours, or the message says `STALE INJURY DATA`, the fetch step did
not run.

## The week number

`ops/run_alert.sh` computes the NFL week from today's date rather than a hardcoded
number, anchored on the season's Week 1 start, `WEEK1` (its `WEEK1=` line; Wednesday 2026-09-09 for
2026):

```
week = (today - WEEK1).days // 7 + 1
```

It's clamped to a minimum of **1**, so a run before the season starts (or a manual
rehearsal during preseason) asks CBS for week 1 instead of a zero or negative week. It's
clamped to a maximum of **18**, the last week of the NFL regular season, so a bug in this
arithmetic - or a run long after the season ends - can't ask CBS for a week that doesn't
exist. Both bounds are simple `min`/`max` calls in the script; there's no fallback logic
if a week outside `[1, 18]` would otherwise have been computed, it's just clamped.

**The date is 2026's and must be changed every season.** In 2027 the 2026 date makes every
run clamp to week 18. Before week 1, set `WEEK1` (the `WEEK1=` line of `ops/run_alert.sh`) to the
Wednesday of the new season's week-1 week, and change `--curves` (the `--curves calibration/` line) if the curves
changed. `docs/operations/preseason-runbook.md`, step 13, has the whole switch-over.

**A stale date or league profile now says so (since 2026-10-21).** The script passes
`WEEK1` to `sffl alert --week1`, which checks it and the league profile's `season:`
against the season of today's date (`sffl.season`; January and February count as the
previous season, so the 2026 season's January runs, the 2027-01-12 results run included,
stay silent). From 2027-03-01, a run still on 2026's values opens the digest with
`!! STALE SEASON VALUES`, one line per value with its runbook step, and exits non-zero;
the digest still goes out. The same run's `sffl collect` prints the warning too and still
files its unit, under the profile's season, so a unit collected that way may need moving
by hand once the values are fixed. If the alert jobs stay loaded through the off-season,
every run from March 1 carries the banner until steps 2 and 13 are done (or Vision unloads
the jobs).

## "I got no alert"

The digest **always sends**, even when capture or scoring fails outright - `sffl alert`
composes a message describing exactly what went wrong and still tries to push it (see
"CAPTURE FAILED" below). So an absent notification can only mean one thing: **the job
itself never ran.**

Check:
```
launchctl list | grep com.sffl
```
If a label is missing, the job isn't loaded - re-run the `launchctl load` command from
setup. If it's listed, check the last exit status in that same output (a non-zero last
exit status without a queued next run can indicate the job crashed before reaching
`sffl alert` at all - e.g. the `cd` in `run_alert.sh` failing), then read the error log:
```
tail logs/alert-tuesday.err
tail logs/alert-friday.err
tail logs/alert-sunday.err
```
The logs are append-only and keep every run since August. Since 2026-11-11 each run
starts and ends with a dated line in both files (`=== run_alert friday (live) started
2026-11-13 16:45:02 EST ===`, then `... finished, exit 0 <date> ===`, or `... finished,
killed by SIGTERM <date> ===` when the job was stopped; an EXIT trap writes it since 11-12,
so an early abort still gets one).
`grep -n '^=== run_alert' logs/alert-friday.log` lists the runs, and the latest one is
everything below the last `started`. Blocks from before that date have no such line, so
a grep hit above the first one (an `UNFILLED`, a `DEGRADED`) is an old run.

**If a run is simply missing, look for a restart first.** FileVault is on, so after a
restart (a power cut or crash included: `pmset autorestart` is 1) the mini boots to the
FileVault unlock screen. There's no GUI session, so no LaunchAgent is loaded and nothing
fires until Jeff logs in. A fire time that passes before that login is never made up:
launchd only catches up on runs missed during sleep, not runs missed before the job was
loaded. Compare `sysctl -n kern.boottime` and `last | grep console` with the fire time.
After a login, `launchctl print gui/$(id -u)/com.sffl.alert.<kind>` shows `runs = 0` and
`last exit code = (never exited)` until the job's first fire. That's normal and doesn't
mean the job is broken. This happened on 2026-11-06: the mini rebooted Thu 11-05 16:06,
the console login came Fri 11-06 16:49, and the Friday 16:45 run never happened.

## "The alert says CAPTURE FAILED / session expired"

The stored CBS browser session has gone stale - this is expected to happen every few
months. Fix:
```
./.venv/bin/python ops/cbs_login.py
```
Log in when the browser window opens, then press Return as prompted. No further action
needed; the next scheduled run reuses the refreshed session.

**A navigation timeout is a different failure.** The message reads `timed out navigating
to <url> after 90000ms x 2 attempt(s)`: CBS was slow, unreachable, or stuck on an
interstitial. The timeout is 90 s with one retry on purpose. Every projections page is
fetched with `?print_rows=9999` (otherwise CBS returns only its top 100 rows), and the
full RB/WR/TE page takes ~33 s to load. Don't tighten it: at 30 s the first scheduled
Friday run (2026-09-04) lost five of eight lineup slots.

## "The alert says a page was refused"

This means the weekly-stats parser (`sffl.cbs_weekly`) met a row shape it doesn't
recognize - most often a manager abbreviation missing from `owner_codes` in
`sources/cbs-weekly.yaml`. The error text **names the offending line** (the first
unmatched row), e.g.:

```
<path>: 1 line(s) contain ' • ' (look like a player row) but do not match the
expected layout ... First offending line: '...'
```

Add the missing code to `owner_codes` and re-run. Do not loosen the matching pattern
itself to "fix" this - the parser refusing a shape it doesn't recognize, instead of
guessing, is deliberate (see the comments in `src/sffl/cbs_weekly.py`).

A code that looks like a number (`12`) is YAML-parsed as an integer rather than a string.
That is handled - the loader coerces every code with `str()` - so it neither crashes the
command nor silently fails to match. Quoting it (`"12"`) is still clearer.

## Where the injury news comes from

Since the StatsDeck switch, `ops/run_alert.sh` runs `sffl injuries-fetch` (no Claude
session, standard library only) and passes `--cbs-designations` to the alert. The feed
(`src/sffl/direct_injuries.py`; the plan is `docs/plans/2026-10-20-replace-statsdeck.md`):

- **nflverse** (the official report, the record). The only source that can fail the fetch.
  It's published once a day, so Friday's digest carries Thursday's report and says "as of".
- **Sleeper** (same-day statuses; cached 24 hours, the digest prints its age) and
  **ESPN's public injury feed** (the news text; at most one call per 12 hours, and switched
  off by `data/cache/espn-off.json` after a refusal). Either can drop out alone; its line
  in `logs/alert-<kind>.log` says why, and the digest goes on without it.
- **CBS's own designations** (Q, D, O, IR, PUP, SUSP), read from the pages' icons by the
  capture itself. An Out, IR, PUP or SUSP label keeps a player out of the recommended
  lineup; a label naming no week benches until CBS removes it.

The fetch is removed before it runs and killed after 300 seconds (`FETCH_TIMEOUT_S`). A
dry run fetches as `--kind manual`: it leaves ESPN out and never touches the scheduled
change state.

**Don't call ESPN by hand within 12 hours of a scheduled run** (`sffl injuries-fetch
--espn`). The 12-hour marker is shared, so the scheduled run would skip ESPN and go out
without its news text. Sleeper and nflverse don't have this limit.

**Rollback.** In `ops/run_alert.sh`, change `INJURY_FEED="${SFFL_INJURY_FEED:-direct}"` to
`statsdeck`: the next run uses `ops/fetch_injuries.sh` (a headless `claude -p` with
StatsDeck's `get_injuries` only) as before the switch. CBS's designations have their own
switch: change the default of `SFFL_CBS_DESIGNATIONS` from 1 to 0. Both stay possible until
StatsDeck is removed (plan section 10).

## "The alert says INJURY DATA UNAVAILABLE"

The injury fetch produced no file, so the digest has its lineup half but no injury news -
and says so, in the message body, rather than printing "no designations on your roster"
the way a genuinely quiet week does. The run exits non-zero. The alert is still sent: a
lineup with no news beats no digest at all.

Read `logs/alert-<kind>.err` (the `WARN` line) and `.log` (the fetch's own lines):

- `WARN: injury fetch killed after 300s`: a source hung. Each request also has its own
  timeouts; check which host was slow before raising the limit.
- `injuries-fetch: nflverse failed (...)`: the official report couldn't be read (GitHub
  down, the file moved or changed shape). Nothing is written on purpose: an empty report
  would read as a clean roster.
- `... under half of the previous run's ...; refusing it as truncated`: nflverse served a
  short week. The next run usually clears it.
- `injuries-fetch: ... is not an earlier injuries-fetch output`: something other than the
  fetcher left a file at that path, and `run_alert.sh` didn't remove it first. Check the
  script wasn't edited.

On the rollback path (`INJURY_FEED=statsdeck`) the messages are `fetch_injuries:` ones:
the session never called the tool, `get_injuries` returned an error or a shape the parser
doesn't know (it knows CLI 2.1.310's `Error: result ... saved to <.txt>` and
`<persisted-output>` pointers), or the session had tools or a mode it shouldn't, which
the script refuses.

Whichever feed runs, the file is removed **before** fetching and again on any failure, so
a failed fetch can never leave the previous run's file to be rendered as today's news.

## "The alert says STALE INJURY DATA"

The injuries file exists and parsed, but is older than an hour - so it was not written by
this run's fetch, and the news in the digest is from an earlier run. Each row carries its
own `reported_date`, so the message can be read with that in mind. This normally means
the fetch step was skipped entirely (`sffl alert --injuries` pointed by hand at an old
file); a *failed* fetch removes the file rather than leaving it behind. The run counts as
degraded and exits non-zero.

## "The digest says older item(s) hidden"

Working as intended. A news feed keeps a player's latest item until there's a newer one,
so for a player nobody has written about lately the newest item is an old one, about a
game already played. Since 2026-10-02 the digest drops intel older than 7 days
(`injuries.INTEL_MAX_AGE_DAYS`, one game cycle) and prints how many it hid, so a hidden
item never reads as a quiet week. Official-report rows are never aged out, and undated
intel is kept, because unknown age is not "old".

## "The alert lists players under NOT EVALUATED"

Working as intended, and deliberately not phrased as advice. Players that could not be
scored used to fall out of the START/SIT diff into the SIT column every single week, which
read as "bench your kicker". They are now named in their own section instead.

**Updated 2026-08-30 (full position coverage).** This section used to say the job captures
"RB/WR/TE only", so "the Team QB, the kicker and the defense are never scored" and a
TQB/K/DST line here is "expected every week". **That is no longer true and should not be
used to dismiss one.** `sffl alert` now captures **four** pages - `RB-WR-TE`, `TQB`, `K`
and `DST`, all four groups defined in `sources/cbs-weekly.yaml` - and scores all eight
starting slots. A kicker under NOT EVALUATED is now a signal, not the weekly norm.

**Four** distinct things are reported there, and telling them apart is the whole point of
the section:

- *Their position is not in the projections page this job captures* - a **permanent**
  scope limit, no reflection on the player. With all four groups wired, no position on a
  legal CBS roster should land here any more; if one does, a group is missing from
  `sources/cbs-weekly.yaml`.
- *Their position IS ordinarily captured, but that page failed to capture or parse on this
  run* - **transient, this-run-only**. The digest also carries a `PROJECTIONS DEGRADED`
  note. Check back next run; if it repeats, read `logs/alert-<kind>.err`.
- *Their position IS captured, that page succeeded, and they still had no projection* - a
  **data problem**. Check the projections capture; a rostered player should have a row.
- *The roster row itself was ambiguous* - a **roster-parsing** problem, not a projections
  problem at all: two roster rows resolved to the same identity key.

The four reasons are `POSITION_NOT_CAPTURED`, `PROJECTION_PAGE_FAILED`,
`PROJECTION_MISSING` and `ROSTER_NAME_AMBIGUOUS` in `src/sffl/alert.py`, which carries the
full rationale for keeping them distinct.

## "The ADD button opened a plain player list"

Each waiver target in the Tuesday and Friday digests carries an ntfy ADD button that opens
CBS with the add already staged (`?default_add=<POS>:<id>`). Two things to know on the
phone:

- **If it lands on a plain player list, tap the button again.** You were probably not
  logged in: CBS sent you through its login page and lost the staged add on the way. The
  second tap goes straight through on the session you now have.
- **The staged add sits in the collapsed TRANSACTION DETAILS bar** at the bottom of the
  page. Tap it to open it and pick the drop.

## "The roster is wrong" (wrong manager's team)

`sffl alert`'s `--team-url` defaults to the bare CBS `/teams` URL with **no team
number** - CBS resolves that to whoever is logged in, which is identity-derived and
can't drift onto another manager's roster. If a numbered `/teams/<N>` URL is ever passed
explicitly, confirm `<N>` is Jeff's team and not another manager's before trusting any
output - a wrong team number captures a different roster and every downstream number is
confidently wrong. There is normally no reason to pass `--team-url` at all.

## "Delivery failed"

`sffl alert` still prints the full digest and exits non-zero when the push itself fails,
so this shows up as `[DELIVERY FAILED] <reason>` in the log, with a real digest above it.
Three distinct causes produce keychain-flavored errors and are easy to mix up:

1. **The scheduled job's keychain read genuinely fails** because the login keychain is
   locked (e.g. the screen was locked long enough for auto-relock, or auto-lock is
   configured aggressively). Fix: unlock it -
   `security unlock-keychain ~/Library/Keychains/login.keychain-db` - or just unlock the
   screen; being logged in to the GUI session normally keeps it unlocked, which is why
   these jobs are LaunchAgents (see "What runs when" above), not LaunchDaemons.
2. **The setup command was run over SSH**, not at the machine - this produces the
   `User interaction is not allowed` error at *setup* time, not at alert time. It is not
   something a scheduled LaunchAgent run will hit (it has GUI-session access an SSH
   session lacks); it only bites the human running `security add-generic-password` by
   hand. Fix: run that command at the machine.
3. **A topic mismatch** between what's in the Keychain and what's configured in the ntfy
   app on the phone - the push succeeds server-side but never reaches the phone because
   nothing is subscribed to that topic. Fix: confirm both sides reference the same topic
   string.
4. **The topic is mixed-case and the ntfy iOS app is silently dropping it** - the
   subscription shows as `?/?` in the app with zero notifications while the server holds
   the messages fine. Fix: switch to an all-lowercase topic on both sides (see
   "First-time setup" step 3).

`topic_from_keychain()` tells these apart rather than guessing: a genuinely missing entry
names the exact `security add-generic-password ... -U` command to create one (see
"First-time setup"), while a **locked** keychain says so explicitly and tells you NOT to
re-create the entry. If you see the create-it message, the entry really is absent; if you
see the unlock message, the entry is fine and creating a new one would only overwrite a
working topic. Any other failure is reported with `security`'s own message and its exit
code, unclassified, rather than being filed under "missing entry".

**Discord is a separate delivery, after the ntfy push.** Each alert also goes to
the #john-madden feed through the Jarvis poster, `~/Projects/jarvis/bin/discord-post`,
and neither channel's failure skips the other. A Discord failure is its own line in
`logs/alert-<kind>.log`, `[DISCORD DELIVERY FAILED] <reason>` - usually
`discord-post exited N`. The poster's own reason goes to `logs/alert-<kind>.err`:
`[discord] not posted: <reason>` for a refusal or a configuration problem (exit 2, e.g.
no webhook in the Keychain), or
`[discord] post to #john-madden failed on message N of M: <status>` when Discord or the
network failed (exit 3). A Discord-only failure still makes the run exit 1, even though
the phone push went out.

## Weekly data collection, and "COLLECT FAILED"

After `sffl alert` has run (never on a dry run), `ops/run_alert.sh` runs
`sffl collect`, which keeps this run's CBS pages before the next run overwrites
`data/captures/`. Added 2026-10-19: Jeff's words, "yes do a fully automatic data
download. you don't need my permission each time for that."

- **What:** the pages this run refreshed (the four weekly groups, the four
  rest-of-season pages when the run took them, the roster, the injury file), plus
  CBS's actual results for a week (`/stats/stats-main/all:<scope>/<wk>:p/standard/stats`):
  Tuesday takes the week just played, Friday takes it again after CBS's stat
  corrections, Sunday takes none. A page older than the run's start is left out
  and named in the unit's `COLLECTED.txt`.
- **Where:** one dated folder per unit (`<date>-<kind>` or `<date>-results`) under
  `wkNN/` - for a Tuesday run's pages, the week they project (the run's `--week` plus
  one), and for results, the week the results are for - in the local archive (`~/Archive/fantasy-football-data/<season>/cbs-weekly/`),
  on the Pi (`Documents/fantasy-football-data/<season>/cbs-weekly/`) and in the
  private data repo (`<season>/cbs/weekly/`), each with a `MANIFEST.sha256`. The data
  repo's top-level manifest gets the new files, and the job commits only those paths
  (`chore: automated: ...`) and pushes main. That commit and push is Jeff's standing
  exception to C&P, for the private data repo only.
- **Never overwrites:** a unit already at a destination is checked against its manifest
  and left alone. Re-running the same day fills in only the missing copies.
- **Auth:** the Pi and GitHub take `~/.ssh/id_ed25519` directly, with no agent and no
  prompt (`BatchMode=yes`). Checked from an empty environment on 2026-10-19.

**If it fails,** the digest has already gone out. The log shows `COLLECT FAILED <where>
<unit>: <reason>`, the `.err` log says `ERROR: weekly data collection failed`, a short
"SFFL data collection FAILED" note goes to ntfy and #john-madden, and the job exits
non-zero. A push that failed goes out with the next run's push.

**`COLLECT FAILED commit -: MANIFEST.sha256 ... holds changes this run didn't make`**
means someone edited the data repo's top-level manifest by hand (staged or not). The job
commits that file whole, so it stops rather than publish the edit: it commits only a
manifest that is HEAD's plus its own units' lines. Commit your edit yourself, or undo it
(`git -C ~/Projects/fantasy-football-data checkout HEAD -- MANIFEST.sha256` is fine: the next
run writes its units' lines back), and the next run commits the waiting units.

**`COLLECT FAILED repo <unit>: ... files differ from HEAD`** means a unit the data repo
already committed was changed by hand (a file edited, added or removed). A collected unit
never changes, so the job refuses rather than re-hash it into its commit. Undo it with
`git -C ~/Projects/fantasy-football-data checkout HEAD -- <the unit's path>` (and delete
any file you added there). **`MANIFEST.sha256 line <n> is malformed`** means that line of
the top-level manifest isn't `<sha256>  <path>` (two spaces); fix or remove that line.

To retry by hand, same day, from the repo root:
```
PYTHONPATH=src ./.venv/bin/python -m sffl.cli collect --kind tuesday --week <N> \
  --since <epoch the run started> --results-week <N>
```
`<N>` is the run's own week, as `run_alert.sh` computed it: a Tuesday run's pages land
under week N+1 and its results under week N. `--since 0` takes whatever is in
`data/captures/` now, so check the files' dates first.
`--no-pi`, `--no-repo` and `--no-push` turn a destination off. `--backfill-weeks 1-5`
captures past weeks' projections and results as CBS serves them today.

## What is deliberately NOT automated

The alert **recommends, it never acts**. Waiver-wire submission and lineup edits stay
strictly read-only: `sffl alert` reads the roster and projections, composes a digest,
and pushes it - it never submits a claim or changes a lineup on CBS. Every start/sit or
waiver decision the digest surfaces is still Jeff's to execute by hand.

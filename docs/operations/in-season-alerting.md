# In-season alerting: what it does, and what to do when it doesn't

Two unattended jobs run `sffl alert` against the live CBS league site and push a digest
to Jeff's phone over ntfy. This doc is the runbook: what runs when, how to set it up the
first time, and what each failure mode means and how to fix it.

## What runs when

| Job | Fires | Carries |
|---|---|---|
| `com.sffl.alert.friday` | Friday 16:45 local | Practice participation - the actionable signal, with two days of runway to make a waiver claim before Sunday. |
| `com.sffl.alert.sunday` | Sunday 11:30 local | Official inactives, ninety minutes before the 1pm kickoff window. |

Both are `launchd` **LaunchAgent**s (`ops/com.sffl.alert.friday.plist`,
`ops/com.sffl.alert.sunday.plist`), each running `ops/run_alert.sh <friday|sunday>`.

`StartCalendarInterval`'s `Hour`/`Minute` are the **machine's local time**. This Mac's
local time is already Eastern, which is the league's timezone, so 16:45/11:30 fire at
4:45pm/11:30am ET exactly as intended and this needs **no timezone handling anywhere in
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
3. Put the ntfy topic in the login Keychain. **Do this at the machine (Terminal.app),
   not over SSH** - `security` needs the window server to be able to unlock/write the
   keychain, and an SSH session (e.g. Termius) does not have one:
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
digest reads sensibly for the current week, the roster age reads a small number of
minutes-to-hours (not days), and no StatsDeck point values appear anywhere in the text.

## The week number

`ops/run_alert.sh` computes the NFL week from today's date rather than a hardcoded
number, anchored on the 2026 season's Week 1 start (Wednesday 2026-09-09):

```
week = (today - 2026-09-09).days // 7 + 1
```

It's clamped to a minimum of **1**, so a run before the season starts (or a manual
rehearsal during preseason) asks CBS for week 1 instead of a zero or negative week. It's
clamped to a maximum of **18**, the last week of the NFL regular season, so a bug in this
arithmetic - or a run long after the season ends - can't ask CBS for a week that doesn't
exist. Both bounds are simple `min`/`max` calls in the script; there's no fallback logic
if a week outside `[1, 18]` would otherwise have been computed, it's just clamped.

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
tail logs/alert-friday.err
tail logs/alert-sunday.err
```

## "The alert says CAPTURE FAILED / session expired"

The stored CBS browser session has gone stale - this is expected to happen every few
months. Fix:
```
./.venv/bin/python ops/cbs_login.py
```
Log in when the browser window opens, then press Return as prompted. No further action
needed; the next scheduled run reuses the refreshed session.

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

If `topic_from_keychain()` finds no entry at all, the error message names the exact
`security add-generic-password ... -U` command to run - see "First-time setup" above.

## What is deliberately NOT automated

The alert **recommends, it never acts**. Waiver-wire submission and lineup edits stay
strictly read-only: `sffl alert` reads the roster and projections, composes a digest,
and pushes it - it never submits a claim or changes a lineup on CBS. Every start/sit or
waiver decision the digest surfaces is still Jeff's to execute by hand.

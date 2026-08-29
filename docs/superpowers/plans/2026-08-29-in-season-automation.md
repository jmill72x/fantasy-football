# In-Season Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fully automated, unattended in-season assistant that captures Jeff's CBS roster
and weekly projections on its own, hardens the parser against real in-season page shapes,
refuses to start a player who is Out, and pushes a Friday and a Sunday digest to his phone.

**Architecture:** A Playwright browser profile owned by the automation logs into CBS once,
by hand, and thereafter captures both league pages headlessly. Everything downstream is
deterministic Python: parse → score → optimize → compose → deliver. `claude -p` appears
exactly once in the pipeline, as the transport for StatsDeck's MCP-only injury feed, and it
writes raw JSON rather than prose — every word the phone displays is composed by a pure,
unit-tested Python function.

**Tech Stack:** Python 3.9.6, pytest, Playwright (new), launchd, ntfy, StatsDeck MCP via
`claude -p`.

**Spec:** `docs/superpowers/specs/2026-08-29-in-season-alerting-design.md`

> **The spec is superseded on two points**, by Jeff's decision on 2026-08-29 — *"I want to do
> option C. I don't want to hand maintain my roster. You'll have to scrape the website for the
> roster before the Fri run,"* and *"I want this built correctly like a production grade app,
> with full automation."* Where this plan and the spec disagree, **this plan governs**:
>
> 1. The spec's "hand-maintained roster file" decision is **reversed**. The roster is captured.
> 2. The spec's "Automated CBS page capture — deliberately not attempted" is **reversed**, and
>    with it "Lineup recommendations in the Sunday alert" moves from out-of-scope to in-scope.
>    Once a job can capture the roster page it can capture the projections page in the same
>    session, and an alert that knows the roster but refuses to say who to start would be
>    withholding the answer it already has.
>
> Everything else in the spec stands, in particular the `get_injuries` contract rules and the
> testing rules.

---

## Global Constraints

Copied verbatim from `CLAUDE.md` and the spec. Every task's requirements include these.

- **Python 3.9.6 only.** No `match` statements, no PEP 604 (`int | None`) annotations.
- **Use the venv:** `./.venv/bin/pytest`, `./.venv/bin/python`. `sffl` is not pip-installed,
  so ad-hoc scripts need `PYTHONPATH=src`.
- **This repo is public.** `data/extracts/` and `data/weekly/` are gitignored. Never commit a
  file from either, and extend `.gitignore` before adding any new data path.
- **The scoring engine in `src/sffl/scoring.py` is validated against ~250 real CBS weekly
  observations.** Do not modify it without new ground-truth evidence.
- **Never validate current scoring against pre-2025 data.** The league's rules changed between
  2024 and 2025.
- **No test may call StatsDeck, launch a browser, reach the network, or send an ntfy message.**
- **No secret is committed.** The ntfy topic and the CBS profile path live in Keychain and in a
  gitignored local config, never in the repo.
- **Never quote StatsDeck's fantasy points for a STRIPES player.** StatsDeck is connected to a
  different league (Yahoo, half-PPR). Use only its league-agnostic NFL data — injury status,
  practice participation, news. Points come from this project's own banded engine.
- **The official injury report is the record; intel supplements it and never overrides it.**
  When they disagree, show both with their dates and pick neither.
- **`tier` is corroboration strength, not severity.** Never render it as a severity signal.
- **`reported_date` travels with every intel line.**

---

## Why the capture mechanism is Playwright — evidence, not preference

Four candidates were tested on this machine on 2026-08-29 before this plan was written. Do not
re-litigate these; they cost real time to establish.

| candidate | result | verdict |
|---|---|---|
| Claude-in-Chrome MCP from headless `claude -p` | `claude -p "…tools starting with mcp__claude-in-chrome__?"` answered **NO** | **Dead.** Chrome tools are injected by the app/extension pairing and are absent from `claude mcp list`. A launchd job cannot drive Chrome through Claude. |
| AppleScript to the live Chrome | `execution error: Google Chrome got an error: AppleEvent timed out. (-1712)` | **Rejected.** Also couples unattended automation to the state of Jeff's interactive browser. |
| Chrome cookie store → `curl` | Read of `~/Library/Application Support/Google/Chrome/*/Cookies` **blocked by policy** | **Rejected.** Correctly gated, and Chrome's cookie encryption is a moving target across versions. |
| CBS legacy fantasy JSON API | `api.cbssports.com/fantasy/league/rosters` is live and validates params (`"Missing league_id"`), but returns HTTP 500 without a token, and `general/oauth/login` is **404** | **Rejected.** The only documented token flow wants a password, which this project must not handle. Unverifiable end to end. |

**Chosen: Playwright with a dedicated persistent profile.** Jeff logs in once, by hand, into a
browser window Playwright opens; the session persists in a profile directory the automation
owns. Every run afterwards is headless and unattended. No password ever passes through this
code, no cookie is decrypted, and nothing depends on Jeff's own Chrome being open.

**Verified failure mode.** An unauthenticated fetch of the league does not hang or return
partial data — it 302s to `https://www.cbssports.com/login?...` and serves a page titled
`Sign In - CBSSports.com`. That exact string is the session-expiry detector in Task 1.

---

## File Structure

| path | responsibility | task |
|---|---|---|
| `src/sffl/capture.py` | **new.** Authenticated CBS page capture. The only module that touches a browser. Saves page text; detects session expiry. | 1 |
| `ops/cbs_login.py` | **new.** One-time headed login that seeds the persistent profile. Run by hand. | 1 |
| `src/sffl/cbs_roster.py` | **new.** Parse a captured team page into roster names. | 2 |
| `sources/cbs-weekly.yaml` | **modify.** Gains `owner_codes` — the enumerated league manager abbreviations the parser will accept. | 3 |
| `src/sffl/cbs_weekly.py` | **modify.** Config-driven `avail` group; optional injury designation; `classify_avail` reads the configured codes. | 3 |
| `src/sffl/schema.py` | **modify.** `PlayerProjection` gains `status`. | 4 |
| `src/sffl/cli.py` | **modify.** `_cmd_week` excludes OUT players and names them. | 4 |
| `src/sffl/injuries.py` | **new.** Normalize StatsDeck's `get_injuries` JSON into records. Pure. | 5 |
| `ops/fetch_injuries.sh` | **new.** The one `claude -p` call. Writes raw JSON, composes nothing. | 5 |
| `src/sffl/alert.py` | **new.** Compose the digest text. Pure, no I/O, exhaustively tested. | 6 |
| `src/sffl/notify.py` | **new.** ntfy delivery. The only module that POSTs. | 7 |
| `src/sffl/cli.py` | **modify.** `sffl alert` subcommand — the orchestrator. | 7 |
| `ops/com.sffl.alert.friday.plist` | **new.** launchd, Fri 16:45 local. | 8 |
| `ops/com.sffl.alert.sunday.plist` | **new.** launchd, Sun 11:30 local. | 8 |
| `ops/run_alert.sh` | **new.** The launchd entry point: capture → parse → injuries → compose → send. | 8 |
| `docs/operations/in-season-alerting.md` | **new.** Runbook: setup, re-login, failure triage. | 8 |

---

## Task 1: Authenticated CBS capture

**Files:**
- Create: `src/sffl/capture.py`
- Create: `ops/cbs_login.py`
- Create: `tests/test_capture.py`
- Modify: `.gitignore`
- Modify: `requirements.txt` (create if absent)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `capture.SESSION_EXPIRED_TITLE` → `str` (`"Sign In - CBSSports.com"`)
  - `capture.CaptureError(Exception)`
  - `capture.SessionExpired(CaptureError)`
  - `capture.check_page_text(text, url)` → `None`; raises `SessionExpired` or `CaptureError`. **Pure — this is the tested part.**
  - `capture.capture(urls, out_dir, profile_dir, timeout_ms=30000)` → `dict` mapping url → written file path. Launches a browser; never called from a test.

> **Gate before starting.** Run `./.venv/bin/pip install playwright && ./.venv/bin/python -m playwright install chromium`. Python here is 3.9.6; if Playwright refuses to install on 3.9, STOP and report BLOCKED with the exact pip error rather than substituting another mechanism — the four alternatives were already tested and rejected (see the evidence table above), so a substitution needs Jeff's decision, not an implementer's.

- [ ] **Step 1: Write the failing test**

Create `tests/test_capture.py`. Note that only the pure predicate is tested — no test launches
a browser.

```python
import pytest

from sffl import capture


def test_a_login_page_is_reported_as_an_expired_session():
    text = "Sign In - CBSSports.com\nLog In\nEmail\nPassword"
    with pytest.raises(capture.SessionExpired) as exc:
        capture.check_page_text(text, "https://example.invalid/teams/1")
    assert "log in again" in str(exc.value).lower()


def test_an_empty_page_is_refused_rather_than_saved():
    with pytest.raises(capture.CaptureError) as exc:
        capture.check_page_text("   \n  \n", "https://example.invalid/teams/1")
    assert "empty" in str(exc.value).lower()


def test_a_suspiciously_short_page_is_refused():
    # A real CBS page is thousands of characters. A 200-character body means
    # an interstitial, a rate limit, or an error page - never a roster.
    with pytest.raises(capture.CaptureError):
        capture.check_page_text("x" * 200, "https://example.invalid/teams/1")


def test_a_plausible_page_passes():
    assert capture.check_page_text("y" * 5000, "https://example.invalid/x") is None


def test_session_expiry_is_a_capture_error_so_one_handler_catches_both():
    assert issubclass(capture.SessionExpired, capture.CaptureError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_capture.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sffl.capture'`

- [ ] **Step 3: Write the implementation**

Create `src/sffl/capture.py`:

```python
"""Authenticated capture of the CBS league site.

THE ONLY MODULE THAT DRIVES A BROWSER. Everything downstream reads the text
files this writes, so the rest of the pipeline stays fixture-testable and
offline - the same discipline `cbs_weekly.parse` already follows.

WHY PLAYWRIGHT AND NOT SOMETHING LIGHTER. Four alternatives were tested on
2026-08-29 and each failed for a recorded reason: a headless `claude -p` has no
Chrome tools at all; AppleScript to the live Chrome timed out and would couple
unattended runs to Jeff's interactive browser; reading Chrome's cookie store is
policy-blocked and its encryption moves between versions; and CBS's legacy
fantasy JSON API 500s without a token whose only documented issuer wants a
password this project must never handle. Playwright with a persistent profile
needs a password exactly once, typed by Jeff into a real browser window, and
never through this code.

WHY A BAD CAPTURE MUST RAISE. An expired session does not return an error - it
returns HTTP 200 and a perfectly well-formed login page. Saved blindly, that
page parses to zero roster rows, the lineup optimises to empty, and the alert
confidently reports a roster Jeff does not have. Every capture is therefore
checked before it is written, and a failed check raises rather than returning
a shorter string.
"""

import os

# What CBS serves instead of the page when the session has expired. Verified
# 2026-08-29: an unauthenticated GET of the league 302s to
# cbssports.com/login and the resulting document carries this exact title.
SESSION_EXPIRED_TITLE = "Sign In - CBSSports.com"

# A real CBS roster or projections page is thousands of characters. Anything
# under this is an interstitial, a rate limit, or an error page. The bound is
# deliberately far below any real page and far above any error page, so it
# never has to be tuned.
_MIN_PLAUSIBLE_CHARS = 1000


class CaptureError(Exception):
    """A page was fetched but must not be used."""


class SessionExpired(CaptureError):
    """CBS served its login page - the stored browser profile needs a re-login."""


def check_page_text(text, url):
    """Raise unless `text` is plausibly the real page for `url`.

    Returns None on success so callers read as `check_page_text(...)` followed
    by a write, rather than threading a boolean nobody checks.
    """
    if SESSION_EXPIRED_TITLE in text:
        raise SessionExpired(
            "%s returned the CBS sign-in page, so the stored browser profile "
            "is no longer logged in. Nothing was saved - a login page parses "
            "to an EMPTY roster, which would read downstream as 'Jeff rosters "
            "nobody' rather than as a failure. Re-run "
            "`./.venv/bin/python ops/cbs_login.py` to log in again." % url)
    if not text.strip():
        raise CaptureError("%s returned an empty page - nothing saved" % url)
    if len(text) < _MIN_PLAUSIBLE_CHARS:
        raise CaptureError(
            "%s returned only %d characters, below the %d-character floor for "
            "a real CBS page - this is an interstitial or an error page, not "
            "a roster. Nothing saved."
            % (url, len(text), _MIN_PLAUSIBLE_CHARS))
    return None


def capture(urls, out_dir, profile_dir, timeout_ms=30000):
    """Fetch each url with the stored login and save its text. Returns {url: path}.

    NOT UNIT TESTED ON PURPOSE - it launches a browser. The logic worth testing
    is `check_page_text`, which is pure and called here on every page.
    """
    from playwright.sync_api import sync_playwright

    if not os.path.isdir(profile_dir):
        raise CaptureError(
            "no browser profile at %s - run "
            "`./.venv/bin/python ops/cbs_login.py` once to create it and log "
            "in to CBS" % profile_dir)

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    written = {}
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            profile_dir, headless=True, timeout=timeout_ms)
        try:
            page = ctx.new_page()
            for name, url in urls.items():
                page.goto(url, timeout=timeout_ms, wait_until="networkidle")
                text = page.inner_text("body")
                check_page_text(text, url)
                path = os.path.join(out_dir, "%s.txt" % name)
                with open(path, "w") as fh:
                    fh.write(text)
                written[url] = path
        finally:
            ctx.close()
    return written
```

Create `ops/cbs_login.py`:

```python
"""ONE-TIME, BY HAND: log in to CBS and leave the session in the automation's profile.

    ./.venv/bin/python ops/cbs_login.py

Opens a real browser window. Log in to CBS yourself - this script never sees,
asks for, or stores a password; it only holds the window open while you use it,
then closes it so the session is flushed to the profile directory. Every
scheduled run afterwards reuses that profile headlessly.

Re-run this whenever an alert reports SessionExpired.
"""

import sys

from playwright.sync_api import sync_playwright

PROFILE_DIR = "data/browser-profile"
LEAGUE = "https://stripesfantasyfootballleague.football.cbssports.com/"


def main():
    print("Opening a browser window. Log in to CBS, then press Return here.")
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(PROFILE_DIR, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LEAGUE)
        input("Press Return once you can see the league home page... ")
        text = page.inner_text("body")
        ctx.close()
    if "Sign In - CBSSports.com" in text:
        print("Still on the sign-in page - the session was NOT saved.")
        return 1
    print("Logged in. Session saved to %s" % PROFILE_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Add the profile and captures to `.gitignore`**

Append to `.gitignore`:

```
# Playwright profile holding a live CBS login - a credential, never committed
data/browser-profile/
# Pages captured from the CBS league site
data/captures/
```

- [ ] **Step 5: Record the dependency**

Create `requirements.txt` (or append if it exists):

```
playwright>=1.40
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_capture.py -v`
Expected: 5 passed

- [ ] **Step 7: Run the full suite for regressions**

Run: `./.venv/bin/pytest -q`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add src/sffl/capture.py ops/cbs_login.py tests/test_capture.py .gitignore requirements.txt
git commit -m "feat(capture): authenticated CBS page capture with loud session-expiry

A Playwright profile the automation owns, seeded by one hand-run login.
No password passes through this code and no cookie is decrypted.

An expired CBS session returns HTTP 200 and a well-formed login page, so
every capture is checked before it is written: a login page, an empty
page, or one below a 1000-character floor raises instead of being saved.
Saving one would parse to an empty roster and read downstream as 'Jeff
rosters nobody' rather than as a failure."
```

---

## Task 2: Roster page parser

**Files:**
- Create: `src/sffl/cbs_roster.py`
- Create: `tests/test_cbs_roster.py`
- Create: `tests/fixtures/cbs_team_page.txt`

**Interfaces:**
- Consumes: `capture.capture` (Task 1) produces the file this parses.
- Produces: `cbs_roster.parse_roster(path)` → `list` of `str` — player display names, page
  order preserved, duplicates removed.

> **This task begins by capturing a real page.** Run
> `./.venv/bin/python ops/cbs_login.py` (once), then capture Jeff's team page to
> `data/captures/roster.txt`. Build the fixture from that real capture — the pre-season
> projections fixture already in this repo is exactly the "we only ever saw one page shape"
> trap this plan exists to fix, and inventing a second one would repeat it.
>
> **The fixture is committed to a PUBLIC repo.** Player names are public information and stay.
> **Replace every other manager's name and team name with a placeholder** before committing,
> and keep enough rows to cover: a healthy player, a player carrying an injury designation, a
> DST row, and a K row.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cbs_roster.py`:

```python
import pytest

from sffl.cbs_roster import parse_roster

FIXTURE = "tests/fixtures/cbs_team_page.txt"


def test_the_real_captured_page_yields_a_full_roster():
    names = parse_roster(FIXTURE)
    # The league starts 8 and rosters more; anything under 8 means the parser
    # matched a fragment of the page rather than the roster table.
    assert len(names) >= 8


def test_names_are_unique_and_in_page_order():
    names = parse_roster(FIXTURE)
    assert len(names) == len(set(names))


def test_an_empty_page_raises_rather_than_returning_an_empty_roster(tmp_path):
    # An empty roster is indistinguishable downstream from "Jeff owns nobody",
    # which optimises to an empty lineup and ranks every free agent as a claim
    # - the same failure `_cmd_week`'s empty-roster guard already raises for.
    p = tmp_path / "empty.txt"
    p.write_text("Nothing here at all\n")
    with pytest.raises(ValueError) as exc:
        parse_roster(str(p))
    assert "0 player" in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_cbs_roster.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sffl.cbs_roster'`

- [ ] **Step 3: Write the implementation**

Create `src/sffl/cbs_roster.py`. **Adjust `_ROW` to the real captured layout** — the shape
below matches the projections page's identity prefix, which the team page is expected to share,
but the fixture is the authority. Do not loosen it into a catch-all; a roster parsed loosely is
how a page-furniture line becomes a phantom player.

```python
"""Parse Jeff's CBS team page into the list of players he rosters.

NO NETWORK I/O - `sffl.capture` fetches, this parses, exactly as
`cbs_weekly.parse` does. That keeps every test a fixture test.

WHY AN EMPTY RESULT RAISES. Downstream, an empty roster is not an error state -
it is a perfectly valid input meaning "Jeff owns nobody", which optimises to an
empty lineup and ranks every free agent as a worthwhile claim. `_cmd_week`
already raises rather than accept that from a roster FILE; a captured roster
must clear the same bar.
"""

import re

# "Christian McCaffrey RB • SF" - the same identity shape the weekly
# projections page uses, with an optional injury designation. Anchored at both
# ends against the position and the bullet so page furniture cannot match.
_ROW = re.compile(
    r"^\s*(?P<name>[A-Za-z][A-Za-z.'\- ]+?)\s+"
    r"(?:(?P<status1>Q|D|O|IR|PUP|SUSP|NA)\s+)?"
    r"(?P<pos>TQB|QB|RB|WR|TE|K|DST)\s+"
    r"(?:(?P<status2>Q|D|O|IR|PUP|SUSP|NA)\s+)?"
    r"[•\-]\s+"
    r"(?P<team>[A-Z]{2,3})\b")


def parse_roster(path):
    """Player display names from a captured CBS team page, in page order."""
    names = []
    seen = set()
    with open(path) as fh:
        for raw_line in fh:
            m = _ROW.match(raw_line.rstrip("\n"))
            if not m:
                continue
            name = m.group("name").strip()
            if name in seen:
                continue
            seen.add(name)
            names.append(name)

    if not names:
        raise ValueError(
            "%s: 0 player rows matched - refusing to return an empty roster. "
            "Downstream an empty roster is a VALID input meaning 'Jeff owns "
            "nobody': it optimises to an empty lineup and ranks every free "
            "agent as a claim. Either the capture is a login page (see "
            "sffl.capture.SessionExpired) or CBS changed the team-page "
            "layout." % path)
    return names
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_cbs_roster.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/sffl/cbs_roster.py tests/test_cbs_roster.py tests/fixtures/cbs_team_page.txt
git commit -m "feat(roster): parse the captured CBS team page

Replaces the hand-maintained roster file. Built against a real captured
page rather than a constructed one - the pre-season-only projections
fixture is exactly the blind spot this work exists to close.

An empty parse raises. Downstream an empty roster is not an error but a
valid input meaning 'Jeff owns nobody', which optimises to an empty
lineup and ranks every free agent as a claim.

Other managers' names are placeholdered in the committed fixture; this
repo is public."
```

---

## Task 3: Parser hardening

**Files:**
- Modify: `sources/cbs-weekly.yaml`
- Modify: `src/sffl/cbs_weekly.py:34-66` (the `_LINE` regex and `classify_avail`)
- Modify: `tests/test_cbs_weekly.py` (create if absent)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `cbs_weekly.build_line_re(owner_codes)` → compiled regex
  - `cbs_weekly.classify_avail(avail, owner_codes)` → `"available"` | `"owned"` | `None`
    — **signature change**, `owner_codes` is a new required second parameter.
  - `_LINE` group `status` is available via `m.group("status1") or m.group("status2") or ""`.

**The bug this must not reintroduce (F4).** Widening `avail` to accept short mixed-case tokens
would make `DJ Moore WR • CHI ...` — a real row that is simply missing its status token —
match with `avail="DJ"` and `name="Moore"`, silently attributing a real player's stats to a
fabricated one. So `avail` is **not** widened into a pattern. The league's manager
abbreviations are a small, knowable, fixed set, so they are **enumerated in the profile YAML**
and the regex is built from that list. Any token outside the list still fails to match and is
still caught loudly by the unmatched-line count. This fixes 2-letter, mixed-case, and
digit-bearing abbreviations completely, with no guessing.

- [ ] **Step 1: Add the owner codes to the profile**

Edit `sources/cbs-weekly.yaml`, appending at the top level (sibling of `groups:`):

```yaml
# The league's twelve manager abbreviations, exactly as CBS prints them in the
# leftmost column of the ALL PLAYERS view.
#
# ENUMERATED, NOT PATTERN-MATCHED, ON PURPOSE. A pattern loose enough to accept
# a two-letter abbreviation ("JM") also accepts the two-initial first name of a
# row that is MISSING its status token - "DJ Moore WR - CHI" parses as
# avail="DJ", name="Moore", quietly filing a real player's stats under a
# fabricated one. That is F4, and it was found in real data. A closed list
# cannot do that: an unknown token fails to match and is reported by the
# unmatched-line count instead.
#
# WHEN A MANAGER JOINS OR LEAVES, ADD OR REMOVE THEIR CODE HERE. The failure if
# you forget is loud - the page is refused and the offending line is named.
owner_codes:
  - REPLACE_ME
```

> **The list above is a placeholder and the implementer must fill it in** from the real
> captured page: `awk '{print $1}' data/captures/projections.txt | sort -u`, keeping the tokens
> that are manager abbreviations and discarding `FA` and `W`. If no in-season page with owner
> codes is available yet, leave a single-entry list containing the one code you can verify and
> say so in the report — do NOT invent twelve plausible abbreviations.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_cbs_weekly.py`:

```python
import pytest

from sffl.cbs_weekly import build_line_re, classify_avail

CODES = ["JM", "Bp3", "SMITH"]


def test_a_two_letter_manager_code_parses():
    m = build_line_re(CODES).match("JM Nick Chubb RB • CLE @PIT 1 2 3")
    assert m is not None
    assert m.group("avail") == "JM"
    assert m.group("name") == "Nick Chubb"


def test_a_mixed_case_code_with_a_digit_parses():
    m = build_line_re(CODES).match("Bp3 Nick Chubb RB • CLE @PIT 1 2 3")
    assert m is not None
    assert m.group("avail") == "Bp3"


def test_a_row_missing_its_status_token_still_does_not_match():
    # F4. "DJ" is a first name here, not a manager code. It is not in
    # CODES, so the line must fail rather than parse as avail="DJ",
    # name="Moore" - which files a real player's stats under a fake one.
    assert build_line_re(CODES).match("DJ Moore WR • CHI @GB 1 2 3") is None


def test_an_injury_tag_after_the_position_is_captured_not_swallowed():
    m = build_line_re(CODES).match("FA Nick Chubb RB Q • CLE @PIT 1 2 3")
    assert m is not None
    assert m.group("name") == "Nick Chubb"
    assert (m.group("status1") or m.group("status2")) == "Q"


def test_an_injury_tag_after_the_name_is_captured_not_swallowed():
    m = build_line_re(CODES).match("FA Nick Chubb Q RB • CLE @PIT 1 2 3")
    assert m is not None
    # The bug: the greedy name group used to absorb this, renaming the
    # player to "Nick Chubb Q" - who matches nothing downstream.
    assert m.group("name") == "Nick Chubb"
    assert (m.group("status1") or m.group("status2")) == "Q"


@pytest.mark.parametrize("tag", ["Q", "D", "O", "IR", "PUP", "SUSP", "NA"])
def test_every_standard_designation_is_recognized(tag):
    m = build_line_re(CODES).match(
        "FA Nick Chubb %s RB • CLE @PIT 1 2 3" % tag)
    assert m is not None
    assert (m.group("status1") or m.group("status2")) == tag


def test_an_undesignated_row_still_parses_with_no_status():
    m = build_line_re(CODES).match("FA Nick Chubb RB • CLE @PIT 1 2 3")
    assert m is not None
    assert (m.group("status1") or m.group("status2")) is None


def test_waiver_and_free_agent_are_available():
    assert classify_avail("FA", CODES) == "available"
    assert classify_avail("W", CODES) == "available"
    assert classify_avail("W (9/16)", CODES) == "available"


def test_a_configured_manager_code_is_owned():
    assert classify_avail("JM", CODES) == "owned"
    assert classify_avail("Bp3", CODES) == "owned"


def test_an_unconfigured_code_is_refused_not_guessed():
    # Must not fall back to "owned". An unknown token means the config is
    # stale, and guessing either way silently mis-ranks the waiver board.
    assert classify_avail("ZZZ", CODES) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_cbs_weekly.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_line_re'`

- [ ] **Step 4: Write the implementation**

In `src/sffl/cbs_weekly.py`, replace the `_LINE` block and `classify_avail` (lines 34–66) with:

```python
# The standard CBS injury designations, longest first so "IR" cannot be
# matched as "I" and "SUSP" cannot be matched as "S".
_STATUS_TAGS = ("SUSP", "PUP", "IR", "NA", "Q", "D", "O")

_AVAIL_WAIVER = re.compile(r"^W(\s*\(.*\))?$")


def build_line_re(owner_codes):
    """The row regex, with the league's manager abbreviations built into it.

    WHY THE OWNER CODES ARE ENUMERATED RATHER THAN MATCHED BY SHAPE. The
    previous pattern required a bare token to be "FA", "W", or at least THREE
    letters, which refused every real two-letter manager abbreviation and so
    refused the whole page. The obvious fix - accept two-letter tokens too -
    reintroduces F4: "DJ Moore WR - CHI", a genuine row missing its status
    token, then parses as avail="DJ", name="Moore", filing a real player's
    stats under a fabricated one while the real DJ Moore prints as "no
    projection". A closed list from the profile is the only widening that
    cannot do that - an unknown token fails to match and is reported by the
    unmatched-line count.

    The injury designation is captured in BOTH observed positions (after the
    name and after the position) because the page has been seen to put it in
    either. It is optional: a healthy row has neither group.
    """
    tags = "|".join(_STATUS_TAGS)
    codes = "|".join(re.escape(c) for c in sorted(owner_codes, key=len,
                                                  reverse=True))
    alternatives = [r"[A-Z]+\s*\([^)]*\)", "FA", "W"]
    if codes:
        alternatives.append(codes)
    return re.compile(
        r"^\s*(?P<avail>" + "|".join(alternatives) + r")\s+"
        r"(?P<name>.+?)\s+"
        r"(?:(?P<status1>" + tags + r")\s+)?"
        r"(?P<pos>TQB|QB|RB|WR|TE|K|DST)\s+"
        r"(?:(?P<status2>" + tags + r")\s+)?"
        r"[•\-]\s+"
        r"(?P<team>[A-Z]{2,3})\s+"
        r"(?P<rest>.+)$")


def classify_avail(avail, owner_codes):
    """Sort a raw `avail` token into "available", "owned", or None.

    "available" covers a genuine free agent ("FA") or a waiver-claimable
    player ("W" or "W (9/16)") - both fair game for a waiver ranking.
    "owned" is a token in the league's CONFIGURED manager list: that player is
    on another manager's roster, and F3 is exactly the bug of ranking that
    case as if it were claimable.

    Anything else returns None rather than guessing - most likely a manager
    code missing from `owner_codes` in the profile. The caller must refuse to
    rank it, not assume either bucket; see F3's "do not guess" requirement.
    """
    if avail == "FA" or _AVAIL_WAIVER.match(avail):
        return "available"
    if avail in owner_codes:
        return "owned"
    return None
```

- [ ] **Step 5: Thread the codes through `parse`**

In `src/sffl/cbs_weekly.py`, inside `parse`, after `groups = _load_groups(profile_path)` add
the profile read and build the regex, then use it in place of `_LINE`:

```python
    owner_codes = _load_owner_codes(profile_path)
    line_re = build_line_re(owner_codes)
```

Replace `m = _LINE.match(line)` with `m = line_re.match(line)`.

Add beside `_load_groups`:

```python
def _load_owner_codes(profile_path):
    with open(profile_path) as fh:
        raw = yaml.safe_load(fh) or {}
    return list(raw.get("owner_codes", []))
```

Set `status` on the constructed `PlayerProjection` — the field lands in Task 4, so for now
capture it into a local and leave the constructor unchanged:

```python
            status = m.group("status1") or m.group("status2") or ""
```

- [ ] **Step 6: Update `classify_avail`'s caller**

In `src/sffl/cli.py:_cmd_week`, the call `classify_avail(p.avail)` now needs the codes. Add
near the top of `_cmd_week`, after the other `cbs_weekly` imports:

```python
    from sffl.cbs_weekly import _load_owner_codes
    owner_codes = _load_owner_codes(args.profile)
```

and change the call site to `classify_avail(p.avail, owner_codes)`.

If `_cmd_week` has no `args.profile`, use `sffl.cbs_weekly.DEFAULT_PROFILE`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_cbs_weekly.py -v`
Expected: all pass

- [ ] **Step 8: Run the full suite — the existing fixture must still parse**

Run: `./.venv/bin/pytest -q`
Expected: all pass. The committed `cbs_weekly_rbwrte.txt` uses only `W` tokens, which the
`W` alternative still matches, so it must be unaffected.

- [ ] **Step 9: Commit**

```bash
git add sources/cbs-weekly.yaml src/sffl/cbs_weekly.py src/sffl/cli.py tests/test_cbs_weekly.py
git commit -m "fix(parser): accept real in-season rows without reopening F4

The parser had only ever seen a pre-season page: no byes, no injury
designations, no rows owned by other managers. Three failures were
measured against the real regex - a two-letter manager code refused the
whole page, an injury tag before the bullet refused the whole page, and
an injury tag after the name silently renamed the player.

Manager codes are now ENUMERATED in the profile rather than matched by
shape. Widening the pattern to accept two-letter tokens would have
reintroduced F4, where 'DJ Moore WR - CHI' - a row missing its status
token - parses as avail=DJ, name=Moore and files a real player's stats
under a fabricated one. A closed list cannot do that; an unknown code
fails to match and is named by the unmatched-line count.

Injury designations are captured in both observed positions. expect_tokens
is untouched: the designation sits before the bullet, so the stat block's
width is unchanged, and the width guard is what catches a column shift."
```

---

## Task 4: Injury status reaches the lineup

**Files:**
- Modify: `src/sffl/schema.py:8-24`
- Modify: `src/sffl/cbs_weekly.py` (pass `status` into `PlayerProjection`)
- Modify: `src/sffl/cli.py:_cmd_week`
- Modify: `tests/test_cbs_weekly.py`
- Create: `tests/test_lineup_status.py`

**Interfaces:**
- Consumes: `build_line_re` / `classify_avail(avail, owner_codes)` from Task 3.
- Produces:
  - `PlayerProjection.status` → `str`, `""` when absent.
  - `cbs_weekly.OUT_STATUSES` → `frozenset({"O", "IR", "PUP", "SUSP"})`
  - `cbs_weekly.is_out(status)` → `bool`

**The correctness bug.** Today's optimizer scores a player's projection and starts him whether
or not he is playing. A player designated Out scores zero. `Q` and `D` are **flagged, never
excluded** — a questionable player usually plays, and silently benching him is the worse error.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lineup_status.py`:

```python
import pytest

from sffl.cbs_weekly import OUT_STATUSES, is_out


@pytest.mark.parametrize("tag", ["O", "IR", "PUP", "SUSP"])
def test_a_player_who_will_not_play_is_out(tag):
    assert is_out(tag) is True


@pytest.mark.parametrize("tag", ["Q", "D", "NA", "", "  "])
def test_a_player_who_might_play_is_not_out(tag):
    # Q and D usually play. Silently benching them would be a worse error
    # than starting them, so they are flagged elsewhere, never excluded here.
    assert is_out(tag) is False


def test_out_statuses_is_exactly_the_four_that_mean_will_not_play():
    assert OUT_STATUSES == frozenset({"O", "IR", "PUP", "SUSP"})


def test_status_is_case_and_whitespace_insensitive():
    assert is_out(" o ") is True
    assert is_out("ir") is True
```

Add to `tests/test_cbs_weekly.py`:

```python
def test_status_reaches_the_projection_record(tmp_path):
    from sffl.cbs_weekly import parse
    page = tmp_path / "p.txt"
    # 17 tokens after the team code, matching sources/cbs-weekly.yaml.
    stats = " ".join(["1"] * 17)
    page.write_text(
        "FA Nick Chubb O RB • CLE %s\n"
        "FA Bijan Robinson RB • ATL %s\n" % (stats, stats))
    rows = dict((p.name, p) for p in parse(str(page), group="RB-WR-TE", week=1))
    assert rows["Nick Chubb"].status == "O"
    assert rows["Bijan Robinson"].status == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_lineup_status.py tests/test_cbs_weekly.py -v`
Expected: FAIL — `ImportError: cannot import name 'OUT_STATUSES'`

- [ ] **Step 3: Add the field to the schema**

In `src/sffl/schema.py`, add after the `avail` field (keep it last so no positional call
breaks):

```python
    status: str = ""                # raw injury designation from the source's
                                    # page (Q/D/O/IR/PUP/SUSP/NA), "" when the
                                    # player carries none - see sffl.cbs_weekly
```

- [ ] **Step 4: Add the predicate and pass the value through**

In `src/sffl/cbs_weekly.py`, add beside `_STATUS_TAGS`:

```python
# The designations that mean the player will not take the field. A player who
# does not play scores zero, so starting one is a pure loss - this is a
# correctness gate, not a preference.
#
# "Q" AND "D" ARE DELIBERATELY ABSENT. A questionable player usually plays.
# Benching him on the strength of a Q would lose more points across a season
# than occasionally starting one who sits, and it would do it silently.
OUT_STATUSES = frozenset({"O", "IR", "PUP", "SUSP"})


def is_out(status):
    """True if this designation means the player will not play."""
    return (status or "").strip().upper() in OUT_STATUSES
```

In `parse`, pass the captured local into the record:

```python
                status=status,
```

- [ ] **Step 5: Exclude Out players in `_cmd_week`**

In `src/sffl/cli.py:_cmd_week`, immediately before `roster = [cand(by_key[k]) for k in owned if k in by_key]`:

```python
    # A player designated Out will not take the field and scores zero, so the
    # optimiser would otherwise start him and report a lineup total that
    # cannot happen. Excluded here - and NAMED, never dropped silently, the
    # same treatment `missing` and `not_evaluated` already get, because a
    # player who quietly vanishes from the board reads as "no longer on your
    # roster" rather than as "ruled out."
    from sffl.cbs_weekly import is_out
    sidelined = sorted((by_key[k].name, by_key[k].status)
                       for k in owned if k in by_key and is_out(by_key[k].status))
    for name, status in sidelined:
        print("  %s is %s - excluded from the lineup, he will not play"
              % (name, status))

    roster = [cand(by_key[k]) for k in owned
              if k in by_key and not is_out(by_key[k].status)]
```

And immediately after that, flag the questionable ones:

```python
    # Flagged, NOT excluded - see cbs_weekly.OUT_STATUSES.
    questionable = sorted((by_key[k].name, by_key[k].status)
                          for k in owned
                          if k in by_key and by_key[k].status in ("Q", "D"))
    for name, status in questionable:
        print("  %s is %s - STARTED anyway; check his status before kickoff"
              % (name, status))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_lineup_status.py tests/test_cbs_weekly.py -v`
Expected: all pass

- [ ] **Step 7: Run the full suite**

Run: `./.venv/bin/pytest -q`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add src/sffl/schema.py src/sffl/cbs_weekly.py src/sffl/cli.py tests/test_lineup_status.py tests/test_cbs_weekly.py
git commit -m "fix(lineup): never start a player who is ruled out

The optimiser scored a player's projection and started him whether or not
he was playing, so a roster carrying an O or IR designation produced a
lineup total that could not happen.

O/IR/PUP/SUSP are excluded and NAMED - a player who quietly vanishes from
the board reads as 'no longer on your roster' rather than 'ruled out',
which is the same reasoning behind the existing missing-projection notice.

Q and D are flagged and STARTED. A questionable player usually plays, and
silently benching him would lose more across a season than occasionally
starting one who sits."
```

---

## Task 5: Fetch injuries through StatsDeck

**Files:**
- Create: `src/sffl/injuries.py`
- Create: `ops/fetch_injuries.sh`
- Create: `tests/test_injuries.py`
- Create: `tests/fixtures/statsdeck_injuries.json`

**Interfaces:**
- Consumes: `cbs_roster.parse_roster` (Task 2) supplies the names to filter to.
- Produces:
  - `injuries.Report` — `namedtuple("Report", "name team status practice reported_date detail source")`
  - `injuries.load(path)` → `list` of `Report`
  - `injuries.for_roster(reports, roster_names)` → `list` of `Report`, roster order

**Why `claude -p` writes JSON and not prose.** StatsDeck is MCP-only, so Claude is the only
transport to `get_injuries`. That makes Claude a *data fetcher* here, nothing more: it writes
raw JSON to a file, and every word that reaches Jeff's phone is composed by the pure Python in
Task 6. A model that both fetches and writes the message is a model that can quietly reword a
designation.

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/statsdeck_injuries.json`. Field names must match what `get_injuries`
actually returns — **the implementer must confirm against one real call and adjust both the
fixture and `injuries.load` together** if they differ.

```json
{
  "injuries": [
    {"player": "Ja'Marr Chase", "team": "CIN", "status": "Questionable",
     "practice": "Limited", "reported_date": "2026-09-05",
     "detail": "hyperextended knee", "source": "official"},
    {"player": "Nick Chubb", "team": "CLE", "status": "Out",
     "practice": "DNP", "reported_date": "2026-09-05",
     "detail": "foot", "source": "official"},
    {"player": "Ja'Marr Chase", "team": "CIN", "status": "",
     "practice": "", "reported_date": "2026-09-06",
     "detail": "expected to play per beat writer", "source": "intel"}
  ]
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_injuries.py`:

```python
from sffl.injuries import Report, for_roster, load

FIXTURE = "tests/fixtures/statsdeck_injuries.json"


def test_every_row_loads_with_its_reported_date():
    reports = load(FIXTURE)
    assert len(reports) == 3
    # reported_date is load-bearing: the feed carries non-injury designations
    # (holdouts, rest days) and a status with no date cannot be judged.
    assert all(r.reported_date for r in reports)


def test_rows_are_filtered_to_the_roster_and_nobody_else():
    reports = load(FIXTURE)
    mine = for_roster(reports, ["Ja'Marr Chase"])
    assert {r.name for r in mine} == {"Ja'Marr Chase"}
    assert len(mine) == 2  # the official row and the intel row


def test_a_roster_name_with_different_punctuation_still_matches():
    # "JaMarr Chase" from one page must match "Ja'Marr Chase" from another.
    reports = load(FIXTURE)
    assert len(for_roster(reports, ["JaMarr Chase"])) == 2


def test_a_clean_roster_yields_no_rows_rather_than_an_error():
    reports = load(FIXTURE)
    assert for_roster(reports, ["Bijan Robinson"]) == []


def test_official_and_intel_are_kept_distinct():
    # The official report is the record; intel supplements and never
    # overrides. Collapsing them would let a beat writer outrank the report.
    mine = for_roster(load(FIXTURE), ["Ja'Marr Chase"])
    assert {r.source for r in mine} == {"official", "intel"}


def test_a_missing_file_raises_rather_than_returning_nothing(tmp_path):
    import pytest
    with pytest.raises(IOError):
        load(str(tmp_path / "nope.json"))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_injuries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sffl.injuries'`

- [ ] **Step 4: Write the implementation**

Create `src/sffl/injuries.py`:

```python
"""Normalize StatsDeck's injury feed into records this project can render.

PURE. `ops/fetch_injuries.sh` performs the one MCP call and writes raw JSON;
this module reads that file. No test touches StatsDeck.

WHAT THIS MODULE MUST NOT DO. StatsDeck is connected to a DIFFERENT league
(Yahoo, half-PPR), so only its league-agnostic NFL data is safe to use here -
injury status, practice participation, news. Its fantasy points are computed
under the wrong rules and are never carried across. Nothing below reads a
points field, and nothing should be added that does.

`source` IS LOAD-BEARING. The official injury report is the record; intel
supplements it and never overrides it. The two are kept as separate rows so
the renderer can show both with their dates when they disagree, rather than
adjudicating between them.
"""

import json
from collections import namedtuple

from sffl.identity import normalize_name

Report = namedtuple("Report", "name team status practice reported_date detail source")


def load(path):
    """Every row in a saved `get_injuries` payload, as Report tuples."""
    with open(path) as fh:
        raw = json.load(fh)
    rows = raw.get("injuries", raw if isinstance(raw, list) else [])
    out = []
    for row in rows:
        out.append(Report(
            name=(row.get("player") or row.get("name") or "").strip(),
            team=(row.get("team") or "").strip(),
            status=(row.get("status") or "").strip(),
            practice=(row.get("practice") or "").strip(),
            reported_date=(row.get("reported_date") or "").strip(),
            detail=(row.get("detail") or row.get("note") or "").strip(),
            source=(row.get("source") or "official").strip(),
        ))
    return out


def for_roster(reports, roster_names):
    """The rows naming a player on `roster_names`, in roster order.

    Matched on `normalize_name` because the two pages disagree about
    punctuation - "Ja'Marr Chase" on one, "JaMarr Chase" on the other - and a
    literal comparison would silently report a clean bill of health for an
    injured starter.
    """
    by_key = {}
    for r in reports:
        by_key.setdefault(normalize_name(r.name), []).append(r)
    out = []
    for name in roster_names:
        out.extend(by_key.get(normalize_name(name), []))
    return out
```

- [ ] **Step 5: Write the fetch script**

Create `ops/fetch_injuries.sh` (and `chmod +x` it):

```bash
#!/bin/bash
# The ONE StatsDeck call in this pipeline.
#
# Claude is a transport here, not an author: it writes raw JSON and composes
# nothing. Every word that reaches the phone is built by src/sffl/alert.py,
# which is pure and unit-tested. A model that both fetched and phrased the
# message could quietly reword a designation, and nothing downstream would
# catch it.
#
# Usage: ops/fetch_injuries.sh <output.json>
set -euo pipefail

OUT="${1:?usage: fetch_injuries.sh <output.json>}"

claude -p "Call the StatsDeck get_injuries tool with no player filter. Write \
its result to ${OUT} as a single JSON object of the form {\"injuries\": [...]}, \
one array entry per reported player, each with the keys: player, team, status, \
practice, reported_date, detail, source. Set source to \"official\" for rows \
from the official injury report and \"intel\" for rows from the news/intel \
feed. Do not summarise, rank, interpret, or drop any row. Do not include any \
fantasy points field. Output nothing to stdout except the word DONE." \
  --allowedTools "mcp__claude_ai_StatsDeck__get_injuries,Write" \
  >/dev/null

test -s "$OUT" || { echo "fetch_injuries: ${OUT} was not written" >&2; exit 1; }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_injuries.py -v`
Expected: 6 passed

- [ ] **Step 7: Verify the fetch script against the real feed once**

Run: `ops/fetch_injuries.sh /tmp/inj.json && ./.venv/bin/python -c "
import sys; sys.path.insert(0,'src')
from sffl.injuries import load
r = load('/tmp/inj.json'); print(len(r), 'rows'); print(r[0])"`

Expected: a non-zero row count and a well-formed `Report`. **If the real keys differ from the
fixture, fix the fixture AND `load` together, and say so in the report.** Do not leave the
fixture describing a shape the feed does not produce.

- [ ] **Step 8: Commit**

```bash
git add src/sffl/injuries.py ops/fetch_injuries.sh tests/test_injuries.py tests/fixtures/statsdeck_injuries.json
git commit -m "feat(injuries): normalize the StatsDeck feed, keep official and intel apart

StatsDeck is MCP-only, so claude -p is the transport - but only the
transport. It writes raw JSON and composes nothing; every word that
reaches the phone is built by pure Python. A model that both fetched and
phrased the message could reword a designation unnoticed.

Official and intel rows stay separate so the renderer can show both with
their dates when they disagree. The official report is the record; intel
supplements and never overrides.

Names are matched on normalize_name: the two pages disagree about
punctuation, and a literal comparison would report a clean bill of health
for an injured starter."
```

---

## Task 6: Compose the digest

**Files:**
- Create: `src/sffl/alert.py`
- Create: `tests/test_alert.py`

**Interfaces:**
- Consumes: `injuries.Report` (Task 5), `lineup.LineupResult` and `lineup.Candidate`
  (existing `src/sffl/lineup.py`).
- Produces:
  - `alert.compose(kind, roster_age_days, reports, lineup_result, sidelined, capture_error=None)` → `str`
  - `alert.STALE_ROSTER_DAYS` → `int` (10)

**Rules this function enforces.** Friday leads with practice participation and reads as "here
is what to plan around"; Sunday leads with official status and reads as "here is what changed."
The digest **always** produces text, including when there is no news — an absent message must
mean a dead job, not a quiet week. When a capture failed, the message says so at the top and
does **not** present a roster it could not verify.

- [ ] **Step 1: Write the failing test**

Create `tests/test_alert.py`:

```python
import pytest

from sffl.alert import STALE_ROSTER_DAYS, compose
from sffl.injuries import Report
from sffl.lineup import Candidate, LineupResult

CHASE_OFFICIAL = Report("Ja'Marr Chase", "CIN", "Questionable", "Limited",
                        "2026-09-05", "hyperextended knee", "official")
CHASE_INTEL = Report("Ja'Marr Chase", "CIN", "", "", "2026-09-06",
                     "expected to play per beat writer", "intel")
CHUBB_OUT = Report("Nick Chubb", "CLE", "Out", "DNP", "2026-09-05",
                   "foot", "official")

LINEUP = LineupResult(
    slots=[("RB", Candidate("Bijan Robinson", "RB", 18.0)),
           ("WR/TE", Candidate("Ja'Marr Chase", "WR", 16.5))],
    total=34.5)


def test_a_quiet_week_still_produces_a_message():
    # An absent push must mean a DEAD JOB, never a quiet week. If this
    # function could return "" the two would be indistinguishable.
    msg = compose("friday", 2, [], LINEUP, [])
    assert msg.strip()
    assert "no" in msg.lower()


def test_friday_leads_with_practice_participation():
    msg = compose("friday", 2, [CHASE_OFFICIAL], LINEUP, [])
    assert "Limited" in msg
    assert msg.lower().index("practice") < msg.lower().index("lineup")


def test_sunday_leads_with_official_status():
    msg = compose("sunday", 2, [CHUBB_OUT], LINEUP, [])
    assert "Out" in msg
    assert "Nick Chubb" in msg


def test_the_message_names_which_job_produced_it():
    assert "Friday" in compose("friday", 2, [], LINEUP, [])
    assert "Sunday" in compose("sunday", 2, [], LINEUP, [])


def test_every_intel_line_carries_its_reported_date():
    msg = compose("friday", 2, [CHASE_INTEL], LINEUP, [])
    assert "2026-09-06" in msg


def test_official_and_intel_are_both_shown_when_they_disagree():
    # The alert quotes; it does not adjudicate.
    msg = compose("friday", 2, [CHASE_OFFICIAL, CHASE_INTEL], LINEUP, [])
    assert "hyperextended knee" in msg
    assert "beat writer" in msg
    assert "2026-09-05" in msg and "2026-09-06" in msg


def test_a_stale_roster_says_so_loudly():
    msg = compose("friday", STALE_ROSTER_DAYS + 1, [], LINEUP, [])
    assert "STALE" in msg.upper()


def test_a_fresh_roster_still_states_its_age():
    # Visible staleness beats invisible staleness - the age prints every time.
    assert "2 day" in compose("friday", 2, [], LINEUP, [])


def test_a_capture_failure_replaces_the_roster_report_entirely():
    msg = compose("sunday", 2, [], LINEUP, [], capture_error="session expired")
    assert "session expired" in msg
    # Must NOT present a lineup it could not verify.
    assert "Bijan Robinson" not in msg


def test_sidelined_players_are_named_not_silently_dropped():
    msg = compose("sunday", 2, [CHUBB_OUT], LINEUP, [("Nick Chubb", "O")])
    assert "Nick Chubb" in msg
    assert "excluded" in msg.lower()


def test_no_statsdeck_fantasy_points_can_leak_in():
    # StatsDeck is wired to a half-PPR Yahoo league. Its points are wrong
    # here by construction, so nothing in the payload should reach the text.
    msg = compose("friday", 2, [CHASE_OFFICIAL, CHUBB_OUT], LINEUP, [])
    assert "PPR" not in msg.upper()


def test_an_unknown_kind_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        compose("tuesday", 2, [], LINEUP, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_alert.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sffl.alert'`

- [ ] **Step 3: Write the implementation**

Create `src/sffl/alert.py`:

```python
"""Compose the push message. PURE - no I/O, no network, no clock.

EVERY WORD THE PHONE SHOWS IS BUILT HERE, so this is the piece that must be
exhaustively tested. `claude -p` fetches the injury feed but writes none of
this text; see ops/fetch_injuries.sh.

WHY A QUIET WEEK STILL SENDS. If this returned "" when there was no news, a
silent Sunday would be indistinguishable from a launchd job that died in
August. The digest always has a body, so an absent push means exactly one
thing: the job is broken.

WHY A FAILED CAPTURE SUPPRESSES THE LINEUP. An expired CBS session returns a
well-formed login page, which parses to an empty roster - a valid-looking
input meaning "Jeff owns nobody". Printing a lineup derived from an
unverified capture is how a confident, entirely wrong start/sit reaches the
phone ninety minutes before kickoff.
"""

# Past this many days, the roster file's age is called out as a problem rather
# than merely stated. Visible staleness beats invisible staleness.
STALE_ROSTER_DAYS = 10

_KINDS = {
    "friday": ("Friday practice report",
               "What to plan around - two days left to make a claim."),
    "sunday": ("Sunday inactives",
               "What changed since Friday. Kickoff is close."),
}


def _roster_age_line(days):
    if days > STALE_ROSTER_DAYS:
        return ("!! STALE ROSTER: captured %d days ago (over %d). "
                "The lineup below may be wrong." % (days, STALE_ROSTER_DAYS))
    return "Roster captured %d day%s ago." % (days, "" if days == 1 else "s")


def _report_line(r):
    """One feed row. `source` and `reported_date` always travel with it."""
    bits = []
    if r.status:
        bits.append(r.status)
    if r.practice:
        bits.append("practice: %s" % r.practice)
    if r.detail:
        bits.append(r.detail)
    return "  - %s (%s) %s [%s %s]" % (
        r.name, r.team or "?", " / ".join(bits) or "no detail",
        r.source, r.reported_date or "undated")


def compose(kind, roster_age_days, reports, lineup_result, sidelined,
            capture_error=None):
    """The full digest text for one run.

    `kind` is "friday" or "sunday". `sidelined` is a list of (name, status)
    for roster players excluded from the lineup.
    """
    if kind not in _KINDS:
        raise ValueError(
            "unknown alert kind %r - expected one of %s. Guessing would send "
            "a message whose heading contradicts its schedule."
            % (kind, sorted(_KINDS)))
    title, subtitle = _KINDS[kind]

    lines = [title, subtitle, ""]

    if capture_error:
        lines.append("!! CAPTURE FAILED: %s" % capture_error)
        lines.append("")
        lines.append("No roster could be read, so no lineup is shown below - "
                     "an unverified capture parses to an EMPTY roster, and a "
                     "lineup built from that would be confidently wrong.")
        lines.append("Fix: ./.venv/bin/python ops/cbs_login.py")
        return "\n".join(lines)

    lines.append(_roster_age_line(roster_age_days))
    lines.append("")

    official = [r for r in reports if r.source == "official"]
    intel = [r for r in reports if r.source != "official"]

    # Friday leads with practice participation, Sunday with official status.
    # A Sunday alert that just repeats Friday trains its reader to ignore it.
    if kind == "friday":
        lines.append("PRACTICE / STATUS on your roster:")
    else:
        lines.append("OFFICIAL STATUS on your roster:")
    if official:
        lines.extend(_report_line(r) for r in official)
    else:
        lines.append("  no designations on your roster.")
    lines.append("")

    # Shown SEPARATELY and never merged into the official block: the official
    # report is the record, intel supplements it and never overrides it. When
    # the two disagree the reader sees both, with dates, and decides.
    lines.append("INTEL (supplements the official report, never overrides it):")
    if intel:
        lines.extend(_report_line(r) for r in intel)
    else:
        lines.append("  nothing new.")
    lines.append("")

    if sidelined:
        lines.append("EXCLUDED from the lineup - will not play:")
        lines.extend("  - %s (%s)" % (n, s) for n, s in sidelined)
        lines.append("")

    lines.append("BEST LINEUP (%.2f pts, this league's scoring):" %
                 lineup_result.total)
    for slot, pick in lineup_result.slots:
        lines.append("  %-6s %s" % (slot, pick.name if pick else "-- UNFILLED"))

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_alert.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/sffl/alert.py tests/test_alert.py
git commit -m "feat(alert): compose the digest, purely and testably

Every word the phone shows is built here, so this is the piece that gets
exhaustive tests. Friday leads with practice participation and reads as
'what to plan around'; Sunday leads with official status and reads as
'what changed' - a Sunday alert that repeats Friday trains its reader to
ignore it.

A quiet week still sends. If this returned empty when there was no news, a
silent Sunday would be indistinguishable from a job that died in August.

A failed capture suppresses the lineup entirely rather than printing one
from an unverified page. An expired CBS session returns a well-formed
login page that parses to an empty roster, and a lineup built on that
would be confidently wrong ninety minutes before kickoff."
```

---

## Task 7: Deliver, and wire the orchestrator

**Files:**
- Create: `src/sffl/notify.py`
- Create: `tests/test_notify.py`
- Modify: `src/sffl/cli.py` (new `alert` subcommand)

**Interfaces:**
- Consumes: `capture.capture` / `capture.CaptureError` (1), `cbs_roster.parse_roster` (2),
  `cbs_weekly.parse` / `is_out` (3, 4), `injuries.load` / `injuries.for_roster` (5),
  `alert.compose` (6), `lineup.best_lineup` and `pool.score_week` (existing).
- Produces:
  - `notify.topic_from_keychain(account)` → `str`; raises `RuntimeError` when unset
  - `notify.send(topic, title, body, dry_run=False)` → `bool`
  - CLI: `sffl alert --kind friday|sunday [--dry-run]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_notify.py`. **No test sends anything** — `dry_run` is the seam.

```python
import pytest

from sffl import notify


def test_dry_run_sends_nothing_and_reports_it():
    assert notify.send("topic", "t", "body", dry_run=True) is False


def test_an_empty_topic_raises_rather_than_posting_nowhere():
    with pytest.raises(ValueError):
        notify.send("", "t", "body")


def test_an_empty_body_raises():
    # A push with no body is worse than none: it looks like the job ran.
    with pytest.raises(ValueError):
        notify.send("topic", "t", "   ")


def test_a_missing_keychain_entry_names_the_command_that_creates_it():
    with pytest.raises(RuntimeError) as exc:
        notify.topic_from_keychain("sffl-alert-does-not-exist-%s" % id(object()))
    assert "security add-generic-password" in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_notify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sffl.notify'`

- [ ] **Step 3: Write the implementation**

Create `src/sffl/notify.py`:

```python
"""Push one message to ntfy. THE ONLY MODULE THAT POSTS ANYWHERE.

The topic is a secret - anyone holding it can push to Jeff's phone - so it
lives in the login Keychain and never in this public repo. `dry_run` is the
seam every test uses; nothing here is exercised against the network.

`PushNotification` IS DELIBERATELY NOT USED. It requires Remote Control to be
connected, and a launchd job at 4:45pm on a Friday cannot rely on that.
"""

import subprocess
import urllib.request

NTFY_URL = "https://ntfy.sh/%s"
KEYCHAIN_ACCOUNT = "sffl-alert-ntfy-topic"


def topic_from_keychain(account=KEYCHAIN_ACCOUNT):
    """The ntfy topic, read from the login Keychain."""
    try:
        out = subprocess.check_output(
            ["security", "find-generic-password", "-a", account, "-w"],
            stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, OSError):
        raise RuntimeError(
            "no Keychain entry for account %r. The ntfy topic is a secret and "
            "is never committed to this public repo. Create it once with:\n"
            "  security add-generic-password -a %s -s sffl -w <your-topic>"
            % (account, account))
    return out.decode("utf-8").strip()


def send(topic, title, body, dry_run=False):
    """POST `body` to the topic. Returns True if a request was actually made."""
    if not topic:
        raise ValueError("empty ntfy topic - refusing to post nowhere")
    if not body or not body.strip():
        raise ValueError(
            "empty alert body - refusing to send. A push with no body looks "
            "like the job ran correctly, which is worse than no push at all")
    if dry_run:
        return False
    req = urllib.request.Request(
        NTFY_URL % topic, data=body.encode("utf-8"),
        headers={"Title": title, "Priority": "default"})
    urllib.request.urlopen(req, timeout=30).read()
    return True
```

- [ ] **Step 4: Add the `alert` subcommand**

In `src/sffl/cli.py`, add the handler:

```python
def _cmd_alert(args):
    """Capture, score, and push one digest. The launchd entry point.

    ORDER MATTERS. Capture first and let a failure short-circuit everything:
    a stale or unverified page must never reach the composer, because an
    expired CBS session parses to an empty roster that looks exactly like a
    real one with nobody on it.
    """
    import datetime
    import os

    from sffl.alert import compose
    from sffl.capture import CaptureError, capture
    from sffl.cbs_roster import parse_roster
    from sffl.cbs_weekly import is_out
    from sffl.cbs_weekly import parse as parse_weekly
    from sffl.calibrate import load_curves
    from sffl.identity import normalize_name
    from sffl.injuries import for_roster, load as load_injuries
    from sffl.league import load_league
    from sffl.lineup import Candidate, best_lineup
    from sffl.notify import send, topic_from_keychain
    from sffl.pool import score_week

    lg = load_league(args.league)
    urls = {
        "roster": args.team_url,
        "projections": args.projections_url,
    }

    capture_error = None
    roster_names = []
    reports = []
    sidelined = []
    result = None
    age_days = 0

    try:
        written = capture(urls, args.out_dir, args.profile_dir)
        roster_path = os.path.join(args.out_dir, "roster.txt")
        proj_path = os.path.join(args.out_dir, "projections.txt")
        roster_names = parse_roster(roster_path)
        age_days = int(
            (datetime.datetime.now()
             - datetime.datetime.fromtimestamp(os.path.getmtime(roster_path)))
            .total_seconds() // 86400)

        projections = parse_weekly(proj_path, group=args.group,
                                   week=args.week, season=lg.season)
        curves = load_curves(args.curves) if args.curves else None
        by_key = dict((normalize_name(p.name), p) for p in projections)
        owned = [normalize_name(n) for n in roster_names]

        sidelined = sorted((by_key[k].name, by_key[k].status)
                           for k in owned
                           if k in by_key and is_out(by_key[k].status))
        result = best_lineup(lg, [
            Candidate(name=by_key[k].name, pos=by_key[k].pos,
                      points=score_week(lg, by_key[k], curves))
            for k in owned if k in by_key and not is_out(by_key[k].status)])
    except (CaptureError, ValueError) as exc:
        capture_error = str(exc)

    if args.injuries and os.path.exists(args.injuries):
        reports = for_roster(load_injuries(args.injuries), roster_names)

    body = compose(args.kind, age_days, reports, result, sidelined,
                   capture_error=capture_error)
    print(body)

    topic = topic_from_keychain()
    sent = send(topic, "SFFL %s" % args.kind.title(), body,
                dry_run=args.dry_run)
    print("\n[%s]" % ("sent" if sent else "dry run - nothing sent"))
    # A capture failure is still DELIVERED (Jeff must learn the job broke),
    # but the exit code is non-zero so launchd's log records it as a failure.
    return 1 if capture_error else 0
```

And register it beside the other subparsers:

```python
    alr = sub.add_parser("alert", help="capture, score, and push the weekly digest")
    alr.add_argument("--kind", choices=["friday", "sunday"], required=True)
    alr.add_argument("--league", default=DEFAULT_LEAGUE)
    alr.add_argument("--week", type=int, required=True)
    alr.add_argument("--group", default="RB-WR-TE")
    alr.add_argument("--curves")
    alr.add_argument("--injuries", help="JSON written by ops/fetch_injuries.sh")
    alr.add_argument("--team-url", required=True)
    alr.add_argument("--projections-url", required=True)
    alr.add_argument("--out-dir", default="data/captures")
    alr.add_argument("--profile-dir", default="data/browser-profile")
    alr.add_argument("--dry-run", action="store_true")
    alr.set_defaults(func=_cmd_alert)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_notify.py -v`
Expected: 4 passed

- [ ] **Step 6: Run the full suite**

Run: `./.venv/bin/pytest -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/sffl/notify.py tests/test_notify.py src/sffl/cli.py
git commit -m "feat(alert): ntfy delivery and the sffl alert orchestrator

The ntfy topic is a secret - anyone holding it can push to Jeff's phone -
so it lives in the login Keychain, never in this public repo.
PushNotification is not used: it needs Remote Control connected, which a
launchd job at 4:45 on a Friday cannot rely on.

Capture runs first and a failure short-circuits scoring, so an
unverified page never reaches the composer. The alert is still DELIVERED
on failure - Jeff has to learn the job broke - but exits non-zero so
launchd's log records it as one."
```

---

## Task 8: Schedule it, and write the runbook

**Files:**
- Create: `ops/run_alert.sh`
- Create: `ops/com.sffl.alert.friday.plist`
- Create: `ops/com.sffl.alert.sunday.plist`
- Create: `docs/operations/in-season-alerting.md`

**Interfaces:**
- Consumes: `ops/fetch_injuries.sh` (5), `sffl alert` (7), `ops/cbs_login.py` (1).
- Produces: two loaded launchd jobs.

**Schedule (from the spec, decided 2026-08-29).** Friday **16:45** local — practice
participation, the actionable signal, two days of runway. Sunday **11:30** local — official
inactives, ninety minutes before the 1pm window.

> `StartCalendarInterval` uses the machine's **local** time, so these fire at 4:45pm and
> 11:30am ET while the mini is on Eastern time. This is correct as written and needs no TZ
> handling; note it in the runbook so a future reader does not "fix" it.

- [ ] **Step 1: Write the runner**

Create `ops/run_alert.sh` (and `chmod +x`):

```bash
#!/bin/bash
# launchd entry point. One argument: friday | sunday
#
# Runs from the repo root regardless of how launchd invokes it, because
# every default path in `sffl alert` is repo-relative.
set -uo pipefail

KIND="${1:?usage: run_alert.sh friday|sunday}"
cd "$(dirname "$0")/.."
mkdir -p logs data/captures

WEEK=$(./.venv/bin/python -c "
import datetime
# NFL week 1 of the 2026 season begins Wed 2026-09-09.
start = datetime.date(2026, 9, 9)
print(max(1, (datetime.date.today() - start).days // 7 + 1))
")

# The injury fetch is allowed to fail without taking the alert with it: a
# digest carrying the lineup but no news is far better than no digest at all,
# and a missing --injuries file composes cleanly as "nothing new".
INJ="data/captures/injuries-${KIND}.json"
ops/fetch_injuries.sh "$INJ" || echo "WARN: injury fetch failed; continuing" >&2

PYTHONPATH=src ./.venv/bin/python -m sffl.cli alert \
  --kind "$KIND" \
  --week "$WEEK" \
  --curves calibration/2025.yaml \
  --injuries "$INJ" \
  --team-url "https://stripesfantasyfootballleague.football.cbssports.com/teams/1" \
  --projections-url "https://stripesfantasyfootballleague.football.cbssports.com/players/PROJECTIONS/RB-WR-TE"
```

> **The two URLs are the implementer's job to confirm.** Open each in the browser Playwright
> seeded, check that `/teams/1` is Jeff's team and that the projections URL lands on the
> ALL PLAYERS / RB-WR-TE weekly view, and correct them here if not. A wrong `/teams/N` captures
> **another manager's roster** and every downstream number would be confidently wrong — so
> verify this before loading the jobs, not after the first Sunday.

- [ ] **Step 2: Write the launchd jobs**

Create `ops/com.sffl.alert.friday.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.sffl.alert.friday</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/jeff/Projects/fantasy-football/ops/run_alert.sh</string>
    <string>friday</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>5</integer>
    <key>Hour</key><integer>16</integer>
    <key>Minute</key><integer>45</integer>
  </dict>
  <key>WorkingDirectory</key>
  <string>/Users/jeff/Projects/fantasy-football</string>
  <key>StandardOutPath</key>
  <string>/Users/jeff/Projects/fantasy-football/logs/alert-friday.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/jeff/Projects/fantasy-football/logs/alert-friday.err</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
```

Create `ops/com.sffl.alert.sunday.plist` — identical except `Label`
`com.sffl.alert.sunday`, the argument `sunday`, `Weekday` `0`, `Hour` `11`, `Minute` `30`,
and the two log paths ending `alert-sunday.log` / `alert-sunday.err`.

- [ ] **Step 3: Ignore the logs**

Append to `.gitignore`:

```
# launchd job output
logs/
```

- [ ] **Step 4: Dry-run the whole pipeline end to end**

Run: `ops/run_alert.sh friday` after temporarily adding `--dry-run` to the `sffl alert` call.

Expected: a complete digest printed to stdout, nothing pushed. **Confirm before proceeding:**
the roster names are Jeff's, the lineup fills all 8 slots, the roster age reads 0 days, and
no StatsDeck points appear anywhere in the text.

- [ ] **Step 5: Load the jobs**

```bash
cp ops/com.sffl.alert.*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.sffl.alert.friday.plist
launchctl load ~/Library/LaunchAgents/com.sffl.alert.sunday.plist
launchctl list | grep com.sffl
```

Expected: both labels listed.

- [ ] **Step 6: Force one real run and confirm the push lands**

```bash
launchctl start com.sffl.alert.friday
sleep 90
tail -40 logs/alert-friday.log
```

Expected: the digest in the log, and the notification on Jeff's phone.

- [ ] **Step 7: Write the runbook**

Create `docs/operations/in-season-alerting.md` covering, each as its own short section:

- **What runs when** — the two jobs, their times, and that `StartCalendarInterval` is local
  time, so it is already ET on this machine and needs no TZ handling.
- **First-time setup** — `pip install playwright`, `playwright install chromium`,
  `ops/cbs_login.py`, the `security add-generic-password` line for the ntfy topic, and
  `launchctl load`.
- **"I got no alert"** — check `launchctl list | grep com.sffl`, then
  `tail logs/alert-*.err`. A dead job is the *only* thing an absent message can mean, because
  the digest always sends.
- **"The alert says CAPTURE FAILED / session expired"** — run
  `./.venv/bin/python ops/cbs_login.py`, log in, done. Expect this every few months.
- **"The alert says a page was refused"** — the parser met a row shape it does not know.
  Most likely a manager code missing from `owner_codes` in `sources/cbs-weekly.yaml`; the
  error names the offending line. Add the code and re-run.
- **"The roster is wrong"** — confirm `--team-url` points at Jeff's team, not another
  manager's.
- **What is deliberately NOT automated** — waiver submission and lineup writing remain
  read-only; the alert recommends and never acts.

- [ ] **Step 8: Commit**

```bash
git add ops/run_alert.sh ops/com.sffl.alert.friday.plist ops/com.sffl.alert.sunday.plist docs/operations/in-season-alerting.md .gitignore
git commit -m "feat(ops): schedule the Friday and Sunday digests

Friday 16:45 local carries practice participation - the actionable
signal, with two days left to make a claim. Sunday 11:30 local carries
official inactives, ninety minutes before the 1pm window.

The injury fetch may fail without taking the alert down: a digest with
the lineup but no news beats no digest. A capture failure still delivers
a message saying so, and exits non-zero so the log records it.

Runbook covers first-time setup, the periodic CBS re-login, and the one
thing an absent push can mean."
```

---

## Self-Review

**1. Spec coverage.**

| spec requirement | task |
|---|---|
| Widen `avail` for short/mixed-case/digit codes | 3 (enumerated, not pattern-widened — reason recorded) |
| Optional injury designation, both positions | 3 |
| Keep the near-miss counter loud | 3 (untouched; still raises) |
| Do NOT relax `expect_tokens` | 3 (untouched — designation sits before the bullet) |
| `PlayerProjection` gains `status` | 4 |
| O/IR/PUP/SUSP excluded from the lineup | 4 |
| Q/D flagged, never excluded | 4 |
| Excluded players named in output | 4, 6 |
| `get_injuries` with no CBS connection | 5 |
| Official is the record; intel never overrides | 5 (separate rows), 6 (separate blocks) |
| `tier` is corroboration, not severity | 6 — **gap: `tier` is not carried at all.** Not rendered, so the rule cannot be violated. Acceptable; noted so a future task that adds it knows the rule. |
| `reported_date` on every line | 5, 6 |
| Never quote StatsDeck points | 5 (no points field read), 6 (asserted) |
| Own ntfy topic, in Keychain, not the repo | 7 |
| `PushNotification` not used | 7 |
| Digest, not change-detection | 6 |
| Roster staleness visible in every alert | 6 — **superseded**: the roster is captured, and the age printed is the capture's age, which is minutes rather than days. The stale path is retained because a capture failure can leave yesterday's file in place. |
| Friday 4:45pm ET / Sunday 11:30am ET | 8 |
| Friday and Sunday read differently | 6 |
| Fixture-based parser tests; no constructed lines in the real fixture | 3 (tests build their own strings), 2 (new fixture from a real capture) |
| No test calls StatsDeck or sends ntfy | 5, 7 (`dry_run` seam) |
| launchd verified by manual dry run | 8 steps 4–6 |

**2. Placeholder scan.** Two intentional, both flagged inline and both requiring real data the
implementer must go get, not invent: `owner_codes: [REPLACE_ME]` in Task 3 Step 1, and the two
CBS URLs in Task 8 Step 1. Each carries an explicit instruction to verify against the live page
and an explicit prohibition on making values up. The `_ROW` regex in Task 2 is likewise marked
"the fixture is the authority."

**3. Type consistency.** `classify_avail` changes arity in Task 3 and its only caller is updated
in the same task. `Report` fields are used identically in Tasks 5 and 6. `compose`'s signature
in Task 6 matches its call in Task 7. `is_out` is defined in Task 4 and used in Tasks 4 and 7.
`LineupResult.slots` is `[(slot, Candidate|None)]` in both `lineup.py` and Task 6's renderer.

**4. Known risk, stated rather than hidden.** Task 1 depends on Playwright installing under
Python 3.9.6, which could not be verified while writing this plan — `pip download` was
blocked by policy. Task 1 opens with an explicit gate: if the install fails, STOP and report
BLOCKED rather than substituting a mechanism, because the four alternatives were already
tested and rejected and a substitution is Jeff's call.

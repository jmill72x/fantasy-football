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

FRIDAY AND SUNDAY MUST ACTUALLY READ DIFFERENTLY, NOT JUST BE TITLED
DIFFERENTLY. The original version of this module led both kinds with the
same official-then-intel block and only changed two header words - a
cosmetic difference the spec explicitly rules out ("a Sunday alert that
simply repeats Friday's news trains its reader to ignore it"). The fix was
going to be "Friday leads with practice participation," but the real
StatsDeck feed has no practice field at all - practice information, if it
exists, is buried as prose inside `detail`. So Friday's lead block is status
(with practice inlined per row when the feed happens to carry it), and when
the feed carries NO practice data for anyone on the roster, Friday says that
explicitly rather than letting an empty `practice` field read as "nobody
practiced" - an absent measurement must never print as a fact.

Sunday's genuine differentiator is `previous_status` / `status_since` (see
`sffl.injuries`): the feed's own record of what a status moved FROM and
WHEN. Sunday LEADS with exactly those rows, rendered so the change is the
point. When nothing changed, Sunday says so explicitly instead of printing
an empty "WHAT CHANGED" heading.

A CHANGED ROW IS STILL LISTED IN THE STATUS BLOCK BELOW. It used to be
removed from that split - "shown here, not duplicated below" - which meant
a row that was both official AND changed (a starter moving Questionable ->
Out on Sunday morning: the single most important row the feed can produce)
emptied the OFFICIAL block, and the block then printed "no designations on
your roster" while that starter was Out. The heading must never lie about
what is under it, so the official/intel split is built from every row.

WHAT A ROW IS NOT ALLOWED TO RENDER AS. Two blank-field failures used to
print as good news. An official row whose `status` arrived empty - the exact
shape a renamed feed field produces, and `sffl.injuries` says that mapping
is still provisional - collapsed to "no detail" in the status block and to
"Questionable -> , since ..." in the change block; both read as "nothing
wrong with this player". `_status_text` prints an official row's missing
status as an explicit unknown instead. And a row with no status, practice,
OR detail now says so, rather than "no detail". Meanwhile `outlet` and
`tier` were carried all the way here and then dropped on the floor, so every
intel line read `[intel <date>]` - a repeat of its own heading, with
`sleeper_feed` vs `web_digest` lost. `_provenance` renders both, `tier`
always behind the literal word "corroboration" because it is SOURCING
STRENGTH, never injury severity.

THE START/SIT BLOCK (`current_starters`). Task 7's orchestrator found that
the single most actionable fact in the whole system - the diff between
Jeff's CURRENT CBS lineup and the optimal one this module already computes -
never reached the phone, because `compose` had nowhere to put it and was
printing it to stdout only. `current_starters=None` means the caller does
not know the current lineup (e.g. capture failed before it could be read);
that is NOT the same state as `current_starters=[]`, which means "known, and
nothing is currently started" - a real, renderable state. Comparing on raw
names would invent phantom moves, since the roster page and the projections
page disagree about punctuation ("Ja'Marr Chase" vs "JaMarr Chase"), so
names are compared via `sffl.identity.normalize_name` - the same function
the rest of this codebase already uses for exactly this mismatch. Importing
it is this module's first import; it is a plain, pure string function with
no I/O, so it does not compromise the structural purity this module was
reviewed for - noted here explicitly so the next reviewer reads it as
deliberate, not as a regression. The block is placed right after the
roster-age line, ahead of every news block, because it is the one thing
here that tells Jeff to actually DO something before kickoff; buried under
the injury news it would be the least-read line in the message instead of
the most.

A FAILED INJURY FETCH IS NOT A CLEAN BILL OF HEALTH (`injury_error`). When
StatsDeck is down or `claude -p` fails, no injuries file is written, and the
caller used to hand this function `reports=[]` - which rendered "no
designations on your roster." and "nothing new.", byte-identical to a
genuinely quiet week, at exit 0, with the only warning on stderr where a
phone never sees it. "Fetched, nothing to report" and "could not fetch" are
now separate inputs and read completely differently. The same reasoning
gives the injuries file the staleness check that used to sit only on the
roster (see STALE_ROSTER_DAYS): the roster is written milliseconds before it
is read, while the injuries file is the one input that can genuinely be a
week old.

A PLAYER WHO WAS NEVER EVALUATED IS NEVER A SIT (`unevaluated_starters`).
The optimizer can only fill RB/WR/TE, because that is the only position
group the projections capture covers. CBS sets eight starters. So the TQB,
the kicker and the defense are in the current lineup and can never be in the
optimal one - and this block, being a plain set difference, rendered all
three as SIT every single week, in the block placed FIRST as the most-read
content. The same mechanism swept up any rostered RB/WR/TE simply missing
from the projections page. Those players are now excluded from the diff and
named in their own section, which distinguishes "we do not capture this
position" (a known limit of the tool, and no reflection on the player) from
"his position IS captured and he had no projection anyway" (a data problem
worth chasing). `_cmd_week` has handled it this way since it grew a
--current flag; the language here mirrors its.
"""

from collections import namedtuple

from sffl.identity import normalize_name

# One roster player as the digest sees him. `points` is None when he could
# not be scored at all (no projection row, or his page failed) - which is a
# DIFFERENT state from 0.00 and must never render as one: a genuine 0.00 is
# a real projection saying "expect nothing", while None is "we do not know",
# and confusing the two is how a healthy player gets benched by an absent
# data file. `why` carries the reason for None (one of the reason constants
# above), or None when he was scored.
BoardRow = namedtuple("BoardRow", "name pos team points status why")

# Past this many days, the roster file's age is called out as a problem rather
# than merely stated. Visible staleness beats invisible staleness.
#
# KEPT DELIBERATELY, THOUGH IT CANNOT FIRE FOR `_cmd_alert`: that caller
# captures the roster page and reads its mtime milliseconds later, so the
# age is always 0 and the loud branch is unreachable from there. The final
# review was right that the staleness budget had been spent on the one input
# that can never be stale - but the fix for that is the injuries check below,
# which is where the staleness actually lives, not the deletion of a true
# statement. `compose` is a pure function with no privileged caller; anything
# composing from a roster captured earlier (a replay, a manual re-run against
# a saved page) gets the guard, and "Roster captured N days ago" is a fact
# about the input either way, printed on every run precisely so a reader
# never has to wonder whether it was checked.
STALE_ROSTER_DAYS = 10

# Past this many minutes, the injuries file was NOT written by this run.
# `ops/run_alert.sh` fetches immediately before invoking the alert, so a
# fresh file is seconds old and even a slow `claude -p` fetch is minutes;
# an hour means the fetch step did not run, and the news being rendered is
# a previous run's. Unlike the roster, this input genuinely CAN be stale:
# nothing in this pipeline rewrites it when the fetch fails.
STALE_INJURIES_MINUTES = 60

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


def _injuries_age_line(minutes):
    if minutes > STALE_INJURIES_MINUTES:
        return ("!! STALE INJURY DATA: the injuries file is %d minutes old "
                "(over %d), so this run's fetch did not write it. The news "
                "below is from an EARLIER run - check each row's date."
                % (minutes, STALE_INJURIES_MINUTES))
    return "Injury data fetched %d minute%s ago." % (
        minutes, "" if minutes == 1 else "s")


_UNKNOWN_STATUS = "STATUS UNKNOWN (feed carried no status for this row)"


def _status_text(r):
    """The row's status, or an explicit unknown for an official row.

    An official row with a blank status is a DATA PROBLEM, never a clean
    bill of health. The official-row field mapping in `sffl.injuries` is
    provisional (it has never been exercised against a real `report` row),
    and if the feed spells the field differently every official row arrives
    blank - which, interpolated raw, produced "Questionable -> , since ..."
    in the change block and collapsed to "no detail" in the status block.
    Both read as "nothing wrong with this player". Printed as an explicit
    unknown instead, a broken mapping is unmissable in the message itself.

    An INTEL row with no status is ordinary and stays blank: intel rows
    routinely carry only prose (the real feed has one), and their detail
    text is the content. Only the record is held to having a status.
    """
    if r.status:
        return r.status
    if r.source == "official":
        return _UNKNOWN_STATUS
    return ""


def _provenance(r):
    """The `[bucket date]` tag, plus the row-level provenance it carries.

    `outlet` is the feed's OWN label for where a row came from
    ("sleeper_feed", "web_digest", a beat writer) and is the whole reason
    intel rows are worth reading separately from each other - without it
    every intel line reads `[intel <date>]`, which merely repeats the block
    heading. Official rows never carry one (see `sffl.injuries`).

    `tier` IS CORROBORATION STRENGTH, NEVER INJURY SEVERITY - "corroborated"
    vs "unconfirmed" says how sure StatsDeck's pipeline is that the report
    is real, not how bad the injury is. Rendered ONLY behind the literal
    word "corroboration" so it cannot be read as a designation: a bare
    "unconfirmed" sitting next to "Questionable" would look like a second
    opinion on the player rather than a note about the sourcing.
    """
    bits = ["%s %s" % (r.source, r.reported_date or "undated")]
    if getattr(r, "outlet", ""):
        bits.append("via %s" % r.outlet)
    if getattr(r, "tier", ""):
        bits.append("corroboration: %s" % r.tier)
    return "[%s]" % ", ".join(bits)


def _report_line(r):
    """One feed row. `source` and `reported_date` always travel with it."""
    bits = []
    status = _status_text(r)
    if status:
        bits.append(status)
    if r.practice:
        bits.append("practice: %s" % r.practice)
    if r.detail:
        bits.append(r.detail)
    # NOT "no detail" - that reads as "nothing to report about this player",
    # i.e. as health, when what actually happened is that the row arrived
    # carrying no information at all. Say which.
    return "  - %s (%s) %s %s" % (
        r.name, r.team or "?",
        " / ".join(bits) or "row carried no status, practice, or detail",
        _provenance(r))


def _change_line(r):
    """A Sunday change row: what moved, from what, to what, and when.

    `previous_status` and `status_since` are the only change signal the feed
    gives for free (see the `injuries` module docstring) - carried verbatim,
    never derived here by comparing rows. `detail` and `reported_date` still
    travel with the row so nothing the record knows is lost by leading with
    the change instead of the static status.
    """
    detail = " - %s" % r.detail if r.detail else ""
    return "  - %s (%s): %s -> %s, since %s%s %s" % (
        r.name, r.team or "?", r.previous_status or "unknown",
        _status_text(r) or "unknown",
        r.status_since or "date unknown", detail,
        _provenance(r))


def _is_changed(r):
    """A row the feed itself marks as having moved status.

    Requires BOTH a non-empty `previous_status` and that it differ from the
    current `status` - a row can carry `previous_status == status` when a
    designation was merely reconfirmed, which is not a change worth leading
    with.
    """
    return bool(r.previous_status) and r.previous_status != r.status


# Why a starter was never scored. These are NOT interchangeable - each is a
# genuinely different fact about the run, and rendering any two of them as
# one bucket (or worse, as a SIT recommendation) throws away a real signal:
#
#   POSITION_NOT_CAPTURED - a PERMANENT scope limit. This pipeline never
#     captures this position at all (no group in sources/cbs-weekly.yaml
#     covers it). Says nothing about the player.
#
#   PROJECTION_PAGE_FAILED - a TRANSIENT, THIS-RUN-ONLY failure. The
#     position IS ordinarily captured, but its page failed to capture or
#     parse on this specific run (see the "!! PROJECTIONS DEGRADED" note
#     elsewhere in the digest). Distinct from POSITION_NOT_CAPTURED on
#     purpose: reusing that wording for a page that failed today would
#     read as "this pipeline has never covered defenses," which is false
#     and hides the actual, fixable, one-run failure - fixed 2026-08-30
#     after a reviewer reproduced exactly this misreport with a K-page
#     failure.
#
#   PROJECTION_MISSING - a DATA PROBLEM. The position IS captured, this
#     run's page for it DID succeed, and this specific player still has no
#     row - worth chasing, not a tool limit or a transient failure.
#
#   ROSTER_NAME_AMBIGUOUS - a ROSTER-PARSING PROBLEM, not a projections
#     problem at all. This was `_cmd_alert`'s FIRST fix (2026-08-30) for a
#     reviewer-reproduced bug: CBS's TQB and DST pages both use the NFL
#     team nickname as a row's "player name", so nothing stops a manager
#     from rostering the SAME real team for both slots - "Chargers" TQB
#     and "Chargers" DST are both legitimate, independent picks - and the
#     old `parse_lineup`/`parse_positions` (name-only) silently lost the
#     second row entirely, rendering its slot `-- UNFILLED` at exit 0 with
#     no mention anywhere. `sffl.cbs_roster.find_name_position_collisions`
#     found this collision; the fix at the time was to exclude both names
#     from scoring and report them here instead. SUPERSEDED, the same day,
#     by a more complete fix: `cbs_roster.parse_lineup_rows` now keeps each
#     row's own (name, slot, team) from the start, so this ambiguity never
#     arises - both entries resolve correctly and independently, and
#     `_cmd_alert` no longer produces this reason. Kept here (and still
#     rendered correctly by `compose` below) as a supported, tested part of
#     this function's CONTRACT, in case a future caller ever needs it -
#     removing it outright would be presuming no one else ever will.
POSITION_NOT_CAPTURED = "position-not-captured"
PROJECTION_PAGE_FAILED = "projection-page-failed"
PROJECTION_MISSING = "projection-missing"
ROSTER_NAME_AMBIGUOUS = "roster-name-ambiguous"

# Short forms of the same reasons for the BENCH block, which is a table:
# `_UNEVALUATED_REASONS`'s values are paragraph-length and end in ":" because
# they are section HEADERS introducing a list of players. Reusing them per-row
# would wrap a paragraph into every bench line.
_BENCH_REASONS = {
    POSITION_NOT_CAPTURED: "position not captured by this job",
    PROJECTION_PAGE_FAILED: "that page failed this run",
    PROJECTION_MISSING: "no projection row - data problem",
    ROSTER_NAME_AMBIGUOUS: "name ambiguous on the roster page",
}

_UNEVALUATED_REASONS = {
    POSITION_NOT_CAPTURED: (
        "Their position is not in the projections page this job captures, so "
        "they were never scored. This says NOTHING about whether to start "
        "them - it is a limit of the tool, not a judgement on the player:"),
    PROJECTION_PAGE_FAILED: (
        "Their position IS ordinarily captured, but that page's capture or "
        "parse FAILED on this specific run (see the PROJECTIONS DEGRADED "
        "note in this digest) - so they were not scored today. This is NOT "
        "a permanent limit of the tool; check back next run:"),
    PROJECTION_MISSING: (
        "Their position IS captured and they still had no projection - so "
        "this is a DATA PROBLEM, not advice. Check the projections capture "
        "for these names:"),
    ROSTER_NAME_AMBIGUOUS: (
        "This name appears on your CBS roster page more than once, for "
        "DIFFERENT positions - most likely the same NFL team rostered for "
        "both TQB and DST. This pipeline cannot tell the two roster slots "
        "apart from the page alone, so NEITHER was scored; check your "
        "roster manually for these names (position shown is one of the "
        "colliding ones, not necessarily the right one):"),
}


def _start_sit_diff(lineup_result, current_starters, sidelined, unevaluated):
    """(start, sit) display names: optimal lineup vs the CBS current one.

    `current_starters` is a list of `(name, pos, team)` triples, NOT bare
    names - see `compose`'s docstring for why. Compared on
    `(normalize_name(name), pos, team)`, never on name alone: the roster
    page and the projections page disagree about punctuation ("Ja'Marr
    Chase" vs "JaMarr Chase" - `normalize_name` handles that), but a
    name-only key ALSO cannot tell two rostered picks with the SAME
    display name apart - an NFL team rostered for both TQB and DST
    ("Chargers" is a real row on both CBS pages) is a reproduced case; two
    different NFL players sharing a name at the same position on different
    teams is a real one too (see `sffl.cli._merge_projection_groups`'s
    docstring for both). A name-only diff would collapse either pair into
    one dict entry and silently drop half of a real start/sit comparison.

    `sidelined` names are dropped from the optimal side before the diff runs
    at all, so a player excluded because he will not play can never be
    reported as a "start" - regardless of how he got into `lineup_result`
    (the optimizer's own candidate pool already omits Out players, but this
    is the one place that guarantees it rather than assuming it).
    Name-only, a narrower heuristic than the (name, pos, team) key used
    everywhere else here - `sidelined` is `(name, status)` pairs with no
    position attached (see `_cmd_alert`), and upgrading its shape too was
    judged disproportionate for a residual this narrow: the practical
    effect of a false-positive match here is a HEALTHY player's start
    getting incorrectly suppressed, which is a strictly smaller harm than
    what this whole fix round targets (a real player's SLOT silently
    vanishing or being filled by the wrong data).

    `unevaluated` names are dropped from the CURRENT side before the diff,
    for the same class of reason and with more urgency: a starter who was
    never scored is "in current, not in optimal" by construction, which this
    diff would otherwise render as a merit-based SIT. That is how the block
    came to recommend benching the TQB, the kicker and the defense EVERY
    SINGLE WEEK - the optimizer can only fill RB/WR/TE, so the other five
    starters could never be in the optimal lineup no matter how well they
    were playing. Excluded here, named separately by `compose`. `_cmd_week`
    has done exactly this since it grew a --current flag; its comment says a
    player who quietly vanishes reads as "no longer on your roster" rather
    than "ruled out", and the same applies to one who quietly appears under
    SIT. Matched on (normalize_name, pos) - `unevaluated` carries a position
    but no team, matching how far `_cmd_alert` can currently take it.
    """
    sidelined_keys = set(normalize_name(name) for name, _status in sidelined)
    unevaluated_keys = set((normalize_name(name), pos) for name, pos, _why
                           in unevaluated)

    optimal_by_key = {}
    for _slot, pick in lineup_result.slots:
        if pick is None:
            continue
        if normalize_name(pick.name) in sidelined_keys:
            continue
        key = (normalize_name(pick.name), pick.pos, pick.team)
        optimal_by_key[key] = pick.name

    current_by_key = dict(
        ((normalize_name(name), pos, team), name)
        for name, pos, team in current_starters
        if (normalize_name(name), pos) not in unevaluated_keys)

    start = sorted(optimal_by_key[k] for k in optimal_by_key
                   if k not in current_by_key)
    sit = sorted(current_by_key[k] for k in current_by_key
                if k not in optimal_by_key)
    return start, sit


def _bench_block(roster_board, lineup_result):
    """The rostered players the optimal lineup did NOT start, with their points.

    Keyed on `(normalize_name, pos, team)` - the same triple
    `_start_sit_diff` uses, and for the same reproduced reason: a name-only
    key cannot tell an NFL team rostered at both TQB and DST apart, so
    "Chargers" started at TQB would wrongly suppress "Chargers" at DST from
    this block, hiding a real rostered asset.

    Sorted by points DESCENDING, because the only question this block
    answers is "is someone on my bench out-projecting a starter?" - and the
    answer is the top row or nowhere. Unscored players (`points is None`)
    sort last under their own reason rather than being dropped: a player the
    pipeline could not score is exactly the one worth eyeballing manually,
    and silently omitting him is how a roster of thirteen renders as twelve.
    """
    started = set()
    for _slot, pick in lineup_result.slots:
        if pick is not None:
            started.add((normalize_name(pick.name), pick.pos, pick.team))

    bench = [r for r in roster_board
             if (normalize_name(r.name), r.pos, r.team) not in started]

    out = ["BENCH - rostered, not in the optimal lineup (%d):" % len(bench)]
    if not bench:
        out.append("  none - all %d rostered players are starting."
                   % len(roster_board))
        return out

    scored = sorted((r for r in bench if r.points is not None),
                    key=lambda r: -r.points)
    unscored = [r for r in bench if r.points is None]
    for r in scored:
        note = "  (%s)" % r.status if r.status else ""
        out.append("  %-6s %-20s %6.2f%s" % (r.pos or "?", r.name, r.points, note))
    for r in unscored:
        why = _BENCH_REASONS.get(r.why, r.why or "not scored")
        out.append("  %-6s %-20s %6s  - %s"
                   % (r.pos or "?", r.name, "--", why))
    return out


def compose(kind, roster_age_days, reports, lineup_result, sidelined,
            capture_error=None, current_starters=None,
            unevaluated_starters=None, injury_error=None,
            injuries_age_minutes=None, projections_capture_error=None,
            roster_board=None):
    """The full digest text for one run.

    `kind` is "friday" or "sunday". `sidelined` is a list of (name, status)
    for roster players excluded from the lineup. `current_starters` is a
    list of `(name, pos, team)` triples for who CBS currently has starting,
    if known - `None` means unknown (no diff is rendered); `[]` means
    known-and-empty (a real state, which CAN render a diff recommending
    every optimal starter). NOT bare names: see `_start_sit_diff`'s
    docstring for why name alone cannot tell two rostered picks that share
    a display name apart (an NFL team rostered for both TQB and DST; two
    different NFL players sharing a name at the same position on different
    teams), both of which are real, reproduced hazards, not hypotheticals.

    `unevaluated_starters` is a list of (name, position, reason) for current
    starters that were never scored - see `POSITION_NOT_CAPTURED`,
    `PROJECTION_PAGE_FAILED`, `PROJECTION_MISSING` and
    `ROSTER_NAME_AMBIGUOUS` above for what each `reason` means and how they
    differ. They are excluded from the SIT column and named in their own
    section instead - see `_start_sit_diff`. It defaults to `None` (treated
    as empty) so a caller that does not know is not forced to lie about it;
    `_cmd_alert` always passes it.

    `injury_error` is why the injury feed could not be read, if it could
    not. It is NOT the same state as `reports=[]`, which means the feed was
    read and had nothing on this roster - and the whole point of carrying it
    is that the two used to render identically. `injuries_age_minutes` is
    how old the injuries file was when it was read, or `None` if there was
    no file to age.

    `capture_error` and `projections_capture_error` are BOTH "nothing here
    can be trusted, short-circuit the whole digest" states, and are
    DELIBERATELY NOT interchangeable, even though both suppress the same
    downstream content. `capture_error` means the ROSTER could not be read
    - nothing at all is known, including who Jeff even rosters, so the fix
    is CBS login. `projections_capture_error` means the roster WAS read
    successfully but every one of the four projection pages failed, so no
    lineup could be SCORED - a completely different failure with a
    completely different fix (a projections-page problem, not a login
    problem). Reusing `capture_error`'s roster-failure prose for this case
    - which `_cmd_alert` did before a reviewer caught it - tells the reader
    to re-run `cbs_login.py` when the login was never the problem.

    `roster_board` is EVERY rostered player as a `BoardRow` - all thirteen,
    not the eight the optimizer started. The optimizer has always CONSIDERED
    all thirteen (`_cmd_alert` builds its candidate pool from starters plus
    reserves), but the digest only ever NAMED the eight it picked, so the
    bench's projections - the numbers that justify the pick, and the only
    way to see a reserve out-projecting a starter the optimizer could not
    legally slot - never reached the phone. `None` means the caller does not
    know the full roster and the section is omitted entirely, which keeps
    every pre-existing caller's output byte-identical.
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

    if projections_capture_error:
        lines.append("!! ALL PROJECTIONS CAPTURE FAILED: %s"
                     % projections_capture_error)
        lines.append("")
        lines.append("Your ROSTER was read successfully, but none of the "
                     "four position-group projection pages could be "
                     "captured or parsed this run, so no lineup can be "
                     "scored. This is a projections-page problem, NOT a "
                     "login problem - the roster capture above worked fine.")
        lines.append("Fix: check CBS's stats-main pages directly (they may "
                     "be down or slow), or re-run this job again shortly; "
                     "re-running cbs_login.py will not help here.")
        return "\n".join(lines)

    lines.append(_roster_age_line(roster_age_days))
    lines.append("")

    # Placed ahead of every news block, deliberately: this is the one thing
    # in the whole message that tells Jeff to DO something before kickoff.
    # `None` means the caller does not know the current lineup (e.g. capture
    # failed before it could be read) and must not render a diff - that
    # would falsely claim everything should be benched. `[]` is a known,
    # real, renderable state: nothing is currently started.
    unevaluated = list(unevaluated_starters or [])
    for _name, _pos, why in unevaluated:
        if why not in _UNEVALUATED_REASONS:
            raise ValueError(
                "unknown un-evaluated reason %r - expected one of %s. This "
                "controls whether a starter is described as a known scope "
                "limit or as a data problem; guessing would tell the reader "
                "the wrong one." % (why, sorted(_UNEVALUATED_REASONS)))

    if current_starters is not None:
        start, sit = _start_sit_diff(lineup_result, current_starters,
                                     sidelined, unevaluated)
        lines.append("START / SIT vs your current CBS lineup:")
        if start or sit:
            lines.append("  START           SIT")
            for i in range(max(len(start), len(sit))):
                a = start[i] if i < len(start) else ""
                b = sit[i] if i < len(sit) else ""
                lines.append("    %-15s %s" % (a, b))
        elif unevaluated:
            # "already optimal" would be a confident overstatement while
            # some starters were never scored at all - it claims a
            # comparison that did not happen for part of the lineup.
            lines.append("  no changes to make among the players that could "
                         "be evaluated (see below).")
        else:
            lines.append("  lineup is already optimal - no changes to make.")
        lines.append("")

        if unevaluated:
            # Immediately under START/SIT, because this is the scope of the
            # block above and reading that block without it is how a kicker
            # ends up looking benched. NOT phrased as advice: every line
            # here says what was NOT done, never what to do.
            lines.append("NOT EVALUATED for start/sit - these are NOT "
                         "recommendations to bench anyone:")
            for why in (POSITION_NOT_CAPTURED, PROJECTION_PAGE_FAILED,
                       PROJECTION_MISSING, ROSTER_NAME_AMBIGUOUS):
                rows = sorted(r for r in unevaluated if r[2] == why)
                if not rows:
                    continue
                lines.append("  %s" % _UNEVALUATED_REASONS[why])
                for name, pos, _why in rows:
                    lines.append("    - %s (%s)" % (name, pos or "?"))
            lines.append("")

    # THE NEWS BELOW IS ONLY AS GOOD AS THE FETCH THAT PRODUCED IT, so say
    # so BEFORE any of it, not on stderr where the phone will never see it.
    # A failed StatsDeck fetch used to leave `reports` empty, which rendered
    # byte-identically to a genuinely quiet week - "no designations on your
    # roster.", "nothing new." - at exit 0. The three "nothing to report"
    # lines below are replaced with an explicit not-fetched line for the
    # same reason: an absent measurement must never print as a fact.
    if injury_error:
        lines.append("!! INJURY DATA UNAVAILABLE: %s" % injury_error)
        lines.append("   The status blocks below are empty because NOTHING "
                     "WAS FETCHED, not because your roster is clean.")
        lines.append("")
    elif injuries_age_minutes is not None:
        lines.append(_injuries_age_line(injuries_age_minutes))
        lines.append("")

    no_news = ("  NOT FETCHED - see the injury-data warning above. This is "
               "not a clean bill of health." if injury_error else None)

    if kind == "sunday":
        # Sunday leads with what CHANGED - the feed's own previous_status /
        # status_since - not a cosmetic reheading of Friday's static status
        # block.
        changed = [r for r in reports if _is_changed(r)]

        lines.append("WHAT CHANGED since the last report:")
        if changed:
            lines.extend(_change_line(r) for r in changed)
        else:
            lines.append(no_news or
                         "  no status changes since the previous report.")
        lines.append("")

    # EVERY row, INCLUDING the ones the Sunday change block just led with. A
    # changed row used to be REMOVED from this split, on the reasoning that
    # showing it twice was redundant - but a row can be both official AND
    # changed (a starter who moved Questionable -> Out on Sunday morning is
    # precisely that row, and precisely the one that matters most). Removing
    # it emptied the block below, which then printed "no designations on
    # your roster" ninety minutes before kickoff with a starter ruled Out.
    # The block is titled OFFICIAL STATUS and this module's own docstring
    # calls the official report "the record"; a record with rows silently
    # withheld is not a record. Two lines of duplication on a phone screen
    # is a trivial price for the heading never lying about its contents.
    official = [r for r in reports if r.source == "official"]
    intel = [r for r in reports if r.source != "official"]

    if kind == "friday":
        lines.append("PRACTICE / STATUS on your roster:")
        # The real feed currently has no `practice` field at all - it is
        # never inferred from prose. A blank field printed as "no practice
        # data" is a stated absence; printed silently it would read as "this
        # player practiced fully," a fact nobody measured.
        if not injury_error and not any(r.practice for r in reports):
            lines.append("  (feed carried no practice data for your roster "
                         "today - status only below.)")
    else:
        lines.append("OFFICIAL STATUS on your roster:")
    if official:
        lines.extend(_report_line(r) for r in official)
    else:
        lines.append(no_news or "  no designations on your roster.")
    lines.append("")

    # Shown SEPARATELY and never merged into the official block: the official
    # report is the record, intel supplements it and never overrides it. When
    # the two disagree the reader sees both, with dates, and decides.
    lines.append("INTEL (supplements the official report, never overrides it):")
    if intel:
        lines.extend(_report_line(r) for r in intel)
    else:
        lines.append(no_news or "  nothing new.")
    lines.append("")

    if sidelined:
        lines.append("EXCLUDED from the lineup - will not play:")
        lines.extend("  - %s (%s)" % (n, s) for n, s in sidelined)
        lines.append("")

    lines.append("BEST LINEUP (%.2f pts, this league's scoring):" %
                 lineup_result.total)
    for slot, pick in lineup_result.slots:
        if pick is None:
            lines.append("  %-6s %s" % (slot, "-- UNFILLED"))
        else:
            lines.append("  %-6s %-20s %6.2f" % (slot, pick.name, pick.points))

    if roster_board is not None:
        lines.append("")
        lines.extend(_bench_block(roster_board, lineup_result))

    return "\n".join(lines)

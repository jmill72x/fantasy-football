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
"""

from sffl.identity import normalize_name

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


def _start_sit_diff(lineup_result, current_starters, sidelined):
    """(start, sit) display names: optimal lineup vs the CBS current one.

    Compared on `normalize_name`, never on raw strings - the roster page and
    the projections page disagree about punctuation, and a literal
    comparison would invent a phantom move for the same player.

    `sidelined` names are dropped from the optimal side before the diff runs
    at all, so a player excluded because he will not play can never be
    reported as a "start" - regardless of how he got into `lineup_result`
    (the optimizer's own candidate pool already omits Out players, but this
    is the one place that guarantees it rather than assuming it).
    """
    sidelined_keys = set(normalize_name(name) for name, _status in sidelined)

    optimal_by_key = {}
    for _slot, pick in lineup_result.slots:
        if pick is None:
            continue
        key = normalize_name(pick.name)
        if key in sidelined_keys:
            continue
        optimal_by_key[key] = pick.name

    current_by_key = dict((normalize_name(n), n) for n in current_starters)

    start = sorted(optimal_by_key[k] for k in optimal_by_key
                   if k not in current_by_key)
    sit = sorted(current_by_key[k] for k in current_by_key
                if k not in optimal_by_key)
    return start, sit


def compose(kind, roster_age_days, reports, lineup_result, sidelined,
            capture_error=None, current_starters=None):
    """The full digest text for one run.

    `kind` is "friday" or "sunday". `sidelined` is a list of (name, status)
    for roster players excluded from the lineup. `current_starters` is the
    list of names CBS currently has starting, if known - `None` means
    unknown (no diff is rendered); `[]` means known-and-empty (a real state,
    which CAN render a diff recommending every optimal starter).
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

    # Placed ahead of every news block, deliberately: this is the one thing
    # in the whole message that tells Jeff to DO something before kickoff.
    # `None` means the caller does not know the current lineup (e.g. capture
    # failed before it could be read) and must not render a diff - that
    # would falsely claim everything should be benched. `[]` is a known,
    # real, renderable state: nothing is currently started.
    if current_starters is not None:
        start, sit = _start_sit_diff(lineup_result, current_starters, sidelined)
        lines.append("START / SIT vs your current CBS lineup:")
        if start or sit:
            lines.append("  START           SIT")
            for i in range(max(len(start), len(sit))):
                a = start[i] if i < len(start) else ""
                b = sit[i] if i < len(sit) else ""
                lines.append("    %-15s %s" % (a, b))
        else:
            lines.append("  lineup is already optimal - no changes to make.")
        lines.append("")

    if kind == "sunday":
        # Sunday leads with what CHANGED - the feed's own previous_status /
        # status_since - not a cosmetic reheading of Friday's static status
        # block. A row that changed is shown here, not duplicated below.
        changed = [r for r in reports if _is_changed(r)]

        lines.append("WHAT CHANGED since the last report:")
        if changed:
            lines.extend(_change_line(r) for r in changed)
        else:
            lines.append("  no status changes since the previous report.")
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
        if not any(r.practice for r in reports):
            lines.append("  (feed carried no practice data for your roster "
                         "today - status only below.)")
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

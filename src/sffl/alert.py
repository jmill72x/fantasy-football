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
WHEN. Sunday leads with exactly those rows, rendered so the change is the
point, and pushes rows with no recorded change down into the ordinary
status block below. When nothing changed, Sunday says so explicitly instead
of printing an empty "WHAT CHANGED" heading.

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


def _change_line(r):
    """A Sunday change row: what moved, from what, to what, and when.

    `previous_status` and `status_since` are the only change signal the feed
    gives for free (see the `injuries` module docstring) - carried verbatim,
    never derived here by comparing rows. `detail` and `reported_date` still
    travel with the row so nothing the record knows is lost by leading with
    the change instead of the static status.
    """
    detail = " - %s" % r.detail if r.detail else ""
    return "  - %s (%s): %s -> %s, since %s%s [%s %s]" % (
        r.name, r.team or "?", r.previous_status or "unknown", r.status,
        r.status_since or "date unknown", detail,
        r.source, r.reported_date or "undated")


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
        changed_ids = set(id(r) for r in changed)
        rest = [r for r in reports if id(r) not in changed_ids]

        lines.append("WHAT CHANGED since the last report:")
        if changed:
            lines.extend(_change_line(r) for r in changed)
        else:
            lines.append("  no status changes since the previous report.")
        lines.append("")
    else:
        # Friday has no change signal to lead with two days out - it leads
        # with status-and-practice, the plan-around view.
        rest = reports

    official = [r for r in rest if r.source == "official"]
    intel = [r for r in rest if r.source != "official"]

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

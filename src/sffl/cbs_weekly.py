"""Parse the CBS league site's weekly projections table from saved page text.

NO NETWORK I/O. The page is fetched by an operator (browser tools) and saved;
this module parses the file. That keeps every test a fixture test and keeps the
parser honest about a layout it cannot control.

A ROW MAY CARRY A LEADING `id=<digits>\t` PREFIX, put there by
`sffl.capture.capture` when it could pair that row with a CBS
`playerpage/<id>` link (a genuinely unique join key - see `identity.
resolve_key`). It is stripped off (`_strip_id_prefix`) before either
delimiter path parses the rest of the line, so it can never affect
`expect_tokens` or the stat-block slice. This covers TQB and DST rows too,
not just individual players - verified live 2026-08-30, CBS gives each
team's TQB unit and DST unit its own synthetic id (a genuine surprise
against an earlier assumption; the Chargers' TQB unit and DST unit carry
DIFFERENT ids, so this does not collide the two). Absent only on a row
`capture()` truly could not pair with a link (page furniture) and on
every row from any other source (a `--projections` fixture saved by hand,
another vendor entirely) - `PlayerProjection.player_id` is `""` in both
cases, and `resolve_key` falls back to the (name, team, pos) composite
automatically.

STAT NAMES IN A PROFILE'S `stats:` LIST MAY REPEAT. The list is positional -
one token, one name - EXCEPT that a name appearing MORE THAN ONCE means those
columns are SUMMED into that one key. This exists because CBS splits a single
scored stat across multiple columns - e.g. `fg_u30` is scored as one
number but CBS prints it as a `1-19` column and a `20-29` column - which a
strictly positional map cannot express. `_` (a column the scoring engine does
not use) is exempt: repeating `_` still discards every one of those columns
and never creates a stat literally named `_`.
"""

import datetime
import re
import yaml

from sffl.identity import normalize_team
from sffl.schema import PlayerProjection
from sffl.scoring import STAT_KEYS

DEFAULT_PROFILE = "sources/cbs-weekly.yaml"

# Names a group's `stats:` list may use OUTSIDE scoring.STAT_KEYS, without
# `_load_groups` refusing the profile. Two different reasons land a name
# here, and both are enumerated rather than inferred, on purpose:
#
#   - CARRIED BUT DELIBERATELY UNSCORED: this league does not score the
#     stat (pass_att, rush_att, tgt, fum_lost) but a profile still names the
#     column so the width/positional accounting stays honest and a future
#     reader can see what CBS put there.
#   - INTERNAL, CONSUMED BY `parse()` BEFORE A ROW IS RETURNED: fg_att_u50
#     exists only to compute the derived `fg_missed` (see the fg_missed
#     block in `parse` below) and is popped out of `stats` before a
#     PlayerProjection is built - it must never appear in scored output,
#     but it must be allowed to appear in the YAML map that produces it.
#
# WHY THIS EXISTS AT ALL: `ingest/profiles.py` validates its `columns:` map
# against exactly this vocabulary (STAT_KEYS) at load time; this module had
# no equivalent check, which is exactly how `sacks` and `fg_under_30` -
# both misspellings of real STAT_KEYS names - reached a committed group map.
# `score_game` reads any stat key with a default of 0, so a bad name does
# not error - it silently scores 0 for that category, forever, for every
# player in the group. See _check_group_stats below.
_ALLOWED_UNSCORED_STATS = frozenset({
    "pass_att", "rush_att", "tgt", "fum_lost",  # carried, not scored
    "fg_att_u50",                                # internal: see fg_missed
})


def _check_group_stats(profile_path, group_name, fields):
    """Raise if `fields` (a group's `stats:` list) names an unrecognized stat.

    Every name must be `_` (discarded), a real scoring key
    (scoring.STAT_KEYS), or on the explicit `_ALLOWED_UNSCORED_STATS` list.
    Anything else is either a misspelling of a real key - which `score_game`
    would silently score as 0 forever, never raising - or a genuinely new
    stat the scoring engine does not know about either way. Both are bugs
    worth failing loudly on, immediately, rather than trusting arithmetic
    that happens to look plausible on one sample row.
    """
    unknown = sorted(set(
        f for f in fields
        if f != "_" and f not in STAT_KEYS and f not in _ALLOWED_UNSCORED_STATS))
    if unknown:
        raise ValueError(
            "%s group %r declares stat name(s) score_game does not read "
            "and that are not on cbs_weekly._ALLOWED_UNSCORED_STATS: %s. A "
            "stat key outside scoring.STAT_KEYS is not an error at scoring "
            "time - score_game defaults a missing key to 0 and scores it "
            "silently, forever. Fix the spelling to match scoring.STAT_KEYS, "
            "or add the name to _ALLOWED_UNSCORED_STATS if it is genuinely "
            "meant to be carried unscored or consumed internally by parse()."
            % (profile_path, group_name, ", ".join(unknown)))

# "W (9/16) Harold Fannin Jr. TE • CLE @JAC ..." - availability, name,
# position, bullet, team, then the rest. `avail` is "FA" (free agent), "W"
# or "W (9/16)" (waiver-claimable, with the date the claim clears), or one of
# the league's configured manager abbreviations (a player another manager
# already rosters) - see `classify_avail` below, which sorts a captured value
# into "available"/"owned"/unclassified for callers that need to tell them
# apart (F3: parse() used to capture this column and throw it away, so the
# waiver ranking could not distinguish a free agent from another team's
# starter).
#
# The standard CBS injury designations, longest first so "IR" cannot be
# matched as "I" and "SUSP" cannot be matched as "S".
_STATUS_TAGS = ("SUSP", "PUP", "IR", "NA", "Q", "D", "O")

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


_AVAIL_WAIVER = re.compile(r"^W(\s*\(.*\))?$")

# The Playwright `capture()` path (used by the scheduled in-season job)
# produces TAB-delimited rows, not the space-delimited text the browser-tool
# capture used for the committed fixture. Both are real, observed shapes -
# see build_line_re vs _TAB_LINE/_TAB_NAME below - and a line is dispatched
# to whichever path matches its own delimiter, per line, so a file can even
# mix the two without either path misreading the other's rows.
#
# Row shape: "\t<owner cell>\t<Name POS • TEAM>\t<OPP>\t<stat1>\t...".
# The owner cell is its OWN tab field here, structurally separated from the
# name - unlike the space path, there is no possible reading in which a
# player's first name gets swallowed as an owner token, because there is no
# token boundary to get wrong: the tab already told us where the cell ends.
# So, unlike build_line_re, this pattern does NOT need owner_codes and is a
# plain module-level constant.
_TAB_LINE = re.compile(
    r"^\t(?P<avail>[^\t]*)\t(?P<namecell>[^\t]+)\t(?P<rest>.+)$")

# An OPTIONAL leading "id=<digits>\t" prefix, present only on a row
# `sffl.capture.capture` was able to pair with a `playerpage/<id>` link (see
# that module's docstring). Stripped BEFORE the row is matched against
# `_TAB_LINE` or `build_line_re`'s pattern, so it can never shift or shorten
# `tokens` (the fields counted by `expect_tokens`, the column-shift guard) -
# `tokens` is derived entirely from `rest`, which starts well after this
# prefix and the row's own leading tab. A row with no such prefix (page
# furniture - a TQB/DST team-aggregate row gets its own id too, see the
# module docstring) parses exactly as before this existed.
_ID_PREFIX = re.compile(r"^id=(?P<id>\d+)\t")


def _strip_id_prefix(line):
    """(player_id, line) - `player_id` is "" when `line` carries no prefix."""
    m = _ID_PREFIX.match(line)
    if not m:
        return "", line
    return m.group("id"), line[m.end():]

# The "Name POS • TEAM" cell, split out from the rest of the tab row.
# Same status-tag handling as build_line_re's per-line pattern (captured in
# both observed positions, optional either way) - the mechanism the two
# paths share is finding the name/status/position/team inside one blob of
# text; only where the OWNER token lives differs between them.
_TAB_NAME = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?:(?P<status1>" + "|".join(_STATUS_TAGS) + r")\s+)?"
    r"(?P<pos>TQB|QB|RB|WR|TE|K|DST)\s+"
    r"(?:(?P<status2>" + "|".join(_STATUS_TAGS) + r")\s+)?"
    r"[•\-]\s*(?P<team>[A-Z]{2,3})\s*$")


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
    # str() every code before it is measured or escaped. `owner_codes` comes
    # from hand-edited YAML and a human is expected to edit it before week 1;
    # a code that looks numeric ("12", "50s" is fine but "12" is not) is
    # YAML-parsed as an int, and both `len()` and `re.escape()` raise
    # TypeError on it. Crashing the whole weekly command over a quoting
    # detail in a config file is a failure the user cannot diagnose from the
    # traceback, and there is no ambiguity about what an int owner code
    # means as a page token: its decimal spelling.
    codes = "|".join(re.escape(str(c))
                     for c in sorted(owner_codes, key=lambda c: len(str(c)),
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

    SPACE PATH ONLY. On that page the owner token sits in the running text
    with no delimiter marking where it ends, so a closed list is the only
    thing standing between a real manager code and a mis-parsed first name
    (F4) - see build_line_re's docstring. classify_avail_tab below is the
    tab-delimited page's counterpart, and needs no such list, because that
    page's owner cell is its own tab field and cannot be confused with a
    player's name no matter what it contains.

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


def classify_avail_tab(avail):
    """Sort a TAB-PATH owner cell into "available", "owned", or None.

    TAB PATH ONLY - classify_avail above is the space-delimited page's
    counterpart. There, an enumerated owner_codes list is essential because
    the owner token is embedded in running text with no delimiter, so a
    player's own first name could be mistaken for one (F4). Here the owner
    cell is its OWN tab field: it cannot be confused with any part of the
    name/position/team cell next to it, no matter what text it holds. F4 is
    therefore impossible BY CONSTRUCTION on this path, not merely guarded
    against by a closed list - and a closed list would not even work here,
    since a real value is a (possibly truncated, ellipsised) fantasy TEAM
    name - "Stupid...", "EM 50s" - not a manager abbreviation. The set of
    truncated team names is open-ended and depends on the export's column
    width, so there is nothing stable to enumerate.

    "available" still covers a genuine free agent ("FA") or a
    waiver-claimable player ("W" or "W (9/16)"). Any OTHER non-empty value
    means the cell names a fantasy team, i.e. the player is owned.

    An EMPTY cell is deliberately NOT "available": "no owner" and "the
    column came back blank" are different facts, and treating the second as
    the first would silently rank an indeterminate row as claimable. Returns
    None so the caller refuses it, the same as any other unrecognized shape.
    """
    if avail == "FA" or _AVAIL_WAIVER.match(avail):
        return "available"
    if avail == "":
        return None
    return "owned"


def _load_groups(profile_path):
    with open(profile_path) as fh:
        raw = yaml.safe_load(fh) or {}
    groups = raw.get("groups", {})
    # Validate EVERY group in the profile, not just the one this call is
    # about to parse - a bad name in a group nobody happens to be testing
    # this week is exactly the failure mode that let `sacks`/`fg_under_30`
    # through, and it should be caught the moment the profile loads, not
    # the first time someone parses that particular group.
    for group_name, group in groups.items():
        _check_group_stats(profile_path, group_name, group.get("stats", []))
    return groups


def _load_owner_codes(profile_path):
    """The league's manager abbreviations, every one of them a string.

    Coerced here as well as in `build_line_re` because `classify_avail`
    tests `avail in owner_codes` against a token lifted from the page, which
    is always a string: an int code from YAML would build into the regex
    (after build_line_re's own str()) and then fail that membership test,
    so the row would match and then classify as unknown.
    """
    with open(profile_path) as fh:
        raw = yaml.safe_load(fh) or {}
    return [str(c) for c in raw.get("owner_codes", [])]


def _parse_row(line, line_re):
    """One row's (avail, name, pos, team, status1, status2, tokens,
    player_id), or None.

    Dispatches PER LINE on whether it contains a tab: the Playwright
    `capture()` path used by the scheduled in-season job emits TAB-delimited
    rows (`_TAB_LINE`/`_TAB_NAME`); the older browser-tool capture path -
    the source of the committed fixture - emits space-delimited rows matched
    by `line_re` (`build_line_re`). Both are real, currently-produced
    shapes, so a file is never assumed to be entirely one or the other -
    each line is matched against whichever pattern fits its own delimiter.

    `tokens` is the "rest" segment (OPP plus the trailing stat columns)
    split into individual fields - by tab on the tab path, by whitespace on
    the space path - so `expect_tokens`/the stat-block slice downstream work
    identically regardless of which path produced the row.

    `player_id` is stripped off the FRONT of `line` first, via
    `_strip_id_prefix`, before either delimiter path ever sees it - so
    `tokens` (and therefore `expect_tokens`) is computed exactly as if the
    prefix had never been there. "" when the line carries no such prefix
    (only ever seen on the tab path in practice - see `_ID_PREFIX`'s
    docstring - but stripped unconditionally so a future space-path capture
    that grew one would not need this function changed again).
    """
    player_id, line = _strip_id_prefix(line)
    if "\t" in line:
        m = _TAB_LINE.match(line)
        if not m:
            return None
        name_m = _TAB_NAME.match(m.group("namecell"))
        if not name_m:
            return None
        # .strip() here mirrors the space path below. Without it a
        # whitespace-only owner cell ("\t \t") is a non-empty string and
        # classify_avail_tab's "any other non-empty value means owned" rule
        # files it as OWNED - the one classification that is silent (an
        # owned row is merely excluded, with no warning), so a blank column
        # would quietly remove a genuine free agent from the waiver board.
        # Stripped, it becomes "" and classifies as None: refused loudly,
        # which is the documented behavior for an indeterminate cell.
        return (m.group("avail").strip(), name_m.group("name").strip(),
                name_m.group("pos"), name_m.group("team"),
                name_m.group("status1"), name_m.group("status2"),
                m.group("rest").split("\t"), player_id)
    m = line_re.match(line)
    if not m:
        return None
    return (m.group("avail").strip(), m.group("name").strip(),
            m.group("pos"), m.group("team"),
            m.group("status1"), m.group("status2"),
            m.group("rest").split(), player_id)


# The page stamps its own freshness: "REPORT UPDATED AS OF 8/31/26 10:26 PM
# EST". The in-season spec named this as THE staleness signal and nothing
# read it until 2026-08-31 - so a capture that silently returned a cached or
# days-old page was indistinguishable from a fresh one, and the alert would
# push a confident lineup off it ninety minutes before kickoff.
_REPORT_STAMP_RE = re.compile(r"REPORT UPDATED AS OF\s+(.+?)\s*$",
                              re.IGNORECASE | re.MULTILINE)
# "8/31/26 10:26 PM EST" - month and day are NOT zero-padded on the real
# page, which %m/%d accept. The trailing timezone word is dropped rather
# than parsed: %Z cannot reliably read "EST" across platforms, and the only
# thing this timestamp is used for is an AGE in hours against a local clock
# that is already in the league's timezone.
_REPORT_STAMP_FORMAT = "%m/%d/%y %I:%M %p"


def read_report_stamp(path):
    """The page's own "REPORT UPDATED AS OF" time, or None if absent.

    Returns a naive datetime in the page's own (Eastern) timezone. None means
    the page carried no stamp - which is NOT the same as a stale page and must
    not be reported as one: an older capture path, or a layout change, would
    both produce it, and treating "unknown" as "stale" would cry wolf every
    single run. Callers say "could not be read", never "is old".

    Deliberately separate from `parse` rather than another return value:
    `parse` returns a plain list and dozens of call sites unpack it that way,
    so widening it to a tuple to carry one timestamp would be a breaking
    change to every one of them for no gain.
    """
    with open(path) as fh:
        m = _REPORT_STAMP_RE.search(fh.read())
    if not m:
        return None
    raw = m.group(1).strip()
    # Drop a trailing timezone token ("EST"/"EDT") if present; see the format
    # constant above for why it is not parsed.
    parts = raw.split()
    if parts and parts[-1].isalpha() and len(parts[-1]) <= 4:
        raw = " ".join(parts[:-1])
    try:
        return datetime.datetime.strptime(raw, _REPORT_STAMP_FORMAT)
    except ValueError:
        return None


# A genuine wrong-week pair disagrees on essentially EVERY shared team; the
# noise floor is a handful. Measured on real captures 2026-08-31, comparing
# MODAL opponents (see `_modal_opponents` for why the mode and not the set):
#
#   all four same-run pages : 2 of 33 shared teams (6.1%)
#   week-1 vs week-2 DST    : 32 of 32 (100%)
#
# The 6.1% is a REAL defect on CBS's TQB page, not noise in this code: GB and
# MIA dissent there while the RB-WR-TE, K and DST pages all agree with each
# other, part of a contiguous chain MIN->GB->LV->MIA->CLE whose OPP cells sit
# one row out. It is confined to the OPP column - every one of those rows
# still carries its full 17 tokens, verified against a correct row on the
# same page, so the positional STAT block (sliced off the END) is unaffected
# and nothing is mis-scored by it.
#
# 25% sits an order of magnitude above the observed noise and far below a
# real mismatch. It is deliberately NOT 0: a check that fires on every
# single run because of a known upstream quirk gets ignored, and an ignored
# check is worse than none.
WEEK_MISMATCH_RATIO = 0.25


def _modal_opponents(pages):
    """{team: {page_label: that page's MODAL opponent for the team}}.

    THE MODE, NOT THE SET, and this is not a detail. CBS's own pages carry a
    small number of rows whose OPP cell disagrees with the rest of their
    team - measured on a real 1710-row RB/WR/TE capture: ARI 58 rows say
    "@LAC" and one says "@SEA"; JAC 45 say "CLE" and one "@LAC"; PIT 75 say
    "ATL" and one "@MIN". Three strays in 1710 rows (0.2%), all on players
    whose listed team CBS's opponent data has evidently not caught up with.
    Those rows are NOT misaligned - every one carries the full 17 tokens, so
    the positional stat block is correct and nothing is mis-scored by them.

    Treating a page's opinion as the SET of opponents it mentions therefore
    flagged three whole teams as cross-page conflicts when all four pages
    actually agreed. The mode is what "this page says team X plays Y" means:
    58 votes to 1 is not a disagreement.
    """
    counts = {}
    for label, rows in pages.items():
        for r in rows:
            if not r.opp:
                continue
            tally = counts.setdefault(r.team, {}).setdefault(label, {})
            tally[r.opp] = tally.get(r.opp, 0) + 1
    modal = {}
    for team, per_label in counts.items():
        modal[team] = dict(
            # -count first, then the opponent string, so an exact tie is
            # broken deterministically rather than by dict ordering.
            (label, sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[0][0])
            for label, tally in per_label.items())
    return modal


def week_conflicts(pages):
    """Teams whose OPPONENT disagrees between two pages of the same run.

    `pages` is {label: [PlayerProjection]}. Returns a sorted list of
    (team, {label: opp}) for every team appearing on more than one page with
    more than one distinct opponent.

    WHY THIS IS THE WEEK CHECK. Every page captured in one run is supposed to
    be the same NFL week, and the TQB and DST pages each list ALL 32 teams,
    so they overlap completely. A team's opponent is fixed for a given week,
    so two pages disagreeing about it are two different weeks. This needs no
    external schedule and nothing that can go stale: the pages check each
    other.

    Returns the raw list; callers should judge it by RATIO against
    `WEEK_MISMATCH_RATIO`, not by "any conflict at all" - see that constant
    for the measured reason.
    """
    out = []
    for team, per_label in sorted(_modal_opponents(pages).items()):
        if len(per_label) < 2:
            continue
        if len(set(per_label.values())) > 1:
            out.append((team, per_label))
    return out


def shared_team_count(pages):
    """How many teams appear on more than one of `pages`.

    The denominator for `week_conflicts`. Zero means the pages have no team
    in common, so the check could not run at all - which is NOT the same as
    "no conflict found" and must never be rendered as a clean result.
    """
    seen = {}
    for label, rows in pages.items():
        for r in rows:
            if r.opp:
                seen.setdefault(r.team, set()).add(label)
    return sum(1 for labels in seen.values() if len(labels) > 1)


def internally_inconsistent_opponents(rows):
    """Teams on ONE page whose opponent does not name them back.

    If A's opponent is B, B's opponent must be A. A page that fails this is
    scrambled or misaligned regardless of which week it is - a different
    failure from `week_conflicts`, which compares two pages and can only see
    a MIXED week, never a single page that is internally wrong.

    Measured 2026-08-31: the DST page scores 0 on both a week-1 and a week-2
    capture; the TQB page scores 4, which is the upstream OPP-column defect
    documented at `WEEK_MISMATCH_RATIO`.
    """
    modal = _modal_opponents({"page": rows})
    opp = dict((team, per["page"].lstrip("@"))
               for team, per in modal.items())
    bad = []
    for team, other in sorted(opp.items()):
        if other not in opp:
            bad.append((team, other, "opponent not listed on this page"))
        elif opp[other] != team:
            bad.append((team, other, "but %s plays %s" % (other, opp[other])))
    return bad


def parse(path, group, week, profile_path=DEFAULT_PROFILE, season=2026):
    """Rows from one saved weekly-projections page, as PlayerProjection.

    Raises ValueError on a stat block whose width has moved - the layout is
    positional, so a changed column count silently reads the wrong stat into
    every field.

    Also raises (F4) if any line looks like a player row - a reasonable
    signal being that it contains " • " - but does not match either the
    tab-delimited or the space-delimited row shape (see `_parse_row`),
    naming the count and the first offending line. A line that fails to
    match this way is not necessarily "not a player row": the observed real
    case ("DJ Moore WR • CHI ...", missing its leading avail token) is a
    genuine player row that the (space-path) regex would otherwise misread
    under the WRONG NAME once the avail group is loose enough to match it by
    accident. Reading a page PARTIALLY - silently dropping the lines that do
    not fit - is worse than refusing it outright, so every such line is
    collected and reported together rather than skipped one at a time.
    """
    groups = _load_groups(profile_path)
    if group not in groups:
        raise ValueError(
            "unknown group %r; %s defines %s"
            % (group, profile_path, sorted(groups)))
    fields = groups[group]["stats"]
    expect_tokens = groups[group].get("expect_tokens")

    owner_codes = _load_owner_codes(profile_path)
    line_re = build_line_re(owner_codes)

    out = []
    unmatched = []
    with open(path) as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue
            parsed = _parse_row(line, line_re)
            if parsed is None:
                if " • " in line:
                    unmatched.append(line)
                continue
            avail, name, pos, team, status1, status2, tokens, player_id = parsed
            if expect_tokens is not None and len(tokens) != expect_tokens:
                raise ValueError(
                    "%s: %r has %d tokens after the team code, expected %d - "
                    "the layout is positional and a shifted column count "
                    "reads the wrong stat into every field, even though the "
                    "trailing slice below would still return a plausible "
                    "block of the right WIDTH"
                    % (path, name, len(tokens), expect_tokens))
            block = tokens[-len(fields):]
            if len(block) != len(fields):
                raise ValueError(
                    "%s: stat block for %r has %d columns, expected %d - the "
                    "layout is positional and a shift reads the wrong stat "
                    "into every field"
                    % (path, name, len(block), len(fields)))
            # A field name repeated in `fields` means those columns are
            # SUMMED into that one key (see the module docstring) - e.g.
            # CBS's `1-19` and `20-29` field-goal columns both feed
            # `fg_u30`. The `_` skip runs BEFORE accumulation so a
            # repeated `_` (there will be many, marking columns the scoring
            # engine ignores) can never create a stat named `_`.
            stats = {}
            for field_name, token in zip(fields, block):
                if field_name == "_":
                    continue
                try:
                    value = float(token)
                except ValueError:
                    raise ValueError(
                        "%s: %r has non-numeric %s %r"
                        % (path, name, field_name, token))
                stats[field_name] = stats.get(field_name, 0.0) + value
            # fg_missed (league-scored, -1 each) is DERIVED - SUB-50 ATTEMPTS
            # minus SUB-50 MADE - which no single CBS column holds, so a
            # positional map cannot express it directly.
            #
            # SUB-50 ONLY, NOT total ATT minus total FG: poc/validate_k_weekly.py
            # scores 17/17 real weeks EXACT against the live league site and its
            # own evidence proves 50+ misses carry NO penalty (week 6: 0-for-2
            # from 50+, engine score still exact against CBS). That script's
            # `missed_under_50` is the arbiter this project has for what
            # `fg_missed` means, and it explicitly excludes the 50+ band. An
            # earlier version of this derivation used total ATT minus total FG
            # (EVERY miss, including 50+) and over-penalized every kicker with
            # a 50+ attempt - see sources/cbs-weekly.yaml's K group comment for
            # the measured size of that bug.
            #
            # A profile that wants this maps CBS's own four sub-50
            # ATTEMPTS columns (1-19, 20-29, 30-39, 40-49) onto the single
            # internal name `fg_att_u50` (repeated - see the summing rule
            # above); if a row produced it, the sub-50 MADE total (already
            # sitting in `fg_u30`/`fg_30_39`/`fg_40_49`, which this does NOT
            # consume - they stay scored normally) is subtracted from it here
            # and the internal name is removed, so it never reaches a
            # PlayerProjection's stats - the scoring engine has never heard
            # of it, deliberately (it is outside scoring.STAT_KEYS). A
            # profile that does not map it is unaffected: this is a no-op
            # unless it is present. Clamped at 0 as a defensive floor - a
            # projection should never show more makes than attempts, but
            # `fg_missed` scores at -1 and a negative value here would pay
            # POINTS for a miss that didn't happen.
            if "fg_att_u50" in stats:
                made_u50 = (stats.get("fg_u30", 0.0)
                            + stats.get("fg_30_39", 0.0)
                            + stats.get("fg_40_49", 0.0))
                missed_u50 = stats.pop("fg_att_u50") - made_u50
                stats["fg_missed"] = max(0.0, missed_u50)
            status = status1 or status2 or ""
            out.append(PlayerProjection(
                name=name,
                team=normalize_team(team),
                pos=pos,
                source="cbs-weekly",
                source_year=season,
                games=1.0,
                stats=stats,
                raw_name=name,
                avail=avail,
                status=status,
                player_id=player_id,
                # `week` was accepted by this function and never used until
                # 2026-08-31. Recording it is what lets anything downstream
                # notice that a saved week-3 page was handed to a week-4 run
                # - which previously exited 0 and produced confident advice.
                week=week,
                # OPP is always the FIRST token after the team code, ahead of
                # the positional stat block (which is sliced off the END, so
                # the two never contend). Verified live against all four
                # group pages 2026-08-31.
                opp=tokens[0] if tokens else "",
            ))

    if unmatched:
        raise ValueError(
            "%s: %d line(s) contain %r (look like a player row) but do not "
            "match the expected layout - a page that cannot be read RELIABLY "
            "is worse than one refused outright, since a line that fails to "
            "match here can also silently mis-match under the WRONG NAME "
            "rather than simply vanish (see F4). First offending line: %r"
            % (path, len(unmatched), " • ", unmatched[0]))

    return out

"""Parse the CBS league site's weekly projections table from saved page text.

NO NETWORK I/O. The page is fetched by an operator (browser tools) and saved;
this module parses the file. That keeps every test a fixture test and keeps the
parser honest about a layout it cannot control.
"""

import re
import yaml

from sffl.identity import normalize_team
from sffl.schema import PlayerProjection

DEFAULT_PROFILE = "sources/cbs-weekly.yaml"

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
    return raw.get("groups", {})


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
    """One row's (avail, name, pos, team, status1, status2, tokens), or None.

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
    """
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
                m.group("rest").split("\t"))
    m = line_re.match(line)
    if not m:
        return None
    return (m.group("avail").strip(), m.group("name").strip(),
            m.group("pos"), m.group("team"),
            m.group("status1"), m.group("status2"),
            m.group("rest").split())


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
            avail, name, pos, team, status1, status2, tokens = parsed
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
            stats = {}
            for field_name, token in zip(fields, block):
                if field_name == "_":
                    continue
                try:
                    stats[field_name] = float(token)
                except ValueError:
                    raise ValueError(
                        "%s: %r has non-numeric %s %r"
                        % (path, name, field_name, token))
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

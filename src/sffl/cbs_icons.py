"""CBS's own injury designations, read from the league pages' icon markup.

WHY THIS EXISTS. CBS draws a player's designation as an icon, and the text a
capture saves (`innerText`) drops icons. Every live capture through 10-19 held
0 designations in 1,876 rows, so `cbs_weekly.OUT_STATUSES` - the gate that
never starts an O, IR, PUP or SUSP player - never had anything to act on. A
read-only probe of the live pages on 2026-10-20 found the designation sitting
in the markup at rest, no click or hover needed:

    <span class="playerIconsWrapper">
      <span title="<label>">
        <a class="playerLink" subtab="Injury Report" aria-label="Injury Report: <label>">
          <span class="icon-red_cross"></span></a></span> ...

`sffl.capture` asks the page for each row's icon links (same `page.evaluate`
call as the row text) and writes them to a sidecar `<page>.icons.json`, keyed
by CBS id. This module turns those raw labels into the parser's tags. PURE
apart from `load_sidecar`: no network, no browser.

THE LABELS (all seen on the week-7 RB/WR/TE page, 197 of 1,714 rows):

    Injury Report: <body part>: Questionable for Week 7 at <opponent>
    Injury Report: <body part>: Out for Week 7 vs. <opponent>
    Injury Report: <body part>: Injured Reserve. Expected Return - Week 9
    Injury Report: <body part>: Physically Unable to Perform. Expected Return - Week 7
    Injury Report: <body part>: Retired          (also Did Not Report, NFI-R)
    Suspension: Suspended for <N> games
    Update: <team>'s <player>: <headline>       (news headline only, no body)
    Status: Cold Player                         (CBS's hot/cold trend)

A LABEL COUNTS ONLY FOR THE WEEK IT NAMES. A bye player's label names his next
game ("Questionable for Week 8" on the week-7 page, 9 rows), and CBS leaves old
labels up (7 rows still named week 5 or 6 on 2026-10-20). A label naming
another week is never applied to this week's lineup. A label naming no week
(IR, PUP, a suspension, retired) always applies.

AN UNREADABLE LABEL IS NEVER A CLEAN BILL OF HEALTH, and never a guess. A
designation phrase this module does not know maps to no tag, so it cannot
bench anyone, but it is kept (with its raw text) so a caller can show it.
"""

import json
import os
import re
from collections import namedtuple

SIDECAR_SUFFIX = ".icons.json"

# One parsed icon. `kind` is "designation", "news", "trend" or "unknown".
# `tag` is the parser's designation tag (see cbs_weekly._STATUS_TAGS), "" when
# the icon is not a designation or its phrase is unknown. `week` is the week
# the label names, None when it names none.
Icon = namedtuple(
    "Icon",
    "kind tag status body week opponent expected_return label icon_class")

# The designation phrases CBS prints, lowercased, and the tag each maps to.
# Exact matches only: a prefix match would let a new phrase that merely starts
# with "out" bench a player on a guess.
#
# Retired and Did Not Report are not on the NFL's report vocabulary, but both
# mean the player will not take the field, so they gate like Out. NFI-R (the
# non-football injury reserve list) is an IR list.
_TAGS = {
    "questionable": "Q",
    "doubtful": "D",
    "out": "O",
    "injured reserve": "IR",
    "nfi-r": "IR",
    "physically unable to perform": "PUP",
    "suspended": "SUSP",
    "retired": "O",
    "did not report": "O",
}

# Icon classes that mark a designation even when the label is unreadable.
_DESIGNATION_ICONS = frozenset((
    "icon-red_cross", "icon-player-status-ir", "icon-player-status-pup",
    "icon-suspended"))

_FOR_WEEK = re.compile(r" for Week (\d+) (at|vs\.?) (.+)$")
_EXPECTED_RETURN = re.compile(r"\. Expected Return - Week (\d+)$")


def tag_for(status):
    """The parser tag for one CBS designation phrase, "" when unknown."""
    return _TAGS.get((status or "").strip().lower(), "")


def parse_icon(icon_class, label):
    """One icon link's raw class and label -> an `Icon`."""
    icon_class = (icon_class or "").strip()
    label = (label or "").strip()

    if label.startswith("Injury Report:"):
        text = label[len("Injury Report:"):].strip()
        # The status sits after the LAST ": " - a body part could carry a
        # colon, a status phrase never does.
        if ": " in text:
            body, rest = text.rsplit(": ", 1)
        else:
            body, rest = "", text
        week = opponent = expected = None
        m = _FOR_WEEK.search(rest)
        if m:
            # "at Chicago" / "vs. Chicago": the home/away word stays with it.
            week = int(m.group(1))
            opponent = "%s %s" % (m.group(2), m.group(3).strip())
            rest = rest[:m.start()]
        m = _EXPECTED_RETURN.search(rest)
        if m:
            expected = int(m.group(1))
            rest = rest[:m.start()]
        status = rest.strip()
        return Icon("designation", tag_for(status), status, body.strip(), week,
                    opponent, expected, label, icon_class)

    if label.startswith("Suspension:"):
        text = label[len("Suspension:"):].strip()
        return Icon("designation", "SUSP", text or "Suspended", "", None, None,
                    None, label, icon_class)

    if label.startswith("Update:"):
        return Icon("news", "", "", "", None, None, None, label, icon_class)

    if label.startswith("Status:"):
        return Icon("trend", "", label[len("Status:"):].strip(), "", None,
                    None, None, label, icon_class)

    if icon_class in _DESIGNATION_ICONS:
        # A designation icon with a label this module cannot read: kept as a
        # designation with no tag, so it is shown and never benches anyone.
        return Icon("designation", "", label or icon_class, "", None, None,
                    None, label, icon_class)

    return Icon("unknown", "", "", "", None, None, None, label, icon_class)


def applies(icon, week):
    """True when this designation counts for `week` (see the module docstring)."""
    return icon.kind == "designation" and (icon.week is None or icon.week == week)


def designation(icons, week):
    """The designation that counts for `week`, or None.

    A tagged designation wins over an unreadable one, so a row carrying both
    is gated on what CBS said plainly.
    """
    live = [i for i in icons if applies(i, week)]
    for i in live:
        if i.tag:
            return i
    return live[0] if live else None


def build_sidecar(rows, url, captured_at):
    """The sidecar dict for one captured page.

    `rows` is what `capture._ID_EXTRACT_JS` returned with icons on: dicts with
    "id", "text" and "icons" (a list of {"icon", "label", "subtab"}). Only rows
    that carry at least one icon are kept; `rows_scanned` says how many rows
    were looked at, so an empty `icons` reads as "nobody had one" rather than
    as "nothing was read".
    """
    icons = {}
    for row in rows:
        found = [{"icon": str(i.get("icon") or ""),
                  "label": str(i.get("label") or ""),
                  "subtab": str(i.get("subtab") or "")}
                 for i in (row.get("icons") or [])]
        if found and row.get("id"):
            icons.setdefault(str(row["id"]), []).extend(found)
    return {"url": url, "captured_at": captured_at, "rows_scanned": len(rows),
            "icons": icons}


def sidecar_path(text_path):
    """Where `capture` writes the sidecar for the page saved at `text_path`."""
    return os.path.splitext(text_path)[0] + SIDECAR_SUFFIX


def load_sidecar(path):
    """{cbs_id: [Icon, ...]} from a sidecar file. Raises ValueError on a bad shape."""
    with open(path) as fh:
        raw = json.load(fh)
    if (not isinstance(raw, dict) or not isinstance(raw.get("icons"), dict)
            or not isinstance(raw.get("rows_scanned"), int)):
        raise ValueError("%s is not a CBS icon sidecar" % path)
    out = {}
    for cbs_id, entries in raw["icons"].items():
        if not isinstance(entries, list):
            raise ValueError("%s: icons for %s are not a list" % (path, cbs_id))
        parsed = []
        for e in entries:
            if not isinstance(e, dict):
                raise ValueError("%s: an icon for %s is not an object"
                                 % (path, cbs_id))
            parsed.append(parse_icon(e.get("icon"), e.get("label")))
        out[str(cbs_id)] = parsed
    return out


Applied = namedtuple("Applied", "applied other_week unreadable")


def apply_designations(projections, icons_by_id, week):
    """Set each projection's `status` from CBS's label, where its text carried none.

    `projections` are `PlayerProjection`s (mutated in place), joined by CBS id
    only - the sidecar and the page are the same capture, so the id is exact.
    A status the page text already carried is left alone. Returns `Applied`:
    (name, tag) pairs set, (name, label) pairs skipped because they name
    another week, and (name, label) pairs whose phrase is unknown.
    """
    applied, other_week, unreadable = [], [], []
    for p in projections:
        icons = icons_by_id.get(p.player_id) if p.player_id else None
        if not icons:
            continue
        d = designation(icons, week)
        if d is None:
            other_week.extend((p.name, i.label) for i in icons
                              if i.kind == "designation")
            continue
        if not d.tag:
            unreadable.append((p.name, d.label))
            continue
        if not p.status:
            p.status = d.tag
            applied.append((p.name, d.tag))
    return Applied(applied, other_week, unreadable)


def detail_text(icon):
    """A short detail for the digest: the body part, then the week it names."""
    bits = []
    if icon.body:
        bits.append(icon.body)
    if icon.week is not None:
        bits.append(("for week %d %s" % (icon.week, icon.opponent)).strip()
                    if icon.opponent else "for week %d" % icon.week)
    if icon.expected_return is not None:
        bits.append("expected back week %d" % icon.expected_return)
    return "; ".join(bits)


def roster_rows(roster, icons_by_id, week, reported_date):
    """Injury-feed rows (the `injuries` contract) for rostered players CBS marks.

    One row per designation that counts for `week` or a LATER week (a bye
    player's label names his next game, and that is news). Labels for an
    EARLIER week are about games already played and are left out. Rows carry
    outlet "cbs" and the player's CBS id, so `injuries.for_roster` matches
    them by id.
    """
    out = []
    for r in roster:
        for icon in icons_by_id.get(r.player_id, []) if r.player_id else []:
            if icon.kind != "designation":
                continue
            if icon.week is not None and icon.week < week:
                continue
            out.append({
                "player": r.name, "team": r.team, "status": icon.status,
                "notes": detail_text(icon), "reported_date": reported_date,
                "source": "cbs", "cbs_id": r.player_id})
    return out

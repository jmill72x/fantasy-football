"""The direct injury feed: nflverse, Sleeper and ESPN, matched to CBS ids.

Built 2026-10-20 to replace StatsDeck's `get_injuries` (the plan:
`docs/plans/2026-10-20-replace-statsdeck.md`). `sffl injuries-fetch` writes
the same `{"report": [...], "intel": [...]}` file `sffl.injuries` reads, plus
a `meta` block saying how each source did. Until the switch it writes to its
own file (`injuries-<kind>.direct.json`), never the one the live alert reads.

THE SOURCES, one GET each per run:

- **nflverse's injury report** - the record. The official NFL report, as a
  CSV in nflverse's GitHub release (CC-BY 4.0), published once a day (its
  schedule says 07:00 UTC). It is exactly what StatsDeck's `report` was, so
  on a Friday at 16:45 it is Thursday's report: each row carries `as_of`, the
  time nflverse published it, so the digest can say so.
- **ffverse/DynastyProcess `db_playerids.csv`** - the id crosswalk that turns
  every source's player id into CBS's. Refreshed weekly upstream; cached here
  for a week. GPL-3.0: read at run time, never committed.
- **Sleeper's `/players/nfl`** - same-day statuses. Sleeper's docs: free for
  non-commercial use, this call at most once a day; cached for 24 hours.
- **ESPN's public injuries feed** - the news text. Jeff's call, 2026-10-20:
  "Let's go with espn since it's 3 times a week and non-commercial", knowing
  ESPN's terms forbid automated extraction. So: one call per run, an honest
  User-Agent, no retry loop, and an HTTP 403 or 429 switches ESPN off until a
  person deletes the marker file (`espn-off.json` in the cache folder).

HOW IT FAILS. nflverse failing fails the whole fetch - no file, so the alert
says INJURY DATA UNAVAILABLE - because an empty official report would render
as "no designations on your roster", a clean bill of health nobody measured.
Every other source failing is recorded in `meta.sources` and printed in the
digest by `sffl.injuries.source_notes`.

LIMITS. HTTPS only, to an allowlist of hosts (redirects checked too), a
timeout and a byte cap on every response, and only CSV and JSON are parsed.
Standard library only.

CHANGE FIELDS. No source says what a status moved from. The fetcher keeps its
own last snapshot (`injury-state.json` in the cache folder) and sets
`previous_status` and `status_since` on a row whose status differs from the
previous run's - "first seen by this pipeline at <time>", never a guess about
when the change really happened. On Sunday that is exactly "what changed
since Friday's run".
"""

import csv
import datetime
import io
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = ("sffl-injuries/1.0 (personal, non-commercial fantasy digest; "
              "+https://github.com/jmill72x/fantasy-football)")
TIMEOUT_S = 60

NFLVERSE_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
                "injuries/injuries_%d.csv")
NFLVERSE_STAMP_URL = ("https://github.com/nflverse/nflverse-data/releases/"
                      "download/injuries/timestamp.json")
CROSSWALK_URL = ("https://raw.githubusercontent.com/dynastyprocess/data/"
                 "master/files/db_playerids.csv")
SLEEPER_URL = "https://api.sleeper.app/v1/players/nfl"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"

# Where a request may go, redirects included. GitHub serves release files
# from its own download hosts.
ALLOWED_HOSTS = frozenset((
    "github.com", "objects.githubusercontent.com",
    "release-assets.githubusercontent.com", "raw.githubusercontent.com",
    "api.sleeper.app", "site.api.espn.com",
))

# Byte caps, several times what each source sent on 2026-10-20 (205 KB,
# 43 B, 2.6 MB, 14.7 MB, 8.7 MB).
MAX_NFLVERSE = 10 * 1024 * 1024
MAX_STAMP = 64 * 1024
MAX_CROSSWALK = 20 * 1024 * 1024
MAX_SLEEPER = 64 * 1024 * 1024
MAX_ESPN = 48 * 1024 * 1024

CROSSWALK_MAX_AGE_S = 7 * 24 * 3600
SLEEPER_MAX_AGE_S = 24 * 3600

ESPN_OFF_FILE = "espn-off.json"
STATE_FILE = "injury-state.json"

_NFLVERSE_COLUMNS = ("season", "season_type", "week", "gsis_id", "full_name",
                     "team", "position", "report_status", "practice_status",
                     "report_primary_injury", "report_secondary_injury")
_CROSSWALK_COLUMNS = ("cbs_id", "gsis_id", "sleeper_id", "espn_id")


class FetchError(Exception):
    """A source could not be read. `status` is the HTTP status, if there was one."""

    def __init__(self, message, status=None):
        super(FetchError, self).__init__(message)
        self.status = status


def check_url(url):
    """Raise FetchError unless `url` is https to an allowed host."""
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise FetchError("refused %s: only https to %s"
                         % (url, ", ".join(sorted(ALLOWED_HOSTS))))


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl)


def http_get(url, max_bytes, timeout=TIMEOUT_S):
    """GET `url` once: allowed hosts only, a timeout, at most `max_bytes`."""
    check_url(url)
    opener = urllib.request.build_opener(_CheckedRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    host = urllib.parse.urlparse(url).hostname
    try:
        with opener.open(req, timeout=timeout) as resp:
            check_url(resp.geturl())
            data = resp.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise FetchError("HTTP %d from %s" % (exc.code, host), status=exc.code)
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        raise FetchError("%s from %s: %s" % (type(exc).__name__, host, exc))
    if len(data) > max_bytes:
        raise FetchError("%s sent more than %d bytes; refused"
                         % (host, max_bytes))
    return data


# --------------------------------------------------------------- parsing

def _id(value):
    """A source id as a clean string: "" for blank or NA, no trailing ".0"."""
    text = str(value if value is not None else "").strip()
    if text in ("", "NA", "None", "nan"):
        return ""
    return text[:-2] if text.endswith(".0") else text


def parse_crosswalk(text):
    """{"gsis"|"sleeper"|"espn": {source id: cbs id}} from db_playerids.csv."""
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in _CROSSWALK_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError("crosswalk is missing column(s) %s" % ", ".join(missing))
    out = {"gsis": {}, "sleeper": {}, "espn": {}}
    for row in reader:
        cbs = _id(row.get("cbs_id"))
        if not cbs:
            continue
        for kind, col in (("gsis", "gsis_id"), ("sleeper", "sleeper_id"),
                          ("espn", "espn_id")):
            source_id = _id(row.get(col))
            if source_id:
                out[kind].setdefault(source_id, cbs)
    return out


def parse_stamp(data):
    """nflverse's `timestamp.json` -> "YYYY-MM-DD HH:MM TZ" (seconds dropped)."""
    raw = json.loads(data.decode("utf-8"))
    stamp = str(raw.get("last_updated") or "") if isinstance(raw, dict) else ""
    m = re.match(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(?::\d{2})?(?: (\S+))?$",
                 stamp.strip())
    if not m:
        raise ValueError("nflverse timestamp has no usable last_updated: %r"
                         % stamp)
    return " ".join(p for p in (m.group(1), m.group(2), m.group(3)) if p)


def parse_nflverse(text, as_of, crosswalk):
    """(week, rows): the latest week's official report rows, contract-shaped.

    "Latest" is the newest (season type, week) in the file - REG before
    POST - which is exactly what StatsDeck served as its `report`. A blank
    `report_status` (on the report for practice only) becomes "Not listed",
    StatsDeck's word for it, so a row never renders with no status.
    """
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in _NFLVERSE_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError("nflverse injuries file is missing column(s) %s"
                         % ", ".join(missing))
    all_rows = list(reader)
    if not all_rows:
        raise ValueError("nflverse injuries file has no rows")

    def order(row):
        return (1 if row["season_type"].strip().upper() == "POST" else 0,
                int(row["week"]))

    latest = max(order(r) for r in all_rows)
    week = latest[1]
    out = []
    for r in all_rows:
        if order(r) != latest:
            continue
        gsis = _id(r["gsis_id"])
        injuries = [x.strip() for x in (r["report_primary_injury"],
                                        r["report_secondary_injury"])
                    if x and x.strip() and x.strip() != "NA"]
        status = r["report_status"].strip()
        out.append({
            "player": r["full_name"].strip(),
            "team": r["team"].strip(),
            "position": r["position"].strip(),
            "status": status if status and status != "NA" else "Not listed",
            "practice": ("" if r["practice_status"].strip() in ("", "NA")
                         else r["practice_status"].strip()),
            "detail": ", ".join(injuries),
            "reported_date": as_of[:10],
            "as_of": as_of,
            "source": "nflverse",
            "gsis_id": gsis,
            "player_id": gsis,
            "cbs_id": crosswalk["gsis"].get(gsis, ""),
            "_key": gsis or r["full_name"].strip(),
        })
    return week, out


def _local_date_from_ms(ms):
    if not ms:
        return ""
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000.0).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _cbs_for_sleeper(pid, player, crosswalk):
    return (crosswalk["sleeper"].get(_id(pid))
            or crosswalk["gsis"].get(_id(player.get("gsis_id")))
            or crosswalk["espn"].get(_id(player.get("espn_id")))
            or "")


def sleeper_rows(players, crosswalk):
    """Intel rows for every active, rostered-in-the-NFL player Sleeper marks injured."""
    if not isinstance(players, dict):
        raise ValueError("Sleeper players feed is not an object")
    out = []
    for pid, p in players.items():
        if not isinstance(p, dict):
            continue
        status = (p.get("injury_status") or "").strip()
        if not status or not p.get("active") or not p.get("team"):
            continue
        name = (p.get("full_name") or "%s %s" % (p.get("first_name") or "",
                                                 p.get("last_name") or "")).strip()
        out.append({
            "player": name,
            "team": p.get("team") or "",
            "position": p.get("position") or "",
            "status": status,
            "notes": (p.get("injury_body_part") or "").strip(),
            "reported_date": _local_date_from_ms(p.get("news_updated")),
            "source": "sleeper",
            "sleeper_id": _id(pid),
            "cbs_id": _cbs_for_sleeper(pid, p, crosswalk),
            "_key": _id(pid),
        })
    return out


def sleeper_cleared_rows(players, crosswalk, prev_state):
    """A "cleared" row for each player the previous run saw injured whom
    Sleeper now lists with no injury status. Sleeper simply drops the status
    when a player is healthy, so without this the return of a questionable
    player would never be news."""
    out = []
    for key, old in prev_state.items():
        if not key.startswith("sleeper:") or not old.get("status"):
            continue
        pid = key.split(":", 1)[1]
        p = players.get(pid) if isinstance(players, dict) else None
        if not isinstance(p, dict) or (p.get("injury_status") or "").strip():
            continue
        if not p.get("active") or not p.get("team"):
            continue
        out.append({
            "player": (p.get("full_name") or "").strip() or pid,
            "team": p.get("team") or "",
            "position": p.get("position") or "",
            "status": "cleared",
            "notes": "",
            "reported_date": _local_date_from_ms(p.get("news_updated")),
            "source": "sleeper",
            "sleeper_id": pid,
            "cbs_id": _cbs_for_sleeper(pid, p, crosswalk),
            "_key": pid,
        })
    return out


_ESPN_ID = re.compile(r"/id/(\d+)/")


def _local_date_from_iso(text):
    if not text:
        return ""
    try:
        when = datetime.datetime.strptime(text.strip(), "%Y-%m-%dT%H:%MZ")
    except ValueError:
        return text.strip()[:10]
    when = when.replace(tzinfo=datetime.timezone.utc).astimezone()
    return when.strftime("%Y-%m-%d")


def espn_rows(data, crosswalk):
    """Intel rows for every player in ESPN's injuries feed, with ESPN's comment
    as the detail. "Active" rows stay: a recent comment on an active player
    (back at practice, cleared) is exactly the news the digest wants."""
    if not isinstance(data, dict) or not isinstance(data.get("injuries"), list):
        raise ValueError("ESPN injuries feed has no 'injuries' list")
    out = []
    for team in data["injuries"]:
        for item in (team.get("injuries") or []) if isinstance(team, dict) else []:
            if not isinstance(item, dict):
                continue
            athlete = item.get("athlete") or {}
            espn_id = ""
            for link in athlete.get("links") or []:
                m = _ESPN_ID.search(str((link or {}).get("href") or ""))
                if m:
                    espn_id = m.group(1)
                    break
            name = (athlete.get("displayName") or "").strip()
            if not name:
                continue
            comment = (item.get("shortComment") or item.get("longComment") or "")
            out.append({
                "player": name,
                "team": ((athlete.get("team") or {}).get("abbreviation") or ""),
                "position": ((athlete.get("position") or {}).get("abbreviation")
                             or ""),
                "status": (item.get("status") or "").strip(),
                "notes": " ".join(str(comment).split()),
                "reported_date": _local_date_from_iso(item.get("date")),
                "return_date": ((item.get("details") or {}).get("returnDate")
                                or ""),
                "source": "espn",
                "espn_id": espn_id,
                "cbs_id": crosswalk["espn"].get(espn_id, "") if espn_id else "",
                "_key": espn_id or name,
            })
    return out


# --------------------------------------------------------------- state

def derive_changes(rows, prev_state, now_iso):
    """Set `previous_status`/`status_since` on each row; return the new state.

    A row whose status differs from the previous run's gets that old status as
    `previous_status` and this run's time as `status_since`. An unchanged row
    keeps the time its status was first seen and no `previous_status`, so the
    digest's change block shows only what changed since the last run. A key
    never seen before starts its clock now, with nothing to compare.
    """
    state = {}
    for row in rows:
        key = "%s:%s" % (row["source"], row.get("_key") or "")
        status = row.get("status") or ""
        old = prev_state.get(key)
        if old is None:
            since, previous = now_iso, ""
        elif old.get("status") == status:
            since, previous = old.get("since") or now_iso, ""
        else:
            since, previous = now_iso, old.get("status") or ""
        row["status_since"] = since
        row["previous_status"] = previous
        if status != "cleared":
            state[key] = {"status": status, "since": since}
    return state


# --------------------------------------------------------------- caching

def _atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def cached_get(cache_dir, name, url, max_bytes, max_age_s, now, get,
               stale_ok=False):
    """(bytes, fetched_at, note): a cached copy younger than `max_age_s`, else
    one fresh GET. With `stale_ok`, a failed GET falls back to an older copy
    and says so in `note`."""
    path = os.path.join(cache_dir, name)
    meta_path = path + ".meta.json"
    cached_at = None
    if os.path.exists(path) and os.path.exists(meta_path):
        try:
            with open(meta_path) as fh:
                cached_at = datetime.datetime.fromisoformat(
                    json.load(fh)["fetched_at"])
        except (ValueError, KeyError, TypeError, OSError):
            cached_at = None
    if cached_at is not None and (now - cached_at).total_seconds() < max_age_s:
        with open(path, "rb") as fh:
            return fh.read(), cached_at.isoformat(timespec="seconds"), "cached"
    try:
        data = get(url, max_bytes)
    except FetchError as exc:
        if stale_ok and cached_at is not None:
            with open(path, "rb") as fh:
                return (fh.read(), cached_at.isoformat(timespec="seconds"),
                        "stale copy (fetch failed: %s)" % exc)
        raise
    _atomic_write(path, data)
    stamp = now.isoformat(timespec="seconds")
    _atomic_write(meta_path, json.dumps({"fetched_at": stamp,
                                         "url": url}).encode("utf-8"))
    return data, stamp, "fetched"


# --------------------------------------------------------------- the run

def season_for(day):
    """The NFL season a date belongs to: January and February are the
    previous season's playoffs."""
    return day.year if day.month >= 3 else day.year - 1


def _strip_keys(rows):
    for row in rows:
        row.pop("_key", None)
    return rows


def fetch(out_path, cache_dir, now=None, season=None, kind="manual",
          use_espn=True, use_sleeper=True, get=http_get, log=print):
    """Run every source once and write the contract file. Returns an exit code.

    The output file is removed first, so a failed run can never leave an old
    file behind to be read as this run's (the same rule as
    `ops/fetch_injuries.sh`).
    """
    now = now or datetime.datetime.now()
    now_iso = now.isoformat(timespec="seconds")
    season = season or season_for(now.date())
    if not os.path.isdir(cache_dir):
        os.makedirs(cache_dir)
    if os.path.exists(out_path):
        os.remove(out_path)

    sources = {}

    # The crosswalk first: every other source's rows need it for CBS ids. A
    # failure here is not fatal - rows just fall back to name-and-team.
    crosswalk = {"gsis": {}, "sleeper": {}, "espn": {}}
    try:
        data, fetched_at, note = cached_get(
            cache_dir, "db_playerids.csv", CROSSWALK_URL, MAX_CROSSWALK,
            CROSSWALK_MAX_AGE_S, now, get, stale_ok=True)
        crosswalk = parse_crosswalk(data.decode("utf-8"))
        sources["crosswalk"] = {"ok": True, "fetched_at": fetched_at,
                                "how": note, "rows": len(crosswalk["gsis"])}
    except (FetchError, ValueError, UnicodeDecodeError) as exc:
        sources["crosswalk"] = {"ok": False, "error": "%s (rows matched by "
                                "name and team only)" % exc}

    # nflverse: the record. Fatal on failure - see the module docstring.
    try:
        as_of = parse_stamp(get(NFLVERSE_STAMP_URL, MAX_STAMP))
        week, report = parse_nflverse(
            get(NFLVERSE_URL % season, MAX_NFLVERSE).decode("utf-8"), as_of,
            crosswalk)
        sources["nflverse"] = {"ok": True, "as_of": as_of, "week": week,
                               "rows": len(report),
                               "with_cbs_id": sum(1 for r in report if r["cbs_id"])}
    except (FetchError, ValueError, UnicodeDecodeError) as exc:
        log("injuries-fetch: nflverse failed (%s); no file written - the "
            "official report is the record, and an empty one would read as a "
            "clean roster" % exc)
        return 1

    state_path = os.path.join(cache_dir, STATE_FILE)
    prev_state = {}
    if os.path.exists(state_path):
        try:
            with open(state_path) as fh:
                prev_state = json.load(fh)
            if not isinstance(prev_state, dict):
                prev_state = {}
        except (ValueError, OSError):
            prev_state = {}

    intel = []
    if use_sleeper:
        try:
            data, fetched_at, note = cached_get(
                cache_dir, "sleeper-players-nfl.json", SLEEPER_URL,
                MAX_SLEEPER, SLEEPER_MAX_AGE_S, now, get)
            players = json.loads(data.decode("utf-8"))
            rows = sleeper_rows(players, crosswalk)
            rows += sleeper_cleared_rows(players, crosswalk, prev_state)
            intel += rows
            sources["sleeper"] = {"ok": True, "fetched_at": fetched_at,
                                  "how": note, "rows": len(rows),
                                  "with_cbs_id": sum(1 for r in rows if r["cbs_id"])}
        except (FetchError, ValueError, UnicodeDecodeError) as exc:
            sources["sleeper"] = {"ok": False, "error": str(exc)}

    if use_espn:
        off_path = os.path.join(cache_dir, ESPN_OFF_FILE)
        if os.path.exists(off_path):
            try:
                with open(off_path) as fh:
                    off = json.load(fh)
            except (ValueError, OSError):
                off = {}
            sources["espn"] = {
                "ok": False, "off": True,
                "error": "ESPN is switched off since %s after HTTP %s; delete "
                         "%s once someone has checked" % (
                             off.get("since", "?"), off.get("status", "?"),
                             off_path)}
        else:
            try:
                rows = espn_rows(json.loads(get(ESPN_URL, MAX_ESPN)
                                            .decode("utf-8")), crosswalk)
                intel += rows
                sources["espn"] = {"ok": True, "rows": len(rows),
                                   "with_cbs_id": sum(1 for r in rows if r["cbs_id"])}
            except FetchError as exc:
                if exc.status in (403, 429):
                    _atomic_write(off_path, json.dumps({
                        "since": now_iso, "status": exc.status,
                        "url": ESPN_URL}).encode("utf-8"))
                    sources["espn"] = {
                        "ok": False, "off": True,
                        "error": "HTTP %d: ESPN is switched off until %s is "
                                 "deleted" % (exc.status, off_path)}
                else:
                    sources["espn"] = {"ok": False, "error": str(exc)}
            except (ValueError, UnicodeDecodeError) as exc:
                sources["espn"] = {"ok": False, "error": str(exc)}

    # Change fields, from our own previous snapshot. A source that failed or
    # was not asked for this run keeps its old entries, so its next good run
    # still compares against the last time it was actually read.
    new_state = derive_changes(report + intel, prev_state, now_iso)
    for key, value in prev_state.items():
        outlet = key.split(":", 1)[0]
        if not sources.get(outlet, {}).get("ok", False):
            new_state.setdefault(key, value)

    # ESPN keeps an "Active" row, usually a game recap, for most players with
    # any recent note (613 of 800 on 2026-10-20). That is not injury news: on
    # the replay it put 10 recaps into a 13-man roster's injury block. An
    # Active row is kept only when it is a CHANGE (a return from a
    # designation); its state is still recorded above, so the next change is
    # seen either way.
    before = len(intel)
    intel = [r for r in intel
             if not (r["source"] == "espn"
                     and (r.get("status") or "").lower() == "active"
                     and not r.get("previous_status"))]
    if "espn" in sources and sources["espn"].get("ok"):
        sources["espn"]["active_recaps_left_out"] = before - len(intel)

    payload = {
        "report": _strip_keys(report),
        "intel": _strip_keys(intel),
        "meta": {"generated_at": now_iso, "kind": kind, "season": season,
                 "week": week, "sources": sources},
    }
    tmp = out_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh)
    os.replace(tmp, out_path)
    _atomic_write(state_path, json.dumps(new_state).encode("utf-8"))

    for name in ("nflverse", "crosswalk", "sleeper", "espn"):
        info = sources.get(name)
        if info is None:
            continue
        if info.get("ok"):
            log("  %-9s ok   %s" % (name, ", ".join(
                "%s=%s" % (k, v) for k, v in sorted(info.items()) if k != "ok")))
        else:
            log("  %-9s FAIL %s" % (name, info.get("error")))
    log("wrote %s: %d official rows (week %d), %d intel rows"
        % (out_path, len(payload["report"]), week, len(payload["intel"])))
    return 0

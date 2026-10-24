"""The direct injury feed: nflverse, Sleeper and ESPN, matched to CBS ids.

Built 2026-10-20 to replace StatsDeck's `get_injuries` (the plan:
`docs/plans/2026-10-20-replace-statsdeck.md`). `sffl injuries-fetch` writes
the same `{"report": [...], "intel": [...]}` file `sffl.injuries` reads, plus
a `meta` block saying how each source did. Until the switch it writes to its
own file under `data/captures/` (`injuries-<kind>.direct.json`), never the one
the live alert reads.

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
- **ESPN's public injuries feed** - the news text, as Jeff decided on
  2026-10-20. At most one call per run and per ~12 hours (unless forced), a
  User-Agent that names the tool, no retries, and manual runs leave it out
  unless asked. An HTTP 401, 403, 429 or 451, a redirect off the allowlist,
  or a 200 that is not JSON switches ESPN off until a person deletes the
  marker file (`espn-off.json` in the shared cache folder).

HOW IT FAILS. nflverse is the only source that can fail the run - no file, so
the alert says INJURY DATA UNAVAILABLE - because an empty official report
would render as "no designations on your roster", a clean bill of health
nobody measured. That includes a latest week that shrank below half of the
previous scheduled run's rows for the same week: a truncated file. Each
optional source (the crosswalk, Sleeper, ESPN) runs inside its own guard: any
error at all - the network, a body that will not parse, a field of the wrong
type - is recorded in `meta.sources` with its type, and that source is left
out of this run. A bad ROW is skipped and counted, never the whole source. A
cached copy is replaced only by a response that parses; when a new response
does not, the previous good copy is used and its age is said.

LIMITS. HTTPS only, to an allowlist of hosts (redirects checked too); a
socket timeout and a wall-clock limit on every request; a byte cap, and a
body shorter than its Content-Length is refused; only CSV and JSON are
parsed; third-party text is capped (notes at about 300 characters, the as-of
time zone to a short code or an offset); error notes name hosts, never URLs.
Standard library only.

CHANGE FIELDS. No source says what a status moved from. The fetcher keeps its
own last snapshot (`injury-state.json` in the cache folder) and sets
`previous_status` and `status_since` on a row whose status differs from the
previous run's - "first seen by this pipeline at <time>", never a guess about
when the change really happened. On Sunday that is exactly "what changed
since Friday's run". Only the scheduled kinds (tuesday, friday, sunday) read
or write it: a manual run never moves the scheduled runs' baseline, and by
default keeps its downloads in its own cache folder too.
"""

import csv
import datetime
import http.client
import io
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

# The NFL season a date belongs to (January and February are the previous
# season's). One rule for the repo, kept in `sffl.season`, which also checks
# the season-bound defaults against it; this module picks nflverse's season
# file with it.
from sffl.season import season_for

USER_AGENT = "sffl-injuries/1.0 (personal, non-commercial fantasy digest)"
TIMEOUT_S = 60           # per socket operation
WALL_S = 120             # per request, start to last byte
CHUNK = 256 * 1024
NOTE_MAX = 300           # characters of third-party text kept per field

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
ESPN_MIN_INTERVAL_S = 12 * 3600

ESPN_OFF_FILE = "espn-off.json"
ESPN_LAST_FILE = "espn-last-call.json"
STATE_FILE = "injury-state.json"
SCHEDULED_KINDS = ("tuesday", "friday", "sunday")
# HTTP statuses that mean ESPN does not want these requests.
ESPN_OFF_STATUSES = (401, 403, 429, 451)

_NFLVERSE_COLUMNS = ("season", "season_type", "week", "gsis_id", "full_name",
                     "team", "position", "report_status", "practice_status",
                     "report_primary_injury", "report_secondary_injury")
_CROSSWALK_COLUMNS = ("cbs_id", "gsis_id", "sleeper_id", "espn_id")
_TZ = re.compile(r"^(?:[A-Z]{2,5}|[+-]\d{2}:?\d{2})$")


class FetchError(Exception):
    """A source could not be read.

    `status` is the HTTP status, if there was one. `kind` says what failed:
    "http", "redirect" (a redirect or final URL off the allowlist), "refused"
    (the URL itself), "network", "size", "time" or "short".
    """

    def __init__(self, message, status=None, kind=""):
        super(FetchError, self).__init__(message)
        self.status = status
        self.kind = kind


def _host(url):
    return urllib.parse.urlparse(url).hostname or "?"


def _allowed(url):
    parts = urllib.parse.urlparse(url)
    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS


def check_url(url):
    """Raise FetchError unless `url` is https to an allowed host."""
    if not _allowed(url):
        raise FetchError("refused %s: only https to the allowed hosts"
                         % _host(url), kind="refused")


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed(newurl):
            raise FetchError("redirect to %s refused: off the allowed hosts"
                             % _host(newurl), kind="redirect")
        return urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl)


def http_get(url, max_bytes, timeout=TIMEOUT_S, wall_s=WALL_S,
             clock=time.monotonic):
    """GET `url` once: allowed hosts only, a socket timeout, a wall-clock
    limit, at most `max_bytes`, and no shorter than its Content-Length."""
    check_url(url)
    host = _host(url)
    opener = urllib.request.build_opener(_CheckedRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    start = clock()
    expected = None
    try:
        with opener.open(req, timeout=timeout) as resp:
            if not _allowed(resp.geturl()):
                raise FetchError("%s ended off the allowed hosts" % host,
                                 kind="redirect")
            length = (resp.headers.get("Content-Length")
                      if getattr(resp, "headers", None) is not None else None)
            if length is not None and str(length).strip().isdigit():
                expected = int(str(length).strip())
                if expected > max_bytes:
                    raise FetchError("%s announced %d bytes, over the %d cap"
                                     % (host, expected, max_bytes), kind="size")
            chunks, total = [], 0
            while True:
                if clock() - start > wall_s:
                    raise FetchError("%s took longer than %d s"
                                     % (host, wall_s), kind="time")
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError("%s sent more than %d bytes; refused"
                                     % (host, max_bytes), kind="size")
            data = b"".join(chunks)
    except FetchError:
        raise
    except urllib.error.HTTPError as exc:
        raise FetchError("HTTP %d from %s" % (exc.code, host),
                         status=exc.code, kind="http")
    except (urllib.error.URLError, http.client.HTTPException, socket.timeout,
            OSError, ValueError) as exc:
        raise FetchError("%s from %s" % (type(exc).__name__, host),
                         kind="network")
    if expected is not None and len(data) < expected:
        raise FetchError("%s sent %d of the %d bytes it announced"
                         % (host, len(data), expected), kind="short")
    return data


# --------------------------------------------------------------- text

def _text(value, cap=NOTE_MAX):
    """A third-party string, whitespace collapsed and capped; "" if not a str."""
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    return text if len(text) <= cap else text[:cap - 3].rstrip() + "..."


def _why(exc):
    """A short, URL-free description of an error for meta and the digest."""
    if isinstance(exc, FetchError):
        return str(exc)
    return "%s: %s" % (type(exc).__name__, _text(str(exc), 120))


def _id(value):
    """A source id as a clean string: "" for blank or NA, no trailing ".0"."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = str(value).strip()
    if text in ("", "NA", "None", "nan"):
        return ""
    return text[:-2] if text.endswith(".0") else text


# --------------------------------------------------------------- parsing

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
    if not out["gsis"]:
        raise ValueError("crosswalk has no CBS ids at all")
    return out


def parse_stamp(data):
    """nflverse's `timestamp.json` -> "YYYY-MM-DD HH:MM[ TZ]" (seconds dropped).

    The time zone is kept only as a short capital code or an offset; anything
    else is dropped rather than carried into the digest.
    """
    raw = json.loads(data.decode("utf-8"))
    stamp = raw.get("last_updated") if isinstance(raw, dict) else None
    stamp = stamp.strip() if isinstance(stamp, str) else ""
    m = re.match(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(?::\d{2})?(?: (\S+))?$",
                 stamp)
    if not m:
        raise ValueError("nflverse timestamp has no usable last_updated")
    tz = m.group(3) if m.group(3) and _TZ.match(m.group(3)) else ""
    return " ".join(p for p in (m.group(1), m.group(2), tz) if p)


def parse_nflverse(text, as_of, crosswalk):
    """(week, rows, skipped): the latest week's official report rows,
    contract-shaped, and how many unreadable rows were skipped.

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
    keyed, skipped = [], 0
    for r in reader:
        try:
            week = int(r["week"])
            post = 1 if (r["season_type"] or "").strip().upper() == "POST" else 0
            name = _text(r["full_name"], 80)
        except (TypeError, ValueError, AttributeError):
            skipped += 1
            continue
        if not name:
            skipped += 1
            continue
        keyed.append(((post, week), r, name))
    if not keyed:
        raise ValueError("nflverse injuries file has no readable rows")

    latest = max(k for k, _, _ in keyed)
    out = []
    for key, r, name in keyed:
        if key != latest:
            continue
        gsis = _id(r["gsis_id"])
        injuries = [x for x in (_text(r["report_primary_injury"], 60),
                                _text(r["report_secondary_injury"], 60))
                    if x and x != "NA"]
        status = _text(r["report_status"], 40)
        practice = _text(r["practice_status"], 60)
        out.append({
            "player": name,
            "team": _text(r["team"], 4),
            "position": _text(r["position"], 4),
            "status": status if status and status != "NA" else "Not listed",
            "practice": "" if practice in ("", "NA") else practice,
            "detail": ", ".join(injuries),
            "reported_date": as_of[:10],
            "as_of": as_of,
            "source": "nflverse",
            "gsis_id": gsis,
            "player_id": gsis,
            "cbs_id": crosswalk["gsis"].get(gsis, ""),
            "_key": gsis or name,
        })
    return latest[1], out, skipped


def _local_date_from_ms(ms):
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or not ms:
        return ""
    try:
        return datetime.datetime.fromtimestamp(ms / 1000.0).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        return ""


def _cbs_for_sleeper(pid, player, crosswalk):
    return (crosswalk["sleeper"].get(_id(pid))
            or crosswalk["gsis"].get(_id(player.get("gsis_id")))
            or crosswalk["espn"].get(_id(player.get("espn_id")))
            or "")


def _sleeper_name(p):
    name = _text(p.get("full_name"), 80)
    if not name:
        name = _text("%s %s" % (p.get("first_name") if isinstance(p.get("first_name"), str) else "",
                                p.get("last_name") if isinstance(p.get("last_name"), str) else ""), 80)
    return name


def sleeper_rows(players, crosswalk):
    """(rows, skipped): intel rows for every active player with a team whom
    Sleeper marks injured. A row with a field of the wrong type is skipped."""
    if not isinstance(players, dict):
        raise ValueError("Sleeper players feed is not an object")
    out, skipped = [], 0
    for pid, p in players.items():
        if not isinstance(p, dict):
            skipped += 1
            continue
        status = p.get("injury_status")
        if status is None or status == "":
            continue
        team, active = p.get("team"), p.get("active")
        if not isinstance(status, str) or not isinstance(active, bool):
            skipped += 1
            continue
        if not active or not team:
            continue
        name = _sleeper_name(p)
        if not isinstance(team, str) or not name:
            skipped += 1
            continue
        out.append({
            "player": name,
            "team": _text(team, 4),
            "position": _text(p.get("position"), 4),
            "status": _text(status, 40),
            "notes": _text(p.get("injury_body_part")),
            "reported_date": _local_date_from_ms(p.get("news_updated")),
            "source": "sleeper",
            "sleeper_id": _id(pid),
            "cbs_id": _cbs_for_sleeper(pid, p, crosswalk),
            "_key": _id(pid),
        })
    return out, skipped


def sleeper_cleared_rows(players, crosswalk, prev_state):
    """A "cleared" row for each player the previous run saw injured whom
    Sleeper now lists with no injury status. Sleeper simply drops the status
    when a player is healthy, so without this the return of a questionable
    player would never be news."""
    out = []
    for key, old in prev_state.items():
        if (not key.startswith("sleeper:") or not isinstance(old, dict)
                or not old.get("status")):
            continue
        pid = key.split(":", 1)[1]
        p = players.get(pid) if isinstance(players, dict) else None
        if not isinstance(p, dict) or p.get("injury_status"):
            continue
        team = p.get("team")
        if p.get("active") is not True or not isinstance(team, str) or not team:
            continue
        out.append({
            "player": _sleeper_name(p) or pid,
            "team": _text(team, 4),
            "position": _text(p.get("position"), 4),
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
    if not isinstance(text, str) or not text.strip():
        return ""
    try:
        when = datetime.datetime.strptime(text.strip(), "%Y-%m-%dT%H:%MZ")
    except ValueError:
        return _text(text, 10)
    when = when.replace(tzinfo=datetime.timezone.utc).astimezone()
    return when.strftime("%Y-%m-%d")


def _espn_row(item, crosswalk):
    """One ESPN injury item -> a row, or None when a field has the wrong type."""
    if not isinstance(item, dict):
        return None
    athlete = item.get("athlete")
    if not isinstance(athlete, dict):
        return None
    name = _text(athlete.get("displayName"), 80)
    status = item.get("status")
    if not name or not isinstance(status, str):
        return None
    links = athlete.get("links")
    espn_id = ""
    for link in links if isinstance(links, list) else []:
        href = link.get("href") if isinstance(link, dict) else None
        m = _ESPN_ID.search(href) if isinstance(href, str) else None
        if m:
            espn_id = m.group(1)
            break
    team = athlete.get("team")
    position = athlete.get("position")
    details = item.get("details")
    comment = _text(item.get("shortComment")) or _text(item.get("longComment"))
    return {
        "player": name,
        "team": _text(team.get("abbreviation"), 4) if isinstance(team, dict) else "",
        "position": (_text(position.get("abbreviation"), 4)
                     if isinstance(position, dict) else ""),
        "status": _text(status, 40),
        "notes": comment,
        "reported_date": _local_date_from_iso(item.get("date")),
        "return_date": (_text(details.get("returnDate"), 10)
                        if isinstance(details, dict) else ""),
        "source": "espn",
        "espn_id": espn_id,
        "cbs_id": crosswalk["espn"].get(espn_id, "") if espn_id else "",
        "_key": espn_id or name,
    }


def espn_rows(data, crosswalk):
    """(rows, skipped): intel rows for every player in ESPN's injuries feed,
    with ESPN's comment as the detail. A malformed team or row is skipped and
    counted. "Active" rows are returned here; `fetch` keeps them only as a
    change."""
    if not isinstance(data, dict) or not isinstance(data.get("injuries"), list):
        raise ValueError("ESPN injuries feed has no 'injuries' list")
    out, skipped = [], 0
    for team in data["injuries"]:
        items = team.get("injuries") if isinstance(team, dict) else None
        if not isinstance(items, list):
            skipped += 1
            continue
        for item in items:
            row = _espn_row(item, crosswalk)
            if row is None:
                skipped += 1
            else:
                out.append(row)
    return out, skipped


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
        if not isinstance(old, dict):
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


# --------------------------------------------------------------- files

def _atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _parse_time(text):
    try:
        return datetime.datetime.fromisoformat(text) if isinstance(text, str) else None
    except ValueError:
        return None


def cached_get(cache_dir, name, url, max_bytes, max_age_s, now, get, parse):
    """(parsed, fetched_at, how) for one cached source.

    A cached copy younger than `max_age_s` is used as it is. Otherwise one GET,
    and its body is PARSED BEFORE it is cached: only a body that parses
    replaces the cached copy. When the GET fails or the new body does not
    parse, the previous good copy is used if there is one, and `how` says so;
    otherwise the error is raised for the caller's guard to record.
    """
    path = os.path.join(cache_dir, name)
    meta_path = path + ".meta.json"
    meta = _read_json(meta_path) if os.path.exists(path) else None
    cached_at = _parse_time(meta.get("fetched_at")) if isinstance(meta, dict) else None

    def from_cache():
        with open(path, "rb") as fh:
            return parse(fh.read())

    if cached_at is not None and (now - cached_at).total_seconds() < max_age_s:
        try:
            return from_cache(), cached_at.isoformat(timespec="seconds"), "cached"
        except Exception:      # a cached copy that no longer parses: refetch
            pass
    try:
        data = get(url, max_bytes)
        parsed = parse(data)
    except Exception as exc:
        if cached_at is not None:
            try:
                return (from_cache(), cached_at.isoformat(timespec="seconds"),
                        "previous good copy (new one failed: %s)" % _why(exc))
            except Exception:
                pass
        raise
    _atomic_write(path, data)
    stamp = now.isoformat(timespec="seconds")
    _atomic_write(meta_path, json.dumps({"fetched_at": stamp,
                                         "host": _host(url)}).encode("utf-8"))
    return parsed, stamp, "fetched"


def _strip_keys(rows):
    for row in rows:
        row.pop("_key", None)
    return rows


def _decode_json(data):
    return json.loads(data.decode("utf-8"))


def _decode_text(data):
    return data.decode("utf-8")


def _espn(espn_dir, now, get, crosswalk, force):
    """(source info, rows) for ESPN, honouring the off marker and the 12-hour
    limit. Raises nothing: every failure is in the info."""
    now_iso = now.isoformat(timespec="seconds")
    off_path = os.path.join(espn_dir, ESPN_OFF_FILE)
    if os.path.exists(off_path):
        off = _read_json(off_path)
        off = off if isinstance(off, dict) else {}
        return {"ok": False, "off": True,
                "error": "ESPN is switched off since %s (%s); delete %s in the "
                         "cache folder once someone has checked"
                         % (off.get("since", "?"), off.get("why", "?"),
                            ESPN_OFF_FILE)}, []
    last = _read_json(os.path.join(espn_dir, ESPN_LAST_FILE))
    last_at = _parse_time(last.get("at")) if isinstance(last, dict) else None
    if (not force and last_at is not None
            and (now - last_at).total_seconds() < ESPN_MIN_INTERVAL_S):
        return {"ok": False, "skipped": True,
                "error": "ESPN skipped: last called %s, under 12 hours ago "
                         "(--force-espn calls it anyway)" % last.get("at")}, []
    # Counted before the call, so a crash mid-request still counts as one.
    _atomic_write(os.path.join(espn_dir, ESPN_LAST_FILE),
                  json.dumps({"at": now_iso}).encode("utf-8"))

    def switch_off(why):
        _atomic_write(off_path, json.dumps({"since": now_iso, "why": why,
                                            "host": _host(ESPN_URL)})
                      .encode("utf-8"))
        return {"ok": False, "off": True,
                "error": "%s: ESPN is switched off until %s is deleted"
                         % (why, ESPN_OFF_FILE)}

    try:
        data = get(ESPN_URL, MAX_ESPN)
    except FetchError as exc:
        if exc.status in ESPN_OFF_STATUSES or exc.kind == "redirect":
            return switch_off(str(exc)), []
        return {"ok": False, "error": str(exc), "error_type": "FetchError"}, []
    try:
        payload = _decode_json(data)
    except (ValueError, UnicodeDecodeError):
        return switch_off("a 200 from %s that was not JSON" % _host(ESPN_URL)), []
    rows, skipped = espn_rows(payload, crosswalk)
    return {"ok": True, "rows": len(rows), "rows_skipped": skipped,
            "with_cbs_id": sum(1 for r in rows if r["cbs_id"])}, rows


def _guarded(name, sources, fn):
    """Run one optional source; any exception is recorded, never raised."""
    try:
        return fn()
    except Exception as exc:
        sources[name] = {"ok": False, "error": _why(exc),
                         "error_type": type(exc).__name__}
        return None


def _previous_output_or_none(path):
    """True when `path` is absent or an earlier fetcher output (it carries
    `meta.generated_at`); False for any other file, which is never deleted."""
    if not os.path.exists(path):
        return True
    raw = _read_json(path)
    return (isinstance(raw, dict) and isinstance(raw.get("meta"), dict)
            and bool(raw["meta"].get("generated_at")))


def fetch(out_path, cache_dir, now=None, season=None, kind="manual",
          use_espn=True, use_sleeper=True, get=http_get, log=print,
          espn_dir=None, force_espn=False):
    """Run every source once and write the contract file. Returns an exit code:
    0 written, 1 nflverse failed (nothing written), 2 refused the output path.

    The output file is removed first, so a failed run can never leave an old
    file behind to be read as this run's (the same rule as
    `ops/fetch_injuries.sh`) - but only when it is an earlier fetcher output.
    """
    now = now or datetime.datetime.now()
    now_iso = now.isoformat(timespec="seconds")
    season = season or season_for(now.date())
    espn_dir = espn_dir or cache_dir
    scheduled = kind in SCHEDULED_KINDS
    if not out_path.lower().endswith(".json"):
        log("injuries-fetch: %s is not a .json file; refusing" % out_path)
        return 2
    if not _previous_output_or_none(out_path):
        log("injuries-fetch: %s exists and is not an earlier injuries-fetch "
            "output (no meta.generated_at); refusing to replace it" % out_path)
        return 2
    for d in (cache_dir, espn_dir):
        if not os.path.isdir(d):
            os.makedirs(d)
    if os.path.exists(out_path):
        os.remove(out_path)

    sources = {}
    state_path = os.path.join(cache_dir, STATE_FILE)
    prev_state = _read_json(state_path) if scheduled else None
    prev_state = prev_state if isinstance(prev_state, dict) else {}

    # The crosswalk first: every other source's rows need it for CBS ids. A
    # failure here is not fatal - rows just fall back to name-and-team.
    crosswalk = {"gsis": {}, "sleeper": {}, "espn": {}}

    def run_crosswalk():
        parsed, fetched_at, how = cached_get(
            cache_dir, "db_playerids.csv", CROSSWALK_URL, MAX_CROSSWALK,
            CROSSWALK_MAX_AGE_S, now, get,
            lambda data: parse_crosswalk(_decode_text(data)))
        sources["crosswalk"] = {"ok": True, "fetched_at": fetched_at,
                                "how": how, "rows": len(parsed["gsis"])}
        return parsed

    got = _guarded("crosswalk", sources, run_crosswalk)
    if got is not None:
        crosswalk = got
    else:
        sources["crosswalk"]["error"] += " (rows matched by name and team only)"

    # nflverse: the record, and the only fatal source - see the docstring.
    try:
        as_of = parse_stamp(get(NFLVERSE_STAMP_URL, MAX_STAMP))
        week, report, skipped = parse_nflverse(
            _decode_text(get(NFLVERSE_URL % season, MAX_NFLVERSE)), as_of,
            crosswalk)
    except Exception as exc:
        log("injuries-fetch: nflverse failed (%s); no file written - the "
            "official report is the record, and an empty one would read as a "
            "clean roster" % _why(exc))
        return 1
    prev_n = prev_state.get("_nflverse") if scheduled else None
    if (isinstance(prev_n, dict) and prev_n.get("week") == week
            and isinstance(prev_n.get("rows"), int)
            and len(report) < prev_n["rows"] / 2.0):
        log("injuries-fetch: nflverse's week-%d report has %d rows, under half "
            "of the previous run's %d; refusing it as truncated, no file "
            "written" % (week, len(report), prev_n["rows"]))
        return 1
    sources["nflverse"] = {"ok": True, "as_of": as_of, "week": week,
                           "rows": len(report), "rows_skipped": skipped,
                           "with_cbs_id": sum(1 for r in report if r["cbs_id"])}

    intel = []
    if use_sleeper:
        def run_sleeper():
            players, fetched_at, how = cached_get(
                cache_dir, "sleeper-players-nfl.json", SLEEPER_URL,
                MAX_SLEEPER, SLEEPER_MAX_AGE_S, now, get, _decode_json)
            rows, bad = sleeper_rows(players, crosswalk)
            rows += sleeper_cleared_rows(players, crosswalk, prev_state)
            age = round((now - _parse_time(fetched_at)).total_seconds()
                        / 3600.0, 1)
            sources["sleeper"] = {
                "ok": True, "fetched_at": fetched_at, "how": how,
                "age_hours": age, "rows": len(rows), "rows_skipped": bad,
                "with_cbs_id": sum(1 for r in rows if r["cbs_id"])}
            return rows

        intel += _guarded("sleeper", sources, run_sleeper) or []

    if use_espn:
        def run_espn():
            info, rows = _espn(espn_dir, now, get, crosswalk, force_espn)
            sources["espn"] = info
            return rows

        intel += _guarded("espn", sources, run_espn) or []

    # Change fields, from our own previous snapshot - scheduled runs only. A
    # source that failed or was not asked for keeps its old entries, so its
    # next good run still compares against the last time it was really read.
    new_state = derive_changes(report + intel, prev_state, now_iso)
    for key, value in prev_state.items():
        outlet = key.split(":", 1)[0]
        if key != "_nflverse" and not sources.get(outlet, {}).get("ok", False):
            new_state.setdefault(key, value)
    new_state["_nflverse"] = {"week": week, "rows": len(report)}

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
    if sources.get("espn", {}).get("ok"):
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
    if scheduled:
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
